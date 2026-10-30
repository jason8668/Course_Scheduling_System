"""特殊日课表 model。

一则规则 = 某范围(全校/某一年级)在某周期(单次某日/每周固定周几/
每月固定几号)内,对若干班级×节次的课做替换。
- 发布 = is_active=True,才参与展开;未发布只是草稿,查课表/提醒/课时都不认。
- 周期默认本学期:新建时没给 start_date/end_date,就取学期起止日。
- 一则规则的条目(entry)以 (class_unit_id, period_no) 为键,同一规则内不重复;
  course_assignment_id 为空 = 该节取消(主课表那节不上,也不换别的课)。
- 同天同节多则规则冲突时优先级:单次 > 每周 > 每月,展开时高优先级覆盖低优先级。
- 校历放假那天特殊日不生效:展开时先判放假,放假的班级×节次跳过特殊日。
"""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class SpecialDayRule(Base):
    __tablename__ = "special_day_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(128))
    # school / grade
    scope_type: Mapped[str] = mapped_column(String(20))
    # grade 时为年级数值;school 时为 None
    scope_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # single / weekly / monthly
    recurrence: Mapped[str] = mapped_column(String(20))
    # single 时为那一天;weekly/monthly 时可为空(以 start/end + weekday/day_of_month 定)
    single_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # weekly 时 1=周一..7=周日
    weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # monthly 时 1..31,缺那天的月份自动跳过
    day_of_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    entries: Mapped[list["SpecialDayEntry"]] = relationship(
        back_populates="rule", cascade="all, delete-orphan", lazy="selectin"
    )


class SpecialDayEntry(Base):
    __tablename__ = "special_day_entries"
    __table_args__ = (
        UniqueConstraint(
            "rule_id", "class_unit_id", "period_no", name="uq_special_day_entry"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(
        ForeignKey("special_day_rules.id", ondelete="CASCADE"), index=True
    )
    class_unit_id: Mapped[int] = mapped_column(
        ForeignKey("class_units.id", ondelete="CASCADE"), index=True
    )
    period_no: Mapped[int] = mapped_column(Integer)
    # 空 = 该节取消;非空 = 换成这门配课(其排课单位须含本班,API 层校验)
    course_assignment_id: Mapped[int | None] = mapped_column(
        ForeignKey("course_assignments.id", ondelete="CASCADE"), nullable=True, index=True
    )

    rule: Mapped[SpecialDayRule] = relationship(back_populates="entries")


class SpecialDayReminderLog(Base):
    """特殊日提醒防重复:同一规则、同一班、同一节、同一天、同一位老师只发一次。

    主课表提醒用 ClassReminderLog(entry_id),特殊日新增的格位没有现成的
    entry_id 可用,故另立此表,以 (rule_id, class_unit_id, period_no, date, teacher)
    为唯一键,语义与主提醒表一一对应。
    """

    __tablename__ = "special_day_reminder_logs"
    __table_args__ = (
        UniqueConstraint(
            "rule_id", "class_unit_id", "period_no", "class_date", "teacher_id",
            name="uq_special_day_reminder",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(
        ForeignKey("special_day_rules.id", ondelete="CASCADE"), index=True
    )
    class_unit_id: Mapped[int] = mapped_column(
        ForeignKey("class_units.id", ondelete="CASCADE"), index=True
    )
    period_no: Mapped[int] = mapped_column(Integer)
    class_date: Mapped[date] = mapped_column(Date, index=True)
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), index=True
    )
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
