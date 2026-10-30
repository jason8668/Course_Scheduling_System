"""代课推荐(M4-2,architecture.md §5.3)。

回答「这一节该找谁代」。两段式:先**硬性过滤**(只留下那个特定日期真的能来的人),
再**排序**(同年级 > 同科目 > 当天已在校 > 本月代课课时少),每位候选附上为什么排这个位置。
跨年级教师不被滤掉,只是排在后面——特殊情况仍可跨年级指派。

「年级」取自配课:教师的年级 = 他所教班级的年级(由配课的排课单位成员班推导);
受影响节次的年级 = 它原来那格课所教班级的年级(溯源 schedule_entry_id /
course_assignment_id,课表改版后对不上时退回空集合,即一律视为跨年级)。
硬性过滤一律经 `availability`——那里才知道「李师周三第二节空堂」不等于「11/11 他能代」
(他自己可能也请假、或已被指派代别班)。排序理由给人看,不是黑箱分数。
"""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.basedata import Teacher
from app.models.leave import AffectedPeriod, AffectedStatus
from app.models.substitution import Substitution
from app.services.availability import Availability


@dataclass(frozen=True, slots=True)
class Candidate:
    teacher_id: int
    teacher_name: str
    same_grade: bool         # 教受影响节次的年级(优先本年级,跨年级只排后面)
    same_subject: bool       # 教这个科目
    at_school_that_day: bool  # 当天本来就有课(免多跑一趟)
    sub_periods_this_month: int  # 本月已代课节数(愈少愈优先,公平)
    reasons: tuple[str, ...]  # 为什么排这个位置(给人看)

    @property
    def sort_key(self) -> tuple:
        # 同年级最重要,其次同科目,再者当天在校,再者本月代课少者优先;同分以姓名稳定排序
        return (
            0 if self.same_grade else 1,
            0 if self.same_subject else 1,
            0 if self.at_school_that_day else 1,
            self.sub_periods_this_month,
            self.teacher_name,
        )


@dataclass
class Recommendation:
    affected_period_id: int
    candidates: list[Candidate] = field(default_factory=list)
    # 全校无人可代时,给组长明确的下一步(并班/自习),而不是空清单
    no_candidate_hint: str = ""


def _subject_teacher_ids(db: Session, semester_id: int, subject_name: str) -> set[int]:
    """教这个科目的教师 id。以科目『名称』比对(受影响节次存的是快照名称)。
    档案 + 配课并集:档案空的教师按配课算本科(与年级的“档案优先、没填按
    配课推导”同款思路,但科目是并集而非整体替换——配课一改档案就自动
    同步,两者本应一致,并集只是给旧数据档案未补同步时兜底)。"""
    if not subject_name:
        return set()
    from app.models.basedata import Subject, teacher_subjects
    from app.services import teacher_subjects as _ts  # noqa: F811 - 与上面表名同名,模块用 _ts

    rows = db.execute(
        select(teacher_subjects.c.teacher_id)
        .join(Subject, Subject.id == teacher_subjects.c.subject_id)
        .join(Teacher, Teacher.id == teacher_subjects.c.teacher_id)
        .where(Teacher.semester_id == semester_id, Subject.name == subject_name)
    ).all()
    return {r[0] for r in rows} | _ts.assignment_subject_teacher_ids(db, semester_id, subject_name)


def _teacher_grades(db: Session, semester_id: int) -> dict[int, set[int]]:
    """每位教师所属的年级集合。

    档案优先:教师档案填了所属年级就以档案为准(整体替换,非并集——
    档案修正后,陈旧的配课推导年级不应继续残留);没填的沿用配课推导
    (配课的排课单位成员班的年级)。
    """
    from app.models.assignment import AssignmentTeacher, CourseAssignment, SchedulingUnitMember
    from app.models.basedata import ClassUnit
    from app.services.teacher_grades import teacher_grade_map

    rows = db.execute(
        select(AssignmentTeacher.teacher_id, ClassUnit.grade)
        .join(CourseAssignment, CourseAssignment.id == AssignmentTeacher.course_assignment_id)
        .join(SchedulingUnitMember, SchedulingUnitMember.scheduling_unit_id == CourseAssignment.scheduling_unit_id)
        .join(ClassUnit, ClassUnit.id == SchedulingUnitMember.class_unit_id)
        .where(CourseAssignment.semester_id == semester_id)
    ).all()
    out: dict[int, set[int]] = {}
    for teacher_id, grade in rows:
        out.setdefault(teacher_id, set()).add(grade)
    for teacher_id, grades in teacher_grade_map(db, semester_id).items():
        out[teacher_id] = grades
    return out


