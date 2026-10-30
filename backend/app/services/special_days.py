"""特殊日展开:主课表 -> 特殊日替换 -> 请假调代课(后者在 teaching_hours 里接)。

展开顺序(已定口径):
1. 主课表按周模板展开;
2. 已发布(is_active)特殊日替换,未填节次沿用主课表;
3. 放假优先:校历放假的班级×节次,特殊日不生效(主课表那节本来就因放假不上,
   故放假检查在特殊日之前,两者都不产出那节的课);
4. 同天同节冲突:单次 > 每周 > 每月,高优先级覆盖低优先级;
5. 请假调代课按换好课之后的最新课程算:teaching_hours 先算特殊日覆盖后的格位,
   再跑请假调代课异动,故 leave overlay 天然作用在覆盖后的格位上。

本模块只做纯展开(不碰提醒发送与课时统计的口径),供三处共用:
- teaching_hours.compute(课时)
- class_reminders.run_class_reminders(提醒)
- API expanded 端点(仪表板本周课表覆盖显示)
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assignment import CourseAssignment, SchedulingUnitMember
from app.models.basedata import ClassUnit
from app.models.calendar import SchoolCalendarEvent
from app.models.special_day import SpecialDayRule

PRIORITY = {"monthly": 1, "weekly": 2, "single": 3}


@dataclass
class Override:
    """某班某节在某天的特殊日结果。assignment_id 为 None = 该节取消。"""

    rule_id: int
    class_unit_id: int
    period_no: int
    course_assignment_id: int | None


def rule_matches_date(rule: SpecialDayRule, on: date) -> bool:
    """规则在某天是否生效(不含放假判断,放假由调用方按班级×节次另判)。"""
    if rule.start_date is not None and on < rule.start_date:
        return False
    if rule.end_date is not None and on > rule.end_date:
        return False
    if rule.recurrence == "single":
        return rule.single_date == on
    if rule.recurrence == "weekly":
        return rule.weekday == on.isoweekday()
    if rule.recurrence == "monthly":
        return rule.day_of_month == on.day
    return False


def _is_holiday(
    holidays: list[SchoolCalendarEvent],
    grade: int,
    class_id: int,
    on: date,
    period_no: int,
) -> bool:
    for ev in holidays:
        if not (ev.start_date <= on <= ev.end_date):
            continue
        if ev.period_start is not None and not (
            ev.period_start <= period_no <= (ev.period_end or ev.period_start)
        ):
            continue
        if ev.scope_type == "school":
            return True
        if ev.scope_type == "grade" and ev.scope_id == grade:
            return True
        if ev.scope_type == "class" and ev.scope_id == class_id:
            return True
    return False


def load_active_rules(db: Session, semester_id: int) -> list[SpecialDayRule]:
    """某学期全部已发布规则(含条目,entries 已 selectin)。"""
    return db.scalars(
        select(SpecialDayRule).where(
            SpecialDayRule.semester_id == semester_id,
            SpecialDayRule.is_active.is_(True),
        )
    ).all()


def load_holidays(db: Session, semester_id: int) -> list[SchoolCalendarEvent]:
    return db.scalars(
        select(SchoolCalendarEvent).where(
            SchoolCalendarEvent.semester_id == semester_id,
            SchoolCalendarEvent.event_type == "holiday",
            SchoolCalendarEvent.weekly_recurring.is_(False),
        )
    ).all()


def overrides_for_date(
    rules: list[SpecialDayRule],
    classes_by_id: dict[int, ClassUnit],
    holidays: list[SchoolCalendarEvent],
    on: date,
) -> dict[tuple[int, int], Override]:
    """某天全部特殊日覆盖,(class_id, period_no) -> Override。

    规则按优先级从低到高应用,高优先级覆盖低优先级;范围不符的条目跳过
    (年级规则只对其年级的班生效);放假的班×节跳过(放假优先)。
    """
    out: dict[tuple[int, int], Override] = {}
    for rule in sorted(rules, key=lambda r: PRIORITY.get(r.recurrence, 0)):
        # 未发布规则不参与展开(调用方多半已只传已发布者,这里再守一层,防直接传全量)
        if not rule.is_active:
            continue
        if not rule_matches_date(rule, on):
            continue
        for entry in rule.entries:
            cls = classes_by_id.get(entry.class_unit_id)
            if cls is None:
                continue
            if rule.scope_type == "grade" and rule.scope_id != cls.grade:
                continue
            if _is_holiday(holidays, cls.grade, cls.id, on, entry.period_no):
                continue
            out[(entry.class_unit_id, entry.period_no)] = Override(
                rule_id=rule.id,
                class_unit_id=entry.class_unit_id,
                period_no=entry.period_no,
                course_assignment_id=entry.course_assignment_id,
            )
    return out


def assignment_teachers(db: Session, assignment_id: int) -> list[int]:
    assignment = db.get(CourseAssignment, assignment_id)
    if assignment is None:
        return []
    return [at.teacher_id for at in assignment.teachers]


def assignment_classes(db: Session, assignment_id: int) -> list[ClassUnit]:
    rows = db.scalars(
        select(ClassUnit)
        .join(SchedulingUnitMember, SchedulingUnitMember.class_unit_id == ClassUnit.id)
        .join(
            CourseAssignment,
            CourseAssignment.scheduling_unit_id == SchedulingUnitMember.scheduling_unit_id,
        )
        .where(CourseAssignment.id == assignment_id)
    ).all()
    return list(rows)
