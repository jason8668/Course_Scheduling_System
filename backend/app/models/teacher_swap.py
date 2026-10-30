"""老师自主发起的调课(不走请假、不走管理员)。

一条记录 = 某一天某一节某一个班的一门课,原任教师换成另一位教师上;
可带一节补课:原任教师在另一天另一节去上换课教师的班(对方的课),
补课那节算原任教师自己的课,不算代课。

审批:发起人必须是原任或换课教师其中一方,另一方同意即生效,
不需要主任/管理员过目。发起人自己不能同意自己的申请。

事后补登:Jason 2026-10-30 09:21 定——时间过了、已经口头通知、
临时已经去上了别人的课,事后仍可在系统里把这节课调过去。
事后补登与事前调课走同一条记录:日期可以是过去,对方在系统里
点同意即确认这件事(不是批准未来的动作),生效后课时统计按换后的算。

课时口径:与请假对调同款——换课那节换课教师计为代课(origin substitute),
补课那节原任教师计为自己的课(origin base);未同意的记录不算。

提醒口径:生效的调课,当天那节原任教师不再收到该班的提醒,
换课教师收到该班的提醒(补课那节反过来);时间已过的记录当天已过,
提醒任务自然不再发,不会补发过去的提醒。
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class TeacherSwap(Base):
    __tablename__ = "teacher_swaps"

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    # 发起人(账号绑定的教师):必须是原任或换课其中一方
    requester_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), index=True
    )
    # pending / approved / rejected
    status: Mapped[str] = mapped_column(String(20), default="pending")
    note: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # 换课那节
    class_date: Mapped[date] = mapped_column(Date, index=True)
    period_no: Mapped[int] = mapped_column(Integer)
    class_unit_id: Mapped[int] = mapped_column(
        ForeignKey("class_units.id", ondelete="CASCADE"), index=True
    )
    course_assignment_id: Mapped[int] = mapped_column(
        ForeignKey("course_assignments.id", ondelete="CASCADE"), index=True
    )
    original_teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), index=True
    )
    handler_teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), index=True
    )

    # 补课那节(可空:不填 = 只换一节,不带补课)
    makeup_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    makeup_period_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    makeup_class_unit_id: Mapped[int | None] = mapped_column(
        ForeignKey("class_units.id", ondelete="CASCADE"), nullable=True, index=True
    )
    makeup_assignment_id: Mapped[int | None] = mapped_column(
        ForeignKey("course_assignments.id", ondelete="CASCADE"), nullable=True, index=True
    )

    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TeacherSwapReminderLog(Base):
    """调课提醒防重复:同一调课、同一班、同一节、同一天、同一位老师只发一次。

    补课那节与换课那节的 (class, period, date) 各不相同,故同一 swap_id
    下两节不会撞键;若同一天同一节有两条调课(罕见),以 swap_id 区分。
    """

    __tablename__ = "teacher_swap_reminder_logs"
    __table_args__ = (
        UniqueConstraint(
            "swap_id", "class_unit_id", "period_no", "class_date", "teacher_id",
            name="uq_teacher_swap_reminder",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    swap_id: Mapped[int] = mapped_column(
        ForeignKey("teacher_swaps.id", ondelete="CASCADE"), index=True
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
