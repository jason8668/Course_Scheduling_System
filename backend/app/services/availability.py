"""特定日期的教师可用性(M4-2)。

**这是「周循环格」与「特定日期」的交界。** 课表只知道「李师周三第二节有课」;
但要判断「11/11(周三)第二节李师能不能来代课」,周格不够——那个周三他自己可能也
请假了,或已经被指派去代别班。这一层把三件事叠起来:

1. **周课表**:李师在该节次的墙钟时间有没有自己的课(D7:跨节次表以时间重叠判定)。
2. **当日请假**:李师那一天那个时段自己是不是也请假了。
3. **当日已接手**:李师是不是已经被指派代别班、或调课到那个时段。

M4-4 的今日看板、M4-2 的代课推荐都建立在这一层上。判断一律用墙钟时间区间,
不用 period_no——不同节次表的「第二节」时间不同(D7)。

单双周(v1.3.0):周课表里单周/双周的课,只在对应的那一周算「有课」。
"""

from dataclasses import dataclass
from datetime import date, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.week_parity import runs_in_week, week_parity
from app.models.assignment import AssignmentTeacher, CourseAssignment
from app.models.leave import AffectedPeriod, AffectedStatus, LeaveRequest, LeaveStatus
from app.models.period import Period
from app.models.semester import Semester
from app.models.substitution import Substitution
from app.models.timetable import ScheduleEntry, Timetable, TimetableStatus
from app.services import period_tables as pt_service


@dataclass(frozen=True, slots=True)
class Interval:
    """某个上课时段的墙钟区间。缺起讫时间时退化为 period_no(单表学校的正确值)。"""

    weekday: int
    period_no: int
    start: time | None
    end: time | None

    def overlaps(self, other: "Interval") -> bool:
        if self.weekday != other.weekday:
            return False
        if self.start and self.end and other.start and other.end:
            return self.start < other.end and other.start < self.end
        # 任一方缺时间:退化为同节次号(单一节次表的学校天然如此)
        return self.period_no == other.period_no


@dataclass(frozen=True, slots=True)
class Conflict:
    """为什么这位教师那个时段不能用。"""

    kind: str  # teaching / on_leave / already_covering
    detail: str


def _window_covers(slot: Interval, begin: time | None, finish: time | None) -> bool:
    """slot 是否落在请假时间窗 [begin, finish] 内(None = 该端点不限,即整天/半天开放端)。"""
    if begin is None and finish is None:
        return True  # 整天假
    if slot.start is None or slot.end is None:
        return True  # 节次缺时间时保守视为涵盖(与 leaves 展开的保守策略一致)
    if finish is not None and slot.start >= finish:
        return False
    if begin is not None and slot.end <= begin:
        return False
    return True


def published_timetable(db: Session, semester_id: int) -> Timetable | None:
    return db.scalar(
        select(Timetable).where(
            Timetable.semester_id == semester_id,
            Timetable.status == TimetableStatus.published.value,
        )
    )


