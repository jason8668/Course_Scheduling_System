"""通知 model(architecture.md §5.3)。

M4-1 只建立资料落地与写入点;**寄送管道**(站内铃铛、Email、v2 的 webhook/钉钉)
由 M4-3 以 `NotificationChannel` 介面实作。这里先把「该通知谁、通知什么」定下来,
因为销假的级联取消必须立刻能通知已被指派的代课教师——那是 M4-1 的验收标准。

收件人以 `teacher_id` 表达而非 `user_id`:外聘师资可能没有系统帐号但有 Email,
站内/Email 两个管道各自从教师主档解析(`teacher.user_id` / `teacher.email`)。
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.basedata import Teacher


class NotificationType(enum.StrEnum):
    leave_registered = "leave_registered"                # 请假已登记(组长代登时通知教师)
    leave_cancelled = "leave_cancelled"                  # 销假
    substitution_assigned = "substitution_assigned"      # 被指派代课(M4-2)
    substitution_cancelled = "substitution_cancelled"    # 原订代课取消(销假级联)
    timetable_published = "timetable_published"          # 课表发布(M4-3)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    teacher_id: Mapped[int | None] = mapped_column(
        ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    type: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str] = mapped_column(String(200), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 「确认收到」:通知层的已读确认,不影响课务状态
    # (2026-07-09 定案:调代课不设邀请/婉拒流程,指派即生效)
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    teacher: Mapped[Teacher | None] = relationship(lazy="selectin")
