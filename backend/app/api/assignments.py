"""配课 API:排课单位(跑班群组)、配课 CRUD、课时/负载统计。

权限:读取 = 年级主任/教务主任;写入 = 年级主任(admin 一律通过)。
所有资源以 semester_id 为范围。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import require_roles
from app.core.db import get_db
from app.models.assignment import (
    BUNDLE_UNIT_TYPES,
    AssignmentTeacher,
    BlockRule,
    CourseAssignment,
    SchedulingUnit,
    SchedulingUnitType,
)
from app.models.basedata import ClassUnit, Room, Subject, Teacher
from app.models.semester import Semester
from app.models.user import Role, User
from app.services import grade_scopes
from app.schemas.assignment import (
    AlternateIn,
    AssignmentIn,
    AssignmentOut,
    ClassLoad,
    GroupIn,
    SchedulingUnitOut,
    TeacherLoad,
)
from app.services import assignments as svc

router = APIRouter(tags=["assignments"])

viewer = require_roles(Role.director)
editor = require_roles(Role.director)


def _require_semester(db: Session, semester_id: int) -> None:
    if db.get(Semester, semester_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到学期")


def _domain(exc: svc.DomainError) -> HTTPException:
    return HTTPException(exc.status_code, exc.message)


# ── 跑班群组 ──────────────────────────
@router.get("/scheduling-units", response_model=list[SchedulingUnitOut])
def list_groups(
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    _: object = Depends(viewer),
):
    """列出跑班群组(single 单班单位为内部用,不在此列出)。"""
    units = db.scalars(
        select(SchedulingUnit).where(
            SchedulingUnit.semester_id == semester_id,
            SchedulingUnit.unit_type == SchedulingUnitType.group.value,
        ).order_by(SchedulingUnit.name)
    ).all()
    return [svc.serialize_unit(u) for u in units]


@router.post(
    "/scheduling-units", response_model=SchedulingUnitOut, status_code=status.HTTP_201_CREATED
)
def create_group(
    body: GroupIn,
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(editor),
):
    _require_semester(db, semester_id)
    _group_grades = db.scalars(
        select(ClassUnit.grade).where(ClassUnit.id.in_(body.class_ids))
    ).all()
    grade_scopes.require_grades(db, user, set(_group_grades))
    try:
        unit = svc.create_group(db, semester_id, body.name, body.class_ids)
    except svc.DomainError as e:
        raise _domain(e) from e
    db.commit()
    db.refresh(unit)
    return svc.serialize_unit(unit)


@router.delete("/scheduling-units/{unit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(
    unit_id: int, db: Session = Depends(get_db), user: User = Depends(editor)
) -> None:
    """删除跑班群组或单双周组(连同组内的配课)。"""
    unit = db.get(SchedulingUnit, unit_id)
    if unit is None or unit.unit_type not in BUNDLE_UNIT_TYPES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到跑班群组或单双周组")
    grade_scopes.require_grades(db, user, grade_scopes.unit_grades(db, unit.id))
    db.delete(unit)  # 级联删除其配课
    db.commit()


# ── 单双周组(v1.3.0)────────────────────
@router.get("/alternate-units", response_model=list[SchedulingUnitOut])
def list_alternates(
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    _: object = Depends(viewer),
):
    units = db.scalars(
        select(SchedulingUnit).where(
            SchedulingUnit.semester_id == semester_id,
            SchedulingUnit.unit_type == SchedulingUnitType.alternate.value,
        ).order_by(SchedulingUnit.name)
    ).all()
    return [svc.serialize_unit(u) for u in units]


@router.post(
    "/alternate-units", response_model=SchedulingUnitOut, status_code=status.HTTP_201_CREATED
)
def create_alternate(
    body: AlternateIn,
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(editor),
):
    """建立单双周组:一个班,之后在组里配单周、双周各一笔课。"""
    _require_semester(db, semester_id)
    _cls = db.get(ClassUnit, body.class_id)
    if _cls is not None:
        grade_scopes.require_grades(db, user, {_cls.grade})
    try:
        unit = svc.create_alternate(db, semester_id, body.class_id, body.name)
    except svc.DomainError as e:
        raise _domain(e) from e
    db.commit()
    db.refresh(unit)
    return svc.serialize_unit(unit)


# ── 统计(需在 /assignments/{id} 之前注册)────
@router.get("/assignments/teacher-load", response_model=list[TeacherLoad])
def teacher_load(
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    _: object = Depends(viewer),
):
    return svc.teacher_loads(db, semester_id)


@router.get("/assignments/class-load", response_model=list[ClassLoad])
def class_load(
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    _: object = Depends(viewer),
):
    return svc.class_loads(db, semester_id)


# ── 配课 CRUD ─────────────────────────
@router.get("/assignments", response_model=list[AssignmentOut])
def list_assignments(
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    _: object = Depends(viewer),
):
    items = db.scalars(
        select(CourseAssignment).where(CourseAssignment.semester_id == semester_id)
        .order_by(CourseAssignment.id)
    ).all()
    return [svc.serialize_assignment(a) for a in items]


def _resolve_unit(db: Session, semester_id: int, body: AssignmentIn) -> SchedulingUnit:
    if body.class_id is not None:
        cu = db.get(ClassUnit, body.class_id)
        if cu is None or cu.semester_id != semester_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "班级无效或不属于本学期")
        return svc.get_or_create_single_unit(db, cu)
    unit = db.get(SchedulingUnit, body.scheduling_unit_id or -1)
    if unit is None or unit.semester_id != semester_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "排课单位无效或不属于本学期")
    return unit


def _validate_refs(db: Session, semester_id: int, body: AssignmentIn) -> None:
    subject = db.get(Subject, body.subject_id)
    if subject is None or subject.semester_id != semester_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "科目无效或不属于本学期")
    if body.room_id is not None:
        room = db.get(Room, body.room_id)
        if room is None or room.semester_id != semester_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "场地无效或不属于本学期")
    teacher_ids = [t.teacher_id for t in body.teachers]
    found = db.scalars(
        select(Teacher.id).where(
            Teacher.id.in_(teacher_ids), Teacher.semester_id == semester_id
        )
    ).all()
    if set(found) != set(teacher_ids):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "教师清单含无效或跨学期的教师")


def _check_week(db: Session, unit: SchedulingUnit, body: AssignmentIn, assignment_id: int | None):
    try:
        svc.check_week_parity(db, unit, body.week_parity, assignment_id)
    except svc.DomainError as e:
        raise _domain(e) from e


def _apply(db: Session, assignment: CourseAssignment, body: AssignmentIn) -> None:
    assignment.subject_id = body.subject_id
    assignment.week_parity = body.week_parity
    assignment.periods_per_week = body.periods_per_week
    assignment.required_room_type = (
        body.required_room_type.value if body.required_room_type else None
    )
    assignment.room_id = body.room_id
    assignment.lock_room = body.lock_room
    assignment.teachers.clear()
    assignment.block_rules.clear()
    db.flush()
    for t in body.teachers:
        assignment.teachers.append(
            AssignmentTeacher(teacher_id=t.teacher_id, is_lead=t.is_lead)
        )
    for b in body.block_rules:
        assignment.block_rules.append(
            BlockRule(block_size=b.block_size, count_per_week=b.count_per_week)
        )


def _check_overtime(db: Session, semester_id: int, body: AssignmentIn) -> None:
    """超课时上限检核。只看这次配到的教师——被移除的教师节数只会变少,不可能新违规。

    必须在 commit 之前呼叫,且要先 flush,统计才看得到这笔尚未提交的配课。
    """
    db.flush()
    try:
        svc.assert_within_overtime_limit(
            db, semester_id, {t.teacher_id for t in body.teachers}
        )
    except svc.DomainError as exc:
        db.rollback()
        raise _domain(exc) from exc


@router.post("/assignments", response_model=AssignmentOut, status_code=status.HTTP_201_CREATED)
def create_assignment(
    body: AssignmentIn,
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(editor),
):
    _require_semester(db, semester_id)
    _validate_refs(db, semester_id, body)
    unit = _resolve_unit(db, semester_id, body)
    grade_scopes.require_grades(db, user, grade_scopes.unit_grades(db, unit.id))
    _check_week(db, unit, body, None)
    assignment = CourseAssignment(
        semester_id=semester_id, scheduling_unit_id=unit.id, subject_id=body.subject_id,
        periods_per_week=body.periods_per_week,
    )
    db.add(assignment)
    db.flush()
    _apply(db, assignment, body)
    _check_overtime(db, semester_id, body)
    db.commit()
    db.refresh(assignment)
    return svc.serialize_assignment(assignment)


@router.get("/assignments/{assignment_id}", response_model=AssignmentOut)
def get_assignment(
    assignment_id: int, db: Session = Depends(get_db), _: object = Depends(viewer)
):
    a = db.get(CourseAssignment, assignment_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到配课")
    return svc.serialize_assignment(a)


@router.patch("/assignments/{assignment_id}", response_model=AssignmentOut)
def update_assignment(
    assignment_id: int,
    body: AssignmentIn,
    db: Session = Depends(get_db),
    user: User = Depends(editor),
):
    a = db.get(CourseAssignment, assignment_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到配课")
    grade_scopes.require_grades(db, user, grade_scopes.assignment_grades(db, a.id))
    _validate_refs(db, a.semester_id, body)
    unit = _resolve_unit(db, a.semester_id, body)
    grade_scopes.require_grades(db, user, grade_scopes.unit_grades(db, unit.id))
    _check_week(db, unit, body, a.id)
    a.scheduling_unit_id = unit.id
    _apply(db, a, body)
    _check_overtime(db, a.semester_id, body)
    db.commit()
    db.refresh(a)
    return svc.serialize_assignment(a)


@router.delete("/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_assignment(
    assignment_id: int, db: Session = Depends(get_db), user: User = Depends(editor)
) -> None:
    a = db.get(CourseAssignment, assignment_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到配课")
    grade_scopes.require_grades(db, user, grade_scopes.assignment_grades(db, a.id))
    db.delete(a)
    db.commit()
