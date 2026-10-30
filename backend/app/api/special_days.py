"""特殊日课表 API,编辑器放在排课中心里,不另设菜单。

权限:读取 = 所有已登录且完成改密者;写入 = 年级主任/管理员,
且年级权限按现有规则:管理员全校,年级主任只能本年级。
全校范围规则只有管理员能建(主任建全校规则会越级影响别的年级)。
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import get_active_user, require_roles
from app.core.db import get_db
from app.models.assignment import CourseAssignment, SchedulingUnitMember
from app.models.basedata import ClassUnit
from app.models.semester import Semester
from app.models.special_day import SpecialDayEntry, SpecialDayRule
from app.models.user import Role, User
from app.schemas.special_day import (
    SpecialDayEntryIn,
    SpecialDayExpandedOut,
    SpecialDayRuleCreate,
    SpecialDayRuleOut,
    SpecialDayRuleUpdate,
)
from app.services import grade_scopes
from app.services.special_days import (
    load_active_rules,
    load_holidays,
    overrides_for_date,
)

router = APIRouter(tags=["special-days"])

editor = require_roles(Role.director)


def _get_semester(db: Session, semester_id: int) -> Semester:
    semester = db.get(Semester, semester_id)
    if semester is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到学期")
    return semester


def _get_rule(db: Session, rule_id: int) -> SpecialDayRule:
    rule = db.get(SpecialDayRule, rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到特殊日规则")
    return rule


def _check_write(db: Session, user: User, scope_type: str, scope_id: int | None,
                 entry_grades: set[int]) -> None:
    """写拦截:全校范围只限管理员;年级范围与条目年级都须在帐号范围内。"""
    allowed = grade_scopes.allowed_grades(db, user)
    if allowed is None:
        return
    if scope_type == "school":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "全校范围的特殊日规则只有管理员能建",
        )
    if scope_id is not None:
        grade_scopes.require_grades(db, user, {scope_id})
    if entry_grades:
        grade_scopes.require_grades(db, user, entry_grades)


def _validate_entries(db: Session, semester: Semester, rule_scope_type: str,
                      rule_scope_id: int | None,
                      entries: list[SpecialDayEntryIn]) -> None:
    """条目校验:班级属本学期、年级规则的班须是该年级、配课属本学期且其单位含本班。"""
    for e in entries:
        cls = db.get(ClassUnit, e.class_unit_id)
        if cls is None or cls.semester_id != semester.id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "条目班级不是该学期的班级",
            )
        if rule_scope_type == "grade" and cls.grade != rule_scope_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "年级规则的条目只能是该年级的班级",
            )
        if e.course_assignment_id is not None:
            assignment = db.get(CourseAssignment, e.course_assignment_id)
            if assignment is None or assignment.semester_id != semester.id:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, "条目配课不是该学期的配课",
                )
            member = db.scalar(
                select(SchedulingUnitMember).where(
                    SchedulingUnitMember.scheduling_unit_id == assignment.scheduling_unit_id,
                    SchedulingUnitMember.class_unit_id == e.class_unit_id,
                )
            )
            if member is None:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, "条目配课不教该班级",
                )


def _entry_grades(db: Session, entries: list[SpecialDayEntryIn]) -> set[int]:
    grades: set[int] = set()
    for e in entries:
        cls = db.get(ClassUnit, e.class_unit_id)
        if cls is not None:
            grades.add(cls.grade)
    return grades


def _apply_entries(db: Session, rule: SpecialDayRule, entries: list[SpecialDayEntryIn]) -> None:
    for old in list(rule.entries):
        db.delete(old)
    db.flush()
    for e in entries:
        db.add(SpecialDayEntry(
            rule_id=rule.id, class_unit_id=e.class_unit_id,
            period_no=e.period_no, course_assignment_id=e.course_assignment_id,
        ))


@router.get("/special-days", response_model=list[SpecialDayRuleOut])
def list_rules(
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_active_user),
):
    _get_semester(db, semester_id)
    return db.scalars(
        select(SpecialDayRule)
        .where(SpecialDayRule.semester_id == semester_id)
        .order_by(SpecialDayRule.id)
    ).all()


@router.post("/special-days", response_model=SpecialDayRuleOut, status_code=status.HTTP_201_CREATED)
def create_rule(
    body: SpecialDayRuleCreate,
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(editor),
):
    semester = _get_semester(db, semester_id)
    _check_write(db, user, body.scope_type, body.scope_id, _entry_grades(db, body.entries))
    _validate_entries(db, semester, body.scope_type, body.scope_id, body.entries)
    # 周期默认本学期:没给起止日就取学期起止日
    start = body.start_date if body.start_date is not None else semester.start_date
    end = body.end_date if body.end_date is not None else semester.end_date
    rule = SpecialDayRule(
        semester_id=semester.id, title=body.title,
        scope_type=body.scope_type, scope_id=body.scope_id if body.scope_type == "grade" else None,
        recurrence=body.recurrence, single_date=body.single_date,
        weekday=body.weekday, day_of_month=body.day_of_month,
        start_date=start, end_date=end, is_active=False, created_by=user.id,
    )
    db.add(rule)
    db.flush()
    _apply_entries(db, rule, body.entries)
    db.commit()
    db.refresh(rule)
    return rule


@router.patch("/special-days/{rule_id}", response_model=SpecialDayRuleOut)
def update_rule(
    rule_id: int,
    body: SpecialDayRuleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(editor),
):
    rule = _get_rule(db, rule_id)
    data = body.model_dump(exclude_unset=True)
    new_scope = data.get("scope_type", rule.scope_type)
    new_scope_id = data["scope_id"] if "scope_id" in data else rule.scope_id
    entry_grades = {c.grade for c in (
        db.get(ClassUnit, e.class_unit_id) for e in rule.entries
    ) if c is not None}
    _check_write(db, user, new_scope, new_scope_id, entry_grades)
    if new_scope == "school":
        new_scope_id = None
    for key, value in data.items():
        if key in ("scope_type", "scope_id"):
            continue
        setattr(rule, key, value)
    rule.scope_type = new_scope
    rule.scope_id = new_scope_id
    # 合并后仍须满足周期必填(只改标题等不影响周期字段时,既有值已满足)
    if rule.recurrence == "single" and rule.single_date is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "单次规则必须提供 single_date")
    if rule.recurrence == "weekly" and rule.weekday is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "每周规则必须提供 weekday")
    if rule.recurrence == "monthly" and rule.day_of_month is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "每月规则必须提供 day_of_month")
    if rule.start_date and rule.end_date and rule.end_date < rule.start_date:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "结束日期不可早于开始日期")
    db.commit()
    db.refresh(rule)
    return rule


@router.put("/special-days/{rule_id}/entries", response_model=SpecialDayRuleOut)
def replace_entries(
    rule_id: int,
    entries: list[SpecialDayEntryIn],
    db: Session = Depends(get_db),
    user: User = Depends(editor),
):
    rule = _get_rule(db, rule_id)
    semester = _get_semester(db, rule.semester_id)
    _check_write(db, user, rule.scope_type, rule.scope_id, _entry_grades(db, entries))
    _validate_entries(db, semester, rule.scope_type, rule.scope_id, entries)
    seen: set[tuple[int, int]] = set()
    for e in entries:
        key = (e.class_unit_id, e.period_no)
        if key in seen:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "同一班级同一节次不可重复")
        seen.add(key)
    _apply_entries(db, rule, entries)
    db.commit()
    db.refresh(rule)
    return rule


@router.post("/special-days/{rule_id}/publish", response_model=SpecialDayRuleOut)
def publish_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(editor),
):
    rule = _get_rule(db, rule_id)
    _check_write(db, user, rule.scope_type, rule.scope_id, set())
    rule.is_active = True
    db.commit()
    db.refresh(rule)
    return rule


@router.post("/special-days/{rule_id}/unpublish", response_model=SpecialDayRuleOut)
def unpublish_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(editor),
):
    rule = _get_rule(db, rule_id)
    _check_write(db, user, rule.scope_type, rule.scope_id, set())
    rule.is_active = False
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/special-days/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(editor),
):
    rule = _get_rule(db, rule_id)
    _check_write(db, user, rule.scope_type, rule.scope_id, set())
    db.delete(rule)
    db.commit()


@router.get("/special-days/expanded", response_model=list[SpecialDayExpandedOut])
def expanded(
    semester_id: int = Query(...),
    from_date: date = Query(...),
    to_date: date = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_active_user),
):
    """仪表板本周课表覆盖显示:某日期区间内已发布特殊日的逐日结果(已扣放假)。"""
    _get_semester(db, semester_id)
    classes = {
        c.id: c for c in db.scalars(
            select(ClassUnit).where(ClassUnit.semester_id == semester_id)
        ).all()
    }
    rules = load_active_rules(db, semester_id)
    holidays = load_holidays(db, semester_id)
    out: list[SpecialDayExpandedOut] = []
    d = from_date
    while d <= to_date:
        day_overrides = overrides_for_date(rules, classes, holidays, d)
        for (class_id, period_no), ov in sorted(day_overrides.items()):
            cls = classes[class_id]
            subject_name = None
            teacher_names: list[str] = []
            if ov.course_assignment_id is not None:
                assignment = db.get(CourseAssignment, ov.course_assignment_id)
                if assignment is not None:
                    subject_name = assignment.subject.name if assignment.subject else None
                    teacher_names = [
                        at.teacher.name for at in assignment.teachers if at.teacher is not None
                    ]
            out.append(SpecialDayExpandedOut(
                date=d, class_unit_id=class_id, class_name=cls.name,
                period_no=period_no, rule_id=ov.rule_id,
                course_assignment_id=ov.course_assignment_id,
                subject_name=subject_name, teacher_names=teacher_names,
            ))
        d += timedelta(days=1)
    return out
