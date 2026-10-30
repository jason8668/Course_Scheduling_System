"""全域系统设置:SMTP 寄信(M4-3)、排课相关规则。管理员专用。"""

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.auth import require_roles
from app.core.db import get_db
from app.models.audit import AuditLog
from app.models.basedata import Teacher
from app.models.semester import Semester
from app.models.timetable import ClassReminderLog
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


class DingTalkAppSettingsIn(BaseModel):
    app_key: str = Field(default="", max_length=128)
    app_secret: str = Field(default="", max_length=128, description="应用密钥;留空 = 不变更")
    agent_id: str = Field(default="", max_length=32, description="企业内部应用的 agentId(数字)")
    lead_minutes: int = Field(default=15, ge=1, le=120, description="上课提醒提前分钟数")


class DingTalkAppSettingsOut(BaseModel):
    app_key: str
    agent_id: str
    configured: bool
    has_app_secret: bool
    lead_minutes: int


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
                 "之后调课、代课的通知会同步推送到这个群。",
        )
    except Exception as exc:  # noqa: BLE001 - 把钉钉错误原文回给管理员
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"发送失败:{exc}") from exc
    return {"sent": True}


def _dingtalk_app_out(db: Session) -> DingTalkAppSettingsOut:
    cfg = app_settings.dingtalk_app_config(db)
    return DingTalkAppSettingsOut(
        app_key=cfg.app_key, agent_id=cfg.agent_id, configured=cfg.configured,
        has_app_secret=bool(cfg.app_secret), lead_minutes=cfg.lead_minutes,
    )


@router.get("/settings/dingtalk-app", response_model=DingTalkAppSettingsOut)
def get_dingtalk_app(db: Session = Depends(get_db), _: User = Depends(admin_only)):
    """钉钉企业内部应用设置(不回传密钥明文)。"""
    return _dingtalk_app_out(db)


class ReminderTeacherBrief(BaseModel):
    id: int
    name: str


class DingTalkAppHealthOut(BaseModel):
    configured: bool
    lead_minutes: int
    job_scheduled: bool | None
    last_sent_at: datetime | None
    sent_7d: int
    teachers_with_phone: int
    teachers_missing_phone: int
    opted_out: list[ReminderTeacherBrief]
    unresolved: list[ReminderTeacherBrief]


@router.get("/settings/dingtalk-app/health", response_model=DingTalkAppHealthOut)
def dingtalk_app_health(db: Session = Depends(get_db), _: User = Depends(admin_only)):
    """上课提醒健康状态(只读):配置、排程任务、最近发送、关提醒与未解析教师。

    不发任何消息、不改任何设置;排程状态查不到(Redis 不可达)时回 null 而不是报错。
    教师计数为全部学期合计(提醒配置本身是全域的)。
    """
    cfg = app_settings.dingtalk_app_config(db)
    job_scheduled: bool | None = None
    try:
        from rq.registry import ScheduledJobRegistry

        from app.workers.queue import ops_queue
        from app.workers.scheduler import CLASS_REMINDER_JOB_ID

        job_scheduled = CLASS_REMINDER_JOB_ID in set(
            ScheduledJobRegistry(queue=ops_queue).get_job_ids())
    except Exception:  # noqa: BLE001 - Redis 不可达时健康页仍要能显示其余项目
        job_scheduled = None
    last_sent = db.query(func.max(ClassReminderLog.sent_at)).scalar()
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    sent_7d = db.query(func.count(ClassReminderLog.id)).filter(
        ClassReminderLog.sent_at >= week_ago).scalar() or 0
    teachers = db.query(Teacher).all()
    with_phone = [t for t in teachers if (t.phone or "").strip()]
    opted_out = [
        ReminderTeacherBrief(id=t.id, name=t.name) for t in teachers if not t.reminder_enabled
    ]
    unresolved = [
        ReminderTeacherBrief(id=t.id, name=t.name)
        for t in with_phone if not (t.dingtalk_userid or "").strip()
    ]
    return DingTalkAppHealthOut(
        configured=cfg.configured, lead_minutes=cfg.lead_minutes,
        job_scheduled=job_scheduled, last_sent_at=last_sent, sent_7d=sent_7d,
        teachers_with_phone=len(with_phone),
        teachers_missing_phone=len(teachers) - len(with_phone),
        opted_out=opted_out, unresolved=unresolved)


