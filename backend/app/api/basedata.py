"""基础资料 API:教师、科目、场地、班级。

权限:读取 = 教学组长/教务主任;写入 = 教学组长(admin 一律通过)。
所有资源以 semester_id 为范围。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import require_roles
from app.core.config import settings
from app.core.db import get_db
from app.core.security import hash_password
from app.models.assignment import AssignmentTeacher
from app.models.basedata import (
    ClassUnit,
    Room,
    Subject,
    Teacher,
    TeacherTimeRule,
    room_subjects,
    teacher_subjects,
)
from app.models.leave import LeaveRequest
from app.models.period import PeriodTable
from app.models.semester import Semester
from app.models.substitution import Substitution
from app.models.user import Role, User, UserRole
from app.schemas.basedata import (
    AccountActiveIn,
    BindableAccount,
    ClassUnitIn,
    ClassUnitOut,
    ResetPasswordIn,
    RoomIn,
    RoomOut,
    SubjectIn,
    SubjectOut,
    TeacherAccountIn,
    TeacherAccountOut,
    TeacherDeleteImpact,
    TeacherIn,
    TeacherOut,
    TeacherTimeRuleIn,
    TeacherTimeRuleOut,
)
from app.schemas.semester import AvailableSlot, PeriodTableOut
from app.schemas.timetable import UnavailableHitOut
from app.services import period_tables as pt_service
from app.services import timetable_check

router = APIRouter(tags=["basedata"])

viewer = require_roles(Role.scheduler, Role.director)
editor = require_roles(Role.scheduler)


def _require_semester(db: Session, semester_id: int) -> None:
    if db.get(Semester, semester_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到学期")


def _resolve_subjects(db: Session, semester_id: int, ids: list[int]) -> list[Subject]:
    if not ids:
        return []
    subjects = db.scalars(
        select(Subject).where(Subject.id.in_(ids), Subject.semester_id == semester_id)
    ).all()
    if len(subjects) != len(set(ids)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "科目清单含无效或跨学期的科目")
    return list(subjects)


# ── 科目 ──────────────────────────────
@router.get("/subjects", response_model=list[SubjectOut])
def list_subjects(
    semester_id: int = Query(...),
    q: str | None = None,
    db: Session = Depends(get_db),
    _: object = Depends(viewer),
):
    stmt = select(Subject).where(Subject.semester_id == semester_id)
    if q:
        stmt = stmt.where(Subject.name.contains(q))
    return db.scalars(stmt.order_by(Subject.name)).all()


@router.post("/subjects", response_model=SubjectOut, status_code=status.HTTP_201_CREATED)
def create_subject(
    body: SubjectIn,
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    _: object = Depends(editor),
) -> Subject:
    _require_semester(db, semester_id)
    subject = Subject(
        semester_id=semester_id,
        name=body.name,
        domain=body.domain,
        required_room_type=body.required_room_type.value if body.required_room_type else None,
        default_block_size=body.default_block_size,
        is_major=body.is_major,
    )
    db.add(subject)
    db.commit()
    db.refresh(subject)
    return subject


@router.patch("/subjects/{subject_id}", response_model=SubjectOut)
def update_subject(
    subject_id: int, body: SubjectIn, db: Session = Depends(get_db), _: object = Depends(editor)
) -> Subject:
    subject = db.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到科目")
    subject.name = body.name
    subject.domain = body.domain
    subject.required_room_type = body.required_room_type.value if body.required_room_type else None
    subject.default_block_size = body.default_block_size
    subject.is_major = body.is_major
    db.commit()
    db.refresh(subject)
    return subject


@router.delete("/subjects/{subject_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_subject(
    subject_id: int, db: Session = Depends(get_db), _: object = Depends(editor)
) -> None:
    subject = db.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到科目")
    t_count = db.scalar(
        select(func.count()).select_from(teacher_subjects).where(
            teacher_subjects.c.subject_id == subject_id
        )
    )
    r_count = db.scalar(
        select(func.count()).select_from(room_subjects).where(
            room_subjects.c.subject_id == subject_id
        )
    )
    if t_count or r_count:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"此科目已被 {t_count} 位教师、{r_count} 间场地引用,请先解除关联再删除",
        )
    db.delete(subject)
    db.commit()


def _validate_teacher_user(
    db: Session, semester_id: int, user_id: int | None, exclude_teacher_id: int | None = None
) -> None:
    """验证欲绑定的帐号:须存在,且同学期未被其他教师绑定(否则 409)。"""
    if user_id is None:
        return
    if db.get(User, user_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "欲绑定的帐号不存在")
    stmt = select(Teacher.id).where(
        Teacher.semester_id == semester_id, Teacher.user_id == user_id
    )
    if exclude_teacher_id is not None:
        stmt = stmt.where(Teacher.id != exclude_teacher_id)
    if db.scalar(stmt) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "此帐号在本学期已绑定其他教师")


# ── 教师 ──────────────────────────────
@router.get("/teachers/bindable-accounts", response_model=list[BindableAccount])
def list_bindable_accounts(
    semester_id: int = Query(...),
    current_teacher_id: int | None = None,
    db: Session = Depends(get_db),
    _: object = Depends(viewer),
):
    """teacher 角色且在本学期尚未绑定的帐号;编辑时另纳入该教师目前绑定的帐号。"""
    bound = set(
        db.scalars(
            select(Teacher.user_id).where(
                Teacher.semester_id == semester_id, Teacher.user_id.is_not(None)
            )
        )
    )
    if current_teacher_id is not None:
        cur = db.get(Teacher, current_teacher_id)
        if cur is not None and cur.user_id is not None:
            bound.discard(cur.user_id)
    teacher_user_ids = db.scalars(
        select(UserRole.user_id).where(UserRole.role == Role.teacher.value)
    )
    available = [uid for uid in set(teacher_user_ids) if uid not in bound]
    if not available:
        return []
    return db.scalars(
        select(User).where(User.id.in_(available), User.is_active.is_(True)).order_by(User.username)
    ).all()


def _teacher_account(db: Session, teacher_id: int) -> tuple[Teacher, User]:
    """取出教师与其绑定帐号;只允许动「纯教师角色」的帐号。

    教学组长本来就能建立教师帐号(Excel 导入就是),但不该通过这条路去改到
    主任/组长/管理员的密码,所以这里挡掉有其他角色的帐号。
    """
    teacher = db.get(Teacher, teacher_id)
    if teacher is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到教师")
    user = db.get(User, teacher.user_id) if teacher.user_id else None
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "此教师尚未绑定登录帐号")
    if user.role_names - {Role.teacher.value}:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "此帐号不只是教师角色,请由系统管理员处理"
        )
    return teacher, user


@router.post(
    "/teachers/{teacher_id}/account",
    response_model=TeacherAccountOut,
    status_code=status.HTTP_201_CREATED,
)
def create_teacher_account(
    teacher_id: int,
    body: TeacherAccountIn,
    db: Session = Depends(get_db),
    _: object = Depends(editor),
) -> User:
    """为既有教师补开登录帐号并绑定。

    先前只有「Excel 导入教师时勾选建立帐号」这一条路,导入后才需要帐号的老师补不了
    (重新导入会因姓名+身分证末四码重复被挡)——用户回报 #9。
    """
    teacher = db.get(Teacher, teacher_id)
    if teacher is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到教师")
    if teacher.user_id is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "此教师已绑定登录帐号")
    username = body.username.strip()
    if db.scalar(select(User.id).where(User.username == username)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"登录帐号「{username}」已存在")
    password = body.password or settings.default_import_password
    if len(password) < settings.min_password_length:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"密码至少需 {settings.min_password_length} 个字元",
        )
    user = User(
        username=username,
        password_hash=hash_password(password),
        display_name=teacher.name,
        must_change_password=True,  # 老师第一次登录自行改掉
        roles=[UserRole(role=Role.teacher.value)],
    )
    db.add(user)
    db.flush()
    teacher.user_id = user.id
    db.commit()
    db.refresh(user)
    return user


@router.post("/teachers/{teacher_id}/account/reset-password", response_model=TeacherAccountOut)
def reset_teacher_password(
    teacher_id: int,
    body: ResetPasswordIn,
    db: Session = Depends(get_db),
    _: object = Depends(editor),
) -> User:
    """重设教师帐号的密码;重设后对方下次登录必须自行改密码。

    密码指纹变了,该帐号既有的登录状态会立即失效。
    """
    _, user = _teacher_account(db, teacher_id)
    password = body.password or settings.default_import_password
    if len(password) < settings.min_password_length:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"密码至少需 {settings.min_password_length} 个字元",
        )
    user.password_hash = hash_password(password)
    user.must_change_password = True
    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()
    db.refresh(user)
    return user


@router.get("/teachers/{teacher_id}/account", response_model=TeacherAccountOut | None)
def get_teacher_account(
    teacher_id: int, db: Session = Depends(get_db), _: object = Depends(viewer)
) -> User | None:
    """这位教师绑定的登录帐号与其状态;没有绑定则回 null。

    停用的帐号不会出现在「可绑定帐号」清单里,所以编辑界面要另外问这一笔。
    """
    teacher = db.get(Teacher, teacher_id)
    if teacher is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到教师")
    return db.get(User, teacher.user_id) if teacher.user_id else None


@router.post("/teachers/{teacher_id}/account/active", response_model=TeacherAccountOut)
def set_teacher_account_active(
    teacher_id: int,
    body: AccountActiveIn,
    db: Session = Depends(get_db),
    _: object = Depends(editor),
) -> User:
    """停用或重新启用教师的登录帐号。

    离职教师要的是「资料留著、人进不来」:停用后立刻无法登录,帐号与请假、
    调代课等历史纪录都保留(用户回报 #19)。先前 `users.is_active` 登录时
    会检查,但没有任何地方设置得了。
    """
    _, user = _teacher_account(db, teacher_id)
    user.is_active = body.is_active
    if not body.is_active:
        user.failed_login_attempts = 0
        user.locked_until = None
    db.commit()
    db.refresh(user)
    return user


@router.get("/teachers/{teacher_id}/delete-impact", response_model=TeacherDeleteImpact)
def teacher_delete_impact(
    teacher_id: int, db: Session = Depends(get_db), _: object = Depends(editor)
) -> TeacherDeleteImpact:
    """删除这位教师会连带失去什么:给删除确认视窗先讲清楚(用户回报 #19)。"""
    teacher = db.get(Teacher, teacher_id)
    if teacher is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到教师")
    user = db.get(User, teacher.user_id) if teacher.user_id else None
    return TeacherDeleteImpact(
        teacher_id=teacher.id,
        teacher_name=teacher.name,
        leave_requests=db.scalar(
            select(func.count()).select_from(LeaveRequest)
            .where(LeaveRequest.teacher_id == teacher_id)) or 0,
        substitutions=db.scalar(
            select(func.count()).select_from(Substitution)
            .where(Substitution.handler_teacher_id == teacher_id)) or 0,
        assignments=db.scalar(
            select(func.count()).select_from(AssignmentTeacher)
            .where(AssignmentTeacher.teacher_id == teacher_id)) or 0,
        homeroom_classes=db.scalar(
            select(func.count()).select_from(ClassUnit)
            .where(ClassUnit.homeroom_teacher_id == teacher_id)) or 0,
        account_username=user.username if user else "",
    )


@router.get("/teachers", response_model=list[TeacherOut])
def list_teachers(
    semester_id: int = Query(...),
    q: str | None = None,
    active_only: bool = False,
    db: Session = Depends(get_db),
    _: object = Depends(viewer),
):
    stmt = select(Teacher).where(Teacher.semester_id == semester_id)
    if q:
        stmt = stmt.where(Teacher.name.contains(q))
    if active_only:
        stmt = stmt.where(Teacher.is_active.is_(True))
    return db.scalars(stmt.order_by(Teacher.name)).all()


@router.post("/teachers", response_model=TeacherOut, status_code=status.HTTP_201_CREATED)
def create_teacher(
    body: TeacherIn,
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    _: object = Depends(editor),
) -> Teacher:
    _require_semester(db, semester_id)
    _validate_teacher_user(db, semester_id, body.user_id)
    teacher = Teacher(
        semester_id=semester_id,
        name=body.name,
        id_last4=body.id_last4,
        base_periods=body.base_periods,
        admin_title=body.admin_title,
        admin_reduction=body.admin_reduction,
        is_external=body.is_external,
        is_active=body.is_active,
        email=body.email,
        phone=body.phone,
        line_id=body.line_id,
        user_id=body.user_id,
        subjects=_resolve_subjects(db, semester_id, body.subject_ids),
    )
    db.add(teacher)
    db.commit()
    db.refresh(teacher)
    return teacher


@router.get("/teachers/{teacher_id}", response_model=TeacherOut)
def get_teacher(
    teacher_id: int, db: Session = Depends(get_db), _: object = Depends(viewer)
) -> Teacher:
    teacher = db.get(Teacher, teacher_id)
    if teacher is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到教师")
    return teacher


@router.patch("/teachers/{teacher_id}", response_model=TeacherOut)
def update_teacher(
    teacher_id: int, body: TeacherIn, db: Session = Depends(get_db), _: object = Depends(editor)
) -> Teacher:
    teacher = db.get(Teacher, teacher_id)
    if teacher is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到教师")
    _validate_teacher_user(db, teacher.semester_id, body.user_id, exclude_teacher_id=teacher.id)
    teacher.name = body.name
    teacher.id_last4 = body.id_last4
    teacher.base_periods = body.base_periods
    teacher.admin_title = body.admin_title
    teacher.admin_reduction = body.admin_reduction
    teacher.is_external = body.is_external
    teacher.is_active = body.is_active
    teacher.email = body.email
    teacher.phone = body.phone
    teacher.line_id = body.line_id
    teacher.user_id = body.user_id
    teacher.subjects = _resolve_subjects(db, teacher.semester_id, body.subject_ids)
    db.commit()
    db.refresh(teacher)
    return teacher


@router.delete("/teachers/{teacher_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_teacher(
    teacher_id: int, db: Session = Depends(get_db), _: object = Depends(editor)
) -> None:
    teacher = db.get(Teacher, teacher_id)
    if teacher is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到教师")
    homeroom_count = db.scalar(
        select(func.count()).select_from(ClassUnit).where(
            ClassUnit.homeroom_teacher_id == teacher_id
        )
    )
    if homeroom_count:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"此教师为 {homeroom_count} 个班级的导师,无法删除;请先更换导师,或将教师设为离职",
        )
    # 教师删了、帐号却还能登录是说不过去的(用户回报 #19)。帐号不删(留稽核轨迹),改为停用
    user = db.get(User, teacher.user_id) if teacher.user_id else None
    if user is not None and not (user.role_names - {Role.teacher.value}):
        user.is_active = False
    db.delete(teacher)
    db.commit()


@router.get("/teachers/{teacher_id}/time-rules", response_model=list[TeacherTimeRuleOut])
def get_time_rules(
    teacher_id: int, db: Session = Depends(get_db), _: object = Depends(viewer)
):
    teacher = db.get(Teacher, teacher_id)
    if teacher is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到教师")
    return teacher.time_rules


@router.put("/teachers/{teacher_id}/time-rules", response_model=list[TeacherTimeRuleOut])
def replace_time_rules(
    teacher_id: int,
    rules: list[TeacherTimeRuleIn],
    db: Session = Depends(get_db),
    _: object = Depends(editor),
):
    teacher = db.get(Teacher, teacher_id)
    if teacher is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到教师")
    seen: set[tuple[int, int]] = set()
    for r in rules:
        key = (r.weekday, r.period_no)
        if key in seen:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "同一格位不可重复设置规则")
        seen.add(key)
    teacher.time_rules.clear()
    db.flush()
    for r in rules:
        teacher.time_rules.append(
            TeacherTimeRule(weekday=r.weekday, period_no=r.period_no, rule_type=r.rule_type.value)
        )
    db.commit()
    db.refresh(teacher)
    return teacher.time_rules


