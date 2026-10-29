"""教师「我的」页:个人上课提醒自配置的出入参。"""

from pydantic import BaseModel, Field


class ReminderPreferenceOut(BaseModel):
    """提醒自配置回显。bound=False = 登录者未绑定教师档案,其余字段为默认值。"""

    bound: bool
    reminder_enabled: bool
    reminder_lead_minutes: int | None
    global_lead_minutes: int
    phone: str | None
    dingtalk_bound: bool


class ReminderPreferenceIn(BaseModel):
    """提醒自配置写入。lead/phone 缺省 = 不改;lead 显式 null = 回到跟随学校设置。"""

    reminder_enabled: bool
    reminder_lead_minutes: int | None = Field(default=None, ge=1, le=120)
    phone: str | None = Field(default=None, max_length=32)
