"""调课:可对调节次的搜寻与逐项检查(v1.2.1)。

调课的语意见 `models/substitution.py`:甲请假那节由乙来上,甲之后补乙的一节。
后端 M4-2 只会「验」组长选好的组合;但组长不会自己去翻乙哪一节、哪一天能换——
这里替他列出请假那周起**数周内**(默认两周,最多四周)所有真的换得成的组合。

**列出的与送出时验的必须是同一套规则**,否则清单上点得到、按下去却被拒绝。
所以逐项检查集中在 `SwapChecker`,`substitutions._validate_swap` 也呼叫它。
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.models.assignment import AssignmentTeacher, CourseAssignment, SchedulingUnitMember
from app.models.basedata import Teacher
from app.models.leave import AffectedPeriod, AffectedStatus, LeaveRequest, LeaveStatus
from app.models.period import PeriodType
from app.models.semester import Semester
from app.models.substitution import Substitution, SubstitutionType
from app.models.timetable import ScheduleEntry
from app.services.availability import Availability


def _period_label(av: Availability, entry: ScheduleEntry, period_no: int) -> str:
    p = av.entry_period(entry, period_no)
    return p.name if p else f"第 {period_no} 格"


def block_periods(av: Availability, entry: ScheduleEntry) -> list[int]:
    """格位占用的每一节中,可以拿来对调的节次号。

    连堂一次占好几节,但补课是一节换一节:乙连堂中的任一节都可以单独换给甲补,
    其余几节照常由乙上。跳过非一般课的节次(与 leaves.expand 展开连堂的规则一致)。
    """
    out = []
    for no in range(entry.period_no, entry.period_no + entry.span):
        p = av.entry_period(entry, no)
        if p is None or p.type == PeriodType.regular.value:
            out.append(no)
    return out


class SwapChecker:
    """针对一个受影响节次,检查「乙能不能来」与「某一节能不能拿来换」。

    同一次搜寻会对很多组合反复问同样的问题(甲某天某节有没有空),故查询结果快取在实例上。
    """

    def __init__(self, db: Session, affected: AffectedPeriod, av: Availability) -> None:
        self.db = db
        self.affected = affected
        self.av = av
        self.absent: Teacher = affected.leave_request.teacher
        self.semester = db.get(Semester, affected.semester_id)
        self._taken: set[tuple[int, date, int]] | None = None

    def partner_blocker(self, partner: Teacher) -> str | None:
        """乙在甲请假那节能不能来上课(自己有课、也请假、已被安排代别班都不行)。"""
        a = self.affected
        conflict = self.av.conflict_for(partner.id, a.date, self.av.slot_of(a))
        if conflict is None:
            return None
        return f"{partner.name} {a.date} {a.period_name} {conflict.detail}"

    def _taken_slots(self) -> set[tuple[int, date, int]]:
        """已经被其他有效调课拿去换的 (乙的格位, 日期, 节次)。同一节课不能换给两个人补。"""
        if self._taken is None:
            rows = self.db.execute(
                select(Substitution.swap_entry_id, Substitution.swap_date,
                       Substitution.swap_period_no)
                .join(AffectedPeriod, Substitution.affected_period_id == AffectedPeriod.id)
                .join(LeaveRequest, AffectedPeriod.leave_request_id == LeaveRequest.id)
                .where(
                    Substitution.semester_id == self.affected.semester_id,
                    Substitution.type == SubstitutionType.swap.value,
                    Substitution.affected_period_id != self.affected.id,
                    AffectedPeriod.status != AffectedStatus.cancelled.value,
                    LeaveRequest.status == LeaveStatus.registered.value,
                )
            ).all()
            self._taken = {
                (e, d, n) for e, d, n in rows if e is not None and d is not None and n is not None
            }
        return self._taken

    def option_blocker(
        self, partner: Teacher, entry: ScheduleEntry, when: date, period_no: int
    ) -> str | None:
        """乙的 `entry` 格位中第 `period_no` 节,在 `when` 这天能不能改由甲来补。"""
        pname = _period_label(self.av, entry, period_no)
        slot = self.av.entry_slot(entry, period_no)
        sem = self.semester
        if sem is not None and (
            (sem.start_date and when < sem.start_date) or (sem.end_date and when > sem.end_date)
        ):
            return f"{when} 不在学期期间内"
        if clock.is_past_slot(when, slot.end):
            return f"{when} {pname} 已经上过,无法补课"
        if self.av.is_on_leave(partner.id, when, slot):
            return f"{partner.name} {when} {pname} 也请假,这节课本身就需要安排,不能拿来对调"
        if (entry.id, when, period_no) in self._taken_slots():
            return f"{partner.name} {when} {pname} 这节已经和别的老师调课了"
        conflict = self.av.conflict_for(self.absent.id, when, slot)
        if conflict is not None:
            return f"{self.absent.name} 无法在 {when} {pname} 补课:{conflict.detail}"
        return None


# ── 搜寻 ─────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SwapOption:
    entry_id: int
    date: date
    weekday: int
    period_no: int
    period_name: str
    class_names: str
    subject_name: str
    same_class: bool  # 与请假那节是同一班(真正的「同班互调」,学生只是两科前后对换)
    in_block: bool    # 是连堂中的一节(只换这一节,其余照常由乙上)


@dataclass
class SwapPartner:
    teacher_id: int
    teacher_name: str
    teaches_same_class: bool
    blocked_reason: str = ""  # 非空 = 乙本身在请假那节就来不了,options 必为空
    options: list[SwapOption] = field(default_factory=list)


@dataclass
class SwapSearch:
    affected_period_id: int
    date_from: date
    date_to: date
    partners: list[SwapPartner] = field(default_factory=list)


DEFAULT_WEEKS = 2
MAX_WEEKS = 4


def search_window(on: date, weeks: int = DEFAULT_WEEKS) -> tuple[date, date]:
    """请假那天所在周的周一,往后共 `weeks` 周(到最后一周的周日)。

    默认两周(当周互调或和下周调);使用学校实务上常有隔周、甚至「本周与隔三周」对调,
    故最多开到四周。范围再大,清单会长到组长找不到要的那一节。
    """
    weeks = max(1, min(weeks, MAX_WEEKS))
    monday = on - timedelta(days=on.isoweekday() - 1)
    return monday, monday + timedelta(days=7 * weeks - 1)


def _class_ids_of(db: Session, assignment_id: int | None) -> set[int]:
    if assignment_id is None:
        return set()
    a = db.get(CourseAssignment, assignment_id)
    return {m.class_unit_id for m in a.scheduling_unit.members} if a else set()


def _same_class_teacher_ids(
    db: Session, timetable_id: int, class_ids: set[int], exclude: int
) -> set[int]:
    """已发布课表中,也在这些班级上课的教师。"""
    if not class_ids:
        return set()
    rows = db.execute(
        select(AssignmentTeacher.teacher_id)
        .join(CourseAssignment, AssignmentTeacher.course_assignment_id == CourseAssignment.id)
        .join(SchedulingUnitMember,
              SchedulingUnitMember.scheduling_unit_id == CourseAssignment.scheduling_unit_id)
        .join(ScheduleEntry, ScheduleEntry.course_assignment_id == CourseAssignment.id)
        .where(
            ScheduleEntry.timetable_id == timetable_id,
            SchedulingUnitMember.class_unit_id.in_(class_ids),
        )
    ).all()
    return {r[0] for r in rows} - {exclude}


def search(
    db: Session,
    affected: AffectedPeriod,
    *,
    teacher_id: int | None = None,
    weeks: int = DEFAULT_WEEKS,
    availability: Availability | None = None,
) -> SwapSearch:
    """列出可对调的节次。

    `teacher_id` 为空时只找「也教这个班」的老师(最常见的同班互调);
    指定时只看那一位(组长心里已经有人选)。
    """
    av = availability or Availability(db, affected.semester_id)
    date_from, date_to = search_window(affected.date, weeks)
    result = SwapSearch(affected_period_id=affected.id, date_from=date_from, date_to=date_to)
    if av.timetable is None:
        return result

    checker = SwapChecker(db, affected, av)
    class_ids = _class_ids_of(db, affected.course_assignment_id)
    same_class_ids = _same_class_teacher_ids(
        db, av.timetable.id, class_ids, exclude=checker.absent.id)

    if teacher_id is not None:
        ids = {teacher_id} - {checker.absent.id}
    else:
        ids = same_class_ids
    if not ids:
        return result
    partners = db.scalars(
        select(Teacher).where(
            Teacher.id.in_(ids),
            Teacher.semester_id == affected.semester_id,
            Teacher.is_active.is_(True),
        ).order_by(Teacher.name)
    ).all()

    dates = [date_from + timedelta(days=i) for i in range((date_to - date_from).days + 1)]
    for partner in partners:
        sp = SwapPartner(
            teacher_id=partner.id, teacher_name=partner.name,
            teaches_same_class=partner.id in same_class_ids,
        )
        result.partners.append(sp)
        blocked = checker.partner_blocker(partner)
        if blocked is not None:
            sp.blocked_reason = blocked
            continue

        entries = db.scalars(
            select(ScheduleEntry)
            .join(AssignmentTeacher,
                  AssignmentTeacher.course_assignment_id == ScheduleEntry.course_assignment_id)
            .where(
                ScheduleEntry.timetable_id == av.timetable.id,
                AssignmentTeacher.teacher_id == partner.id,
            )
        ).unique().all()
        for entry in entries:
            a = db.get(CourseAssignment, entry.course_assignment_id)
            if a is None:
                continue
            entry_classes = {m.class_unit_id for m in a.scheduling_unit.members}
            class_names = "、".join(m.class_unit.name for m in a.scheduling_unit.members)
            for when in dates:
                if when.isoweekday() != entry.weekday or not av.entry_runs_on(entry, when):
                    continue
                for no in block_periods(av, entry):
                    if when == affected.date and no == affected.period_no:
                        continue
                    if checker.option_blocker(partner, entry, when, no) is not None:
                        continue
                    sp.options.append(SwapOption(
                        entry_id=entry.id, date=when, weekday=entry.weekday,
                        period_no=no, period_name=_period_label(av, entry, no),
                        class_names=class_names,
                        subject_name=a.subject.name if a.subject else "",
                        same_class=bool(entry_classes & class_ids),
                        in_block=entry.span > 1,
                    ))
        sp.options.sort(key=lambda o: (not o.same_class, o.date, o.period_no))

    # 有得换的排前面;同班老师优先
    result.partners.sort(key=lambda p: (
        not p.options, not p.teaches_same_class, p.teacher_name))
    return result
