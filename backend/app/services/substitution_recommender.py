"""代课推荐(M4-2,architecture.md §5.3)。

回答「这一节该找谁代」。两段式:先**硬性过滤**(只留下那个特定日期真的能来的人),
再**排序**(同科目 > 当天已在校 > 本月代课课时少),每位候选附上为什么排这个位置。

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
    same_subject: bool       # 教这个科目
    at_school_that_day: bool  # 当天本来就有课(免多跑一趟)
    sub_periods_this_month: int  # 本月已代课节数(愈少愈优先,公平)
    reasons: tuple[str, ...]  # 为什么排这个位置(给人看)

    @property
    def sort_key(self) -> tuple:
        # 同科目最重要,其次当天在校,再者本月代课少者优先;同分以姓名稳定排序
        return (
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
    """教这个科目的教师 id。以科目『名称』比对(受影响节次存的是快照名称)。"""
    if not subject_name:
        return set()
    from app.models.basedata import Subject, teacher_subjects

    rows = db.execute(
        select(teacher_subjects.c.teacher_id)
        .join(Subject, Subject.id == teacher_subjects.c.subject_id)
        .join(Teacher, Teacher.id == teacher_subjects.c.teacher_id)
        .where(Teacher.semester_id == semester_id, Subject.name == subject_name)
    ).all()
    return {r[0] for r in rows}


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
        at_school = av.teaches_on(t.id, affected.weekday, affected.date)
        month_n = month_counts.get(t.id, 0)

        reasons: list[str] = []
        reasons.append("同科目教师" if same_subject else "非本科教师")
        if at_school:
            reasons.append("当天已在校")
        reasons.append(f"本月已代 {month_n} 节")

        rec.candidates.append(Candidate(
            teacher_id=t.id, teacher_name=t.name,
            same_subject=same_subject, at_school_that_day=at_school,
            sub_periods_this_month=month_n, reasons=tuple(reasons),
        ))

    rec.candidates.sort(key=lambda c: c.sort_key)
    if not rec.candidates:
        rec.no_candidate_hint = (
            f"该时段全校 {blocked} 位教师都无法代课,建议改采「并班」或「自习」"
        )
    return rec
