"""请假登记与受影响节次(M4-1)。

RBAC:教师只能登记/销自己的假、只看得到自己的假单;
教学组长与教务主任可代登、可看全校、可代销。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import get_active_user, require_roles
from app.core.db import get_db
from app.models.audit import AuditLog
from app.models.leave import LEAVE_TYPE_CN, AffectedStatus, LeaveRequest, LeaveType
from app.models.semester import Semester
from app.models.user import Role, User
from app.schemas.leave import (
    AffectedPeriodOut,
    LeaveCancelled,
    LeaveRequestIn,
    LeaveRequestOut,
)
from app.services import leaves as leave_service
from app.services.teachers import current_teacher

router = APIRouter(tags=["leaves"])

# 假单清单的保护性上限(M6-5);完整分页 UI 留 v1.2
MAX_LEAVE_ROWS = 1000

registrar = require_roles(Role.scheduler, Role.director)  # 可代登/代销


def _is_registrar(user: User) -> bool:
    """可代登/代销/看全校。admin 一律通过(与 require_roles 一致)。"""
    return bool(user.role_names & {Role.scheduler.value, Role.director.value, Role.admin.value})


def _get_semester(db: Session, semester_id: int) -> Semester:
    sem = db.get(Semester, semester_id)
    if sem is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到学期")
    return sem


def _serialize(leave: LeaveRequest) -> LeaveRequestOut:
    periods = sorted(leave.affected_periods, key=lambda p: (p.date, p.period_no))
    return LeaveRequestOut(
        id=leave.id, semester_id=leave.semester_id,
        teacher_id=leave.teacher_id, teacher_name=leave.teacher.name,
        leave_type=leave.leave_type,
        leave_type_label=LEAVE_TYPE_CN.get(leave.leave_type, leave.leave_type),
        start_date=leave.start_date, start_time=leave.start_time,
        end_date=leave.end_date, end_time=leave.end_time,
        reason=leave.reason, status=leave.status,
        created_by_name=leave.created_by_name, created_at=leave.created_at,
        affected_count=len(periods),
        pending_count=sum(1 for p in periods if p.status == AffectedStatus.pending.value),
        affected_periods=[
            AffectedPeriodOut(
                **{k: getattr(p, k) for k in (
                    "id", "date", "weekday", "period_no", "period_name", "start_time",
                    "end_time", "subject_name", "class_names", "room_name",
                    "handler_teacher_id",
                )},
                status=leave_service.effective_status(p.status, p.date, p.end_time),
                handler_name=p.handler.name if p.handler else None,
                sub_type=p.substitution.type if p.substitution else None,
                swap_date=p.substitution.swap_date if p.substitution else None,
                swap_period_name=p.substitution.swap_period_name if p.substitution else "",
            )
            for p in periods
        ],
    )


def _resolve_target_teacher(db: Session, semester_id: int, body_teacher_id: int | None, user: User):
    """代登指定教师;自登则解析登录者绑定的教师主档。"""
    if body_teacher_id is not None:
        if not _is_registrar(user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "只有教学组长或教务主任可代为登记")
        teacher = leave_service.find_teacher(db, semester_id, body_teacher_id)
        if teacher is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到教师")
        return teacher

    teacher = current_teacher(db, user, semester_id)
    if teacher is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "您的帐号尚未绑定本学期的教师主档,无法登记请假;请洽教学组长",
        )
    return teacher


@router.post("/leaves", response_model=LeaveRequestOut, status_code=status.HTTP_201_CREATED)
def create_leave(
    body: LeaveRequestIn,
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """登记请假,并依已发布课表展开受影响节次。"""
    sem = _get_semester(db, semester_id)
    if body.leave_type not in set(LeaveType):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"未知的假别:{body.leave_type}")

    teacher = _resolve_target_teacher(db, semester_id, body.teacher_id, user)
    on_behalf = teacher.user_id != user.id

    try:
        leave = leave_service.create(
            db, sem, teacher,
            leave_type=body.leave_type,
            start_date=body.start_date, start_time=body.start_time,
            end_date=body.end_date, end_time=body.end_time,
            reason=body.reason,
            created_by_user_id=user.id, created_by_name=user.username,
            notify_teacher=on_behalf,
        )
    except leave_service.LeaveError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    db.add(AuditLog(
        user_id=user.id, username=user.username, action="create_leave",
        target_type="leave_request", target_id=leave.id,
        detail=(
            f"{teacher.name} {leave_service.range_text(leave)}"
            f" {LEAVE_TYPE_CN.get(leave.leave_type, '')},"
            f"受影响 {len(leave.affected_periods)} 节"
        )[:500],
    ))
    db.commit()
    db.refresh(leave)
    return _serialize(leave)


@router.get("/leaves", response_model=list[LeaveRequestOut])
def list_leaves(
    semester_id: int = Query(...),
    teacher_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """组长看全校;教师只看得到自己的假单(即使指定了别人的 teacher_id)。"""
    _get_semester(db, semester_id)
    stmt = select(LeaveRequest).where(LeaveRequest.semester_id == semester_id)

    if not _is_registrar(user):
        me = current_teacher(db, user, semester_id)
        if me is None:
            return []
        stmt = stmt.where(LeaveRequest.teacher_id == me.id)
    elif teacher_id is not None:
        stmt = stmt.where(LeaveRequest.teacher_id == teacher_id)

    # 保护性上限(M6-5):整学期的假单会越积越多,不设限就会一次全部拉进记忆体。
    # 取最新的 MAX_LEAVE_ROWS 笔;完整分页 UI 留 v1.2。
    rows = db.scalars(
        stmt.order_by(LeaveRequest.start_date.desc(), LeaveRequest.id.desc())
        .limit(MAX_LEAVE_ROWS)
    ).unique()
    return [_serialize(leave) for leave in rows]


def _get_leave(db: Session, leave_id: int, user: User) -> LeaveRequest:
    leave = db.get(LeaveRequest, leave_id)
    if leave is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到假单")
    if not _is_registrar(user):
        me = current_teacher(db, user, leave.semester_id)
        if me is None or me.id != leave.teacher_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "只能存取自己的假单")
    return leave


@router.get("/leaves/{leave_id}", response_model=LeaveRequestOut)
def get_leave(leave_id: int, db: Session = Depends(get_db), user: User = Depends(get_active_user)):
    return _serialize(_get_leave(db, leave_id, user))


@router.post("/leaves/{leave_id}/cancel", response_model=LeaveCancelled)
def cancel_leave(
    leave_id: int, db: Session = Depends(get_db), user: User = Depends(get_active_user)
):
    """销假:级联取消所有受影响节次,已被指派的代课教师会收到取消通知。

    已完成的节次不动——那堂课已经上过了,事后销假不能把历史抹掉。
    """
    leave = _get_leave(db, leave_id, user)
    try:
        revoked = leave_service.cancel(db, leave, actor_name=user.username)
    except leave_service.LeaveError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    notified = sorted({p.handler.name for p in revoked if p.handler})
    db.add(AuditLog(
        user_id=user.id, username=user.username, action="cancel_leave",
        target_type="leave_request", target_id=leave.id,
        detail=f"{leave.teacher.name} 销假,取消 {len(revoked)} 节已指派代课"[:500],
    ))
    db.commit()
    return LeaveCancelled(
        id=leave.id, status=leave.status, revoked_count=len(revoked), notified_teachers=notified
    )


@router.get("/leaves/{leave_id}/affected", response_model=list[AffectedPeriodOut])
def list_affected(
    leave_id: int, db: Session = Depends(get_db), user: User = Depends(get_active_user)
):
    return _serialize(_get_leave(db, leave_id, user)).affected_periods


@router.get("/leave-types", response_model=dict[str, str])
def leave_types(_: object = Depends(get_active_user)):
    return {t.value: LEAVE_TYPE_CN[t] for t in LeaveType}
