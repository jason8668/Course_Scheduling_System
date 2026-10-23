"""校历活动 model(批次 #4)。

隶属于某学期(semester_id 范围):放假、集体活动、考试等占用。
- 一次性事件(start_date..end_date):供前端在本周课表/今日看板上覆盖显示占用/停课。
- weekly_recurring=True 的事件:以 start_date 的星期为准,每周重复,
  求解器装配层(services/solver_data)会把它合并为班级/教师的不可排格位。
"""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class SchoolCalendarEvent(Base):
    __tablename__ = "school_calendar_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(128))
    # holiday / activity / exam / other
    event_type: Mapped[str] = mapped_column(String(20))
    # school / grade / class
    scope_type: Mapped[str] = mapped_column(String(20))
    # grade 时为年级数值;class 时为 ClassUnit.id;school 时为 None
    scope_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    # 皆空 = 全天;给定时为当日节次闭区间(period_no)
    period_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    period_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weekly_recurring: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
