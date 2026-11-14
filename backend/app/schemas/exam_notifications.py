"""考务通知 schema(KW-57~61)。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificationSettingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    exam_id: int
    schedule_notify_enabled: bool = True
    invigilation_remind_enabled: bool = True
    score_deadline_remind_enabled: bool = True
    publish_notify_enabled: bool = True


class NotificationSettingPut(BaseModel):
    schedule_notify_enabled: bool = True
    invigilation_remind_enabled: bool = True
    score_deadline_remind_enabled: bool = True
    publish_notify_enabled: bool = True


class NotifyOut(BaseModel):
    sent: int
    failed: int


class NotificationLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    exam_id: int
    notification_type: str
    recipient_name: str = ""
    channel: str = ""
    status: str = ""
    message: str = ""
    error: str | None = None
    sent_at: datetime | None = None
    created_at: datetime | None = None


class NotificationListOut(BaseModel):
    items: list[NotificationLogOut] = []
    total: int = 0


class ResendOut(BaseModel):
    sent: bool
    status: str