class Availability:
    """一个学期的可用性查询器。批次捞好课表/请假/处置,供推荐引擎逐一比对。

    只建构一次、重复查询:代课推荐要对全校教师逐一判断同一个时段。
    """

    def __init__(self, db: Session, semester_id: int, timetable: Timetable | None = None) -> None:
        self.db = db
        self.semester_id = semester_id
        self.timetable = timetable or published_timetable(db, semester_id)
        # 每位教师的授课时段,附上周别(None = 每周;odd/even = 只上单周/双周)
        self._teaching: dict[int, list[tuple[Interval, str | None]]] | None = None
        self._table_periods: dict[int, dict[tuple[int, int], Period]] = {}
        semester = db.get(Semester, semester_id)
        self.semester_start = semester.start_date if semester else None

    def week_of(self, when: date | None) -> str | None:
        """when 是单周还是双周(学期第一周为单周);不知道日期时回 None。"""
        return week_parity(self.semester_start, when) if when else None

    def entry_runs_on(self, entry: ScheduleEntry, when: date) -> bool:
        """这一格的课在 when 那一周有没有上:单双周的课只在对应的那一周。"""
        a = self.db.get(CourseAssignment, entry.course_assignment_id)
        return runs_in_week(a.week_parity if a else None, self.week_of(when))

    # ── 周课表:每位教师的授课时段(墙钟区间)──
    def _teaching_map(self) -> dict[int, list[tuple[Interval, str | None]]]:
        if self._teaching is not None:
            return self._teaching
        result: dict[int, list[tuple[Interval, str | None]]] = {}
        if self.timetable is None:
            self._teaching = result
            return result

        rows = self.db.execute(
            select(
                ScheduleEntry.weekday, ScheduleEntry.period_no, ScheduleEntry.span,
                CourseAssignment.id, AssignmentTeacher.teacher_id, CourseAssignment.week_parity,
            )
            .join(CourseAssignment, ScheduleEntry.course_assignment_id == CourseAssignment.id)
            .join(AssignmentTeacher, AssignmentTeacher.course_assignment_id == CourseAssignment.id)
            .where(ScheduleEntry.timetable_id == self.timetable.id)
        ).all()

        for weekday, period_no, span, a_id, teacher_id, parity in rows:
            table_id = self._table_of_assignment(a_id)
            for k in range(span):
                p = self._period(table_id, weekday, period_no + k) if table_id else None
                result.setdefault(teacher_id, []).append((Interval(
                    weekday, period_no + k,
                    p.start_time if p else None, p.end_time if p else None,
                ), parity))
        self._teaching = result
        return result

    def _table_of_assignment(self, assignment_id: int) -> int | None:
        a = self.db.get(CourseAssignment, assignment_id)
        if a is None or not a.scheduling_unit.members:
            return None
        table = pt_service.resolve_period_table(self.db, a.scheduling_unit.members[0].class_unit)
        return table.id if table else None

    def _period(self, table_id: int, weekday: int, period_no: int) -> Period | None:
        if table_id not in self._table_periods:
            rows = self.db.scalars(select(Period).where(Period.period_table_id == table_id))
            self._table_periods[table_id] = {(p.weekday, p.period_no): p for p in rows}
        return self._table_periods[table_id].get((weekday, period_no))

    # ── 当日请假:该教师自己那天那个时段是否也请假 ──
    def _on_leave(self, teacher_id: int, when: date, slot: Interval) -> bool:
        """该教师在 when 这天的 slot 时段是否请假。

        **必须读假单本身的日期/时间窗,不是展开的 affected_period。**
        后者只在「有课的节次」才存在——一位老师请整天假、而该节恰好是他的空堂时,
        affected_period 不会涵盖那一格,但他人确实不在,不能被找来代课。
        """
        rows = self.db.execute(
            select(LeaveRequest.start_date, LeaveRequest.start_time,
                   LeaveRequest.end_date, LeaveRequest.end_time)
            .where(
                LeaveRequest.teacher_id == teacher_id,
                LeaveRequest.status == LeaveStatus.registered.value,
                LeaveRequest.start_date <= when,
                LeaveRequest.end_date >= when,
            )
        ).all()
        for start_date, start_time, end_date, end_time in rows:
            # 只有假期头尾两天受时间限制,中间整天(与 leaves.expand 同一套语意)
            begin = start_time if when == start_date else None
            finish = end_time if when == end_date else None
            if _window_covers(slot, begin, finish):
                return True
        return False

    # ── 当日已接手:已被指派代别班/调课到那个时段 ──
    def _already_covering(self, teacher_id: int, when: date, slot: Interval) -> Interval | None:
        # (a) 身为其他受影响节次的代课/接手者
        rows = self.db.execute(
            select(AffectedPeriod.weekday, AffectedPeriod.period_no,
                   AffectedPeriod.start_time, AffectedPeriod.end_time)
            .join(LeaveRequest, AffectedPeriod.leave_request_id == LeaveRequest.id)
            .where(
                AffectedPeriod.handler_teacher_id == teacher_id,
                AffectedPeriod.status == AffectedStatus.resolved.value,
                LeaveRequest.status == LeaveStatus.registered.value,
                AffectedPeriod.date == when,
            )
        ).all()
        for weekday, period_no, start, end in rows:
            other = Interval(weekday, period_no, start, end)
            if slot.overlaps(other):
                return other
        # (b) 身为调课的补课者(swap 的甲方,补在 swap_date)。
        # **补课方是该笔调课「请假的当事人」**,不是 handler(乙);必须以
        # AffectedPeriod→LeaveRequest.teacher_id 比对,否则会把全校在该时段都误判为已占用。
        swaps = self.db.execute(
            select(Substitution.swap_period_no)
            .join(AffectedPeriod, Substitution.affected_period_id == AffectedPeriod.id)
            .join(LeaveRequest, AffectedPeriod.leave_request_id == LeaveRequest.id)
            .where(
                Substitution.swap_date == when,
                LeaveRequest.teacher_id == teacher_id,
                LeaveRequest.status == LeaveStatus.registered.value,
                AffectedPeriod.status != AffectedStatus.cancelled.value,
            )
        ).all()
        for (swap_period_no,) in swaps:
            if swap_period_no == slot.period_no:  # 调课补课以节次号记录
                return Interval(slot.weekday, swap_period_no, None, None)
        return None

    # ── 对外:某教师某时段能不能用 ──
    def slot_of(self, affected: AffectedPeriod) -> Interval:
        return Interval(affected.weekday, affected.period_no,
                        affected.start_time, affected.end_time)

    def entry_period(self, entry: ScheduleEntry, period_no: int | None = None) -> Period | None:
        """课表格位的某一节在其班级节次表里的那一节(取名称、类型与起讫时间用)。

        `period_no` 为空取起始节次;连堂格位可指定其中任一节。
        """
        table_id = self._table_of_assignment(entry.course_assignment_id)
        no = entry.period_no if period_no is None else period_no
        return self._period(table_id, entry.weekday, no) if table_id else None

    def entry_slot(self, entry: ScheduleEntry, period_no: int | None = None) -> Interval:
        """课表格位某一节的墙钟区间;节次表查不到时退化为节次号。"""
        no = entry.period_no if period_no is None else period_no
        p = self.entry_period(entry, no)
        return Interval(entry.weekday, no,
                        p.start_time if p else None, p.end_time if p else None)

    def is_on_leave(self, teacher_id: int, when: date, slot: Interval) -> bool:
        return self._on_leave(teacher_id, when, slot)

    def teaching_at(
        self, teacher_id: int, slot: Interval, when: date | None = None
    ) -> Interval | None:
        """该教师在 slot 时段有没有自己的课;给了日期时,单双周的课只看那一周。"""
        week = self.week_of(when)
        for iv, parity in self._teaching_map().get(teacher_id, []):
            if iv.overlaps(slot) and runs_in_week(parity, week):
                return iv
        return None

    def conflict_for(self, teacher_id: int, when: date, slot: Interval) -> Conflict | None:
        """该教师在 when 这一天的 slot 时段,有没有不能来的理由(回第一个)。"""
        if self.teaching_at(teacher_id, slot, when) is not None:
            return Conflict("teaching", "该时段有自己的课")
        if self._on_leave(teacher_id, when, slot):
            return Conflict("on_leave", "当天也请假")
        if self._already_covering(teacher_id, when, slot) is not None:
            return Conflict("already_covering", "已被安排代其他课")
        return None

    def is_free(self, teacher_id: int, when: date, slot: Interval) -> bool:
        return self.conflict_for(teacher_id, when, slot) is None

    def teaches_on(self, teacher_id: int, weekday: int, when: date | None = None) -> bool:
        """该教师在某星期是否有课——用来判断『当天已在校』(免多跑一趟)。"""
        week = self.week_of(when)
        return any(
            iv.weekday == weekday and runs_in_week(parity, week)
            for iv, parity in self._teaching_map().get(teacher_id, [])
        )
