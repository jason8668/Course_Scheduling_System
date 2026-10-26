"""教师实际上课课时统计(仪表板 + 管理员查询/打印共用)。

口径(用户定案):「实际上了几节课」——
- 底数:已发布课表按日期展开(连堂按实际节数计;单双周只计轮到的那一周;
  每位配课教师都计,协同教学两人各计一节;跑班群组一格只计一节)。
- 扣减:校历放假(全天或指定节次)那天/那节不上课。
- 请假调代课(只看仍有效的假单,已销假取消的不算):
  - 代课:缺课教师扣掉,代课教师加上;
  - 自习、停课(不处理):缺课教师扣掉,无人加上;
  - 并班:被并入的班扣掉,接收教师本来的那节已在底数里,不另加;
  - 调课:请假日缺课教师扣、代课教师加;补课日反过来(缺课教师加、原代课教师扣);
  - 尚未处置的待处理节次:请假教师已确定不在,先扣掉,无人加上。
- 只计到今天为止:范围超出今天的部分还没上,不能算「已上」。
  回传 effective_start/effective_end 让界面能注明「统计至今天」。

年级归属:一节课算到它所教班级的年级;跑班群组一格多班时,
该节同时算到所涉的每个年级(故各年级小计之和可能大于总计)。
按年级筛选时,只计包含该年级的节次。

注意:这里的「上课课时」与代课月结统计的「计入/不计」是两回事——
后者管代课费/代课工作量是否计酬;这里只要实际上了课就计,
不论那节代课当初选的是计入还是不计入。
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.week_parity import runs_in_week, week_number
from app.models.basedata import Teacher
from app.models.calendar import SchoolCalendarEvent
from app.models.leave import AffectedPeriod, AffectedStatus, LeaveRequest, LeaveStatus
from app.models.semester import Semester
from app.models.substitution import Substitution, SubstitutionType
from app.models.timetable import ScheduleEntry, Timetable
from app.services.substitution_log import school_today


@dataclass
class TeacherHours:
    teacher_id: int
    teacher_name: str
    total: int = 0
    by_grade: dict[int, int] = field(default_factory=dict)


def _published_timetable(db: Session, semester_id: int) -> Timetable | None:
    return db.scalar(
        select(Timetable)
        .where(Timetable.semester_id == semester_id, Timetable.status == "published")
        .order_by(Timetable.id.desc())
    )


def _holidays(db: Session, semester_id: int) -> list[SchoolCalendarEvent]:
    """一次性放假事件(每周重复的已由求解器挡在课表外,不必再扣)。"""
    return db.scalars(
        select(SchoolCalendarEvent).where(
            SchoolCalendarEvent.semester_id == semester_id,
            SchoolCalendarEvent.event_type == "holiday",
            SchoolCalendarEvent.weekly_recurring.is_(False),
        )
    ).all()


def _is_holiday(
    holidays: list[SchoolCalendarEvent],
    grades: set[int],
    class_ids: set[int],
    on: date,
    period_no: int,
) -> bool:
    for ev in holidays:
        if not (ev.start_date <= on <= ev.end_date):
            continue
        if ev.period_start is not None and not (ev.period_start <= period_no <= (ev.period_end or ev.period_start)):
            continue
        if ev.scope_type == "school":
            return True
        if ev.scope_type == "grade" and ev.scope_id in grades:
            return True
        if ev.scope_type == "class" and ev.scope_id in class_ids:
            return True
    return False


def compute(
    db: Session,
    semester: Semester,
    start: date,
    end: date,
    *,
    teacher_id: int | None = None,
    grade: int | None = None,
) -> tuple[list[TeacherHours], date, date]:
    """回传 (教师课时列, 实际统计起日, 实际统计讫日)。"""
    today = school_today()
    eff_start = start
    eff_end = min(end, today)
    if semester.start_date is not None:
        eff_start = max(eff_start, semester.start_date)
    if semester.end_date is not None:
        eff_end = min(eff_end, semester.end_date)
    if eff_end < eff_start:
        return [], eff_start, eff_end

    tt = _published_timetable(db, semester.id)
    if tt is None:
        return [], eff_start, eff_end

    teachers = {
        t.id: t.name
        for t in db.scalars(
            select(Teacher).where(Teacher.semester_id == semester.id)
        ).all()
    }
    if teacher_id is not None:
        teachers = {k: v for k, v in teachers.items() if k == teacher_id}

    entries = db.scalars(
        select(ScheduleEntry).where(ScheduleEntry.timetable_id == tt.id)
    ).all()

    # (教师, 日期, 节次) -> 年级集合;底数先按已发布课表展开
    slots: dict[tuple[int, date, int], set[int]] = {}
    holidays = _holidays(db, semester.id)
    for e in entries:
        a = e.assignment
        if a is None:
            continue
        member_grades: set[int] = set()
        member_class_ids: set[int] = set()
        for m in a.scheduling_unit.members:
            if m.class_unit is not None:
                member_grades.add(m.class_unit.grade)
                member_class_ids.add(m.class_unit.id)
        teacher_ids = [at.teacher_id for at in a.teachers]
        if teacher_id is not None:
            teacher_ids = [t for t in teacher_ids if t == teacher_id]
        if not teacher_ids:
            continue
        d = eff_start
        while d <= eff_end:
            if d.isoweekday() == e.weekday:
                wn = week_number(semester.start_date, d)
                parity = None if wn is None else ("odd" if wn % 2 == 1 else "even")
                if runs_in_week(a.week_parity, parity):
                    for p in range(e.period_no, e.period_no + (e.span or 1)):
                        if _is_holiday(holidays, member_grades, member_class_ids, d, p):
                            continue
                        for tid in teacher_ids:
                            slots.setdefault((tid, d, p), set()).update(member_grades)
            d += timedelta(days=1)

    # 请假调代课异动:先找底数里对应的那格(拿年级),再扣/加
    def base_grades(tid: int, d: date, p: int) -> set[int]:
        if (tid, d, p) in slots:
            return slots[(tid, d, p)]
        # 课表改版后快照对不上底数时,退回查该教师当天该节的已发布格位
        wn_day = d.isoweekday()
        for e in entries:
            if e.weekday != wn_day or not (e.period_no <= p < e.period_no + (e.span or 1)):
                continue
            if any(at.teacher_id == tid for at in e.assignment.teachers):
                return {m.class_unit.grade for m in e.assignment.scheduling_unit.members
                        if m.class_unit is not None}
        return set()

    aps = db.scalars(
        select(AffectedPeriod)
        .join(LeaveRequest, AffectedPeriod.leave_request_id == LeaveRequest.id)
        .where(
            AffectedPeriod.semester_id == semester.id,
            AffectedPeriod.date >= eff_start,
            AffectedPeriod.date <= eff_end,
            LeaveRequest.status == LeaveStatus.registered.value,
            AffectedPeriod.status != AffectedStatus.cancelled.value,
        )
    ).all()
    subs = {
        s.affected_period_id: s
        for s in db.scalars(
            select(Substitution).where(
                Substitution.affected_period_id.in_([ap.id for ap in aps])
            )
        ).all()
    } if aps else {}

    makeup: list[Substitution] = []
    for ap in aps:
        leave = ap.leave_request
        absent = leave.teacher_id
        sub = subs.get(ap.id)
        if sub is None:
            # 待处理:请假教师确定不在,先扣掉
            slots.pop((absent, ap.date, ap.period_no), None)
            continue
        if sub.type == SubstitutionType.substitute.value:
            grades = base_grades(absent, ap.date, ap.period_no)
            slots.pop((absent, ap.date, ap.period_no), None)
            if sub.handler_teacher_id is not None and (teacher_id is None or sub.handler_teacher_id == teacher_id):
                slots[(sub.handler_teacher_id, ap.date, ap.period_no)] = grades
        elif sub.type in (SubstitutionType.self_study.value, SubstitutionType.cancel.value):
            slots.pop((absent, ap.date, ap.period_no), None)
        elif sub.type == SubstitutionType.merge.value:
            slots.pop((absent, ap.date, ap.period_no), None)
        elif sub.type == SubstitutionType.swap.value:
            grades = base_grades(absent, ap.date, ap.period_no)
            slots.pop((absent, ap.date, ap.period_no), None)
            if sub.handler_teacher_id is not None and (teacher_id is None or sub.handler_teacher_id == teacher_id):
                slots[(sub.handler_teacher_id, ap.date, ap.period_no)] = grades
            if sub.swap_date is not None:
                makeup.append(sub)

    for sub in makeup:
        if not (eff_start <= sub.swap_date <= eff_end):
            continue
        handler = sub.handler_teacher_id
        ap = db.get(AffectedPeriod, sub.affected_period_id)
        absent = ap.leave_request.teacher_id if ap else None
        if handler is None or absent is None:
            continue
        swap_period = sub.swap_period_no or 0
        grades = base_grades(handler, sub.swap_date, swap_period)
        slots.pop((handler, sub.swap_date, swap_period), None)
        if teacher_id is None or absent == teacher_id:
            slots[(absent, sub.swap_date, swap_period)] = grades

    hours: dict[int, TeacherHours] = {}
    for (tid, _d, _p), grades in slots.items():
        if tid not in teachers:
            continue
        if grade is not None and grade not in grades:
            continue
        h = hours.setdefault(tid, TeacherHours(teacher_id=tid, teacher_name=teachers[tid]))
        h.total += 1
        for g in grades:
            h.by_grade[g] = h.by_grade.get(g, 0) + 1
    out = sorted(hours.values(), key=lambda h: h.teacher_name)
    if teacher_id is not None and teacher_id in teachers and teacher_id not in hours:
        out = [TeacherHours(teacher_id=teacher_id, teacher_name=teachers[teacher_id])]
    return out, eff_start, eff_end
