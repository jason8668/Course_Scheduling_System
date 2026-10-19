"""SMTP 寄信(M4-3)。

实际寄送走 RQ(见 workers/email_job.py),不在请求执行绪里卡住。
SMTP 未设置时 `send` 直接回 False——站内通知已经送达,Email 只是加分,不该让整个
调代课流程因为没设信箱而失败。
"""

import smtplib
from email.message import EmailMessage

from sqlalchemy.orm import Session

from app.services import settings as app_settings


def send(db: Session, *, to: str, subject: str, body: str) -> bool:
    """寄一封信。回传是否真的送出(未设置 SMTP、或无收件人时回 False)。"""
    if not to:
        return False
    cfg = app_settings.smtp_config(db)
    if not cfg.configured:
        return False

    msg = EmailMessage()
    msg["From"] = cfg.sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body or subject)

    with smtplib.SMTP(cfg.host, cfg.port, timeout=15) as server:
        if cfg.use_tls:
            server.starttls()
        if cfg.user:
            server.login(cfg.user, cfg.password)
        server.send_message(msg)
    return True
