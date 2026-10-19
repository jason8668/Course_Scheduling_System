"""Email 寄送任务(M4-3,RQ)。

通知的站内部分在请求交易内就已落地;Email 走这里非同步寄出,失败不影响课务。
"""

import logging

logger = logging.getLogger(__name__)


def send_notification_email(to: str, subject: str, body: str) -> None:
    """RQ 进入点。SMTP 未设置或寄送失败都只记 log,不抛出——站内通知已送达。"""
    from app.core.db import SessionLocal
    from app.services import email as email_service

    db = SessionLocal()
    try:
        sent = email_service.send(db, to=to, subject=subject, body=body)
        if not sent:
            logger.info("未寄送通知信(SMTP 未设置或无收件人):%s", subject)
    except Exception as exc:  # noqa: BLE001 - 寄信失败不该让 worker 崩溃
        logger.warning("寄送通知信失败(%s):%s", to, exc)
    finally:
        db.close()
