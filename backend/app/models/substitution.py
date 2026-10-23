"""调代课处置 model(M4-2,architecture.md §5.3)。

一笔 `substitution` = 对一个受影响节次的处置决定。**指派即生效**——没有邀请/婉拒流程
(2026-07-09 定案:组长实务上已事先口头征得同意,通知仅为正式告知)。

处置方式的真相在这里;`affected_period.handler_teacher_id` / `.status` 只是冗余指标,
供今日看板、月结统计直接查询,不必每次回头 join。一个受影响节次至多一笔有效处置
(改派时更新同一笔),故 `affected_period_id` 唯一。

**swap(调课)的语意**:甲请假日的某节由乙代;交换条件是甲之后补乙一节(乙原本那节放掉)。
因此要验四件事都无冲突:乙在甲那节、甲在乙那节、以及两个班各自不重复排课。
`swap_*` 栏位记录「乙原本要放掉、改由甲补」的那一节(以快照保存,课表改版不影响已成立的调课)。
"""

import enum
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.basedata import Teacher


class SubstitutionType(enum.StrEnum):
    substitute = "substitute"    # 代课(找人代)
    swap = "swap"                # 调课(两位教师互换节次)
    merge = "merge"              # 并班(并入他班,不另计代课课时)
    self_study = "self_study"    # 自习(学生自习,不另计代课课时)
    cancel = "cancel"            # 不处理(当天停课/弹性运用)


SUBSTITUTION_TYPE_CN = {
    SubstitutionType.substitute.value: "代课",
    SubstitutionType.swap.value: "调课",
    SubstitutionType.merge.value: "并班",
    SubstitutionType.self_study.value: "自习",
    SubstitutionType.cancel.value: "不处理",
}

# 代课课时由谁支付(印在代课通知单的「计费方式」)。自由文字栏位,这里只是给界面的常用选项,
# 学校要填别的也存得进去。
FUNDING_SOURCES = ("公费代课", "自费代课", "日薪代课", "课务自理", "不支课时")

# 日薪代课(小学常见:班主任请整天假,由一位代课老师整天接手,按日计酬而非按节)。
# 月结统计据此把这些节次从「课时计费节数」移到「日薪天数」(用户回报 #36)。
DAILY_FUNDING = "日薪代课"

# 需要指定一位「处理教师」的处置(代课的代课老师、调课的对调老师、并班的接收老师)
TYPES_WITH_HANDLER = frozenset({
    SubstitutionType.substitute.value,
    SubstitutionType.swap.value,
    SubstitutionType.merge.value,
})


class Substitution(Base):
    __tablename__ = "substitutions"

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    # 一个受影响节次至多一笔有效处置;改派时更新同一笔
    affected_period_id: Mapped[int] = mapped_column(
        ForeignKey("affected_periods.id", ondelete="CASCADE"), unique=True, index=True
    )
    type: Mapped[str] = mapped_column(String(20))

    # 处理教师:代课/调课/并班的接手者;自习/不处理为空
    handler_teacher_id: Mapped[int | None] = mapped_column(
        ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # 是否计代课课时:代课通常计;并班/自习/不处理不计(architecture.md §5.4 月结)
    counts_toward_hours: Mapped[bool] = mapped_column(Boolean, default=True)
    funding_source: Mapped[str] = mapped_column(String(32), default="")  # 经费来源标记(选填)

    # ── 调课的交换节次(乙原本要放掉、改由甲补的那一节)──
    # 以快照保存:课表改版不影响已成立的调课
    swap_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    swap_period_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    swap_period_name: Mapped[str] = mapped_column(String(32), default="")
    swap_class_names: Mapped[str] = mapped_column(String(128), default="")
    swap_subject_name: Mapped[str] = mapped_column(String(64), default="")
    swap_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("schedule_entries.id", ondelete="SET NULL"), nullable=True
    )

    note: Mapped[str] = mapped_column(Text, default="")
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by_name: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    handler: Mapped[Teacher | None] = relationship(lazy="selectin")