def _affected_grades(db: Session, affected: AffectedPeriod) -> set[int]:
    """受影响节次原来那格课所教班级的年级(溯源课表条目,改版后对不上则为空)。"""
    from app.models.timetable import ScheduleEntry

    entry = None
    if affected.schedule_entry_id is not None:
        entry = db.get(ScheduleEntry, affected.schedule_entry_id)
    if entry is None and affected.course_assignment_id is not None:
        entry = db.scalar(
            select(ScheduleEntry).where(
                ScheduleEntry.course_assignment_id == affected.course_assignment_id
            ).limit(1)
        )
    if entry is None or entry.assignment is None:
        return set()
    return {
        m.class_unit.grade
        for m in entry.assignment.scheduling_unit.members
        if m.class_unit is not None
    }


def _monthly_sub_counts(db: Session, semester_id: int, month_start: date) -> dict[int, int]:
    """本月各教师已计课时的代课节数(swap 的补课方也算一节)。"""
    counts: dict[int, int] = {}
    rows = db.execute(
        select(Substitution.handler_teacher_id, func.count())
        .join(AffectedPeriod, AffectedPeriod.id == Substitution.affected_period_id)
        .where(
            Substitution.semester_id == semester_id,
            Substitution.counts_toward_hours.is_(True),
            Substitution.handler_teacher_id.isnot(None),
            # 销假后 substitution 列仍在、但节次已取消——不能算进公平计数的幽灵代课
            # (与 M4-5 统计的 status != cancelled 过滤同口径)
            AffectedPeriod.status != AffectedStatus.cancelled.value,
            AffectedPeriod.date >= month_start,
            AffectedPeriod.date < _next_month(month_start),
        )
        .group_by(Substitution.handler_teacher_id)
    ).all()
    for teacher_id, n in rows:
        if teacher_id is None:  # 查询已过滤掉,这里只是让型别检查看得懂
            continue
        counts[teacher_id] = n
    return counts


def _next_month(d: date) -> date:
    return date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)


def recommend(
    db: Session,
    affected: AffectedPeriod,
    *,
    availability: Availability | None = None,
) -> Recommendation:
    """为一个受影响节次列出可代教师,已排序、附理由。"""
    semester_id = affected.semester_id
    av = availability or Availability(db, semester_id)
    slot = av.slot_of(affected)

    absent_teacher_id = affected.leave_request.teacher_id
    subject_teachers = _subject_teacher_ids(db, semester_id, affected.subject_name)
    grades_of_teacher = _teacher_grades(db, semester_id)
    affected_grades = _affected_grades(db, affected)
    month_counts = _monthly_sub_counts(db, semester_id, affected.date.replace(day=1))

    teachers = db.scalars(
        select(Teacher).where(Teacher.semester_id == semester_id, Teacher.is_active.is_(True))
        .order_by(Teacher.name)
    ).all()

    rec = Recommendation(affected_period_id=affected.id)
    blocked = 0
    for t in teachers:
        if t.id == absent_teacher_id:
            continue
        if av.conflict_for(t.id, affected.date, slot) is not None:
            blocked += 1
            continue

        same_subject = t.id in subject_teachers
        same_grade = bool(grades_of_teacher.get(t.id, set()) & affected_grades)
        at_school = av.teaches_on(t.id, affected.weekday, affected.date)
        month_n = month_counts.get(t.id, 0)

        reasons: list[str] = []
        reasons.append("同年级教师" if same_grade else "跨年级教师")
        reasons.append("同科目教师" if same_subject else "非本科教师")
        if at_school:
            reasons.append("当天已在校")
        reasons.append(f"本月已代 {month_n} 节")

        rec.candidates.append(Candidate(
            teacher_id=t.id, teacher_name=t.name,
            same_grade=same_grade, same_subject=same_subject,
            at_school_that_day=at_school,
            sub_periods_this_month=month_n, reasons=tuple(reasons),
        ))

    rec.candidates.sort(key=lambda c: c.sort_key)
    if not rec.candidates:
        rec.no_candidate_hint = (
            f"该时段全校 {blocked} 位教师都无法代课,建议改采「并班」或「自习」"
        )
    return rec