@router.get(
    "/teachers/{teacher_id}/time-rules/conflicts", response_model=list[UnavailableHitOut]
)
def time_rule_conflicts(
    teacher_id: int, db: Session = Depends(get_db), _: object = Depends(viewer)
):
    """这位教师在草稿/已发布课表中,落在「不可排」时段的课。储存时段规则后由界面查一次。"""
    teacher = db.get(Teacher, teacher_id)
    if teacher is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到教师")
    return [
        UnavailableHitOut(
            timetable_id=h.timetable_id, timetable_name=h.timetable_name,
            timetable_status=h.timetable_status, weekday=h.weekday, period_no=h.period_no,
            period_name=h.period_name, subject=h.subject, classes=h.classes, text=h.text,
        )
        for h in timetable_check.unavailable_hits(db, teacher)
    ]


# ── 场地 ──────────────────────────────
@router.get("/rooms", response_model=list[RoomOut])
def list_rooms(
    semester_id: int = Query(...),
    q: str | None = None,
    db: Session = Depends(get_db),
    _: object = Depends(viewer),
):
    stmt = select(Room).where(Room.semester_id == semester_id)
    if q:
        stmt = stmt.where(Room.name.contains(q))
    return db.scalars(stmt.order_by(Room.name)).all()


@router.post("/rooms", response_model=RoomOut, status_code=status.HTTP_201_CREATED)
def create_room(
    body: RoomIn,
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    _: object = Depends(editor),
) -> Room:
    _require_semester(db, semester_id)
    room = Room(
        semester_id=semester_id,
        name=body.name,
        room_type=body.room_type.value,
        capacity=body.capacity,
        subjects=_resolve_subjects(db, semester_id, body.subject_ids),
    )
    db.add(room)
    db.commit()
    db.refresh(room)
    return room


