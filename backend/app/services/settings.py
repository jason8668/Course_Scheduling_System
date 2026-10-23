"""全域系统设置的读写(M4-3)。"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.app_setting import AppSetting

# 校名。显示于介面、导出的课表(Excel/PDF/PNG)、代课通知信与 A4 公告单。
#
# 先前只能在安装时以 .env 的 SCHOOL_NAME 指定,要改就得编辑档案并重启容器——
# 对只会用网页的教学组长来说形同改不了。现在存在资料库,可随时于系统管理修改;
# 未设置时沿用 .env 的值,既有部署升级后行为不变。
SCHOOL_NAME = "school_name"

# 超课时上限:一位教师每周配课节数,最多可超出其「应授节数」几节。
# 依各地/各校规定自订(实务常见约 8 节)。0 = 不限制。
#
# 为什么是「应授 + N」而不是固定值:应授本身就因身分而异——以浙江省初中为例,
# 语文专任 12 节、兼任班主任 10 节、兼任主任 6 节,固定上限对谁都不合适。
MAX_OVERTIME = "max_overtime_periods"
DEFAULT_MAX_OVERTIME = 8

# 巡堂表下方的「记录说明」。授课情形/学生学习的代码各校不同(有的是 1~3,有的是优良可),
# 写死就只有一所学校能用;默认值取自使用学校的纸本,可在系统管理修改。
PATROL_LEGEND = "patrol_legend"
DEFAULT_PATROL_LEGEND = (
    "一、授课情形(填写代码):1. 融入媒体教学 2. 双语教学 3. 正常教学\n"
    "二、学生学习状况(填写代码):1. 态度积极 2. 秩序良好 3. 未能专心\n"
    "三、注记事项部分请记录巡堂时临时状况"
)

# 钉钉群机器人 Webhook(调代课通知同步推送到教师群)
DINGTALK_WEBHOOK = "dingtalk_webhook"
DINGTALK_SECRET = "dingtalk_secret"


@dataclass(frozen=True, slots=True)
class DingTalkConfig:
    webhook: str
    secret: str

    @property
    def configured(self) -> bool:
        return bool(self.webhook)


def dingtalk_config(db: Session) -> DingTalkConfig:
    values = all_settings(db)
    webhook = values[DINGTALK_WEBHOOK] if DINGTALK_WEBHOOK in values else ""
    sign = values[DINGTALK_SECRET] if DINGTALK_SECRET in values else ""
    return DingTalkConfig(webhook.strip(), sign.strip())


def save_dingtalk(db: Session, webhook: str, secret: str) -> None:
    set_value(db, DINGTALK_WEBHOOK, webhook.strip())
    # 空密钥视为「不变更」(同 SMTP 密码语义),避免每次保存都要重打
    if secret:
        set_value(db, DINGTALK_SECRET, secret.strip())


# SMTP 设置的 key
SMTP_HOST = "smtp_host"
SMTP_PORT = "smtp_port"
SMTP_USER = "smtp_user"
SMTP_PASSWORD = "smtp_password"
SMTP_FROM = "smtp_from"
SMTP_TLS = "smtp_tls"


@dataclass(frozen=True, slots=True)
class SmtpConfig:
    host: str
    port: int
    user: str
    password: str
    sender: str
    use_tls: bool

    @property
    def configured(self) -> bool:
        """只要有主机与寄件人即视为已设置;帐密可空(内网转发常见)。"""
        return bool(self.host and self.sender)


def get(db: Session, key: str, default: str = "") -> str:
    row = db.get(AppSetting, key)
    return row.value if row else default


def set_value(db: Session, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value


def all_settings(db: Session) -> dict[str, str]:
    return {row.key: row.value for row in db.scalars(select(AppSetting))}


def school_name(db: Session) -> str:
    """校名。系统设置优先,未设置时沿用安装时 .env 的 SCHOOL_NAME。"""
    from app.core.config import settings as env_settings

    return get(db, SCHOOL_NAME).strip() or env_settings.school_name


def save_school_name(db: Session, value: str) -> None:
    set_value(db, SCHOOL_NAME, value.strip())


def patrol_legend(db: Session) -> str:
    """巡堂表的记录说明;未设置时用默认值。"""
    return get(db, PATROL_LEGEND).strip() or DEFAULT_PATROL_LEGEND


def save_patrol_legend(db: Session, value: str) -> None:
    set_value(db, PATROL_LEGEND, value.strip())


def max_overtime(db: Session) -> int:
    """超课时上限(节)。未设置或值毁损时回默认值,不让设置问题挡住配课作业。"""
    raw = get(db, MAX_OVERTIME)
    if not raw:
        return DEFAULT_MAX_OVERTIME
    try:
        return max(int(raw), 0)
    except ValueError:
        return DEFAULT_MAX_OVERTIME


def save_max_overtime(db: Session, value: int) -> None:
    set_value(db, MAX_OVERTIME, str(max(value, 0)))


def smtp_config(db: Session) -> SmtpConfig:
    values = all_settings(db)
    return SmtpConfig(
        host=values.get(SMTP_HOST, ""),
        port=int(values.get(SMTP_PORT) or 25),
        user=values.get(SMTP_USER, ""),
        password=values.get(SMTP_PASSWORD, ""),
        sender=values.get(SMTP_FROM, ""),
        use_tls=values.get(SMTP_TLS, "") == "1",
    )


def save_smtp(
    db: Session, *, host: str, port: int, user: str, password: str, sender: str, use_tls: bool
) -> None:
    set_value(db, SMTP_HOST, host.strip())
    set_value(db, SMTP_PORT, str(port))
    set_value(db, SMTP_USER, user.strip())
    # 空密码视为「不变更」,避免每次存设置都要重打密码
    if password:
        set_value(db, SMTP_PASSWORD, password)
    set_value(db, SMTP_FROM, sender.strip())
    set_value(db, SMTP_TLS, "1" if use_tls else "0")