@router.put("/settings/dingtalk-app", response_model=DingTalkAppSettingsOut)
def put_dingtalk_app(
    body: DingTalkAppSettingsIn, db: Session = Depends(get_db), user: User = Depends(admin_only)
):
    app_settings.save_dingtalk_app(
        db, body.app_key, body.app_secret, body.agent_id, body.lead_minutes
    )
    db.add(AuditLog(
        user_id=user.id, username=user.username, action="update_dingtalk_app",
        target_type="app_setting", target_id=None,
        detail="钉钉企业内部应用设置更新"[:500],
    ))
    db.commit()
    return _dingtalk_app_out(db)


@router.post("/settings/dingtalk-app/test", status_code=status.HTTP_200_OK)
def test_dingtalk_app(
    body: DingTalkAppSettingsIn | None = None,
    db: Session = Depends(get_db), _: User = Depends(admin_only),
):
    """只取一次 access_token 验证企业应用三件套;不给任何老师发消息。可用表单上的值先测再存。"""
    from app.services.dingtalk_app import DingTalkAppClient

    cfg = app_settings.dingtalk_app_config(db)
    app_key = (body.app_key if body and body.app_key else cfg.app_key).strip()
    picked_secret = cfg.app_secret
    if body and body.app_secret:
        picked_secret = body.app_secret
    agent_id = (body.agent_id if body and body.agent_id else cfg.agent_id).strip()
    if not app_key or not picked_secret or not agent_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "请先填写 appKey、应用密钥与 agentId")
    try:
        client = DingTalkAppClient(app_key, picked_secret, agent_id)
        _ = client.token
    except Exception as exc:  # noqa: BLE001 - 把钉钉错误原文回给管理员
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"验证失败:{exc}") from exc
    return {"ok": True}


class ReminderDiagnosisStepOut(BaseModel):
    key: str
    label: str
    status: str
    detail: str


class ReminderDiagnosisOut(BaseModel):
    teacher_id: int
    teacher_name: str
    date: date
    period_no: int
    steps: list[ReminderDiagnosisStepOut]
    conclusion: str


@router.get("/settings/dingtalk-app/diagnose", response_model=ReminderDiagnosisOut)
def diagnose_reminder(
    semester_id: int = Query(...),
    teacher_id: int = Query(...),
    on: date = Query(...),
    period_no: int = Query(...),
    db: Session = Depends(get_db), _: User = Depends(admin_only),
):
    """提醒诊断(只读):某老师某天某节为什么没收到提醒,按链一步步查。
    诊断本身不发消息、不写回钉钉 userid 缓存,结论只看这一步的检查结果。"""
    from app.services import reminder_diagnosis as _diag

    sem = db.get(Semester, semester_id)
    if sem is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到学期")
    teacher = db.get(Teacher, teacher_id)
    if teacher is None or teacher.semester_id != semester_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到该学期的教师")
    d = _diag.diagnose(db, sem, teacher, on, period_no)
    return ReminderDiagnosisOut(
        teacher_id=d.teacher_id, teacher_name=d.teacher_name,
        date=d.date, period_no=d.period_no,
        steps=[ReminderDiagnosisStepOut(**vars(s)) for s in d.steps],
        conclusion=d.conclusion,
    )


class TestSendIn(BaseModel):
    teacher_id: int


@router.post("/settings/dingtalk-app/test-send")
def test_send_reminder(
    body: TestSendIn,
    db: Session = Depends(get_db), _: User = Depends(admin_only),
):
    """真发一条测试提醒给指定老师(管理员主动点才发):验的不只是 token,
    而是通讯录找人 + 工作通知权限整条链。失败时回具体原因,不静默。"""
    from app.services.dingtalk_app import DingTalkAppClient

    cfg = app_settings.dingtalk_app_config(db)
    if not cfg.configured:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "企业应用未配置,请先填写并保存")
    teacher = db.get(Teacher, body.teacher_id)
    if teacher is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到教师")
    if not (teacher.phone or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{teacher.name}没有手机号,无法按手机号找人")
    try:
        client = DingTalkAppClient(cfg.app_key, cfg.app_secret, cfg.agent_id)
        userid = teacher.dingtalk_userid or client.get_userid(teacher.phone)
        if not userid:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{teacher.name}的手机号不在企业通讯录里,请核对手机号或通讯录权限",
            )
        client.send_work_notification(
            userid, "测试提醒",
            f"### 测试提醒\n\n{teacher.name}老师,这是一条测试提醒,说明钉钉工作通知通道正常。",
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - 把钉钉错误原文回给管理员
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"测试发送失败:{exc}") from exc
    return {"ok": True, "teacher_name": teacher.name, "userid_found": bool(userid)}


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