@router.patch("/rooms/{room_id}", response_model=RoomOut)
def update_room(
    room_id: int, body: RoomIn, db: Session = Depends(get_db), _: object = Depends(editor)
) -> Room:
    room = db.get(Room, room_id)
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到场地")
    room.name = body.name
    room.room_type = body.room_type.value
    room.capacity = body.capacity
    room.subjects = _resolve_subjects(db, room.semester_id, body.subject_ids)
    db.commit()
    db.refresh(room)
    return room


@router.delete("/rooms/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_room(room_id: int, db: Session = Depends(get_db), _: object = Depends(editor)) -> None:
    room = db.get(Room, room_id)
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到场地")
    db.delete(room)
    db.commit()


# ── 班级 ──────────────────────────────
@router.get("/class-units", response_model=list[ClassUnitOut])
def list_class_units(
    semester_id: int = Query(...),
    q: str | None = None,
    db: Session = Depends(get_db),
    _: object = Depends(viewer),
):
    stmt = select(ClassUnit).where(ClassUnit.semester_id == semester_id)
    if q:
        stmt = stmt.where(ClassUnit.name.contains(q))
    return db.scalars(stmt.order_by(ClassUnit.grade, ClassUnit.name)).all()


def _require_unique_class_name(
    db: Session, semester_id: int, name: str, *, exclude_id: int | None = None
) -> None:
    """同学期不得有两个同名班级(M6-5)。

    冲突讯息、课表、导出全都以班名指称班级——同学期出现两个「301」时,组长在界面上
    根本分不出是哪一班。DB 有 uq 约束兜底,这里先挡下来给人话。
    """
    stmt = select(ClassUnit).where(
        ClassUnit.semester_id == semester_id, ClassUnit.name == name
    )
    if exclude_id is not None:
        stmt = stmt.where(ClassUnit.id != exclude_id)
    if db.scalar(stmt):
        raise HTTPException(status.HTTP_409_CONFLICT, f"本学期已有班级「{name}」")


def _validate_homeroom(db: Session, semester_id: int, teacher_id: int | None) -> None:
    if teacher_id is None:
        return
    teacher = db.get(Teacher, teacher_id)
    if teacher is None or teacher.semester_id != semester_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "导师无效或不属于本学期")


