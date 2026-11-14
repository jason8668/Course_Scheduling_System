"""考务通知 API(KW-57~59/61):通知开关、手动触发三类通知、到期扫、记录查询与重发。

挂在 /api/exam 下,路由里写相对路径,与已有八个 exam 相关 router 共用同一前缀。
触发与重发只允许 admin/director;读接口按可见范围过滤;所有写操作记审计。
考试状态推进到“已发布”时不自动发通知(避免状态机耦合),一律手动触发为准。

新增审计动作名(未进 EXAM_AUDIT_ACTIONS 登记册,由协调员统一追加,
log_exam_action 对未在册动作不抛错,见 exam_audit.py):
exam_notification_settings_update、exam_schedule_notify、
exam_invigilation_notify、exam_score_deadline_notify、
exam_notification_remind_due、exam_notification_resend。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import get_active_user, require_roles
from app.core.db import get_db
from app.models.user import Role, User
from app.schemas.exam_notifications import (
    NotificationListOut,
    NotificationLogOut,
    NotificationSettingOut,
    NotificationSettingPut,
    NotifyOut,
    ResendOut,
)
from app.services import exam_notifications as svc
from app.services.exam import get_exam, require_exam_visible
from app.services.exam_audit import log_exam_action
from app.services.exam_scopes import can_manage_students

router = APIRouter(tags=["exam_notifications"])

writer = require_roles(Role.admin, Role.director)


def _require_can_manage(db: Session, user: User) -> None:
    if not can_manage_students(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "权限不足")


def _exam_or_404(db: Session, exam_id: int):
    return get_exam(db, exam_id)


# ── 通知开关 ────────────────────────────────────────
@router.get(
    "/exams/{exam_id}/notification-settings", response_model=NotificationSettingOut
)
def get_notification_settings(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    row = svc.get_settings(db, exam)
    return NotificationSettingOut(**svc.settings_out(exam, row))


@router.put(
    "/exams/{exam_id}/notification-settings", response_model=NotificationSettingOut
)
def put_notification_settings(
    exam_id: int,
    body: NotificationSettingPut,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    row = svc.upsert_settings(
        db, exam,
        body.schedule_notify_enabled, body.invigilation_remind_enabled,
        body.score_deadline_remind_enabled,
    )
    log_exam_action(
        db, user, "exam_notification_settings_update",
        target_type="exam", target_id=exam.id,
        detail=f"更新考试{exam.name}通知开关",
    )
    db.commit()
    return NotificationSettingOut(**svc.settings_out(exam, row))


# ── 手动触发 ────────────────────────────────────────
@router.post("/exams/{exam_id}/notify/schedule", response_model=NotifyOut)
def notify_schedule(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    sent, failed = svc.notify_schedule(db, exam)
    log_exam_action(
        db, user, "exam_schedule_notify",
        target_type="exam", target_id=exam.id,
        detail=f"发送考试{exam.name}日程通知(成功{sent}人,失败{failed}人)",
    )
    db.commit()
    return NotifyOut(sent=sent, failed=failed)


@router.post("/exams/{exam_id}/notify/invigilation", response_model=NotifyOut)
def notify_invigilation(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    sent, failed = svc.notify_invigilation(db, exam)
    log_exam_action(
        db, user, "exam_invigilation_notify",
        target_type="exam", target_id=exam.id,
        detail=f"发送考试{exam.name}监考提醒(成功{sent}人,失败{failed}人)",
    )
    db.commit()
    return NotifyOut(sent=sent, failed=failed)


@router.post("/exams/{exam_id}/notify/score-deadline", response_model=NotifyOut)
def notify_score_deadline(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    sent, failed = svc.notify_score_deadline(db, exam)
    log_exam_action(
        db, user, "exam_score_deadline_notify",
        target_type="exam", target_id=exam.id,
        detail=f"发送考试{exam.name}录分截止催录提醒(成功{sent}人,失败{failed}人)",
    )
    db.commit()
    return NotifyOut(sent=sent, failed=failed)


# ── 到期扫 ──────────────────────────────────────────
@router.post("/notifications/remind-due", response_model=NotifyOut)
def remind_due(
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    """到期扫:考前一天与当天开考前到点的监考提醒、截止前 24 小时与
    2 小时到点的录分催提醒;供定时任务调用,同一提醒 24 小时内不重复发。"""
    _require_can_manage(db, user)
    sent, failed = svc.remind_due(db)
    log_exam_action(
        db, user, "exam_notification_remind_due",
        target_type="exam", target_id=None,
        detail=f"考务通知到期扫(成功{sent}人,失败{failed}人)",
    )
    db.commit()
    return NotifyOut(sent=sent, failed=failed)


# ── 记录查询与重发 ──────────────────────────────────
@router.get("/exams/{exam_id}/notifications", response_model=NotificationListOut)
def list_notifications(
    exam_id: int,
    type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    q: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    rows, total = svc.list_logs(db, user, exam, type, status, q)
    return NotificationListOut(
        items=[NotificationLogOut(**svc.log_out(r)) for r in rows], total=total
    )


@router.post(
    "/exams/{exam_id}/notifications/{nid}/resend", response_model=ResendOut
)
def resend_notification(
    exam_id: int,
    nid: int,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    log = svc.resend_log(db, exam, nid)
    ok = log.status == "成功"
    log_exam_action(
        db, user, "exam_notification_resend",
        target_type="exam_notification_log", target_id=log.id,
        detail=f"重发考试{exam.name}通知记录#{log.id}({log.recipient_name}),结果{log.status}",
    )
    db.commit()
    return ResendOut(sent=ok, status=log.status)
