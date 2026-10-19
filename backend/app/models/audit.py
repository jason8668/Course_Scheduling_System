"""操作轨迹 model(architecture.md §2.2 audit_log)。

谁在何时改了什么。排课发布、调代课指派等关键异动必记;帐号被删除时保留纪录
(user_id 设为 NULL),避免轨迹消失。
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    username: Mapped[str] = mapped_column(String(64), default="")  # 快照,帐号删除后仍可辨识
    action: Mapped[str] = mapped_column(String(64), index=True)    # 如 publish_timetable
    target_type: Mapped[str] = mapped_column(String(32), default="")
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str] = mapped_column(String(500), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
