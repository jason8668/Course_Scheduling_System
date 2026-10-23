"""请假登记与受影响节次展开(M4-1,architecture.md §5.3)。

**把周循环格展开成日历日期。** 课表说「王师周三第三节上 301 班国文」;
请假说「王师 11/12 上午请假」。这里负责把两者对起来:

1. 走访请假期间的每一天;
2. 跳过该班节次表没有的星期(周末,或六日制学校的周六以外);
3. 取出**已发布课表**中该教师当天的每一节课(连堂展开成每一节);
4. 半天假以墙钟时间区间重叠判定,整天假则全部列入;
5. 写成 `affected_period` 快照。

只看**已发布**课表:草稿随时会变,拿草稿去找代课老师没有意义。
"""

from collections.abc import Iterator
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.week_parity import runs_in_week, week_parity
from app.models.assignment import AssignmentTeacher, CourseAssignment
from app.models.basedata import Room, Subject, Teacher
from app.models.leave import (
    LEAVE_TYPE_CN,
    AffectedPeriod,
    AffectedStatus,
    LeaveRequest,
    LeaveStatus,
)
from app.models.notification import NotificationType
from app.models.period import Period, PeriodType
from app.models.semester import Semester
from app.models.timetable import ScheduleEntry, Timetable, TimetableStatus
from app.services import notifications
from app.services import period_tables as pt_service

MAX_LEAVE_DAYS = 180  # 产假上限约 8 周;180 天足够,同时挡住手残输入的 2099 年


class LeaveError(Exception):
    """请假单本身不合法(呼叫端转为 400)。"""


def school_dates(start: date, end: date) -> Iterator[date]:
    """请假期间的每一天(含头尾)。是否为上课日由节次表决定,不在这里判断。"""
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def _leave_window(leave: LeaveRequest, day: date) -> tuple[time | None, time | None]:
    """该日的请假时间区间。回传 (from, to),None 表示该端点没有限制(整天)。

    只有第一天受 start_time 限制、最后一天受 end_time 限制;中间的日子一律整天。
    「11/12 13:00 ~ 11/14 12:00」= 12 日下午 + 13 日整天 + 14 日上午。
    """
    begin = leave.start_time if day == leave.start_date else None
    finish = leave.end_time if day == leave.end_date else None
    return begin, finish


def _overlaps(period: Period, window: tuple[time | None, time | None]) -> bool:
    """节次是否落在该日的请假区间内。"""
    begin, finish = window
    if begin is None and finish is None:
        return True  # 整天假
    if period.start_time is None or period.end_time is None:
        # 节次表没填起讫时间就无法判定半天假。宁可多列一节让组长删掉,
        # 也不要漏掉一节没人代课——漏掉的那节会直接变成没有老师的教室。
        return True
    if finish is not None and period.start_time >= finish:
        return False
    if begin is not None and period.end_time <= begin:
        return False
    return True


def _published_timetable(db: Session, semester_id: int) -> Timetable | None:
    return db.scalar(
        select(Timetable).where(
            Timetable.semester_id == semester_id,
            Timetable.status == TimetableStatus.published.value,
        )
    )


def _teacher_entries(db: Session, timetable_id: int, teacher_id: int) -> list[ScheduleEntry]:
    return list(
        db.scalars(
            select(ScheduleEntry)
            .join(CourseAssignment, ScheduleEntry.course_assignment_id == CourseAssignment.id)
            .join(AssignmentTeacher, AssignmentTeacher.course_assignment_id == CourseAssignment.id)
            .where(
                ScheduleEntry.timetable_id == timetable_id,
                AssignmentTeacher.teacher_id == teacher_id,
            )
            .order_by(ScheduleEntry.weekday, ScheduleEntry.period_no)
        ).unique()
    )


