"""通知服务(M4-1 起,M4-3 补齐寄送管道)。

**站内通知永远送达**:写入 `notifications` 一列即完成——铃铛轮询读这张表。
**Email 是加分**:资料 commit 后才排入寄送伫列,寄失败不影响课务。
**个人钉钉是加分**:企业内部应用的工作通知,一对一发给通知的收件老师,
寄失败只记日志,不影响站内通知与课务。

寄送以 `NotificationChannel` 分层(architecture.md §5.3):站内、Email、
个人钉钉三个管道。钉钉群机器人已于 2026-11-06 停用:群里不再发任何消息,
群 Webhook 配置保留未删,但不再有任何代码路径往群里发消息。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.models.basedata import Teacher
from app.models.notification import Notification, NotificationType
from app.services.dingtalk_app import DingTalkAppClient

logger = logging.getLogger(__name__)

_OUTBOX_KEY = "notification_email_outbox"
_PERSONAL_DINGTALK_OUTBOX_KEY = "notification_personal_dingtalk_outbox"


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
class _PersonalDingTalkMsg:
    app_key: str
    app_secret: str
    agent_id: str
    userid: str | None  # 已缓存的钉钉 userid;没有时寄出阶段按手机号查
    mobile: str | None
    teacher_name: str
    title: str
    text: str


class PersonalDingTalkChannel:
    """个人钉钉(企业内部应用工作通知):与 Email 相同走寄件匣模式——在交易内
    就把应用三件套与收件人备好(after_commit 阶段已不能再查 DB),commit 后
    只做发送,交易 rollback 就不送。未配置企业应用、或收件老师既无钉钉 userid
    又无手机号时静默略过。所有通知类型都走这条路:请假、调代课、课表发布、
    月度课时确认,全部一对一发给相关老师本人,群里不再发任何消息
    (2026-11-06 起取代旧的「群里只发调代课」规则)。

    寄出阶段:有 userid 直接发;没有则按手机号 getbymobile 查一次(查到
    也不回写教师档案——after_commit 阶段不写 DB,下次由上课提醒/月度任务
    的任务内解析回填)。"""

    key = "personal_dingtalk"

    def deliver(self, db: Session, notification: Notification, teacher: Teacher | None) -> None:
        if teacher is None:
            return
        from app.services import settings as app_settings

        cfg = app_settings.dingtalk_app_config(db)
        if not cfg.configured:
            return
        userid = teacher.dingtalk_userid
        mobile = None if userid else (teacher.phone or None)
        if not userid and not mobile:
            return
        title = notification.title
        body = notification.body or notification.title
        text = f"### {title}\n\n{body}"
        outbox = db.info.setdefault(_PERSONAL_DINGTALK_OUTBOX_KEY, [])
        outbox.append(_PersonalDingTalkMsg(
            cfg.app_key, cfg.app_secret, cfg.agent_id,
            userid, mobile, teacher.name, title, text,
        ))


CHANNELS: list[NotificationChannel] = [InAppChannel(), EmailChannel(), PersonalDingTalkChannel()]


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
    session.info.pop(_PERSONAL_DINGTALK_OUTBOX_KEY, None)


# ── 个人钉钉发送 ────────────────────────────────────────────
@event.listens_for(Session, "after_commit")
def _flush_personal_dingtalk_outbox(session: Session) -> None:
    outbox: list[_PersonalDingTalkMsg] = session.info.pop(_PERSONAL_DINGTALK_OUTBOX_KEY, [])
    if not outbox:
        return
    # 同一次 commit 里的消息共用一个 client(应用三件套全局唯一,token 只取一次);
    # 单条失败只记日志跳过,不影响其他老师。站内通知已送达,个人钉钉只是加分。
    client: DingTalkAppClient | None = None
    client_key: tuple[str, str, str] | None = None
    for msg in outbox:
        try:
            key = (msg.app_key, msg.app_secret, msg.agent_id)
            if client is None or key != client_key:
                client = DingTalkAppClient(*key)
                client_key = key
            userid = msg.userid
            if not userid and msg.mobile:
                userid = client.get_userid(msg.mobile)
            if not userid:
                logger.warning(
                    "个人钉钉跳过:%s 无钉钉 userid(未填手机号或不在企业通讯录)",
                    msg.teacher_name,
                )
                continue
            client.send_work_notification(userid, msg.title, msg.text)
        except Exception:  # noqa: BLE001 - 站内通知已送达;个人钉钉失败留痕即可
            logger.warning(
                "个人钉钉发送失败(%s,标题:%s),站内通知不受影响",
                msg.teacher_name, msg.title,
            )


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