def _validate_period_table(db: Session, semester_id: int, table_id: int | None) -> None:
    if table_id is None:
        return
    table = db.get(PeriodTable, table_id)
    if table is None or table.semester_id != semester_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "节次表无效或不属于本学期")


@router.post("/class-units", response_model=ClassUnitOut, status_code=status.HTTP_201_CREATED)
def create_class_unit(
    body: ClassUnitIn,
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    _: object = Depends(editor),
) -> ClassUnit:
    _require_semester(db, semester_id)
    _require_unique_class_name(db, semester_id, body.name)
    _validate_homeroom(db, semester_id, body.homeroom_teacher_id)
    _validate_period_table(db, semester_id, body.period_table_id)
    cu = ClassUnit(
        semester_id=semester_id,
        grade=body.grade,
        name=body.name,
        track=body.track.value,
        department=body.department,
        student_count=body.student_count,
        homeroom_teacher_id=body.homeroom_teacher_id,
        period_table_id=body.period_table_id,
    )
    db.add(cu)
    db.commit()
    db.refresh(cu)
    return cu


@router.patch("/class-units/{class_id}", response_model=ClassUnitOut)
def update_class_unit(
    class_id: int, body: ClassUnitIn, db: Session = Depends(get_db), _: object = Depends(editor)
) -> ClassUnit:
    cu = db.get(ClassUnit, class_id)
    if cu is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到班级")
    _require_unique_class_name(db, cu.semester_id, body.name, exclude_id=cu.id)
    _validate_homeroom(db, cu.semester_id, body.homeroom_teacher_id)
    _validate_period_table(db, cu.semester_id, body.period_table_id)
    cu.grade = body.grade
    cu.name = body.name
    cu.track = body.track.value
    cu.department = body.department
    cu.student_count = body.student_count
    cu.homeroom_teacher_id = body.homeroom_teacher_id
    cu.period_table_id = body.period_table_id
    db.commit()
    db.refresh(cu)
    return cu


