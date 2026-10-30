"""老师自主调课 API。

发起:登录教师在「我的」页发起,必须是原任或换课其中一方;
对方(另一方)同意即生效,不需要主任/管理员过目。
事后补登同款:日期可以是过去,对方点同意即确认这件事已发生。

查看:管理员看全部;教师看与自己有关的(原任/换课/发起人)。
同意/拒绝:只有对方老师能点,发起人自己不能同意。
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.auth import get_active_user
from app.core.db import get_db
from app.models.assignment import CourseAssignment
from app.models.basedata import ClassUnit, Teacher
from app.models.notification import NotificationType
from app.models.semester import Semester
from app.models.teacher_swap import TeacherSwap
from app.models.user import Role, User
from app.schemas.teacher_swap import TeacherSwapCreate, TeacherSwapOut
from app.services import teacher_swaps as swap_service
from app.services.notifications import notify
from app.services.substitution_log import school_today
from app.services.teachers import current_teacher

router = APIRouter(tags=["teacher_swaps"])


def _get_semester(db: Session, semester_id: int) -> Semester:
    semester = db.get(Semester, semester_id)
    if semester is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到学期")
    return semester


def _check_teacher(db: Session, semester_id: int, teacher_id: int, label: str) -> Teacher:
    teacher = db.get(Teacher, teacher_id)
    if teacher is None or teacher.semester_id != semester_id or not teacher.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{label}不是该学期在职教师")
    return teacher


def _check_class(db: Session, semester_id: int, class_unit_id: int) -> ClassUnit:
    cls = db.get(ClassUnit, class_unit_id)
    if cls is None or cls.semester_id != semester_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "班级不属于该学期")
    return cls


def _out(s: TeacherSwap) -> TeacherSwapOut:
    return TeacherSwapOut(
        id=s.id, semester_id=s.semester_id, requester_id=s.requester_id,
        status=s.status, note=s.note,
        class_date=s.class_date, period_no=s.period_no,
        class_unit_id=s.class_unit_id, course_assignment_id=s.course_assignment_id,
        original_teacher_id=s.original_teacher_id,
        handler_teacher_id=s.handler_teacher_id,
        makeup_date=s.makeup_date, makeup_period_no=s.makeup_period_no,
        makeup_class_unit_id=s.makeup_class_unit_id,
        makeup_assignment_id=s.makeup_assignment_id,
        approver_teacher_id=(
            s.handler_teacher_id if s.requester_id == s.original_teacher_id
            else s.original_teacher_id
        ),
        is_retroactive=s.class_date < school_today(),
    )


@router.get("/teacher-swaps", response_model=list[TeacherSwapOut])
def list_swaps(
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    _get_semester(db, semester_id)
    q = select(TeacherSwap).where(TeacherSwap.semester_id == semester_id)
    if not user.has_role(Role.admin):
        me = current_teacher(db, user, semester_id)
        if me is None:
            return []
        q = q.where(or_(
            TeacherSwap.original_teacher_id == me.id,
            TeacherSwap.handler_teacher_id == me.id,
            TeacherSwap.requester_id == me.id,
        ))
    rows = db.scalars(q.order_by(TeacherSwap.class_date.desc(), TeacherSwap.id.desc())).all()
    return [_out(r) for r in rows]


@router.post("/teacher-swaps", response_model=TeacherSwapOut, status_code=201)
def create_swap(
    body: TeacherSwapCreate,
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    _get_semester(db, semester_id)
    me = current_teacher(db, user, semester_id)
    if me is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "账号未绑定教师档案,无法发起调课")
    # 发起人必须是原任或换课其中一方
    if me.id not in (body.original_teacher_id, body.handler_teacher_id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "只能为自己有关的课发起调课(你是原任或换课其中一方)")
    _check_teacher(db, semester_id, body.original_teacher_id, "原任教师")
    _check_teacher(db, semester_id, body.handler_teacher_id, "换课教师")
    _check_class(db, semester_id, body.class_unit_id)
    a = db.get(CourseAssignment, body.course_assignment_id)
    if a is None or a.semester_id != semester_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "配课不属于该学期")
    if not swap_service.assignment_teaches_class(db, body.course_assignment_id, body.class_unit_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "该配课不教这个班")
    orig_teachers = swap_service.assignment_teachers(db, body.course_assignment_id)
    if body.original_teacher_id not in orig_teachers:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "原任教师不是这门配课的任课教师")
    if body.makeup_date is not None:
        _check_teacher(db, semester_id, body.handler_teacher_id, "换课教师")
        _check_class(db, semester_id, body.makeup_class_unit_id)  # type: ignore[arg-type]
        teaches_makeup = swap_service.assignment_teaches_class(
            db, body.makeup_assignment_id, body.makeup_class_unit_id)  # type: ignore[arg-type]
        if not teaches_makeup:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "补课配课不教补课那个班")
        # 补课那节的原任应是换课教师(对方的课由对方原任,现在反过来由原任去上)
        makeup_teachers = swap_service.assignment_teachers(
            db, body.makeup_assignment_id)  # type: ignore[arg-type]
        if body.handler_teacher_id not in makeup_teachers:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "补课配课的任课教师应含换课教师")
    row = TeacherSwap(
        semester_id=semester_id, requester_id=me.id, status="pending",
        note=body.note,
        class_date=body.class_date, period_no=body.period_no,
        class_unit_id=body.class_unit_id,
        course_assignment_id=body.course_assignment_id,
        original_teacher_id=body.original_teacher_id,
        handler_teacher_id=body.handler_teacher_id,
        makeup_date=body.makeup_date, makeup_period_no=body.makeup_period_no,
        makeup_class_unit_id=body.makeup_class_unit_id,
        makeup_assignment_id=body.makeup_assignment_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    # 站内通知对方(不走钉钉群白名单,故只站内)
    approver_id = (
        row.handler_teacher_id if row.requester_id == row.original_teacher_id
        else row.original_teacher_id
    )
    approver = db.get(Teacher, approver_id)
    if approver is not None:
        notify(
            db, semester_id=semester_id, teacher_id=approver.id,
            type=NotificationType.teacher_swap_requested,
            title="调课申请待确认",
            body=(
                f"{db.get(Teacher, row.original_teacher_id).name}老师"
                f"{row.class_date}第{row.period_no}节的课由"
                f"{db.get(Teacher, row.handler_teacher_id).name}老师上,请确认。"
            ),
            link="/my",
        )
        db.commit()
        db.refresh(row)
    return _out(row)


def _decide(
    db: Session, user: User, swap_id: int, approve: bool,
) -> TeacherSwap:
    row = db.get(TeacherSwap, swap_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到调课申请")
    if row.status != "pending":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "该申请已处理过")
    me = current_teacher(db, user, row.semester_id)
    approver_id = (
        row.handler_teacher_id if row.requester_id == row.original_teacher_id
        else row.original_teacher_id
    )
    if me is None or me.id != approver_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "只有对方老师能同意/拒绝")
    row.status = "approved" if approve else "rejected"
    row.decided_at = datetime.now()
    db.commit()
    db.refresh(row)
    return row


@router.post("/teacher-swaps/{swap_id}/approve", response_model=TeacherSwapOut)
def approve_swap(
    swap_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    return _out(_decide(db, user, swap_id, True))


@router.post("/teacher-swaps/{swap_id}/reject", response_model=TeacherSwapOut)
def reject_swap(
    swap_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    return _out(_decide(db, user, swap_id, False))