class _Expander:
    """一次展开所需的节次表/班级/科目/场地查询,全部先捞好再组装。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self._periods: dict[int, dict[tuple[int, int], Period]] = {}
        self._num_weekdays: dict[int, int] = {}

    def table_of(self, assignment: CourseAssignment) -> int | None:
        members = assignment.scheduling_unit.members
        if not members:
            return None
        table = pt_service.resolve_period_table(self.db, members[0].class_unit)
        return table.id if table else None

    def _load_table(self, table_id: int) -> dict[tuple[int, int], Period]:
        if table_id not in self._periods:
            rows = list(self.db.scalars(select(Period).where(Period.period_table_id == table_id)))
            self._periods[table_id] = {(p.weekday, p.period_no): p for p in rows}
            self._num_weekdays[table_id] = max((p.weekday for p in rows), default=0)
        return self._periods[table_id]

    def is_school_day(self, table_id: int, day: date) -> bool:
        """节次表没有这个星期 = 不上课(周末;六日制学校则周六有课)。"""
        self._load_table(table_id)
        return day.isoweekday() <= self._num_weekdays[table_id]

    def period(self, table_id: int, weekday: int, period_no: int) -> Period | None:
        return self._load_table(table_id).get((weekday, period_no))

    def describe(self, a: CourseAssignment, entry: ScheduleEntry) -> tuple[str, str, str]:
        subject = self.db.get(Subject, a.subject_id)
        classes = "、".join(m.class_unit.name for m in a.scheduling_unit.members)
        room_id = entry.room_id if entry.room_id is not None else a.room_id
        room = self.db.get(Room, room_id) if room_id else None
        return (subject.name if subject else ""), classes, (room.name if room else "")


def expand(db: Session, leave: LeaveRequest) -> list[AffectedPeriod]:
    """依已发布课表展开受影响节次。呼叫端负责 commit。

    课表尚未发布时回传空清单——假单照样成立,只是没有课要处理。
    """
    timetable = _published_timetable(db, leave.semester_id)
    if timetable is None:
        return []

    entries = _teacher_entries(db, timetable.id, leave.teacher_id)
    if not entries:
        return []

    exp = _Expander(db)
    out: list[AffectedPeriod] = []
    seen: set[tuple[date, int, str]] = set()
    semester = db.get(Semester, leave.semester_id)
    sem_start = semester.start_date if semester else None

    for day in school_dates(leave.start_date, leave.end_date):
        window = _leave_window(leave, day)
        weekday = day.isoweekday()
        week = week_parity(sem_start, day)
        for entry in entries:
            if entry.weekday != weekday:
                continue
            a = entry.assignment
            if not runs_in_week(a.week_parity, week):
                continue  # 单双周的课:这一周没有上(v1.3.0)
            table_id = exp.table_of(a)
            if table_id is None or not exp.is_school_day(table_id, day):
                continue

            subject_name, class_names, room_name = exp.describe(a, entry)
            # 连堂占用连续数节,逐节展开:代课是逐节找人的
            for k in range(entry.span):
                period = exp.period(table_id, weekday, entry.period_no + k)
                if period is None or period.type != PeriodType.regular.value:
                    continue
                if not _overlaps(period, window):
                    continue
                key = (day, period.period_no, class_names)
                if key in seen:
                    continue
                seen.add(key)
                out.append(AffectedPeriod(
                    leave_request_id=leave.id, semester_id=leave.semester_id,
                    date=day, weekday=weekday, period_no=period.period_no,
                    period_name=period.name, start_time=period.start_time,
                    end_time=period.end_time,
                    subject_name=subject_name, class_names=class_names, room_name=room_name,
                    schedule_entry_id=entry.id, course_assignment_id=a.id,
                    status=AffectedStatus.pending.value,
                ))

    out.sort(key=lambda p: (p.date, p.period_no))
    return out


def validate(semester: Semester, start: date, end: date) -> None:
    if end < start:
        raise LeaveError("结束日期不可早于开始日期")
    if (end - start).days + 1 > MAX_LEAVE_DAYS:
        raise LeaveError(f"单张假单最长 {MAX_LEAVE_DAYS} 天")
    if semester.start_date is None or semester.end_date is None:
        raise LeaveError(
            "学期尚未设置起讫日期,无法登记请假;"
            "请到「学期与节次表」点该学期的「编辑学期」补上开学日与结业日"
        )
    if start < semester.start_date or end > semester.end_date:
        raise LeaveError(
            f"请假日期须落在学期范围内({semester.start_date} ~ {semester.end_date})"
        )


def create(
    db: Session,
    semester: Semester,
    teacher: Teacher,
    *,
    leave_type: str,
    start_date: date,
    start_time: time | None,
    end_date: date,
    end_time: time | None,
    reason: str,
    created_by_user_id: int | None,
    created_by_name: str,
    notify_teacher: bool,
) -> LeaveRequest:
    """登记请假并展开受影响节次。呼叫端负责 commit。"""
    validate(semester, start_date, end_date)
    if start_date == end_date and start_time and end_time and end_time <= start_time:
        raise LeaveError("结束时间不可早于开始时间")

    leave = LeaveRequest(
        semester_id=semester.id, teacher_id=teacher.id, leave_type=leave_type,
        start_date=start_date, start_time=start_time,
        end_date=end_date, end_time=end_time,
        reason=reason, created_by_user_id=created_by_user_id, created_by_name=created_by_name,
    )
    db.add(leave)
    db.flush()

    for period in expand(db, leave):
        db.add(period)
    db.flush()

    if notify_teacher:
        # 组长代登:当事人要知道有人替他请了假
        notifications.notify(
            db, semester_id=semester.id, teacher_id=teacher.id,
            type=NotificationType.leave_registered,
            title=f"{created_by_name} 已为您登记{LEAVE_TYPE_CN[leave.leave_type]}",
            body=f"{range_text(leave)},共 {len(leave.affected_periods)} 节课受影响",
        )
    return leave


def cancel(db: Session, leave: LeaveRequest, *, actor_name: str) -> list[AffectedPeriod]:
    """销假:级联取消所有受影响节次,并通知已被指派的代课教师。

    回传「原本已指派、现在被取消」的节次。已完成的节次不动——那堂课已经上过了,
    事后销假不能把历史抹掉(课时统计要照算)。
    """
    if leave.status == LeaveStatus.cancelled.value:
        raise LeaveError("此假单已销假")

    leave.status = LeaveStatus.cancelled.value
    leave.cancelled_at = datetime.now().astimezone()

    revoked: list[AffectedPeriod] = []
    for period in leave.affected_periods:
        if period.status == AffectedStatus.completed.value:
            continue
        # 已上过的课不因销假抹除——那堂课发生了,代课课时照算(architecture.md §5.3 已完成)
        if clock.is_past_slot(period.date, period.end_time):
            continue
        if period.status == AffectedStatus.resolved.value:
            revoked.append(period)
        period.status = AffectedStatus.cancelled.value

    # 一位代课老师可能被取消好几节,合并成一封通知
    by_handler: dict[int, list[AffectedPeriod]] = {}
    for period in revoked:
        if period.handler_teacher_id:
            by_handler.setdefault(period.handler_teacher_id, []).append(period)

    for handler_id, periods in by_handler.items():
        detail = "、".join(f"{p.date} {p.period_name}({p.class_names}{p.subject_name})"
                           for p in periods)
        notifications.notify(
            db, semester_id=leave.semester_id, teacher_id=handler_id,
            type=NotificationType.substitution_cancelled,
            title=f"原订代课已取消({leave.teacher.name} 销假)",
            body=f"以下 {len(periods)} 节课不需要您代课了:{detail}",
        )

    notifications.notify(
        db, semester_id=leave.semester_id, teacher_id=leave.teacher_id,
        type=NotificationType.leave_cancelled,
        title=f"{actor_name} 已为您销假" if actor_name != leave.teacher.name else "销假完成",
        body=f"{range_text(leave)} 的{LEAVE_TYPE_CN[leave.leave_type]}已销假",
    )
    db.flush()
    return revoked


def range_text(leave: LeaveRequest) -> str:
    if leave.start_date == leave.end_date:
        if leave.is_half_day:
            begin = leave.start_time.strftime("%H:%M") if leave.start_time else "上课起"
            finish = leave.end_time.strftime("%H:%M") if leave.end_time else "放学"
            return f"{leave.start_date} {begin}~{finish}"
        return f"{leave.start_date} 整天"
    return f"{leave.start_date} ~ {leave.end_date}"


def find_teacher(db: Session, semester_id: int, teacher_id: int) -> Teacher | None:
    return db.scalar(
        select(Teacher).where(Teacher.id == teacher_id, Teacher.semester_id == semester_id)
    )


def effective_status(status: str, day: date, end_time: time | None) -> str:
    """显示用的推导状态:已指派且已上过的节次显示为『已完成』(不落盘,见 core.clock)。"""
    if status == AffectedStatus.resolved.value and clock.is_past_slot(day, end_time):
        return AffectedStatus.completed.value
    return status
