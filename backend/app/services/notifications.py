"""通知服务(M4-1 起,M4-3 补齐寄送管道)。

**站内通知永远送达**:写入 `notifications` 一列即完成——铃铛轮询读这张表。
**Email 是加分**:资料 commit 后才排入寄送伫列,寄失败不影响课务。

寄送以 `NotificationChannel` 分层(architecture.md §5.3):MVP 两个管道,站内与 Email;
v2 加 webhook / 钉钉 只需再实作一个 channel、append 进 `CHANNELS`。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.models.basedata import Teacher
from app.models.notification import Notification, NotificationType

logger = logging.getLogger(__name__)

_OUTBOX_KEY = "notification_email_outbox"
_DINGTALK_OUTBOX_KEY = "notification_dingtalk_outbox"


@dataclass(frozen=True, slots=True)
class _Email:
    to: str
    subject: str
    body: str


# ── 寄送管道 ────────────────────────────────────────────────
class NotificationChannel(Protocol):
    key: str

    def deliver(self, db: Session, notification: Notification, teacher: Teacher | None) -> None:
        ...


class InAppChannel:
    """站内通知:`notifications` 那一列本身即送达,无额外动作。"""

    key = "in_app"

    def deliver(self, db: Session, notification: Notification, teacher: Teacher | None) -> None:
        return


class EmailChannel:
    """Email:把信放进交易的寄件匣;commit 后由 after_commit 事件排入 RQ。

    这里不直接 enqueue——交易若回复(rollback),就不该寄出一封对应到不存在通知的信。
    """

    key = "email"

    def deliver(self, db: Session, notification: Notification, teacher: Teacher | None) -> None:
        if teacher is None or not teacher.email:
            return
        outbox = db.info.setdefault(_OUTBOX_KEY, [])
        outbox.append(_Email(
            to=teacher.email,
            subject=f"[{notification_subject_prefix(db)}] {notification.title}",
            body=notification.body or notification.title,
        ))


@dataclass(frozen=True, slots=True)
class _DingTalkMsg:
    webhook: str
    secret: str
    title: str
    text: str


# 钉钉只发调课/代课:调课(swap)与代课都走 substitution_* 类型(含双方通知与取消);
# 请假(leave_registered / leave_cancelled)只留站内通知,不进钉钉群。课表发布等
# 其他类型也不发钉钉——规则收在这一处,新增 notify 与「再次提醒」重发都同样受限。
_DINGTALK_TYPE_VALUES = frozenset({
    NotificationType.substitution_assigned.value,
    NotificationType.substitution_cancelled.value,
})


class DingTalkChannel:
    """钉钉群机器人:与 Email 相同走寄件匣模式——在交易内就把 Webhook/密钥/
    校名/文案全部备好(after_commit 阶段已不能再查 DB),commit 后只做 POST,
    交易 rollback 就不送。未设置 Webhook 时静默略过。内容是给全群看的广播,
    只同步标题与摘要。只发调课/代课类型(见 _DINGTALK_TYPE_VALUES),请假不发。"""

    key = "dingtalk"

    def deliver(self, db: Session, notification: Notification, teacher: Teacher | None) -> None:
        if notification.type not in _DINGTALK_TYPE_VALUES:
            return
        from app.services import settings as app_settings

        cfg = app_settings.dingtalk_config(db)
        if not cfg.configured:
            return
        school = app_settings.school_name(db)
        outbox = db.info.setdefault(_DINGTALK_OUTBOX_KEY, [])
        title = f"[{school}] {notification.title}"
        text = f"### {notification.title}\n\n{notification.body or notification.title}"
        outbox.append(_DingTalkMsg(cfg.webhook, cfg.secret, title, text))


CHANNELS: list[NotificationChannel] = [InAppChannel(), EmailChannel(), DingTalkChannel()]


def notification_subject_prefix(db: Session) -> str:
    from app.services import settings as app_settings

    return app_settings.school_name(db)


# ── 写入 ────────────────────────────────────────────────────
def notify(
    db: Session,
    *,
    semester_id: int,
    teacher_id: int | None,
    type: NotificationType,
    title: str,
    body: str = "",
    link: str = "",
) -> Notification:
    """建立通知并经各管道送达。呼叫端负责 commit;Email 于 commit 后自动寄出。"""
    n = Notification(
        semester_id=semester_id, teacher_id=teacher_id, type=type.value,
        title=title[:120], body=body, link=link[:200],
    )
    db.add(n)
    teacher = db.get(Teacher, teacher_id) if teacher_id is not None else None
    for channel in CHANNELS:
        channel.deliver(db, n, teacher)
    return n


# ── commit 后把寄件匣排入 RQ ─────────────────────────────────
@event.listens_for(Session, "after_commit")
def _flush_email_outbox(session: Session) -> None:
    outbox: list[_Email] = session.info.pop(_OUTBOX_KEY, [])
    if not outbox:
        return
    try:
        from app.workers.queue import enqueue_email
    except Exception:  # noqa: BLE001 - 测试或无 Redis 环境:静默略过 Email
        return
    for msg in outbox:
        try:
            enqueue_email(msg.to, msg.subject, msg.body)
        except Exception:  # noqa: BLE001 - 伫列不可用不该让已成功的交易报错
            # 站内通知已送达;Email 只是加分。但要留痕,否则 Redis 挂掉时无声消失无从查起
            logger.warning("代课通知 Email 排入伫列失败(收件:%s),站内通知不受影响", msg.to)


@event.listens_for(Session, "after_rollback")
def _discard_email_outbox(session: Session) -> None:
    session.info.pop(_OUTBOX_KEY, None)
    session.info.pop(_DINGTALK_OUTBOX_KEY, None)


# ── 钉钉机器人发送 ──────────────────────────────────────────
def dingtalk_signed_url(webhook: str, secret: str) -> str:
    """加签:sign = base64(HMAC-SHA256(key=secret, msg="{timestamp}\n{secret}"))。"""
    if not secret:
        return webhook
    import base64
    import hashlib
    import hmac
    import time
    from urllib.parse import quote_plus

    timestamp = str(round(time.time() * 1000))
    digest = hmac.new(
        secret.encode(), f"{timestamp}\n{secret}".encode(), digestmod=hashlib.sha256
    ).digest()
    sign = quote_plus(base64.b64encode(digest))
    sep = "&" if "?" in webhook else "?"
    return f"{webhook}{sep}timestamp={timestamp}&sign={sign}"


def send_dingtalk(webhook: str, secret: str, title: str, text: str) -> None:
    """POST 一则 markdown 消息到钉钉群机器人;失败掷出例外(由呼叫端决定如何处理)。"""
    import httpx

    url = dingtalk_signed_url(webhook, secret)
    resp = httpx.post(
        url,
        json={"msgtype": "markdown", "markdown": {"title": title, "text": text}},
        timeout=5.0,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("errcode") != 0:
        raise RuntimeError(f"钉钉回报错误:{payload.get('errmsg', payload)}")


@event.listens_for(Session, "after_commit")
def _flush_dingtalk_outbox(session: Session) -> None:
    outbox: list[_DingTalkMsg] = session.info.pop(_DINGTALK_OUTBOX_KEY, [])
    for msg in outbox:
        try:
            send_dingtalk(msg.webhook, msg.secret, title=msg.title, text=msg.text)
        except Exception:  # noqa: BLE001 - 站内通知已送达;钉钉只是广播,失败留痕即可
            logger.warning("钉钉群通知发送失败(标题:%s),站内通知不受影响", msg.title)


# ── 读取与状态 ──────────────────────────────────────────────
@dataclass
class NotificationView:
    items: list[Notification] = field(default_factory=list)
    unread: int = 0


def for_teacher(db: Session, semester_id: int, teacher_id: int) -> list[Notification]:
    return list(
        db.scalars(
            select(Notification)
            .where(
                Notification.semester_id == semester_id,
                Notification.teacher_id == teacher_id,
            )
            .order_by(Notification.id.desc())
        )
    )


def unread_count(db: Session, semester_id: int, teacher_id: int) -> int:
    return db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.semester_id == semester_id,
            Notification.teacher_id == teacher_id,
            Notification.read_at.is_(None),
        )
    ) or 0


def mark_read(notification: Notification) -> None:
    if notification.read_at is None:
        notification.read_at = datetime.now().astimezone()


def acknowledge(notification: Notification) -> None:
    now = datetime.now().astimezone()
    if notification.read_at is None:
        notification.read_at = now
    notification.acknowledged_at = now
