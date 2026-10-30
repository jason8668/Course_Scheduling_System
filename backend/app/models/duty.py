"""行政值日 model。

全校共用一位,不算课时、不占课,值日当天照常上课。
- 轮值是手动排的,不自动排:管理员在 DutyPattern 里按周几排好(周一 A、周二 B……),
  每周重复;临时调整用 DutyOverride 盖某一天,下周恢复原轮值。
- 轮值人选只有行政岗位老师:教师档案 admin_title 非空且非「无」者(与导入页
  「行政职称填无代表卸任」同一口径)。
- 管理员可直接改(改轮值或改某天覆盖);老师之间换班按调课模式:值日老师发起
  换班申请,对方同意后才替换(只换当天,生成一条覆盖)。
- 值日老师请假时手动指定替班:管理员直接给那天加一条覆盖即可,不走自动逻辑。
"""

from datetime import date, datetime

from sqlalchemy import (
    Date,
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


def is_admin_post(teacher) -> bool:
    """行政岗位判定:admin_title 非空且非「无」。"""
    title = (teacher.admin_title or "").strip() if teacher is not None else ""
    return bool(title) and title != "无"


class DutyPattern(Base):
    """每周轮值:某学期、某周几、某位行政岗老师。"""

    __tablename__ = "duty_patterns"
    __table_args__ = (
        UniqueConstraint("semester_id", "weekday", name="uq_duty_pattern"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    weekday: Mapped[int] = mapped_column(Integer)  # 1=周一..7=周日
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), index=True
    )


class DutyOverride(Base):
    """某天临时覆盖:只影响那一天,下周恢复轮值。"""

    __tablename__ = "duty_overrides"
    __table_args__ = (
        UniqueConstraint("semester_id", "date", name="uq_duty_override"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[date] = mapped_column(Date, index=True)
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), index=True
    )
    # 管理员直接改 / 换班同意后生成 / 请假替班,供列表里说明来源
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class DutySwapRequest(Base):
    """换班申请:值日老师发起,对方同意后才替换(只换当天)。

    status: pending / approved / rejected。同意后由后端生成覆盖,申请本身
    不再重复生效(approved 后再次同意会 400)。
    """

    __tablename__ = "duty_swap_requests"
    # 故意不建唯一键:被拒绝后可再发起,唯一键会挡住再发起;
    # 同一日期待处理重复由 API 层查 pending 挡。

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[date] = mapped_column(Date, index=True)
    from_teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), index=True
    )
    to_teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DutyReminderLog(Base):
    """值日提醒防重复:(学期, 值日日期, 老师, 种类)唯一。

    种类 day_before = 前一天提醒;morning = 当天早上提前半小时提醒。
    """

    __tablename__ = "duty_reminder_logs"
    __table_args__ = (
        UniqueConstraint(
            "semester_id", "duty_date", "teacher_id", "kind",
            name="uq_duty_reminder",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    duty_date: Mapped[date] = mapped_column(Date, index=True)
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20))
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
