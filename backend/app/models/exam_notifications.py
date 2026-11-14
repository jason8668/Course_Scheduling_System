"""考务通知模型(KW-57~61):考试通知开关、通知发送记录。

决策:不复用 notifications 表——那张表强制 semester_id + teacher_id、
没有 channel / status / error / related_type / related_id 栏位,
装不下考务通知上下文,
故按任务要求新建 ExamNotificationLog;开关另存 ExamNotificationSetting。
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

#: 考务通知类型(与清单 KW-57~60 对应)。
NOTIFICATION_TYPES = ("考试日程", "监考提醒", "录分截止", "成绩发布")
#: 发送渠道:钉钉(企业内部应用个人工作通知)/站内(只记记录,不另发)。
NOTIFICATION_CHANNELS = ("钉钉", "站内")
#: 发送状态。
NOTIFICATION_STATUSES = ("成功", "失败", "待发送")


class ExamNotificationSetting(Base):
    """考试通知开关(KW-57~59 共用):一次考试一条,未设过用默认值(全开)。"""

    __tablename__ = "exam_notification_settings"
    __table_args__ = (
        UniqueConstraint("exam_id", name="uq_exam_notification_settings_exam"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    schedule_notify_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    invigilation_remind_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    score_deadline_remind_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ExamNotificationLog(Base):
    """考务通知发送记录(KW-61):每发一次(每位收件人)记一行。

    recipient_user_id 为收件人账号 id:教师取 Teacher.user_id(无账号时为空,
    以 recipient_name 辨识)。related_type / related_id
    标明这条通知关联的实体,供到期扫去重用:
    考试日程为 exam/考试 id;监考手动为 invigilation/教师 id,
    到期扫考前一天为 invigilation_day_before/监考安排 id、
    当天开考前为 invigilation_day_of/监考安排 id;
    录分手动为 score_deadline/教师 id,到期扫 24 小时为
    score_deadline_24h/教师 id、2 小时为 score_deadline_2h/教师 id。
    成绩发布通知已取消,历史记录仍保留该类型。
    """

    __tablename__ = "exam_notification_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    notification_type: Mapped[str] = mapped_column(String(20), index=True)
    recipient_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    recipient_name: Mapped[str] = mapped_column(String(64), default="")
    channel: Mapped[str] = mapped_column(String(10), default="站内")
    status: Mapped[str] = mapped_column(String(10), default="待发送", index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    related_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    related_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