@router.get("/class-units/{class_id}/period-table", response_model=PeriodTableOut)
def class_period_table(
    class_id: int, db: Session = Depends(get_db), _: object = Depends(viewer)
) -> PeriodTable:
    """该班级所属的完整节次表(含午休/早自习等非上课格位),供排课工作台渲染。

    一律经 resolve_period_table,前端不需自行处理「指定表 vs 学期默认表」。
    """
    cu = db.get(ClassUnit, class_id)
    if cu is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到班级")
    table = pt_service.resolve_period_table(db, cu)
    if table is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "此学期尚无任何节次表")
    return table


@router.get("/class-units/{class_id}/available-slots", response_model=list[AvailableSlot])
def class_available_slots(
    class_id: int, db: Session = Depends(get_db), _: object = Depends(viewer)
) -> list[AvailableSlot]:
    """回传该班级的可排课时段(依所属节次表,空则用学期默认表)。M2 排课引擎使用。"""
    cu = db.get(ClassUnit, class_id)
    if cu is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到班级")
    table = pt_service.resolve_period_table(db, cu)
    if table is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "此学期尚无任何节次表")
    rows = pt_service.regular_slots(db, table.id)
    return [
        AvailableSlot(
            weekday=p.weekday, period_no=p.period_no, name=p.name,
            start_time=p.start_time, end_time=p.end_time,
        )
        for p in rows
    ]


@router.delete("/class-units/{class_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_class_unit(
    class_id: int, db: Session = Depends(get_db), _: object = Depends(editor)
) -> None:
    cu = db.get(ClassUnit, class_id)
    if cu is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到班级")
    db.delete(cu)
    db.commit()
