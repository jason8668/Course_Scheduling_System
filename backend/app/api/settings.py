"""全域系统设置:SMTP 寄信(M4-3)、排课相关规则。管理员专用。"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import require_roles
from app.core.db import get_db
from app.models.audit import AuditLog
from app.models.user import Role, User
from app.schemas.notification import SmtpSettingsIn, SmtpSettingsOut
from app.services import email as email_service
from app.services import settings as app_settings

router = APIRouter(tags=["settings"])

admin_only = require_roles(Role.admin)


class SchoolSettings(BaseModel):
    school_name: str = Field(min_length=1, max_length=64)


class SchedulingSettings(BaseModel):
    max_overtime: int = Field(
        ge=0, le=20,
        description="超课时上限(节):教师配课最多可超出应授节数几节。0 = 不限制",
    )


class DingTalkSettingsIn(BaseModel):
    webhook: str = Field(default="", max_length=500)
    secret: str = Field(default="", max_length=128, description="加签密钥;留空 = 不变更")


class DingTalkSettingsOut(BaseModel):
    webhook: str
    configured: bool
    has_secret: bool


class PatrolSettings(BaseModel):
    # app_settings.value 栏位长度 500
    legend: str = Field(max_length=500, description="课堂巡视情况记录表下方的记录说明;留空则恢复默认")


def _smtp_out(db: Session) -> SmtpSettingsOut:
    cfg = app_settings.smtp_config(db)
    return SmtpSettingsOut(
        host=cfg.host, port=cfg.port, user=cfg.user, sender=cfg.sender,
        use_tls=cfg.use_tls, configured=cfg.configured, has_password=bool(cfg.password),
    )


@router.get("/settings/smtp", response_model=SmtpSettingsOut)
def get_smtp(db: Session = Depends(get_db), _: User = Depends(admin_only)):
    """SMTP 设置(不回传密码明文)。"""
    return _smtp_out(db)


@router.put("/settings/smtp", response_model=SmtpSettingsOut)
def put_smtp(
    body: SmtpSettingsIn, db: Session = Depends(get_db), user: User = Depends(admin_only)
):
    app_settings.save_smtp(
        db, host=body.host, port=body.port, user=body.user, password=body.password,
        sender=body.sender, use_tls=body.use_tls,
    )
    db.add(AuditLog(
        user_id=user.id, username=user.username, action="update_smtp",
        target_type="app_setting", target_id=None,
        detail=f"SMTP 设置更新:{body.host}:{body.port}"[:500],
    ))
    db.commit()
    return _smtp_out(db)


@router.get("/settings/school", response_model=SchoolSettings)
def get_school(db: Session = Depends(get_db), _: User = Depends(admin_only)):
    return SchoolSettings(school_name=app_settings.school_name(db))


@router.put("/settings/school", response_model=SchoolSettings)
def put_school(
    body: SchoolSettings, db: Session = Depends(get_db), user: User = Depends(admin_only)
):
    """校名会即时反映在介面、导出课表与通知信,不需重启容器。"""
    app_settings.save_school_name(db, body.school_name)
    db.add(AuditLog(
        user_id=user.id, username=user.username, action="update_school_name",
        target_type="app_setting", target_id=None,
        detail=f"校名改为「{body.school_name}」"[:500],
    ))
    db.commit()
    return SchoolSettings(school_name=app_settings.school_name(db))


def _dingtalk_out(db: Session) -> DingTalkSettingsOut:
    cfg = app_settings.dingtalk_config(db)
    return DingTalkSettingsOut(
        webhook=cfg.webhook, configured=cfg.configured, has_secret=bool(cfg.secret),
    )


@router.get("/settings/dingtalk", response_model=DingTalkSettingsOut)
def get_dingtalk(db: Session = Depends(get_db), _: User = Depends(admin_only)):
    """钉钉设置(不回传密钥明文)。"""
    return _dingtalk_out(db)


@router.put("/settings/dingtalk", response_model=DingTalkSettingsOut)
def put_dingtalk(
    body: DingTalkSettingsIn, db: Session = Depends(get_db), user: User = Depends(admin_only)
):
    app_settings.save_dingtalk(db, body.webhook, body.secret)
    db.add(AuditLog(
        user_id=user.id, username=user.username, action="update_dingtalk",
        target_type="app_setting", target_id=None,
        detail="钉钉群机器人设置更新"[:500],
    ))
    db.commit()
    return _dingtalk_out(db)


@router.post("/settings/dingtalk/test", status_code=status.HTTP_200_OK)
def test_dingtalk(
    body: DingTalkSettingsIn | None = None,
    db: Session = Depends(get_db), _: User = Depends(admin_only),
):
    """发一则测试消息到钉钉群,当场回报结果。可用表单上的值先测再存。"""
    from app.services.notifications import send_dingtalk

    cfg = app_settings.dingtalk_config(db)
    webhook = (body.webhook if body and body.webhook else cfg.webhook).strip()
    picked = cfg.secret
    if body and body.secret:
        picked = body.secret
    if not webhook:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "尚未设置钉钉机器人 Webhook")
    try:
        send_dingtalk(
            webhook, picked,
            title="排课系统测试消息",
            text="### 排课系统测试消息\n\n收到这则消息,代表钉钉群机器人设置正确。"
                 "之后请假、调课、代课的通知会同步推送到这个群。",
        )
    except Exception as exc:  # noqa: BLE001 - 把钉钉错误原文回给管理员
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"发送失败:{exc}") from exc
    return {"sent": True}


@router.get("/settings/scheduling", response_model=SchedulingSettings)
def get_scheduling(db: Session = Depends(get_db), _: User = Depends(admin_only)):
    return SchedulingSettings(max_overtime=app_settings.max_overtime(db))


@router.put("/settings/scheduling", response_model=SchedulingSettings)
def put_scheduling(
    body: SchedulingSettings, db: Session = Depends(get_db), user: User = Depends(admin_only)
):
    app_settings.save_max_overtime(db, body.max_overtime)
    db.add(AuditLog(
        user_id=user.id, username=user.username, action="update_scheduling_settings",
        target_type="app_setting", target_id=None,
        detail=f"超课时上限设为 {body.max_overtime} 节",
    ))
    db.commit()
    return SchedulingSettings(max_overtime=app_settings.max_overtime(db))


@router.get("/settings/patrol", response_model=PatrolSettings)
def get_patrol(db: Session = Depends(get_db), _: User = Depends(admin_only)):
    return PatrolSettings(legend=app_settings.patrol_legend(db))


@router.put("/settings/patrol", response_model=PatrolSettings)
def put_patrol(
    body: PatrolSettings, db: Session = Depends(get_db), user: User = Depends(admin_only)
):
    app_settings.save_patrol_legend(db, body.legend)
    db.add(AuditLog(
        user_id=user.id, username=user.username, action="update_patrol_settings",
        target_type="app_setting", target_id=None, detail="修改课堂巡视情况记录表的记录说明",
    ))
    db.commit()
    return PatrolSettings(legend=app_settings.patrol_legend(db))


@router.post("/settings/smtp/test", status_code=status.HTTP_200_OK)
def test_smtp(
    to: str, db: Session = Depends(get_db), _: User = Depends(admin_only)
):
    """寄一封测试信,当场回报成功或错误(不走 RQ,好让管理员立刻看到结果)。"""
    cfg = app_settings.smtp_config(db)
    if not cfg.configured:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "尚未设置 SMTP 主机与寄件人")
    try:
        sent = email_service.send(
            db, to=to, subject="排课系统测试信",
            body="这是一封测试信,收到代表 SMTP 设置正确。",
        )
    except Exception as exc:  # noqa: BLE001 - 把 SMTP 错误原文回给管理员
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"寄送失败:{exc}") from exc
    return {"sent": sent, "to": to}
