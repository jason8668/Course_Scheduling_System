"""课表版本与格位 model。

Timetable:同学期可多份草稿(draft)并存,仅一份 published(见 architecture.md D4)。
ScheduleEntry:一笔配课排入的格位(weekday × period_no,span 表连堂占用节数)。
跑班群组的多笔配课同时排在同一时段(H7),以「同 scheduling_unit 的多笔 entry」表达。
唯一性(教师/班级/场地同时段不重复)由 conflict_checker 于应用层验证,不设 DB 约束
(跨节次表以墙钟时间判定,非单纯栏位唯一性,见 architecture.md D7)。
"""

import enum
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.assignment import CourseAssignment
from app.models.basedata import Room


class TimetableStatus(enum.StrEnum):
    draft = "draft"          # 草稿(可多份)
    published = "published"  # 已发布(同学期至多一份)
    archived = "archived"    # 已封存


class Timetable(Base):
    __tablename__ = "timetables"

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default=TimetableStatus.draft.value)

    # 部分排课产出时,solver 留下的未排清单(M6-3)。
    # 「哪些配课还缺节数」可由 completeness 从 DB 重算,不必存;但**排不下的原因**只有
    # 建模当下的 solver 知道(例:协同教学两位教师的不可排时段盖满整周)。先前它只活在
    # Redis 24h,草稿一旦 force 发布,那句话就永远遗失了。
    unscheduled: Mapped[list[dict] | None] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # 刻意用默认 lazy(select):课表可能有数千格,取 Timetable 本身时不应连带载入全部格位
    # (check-conflict 为拖曳热路径)。需要格位时由呼叫端明确查询 ScheduleEntry。
    entries: Mapped[list["ScheduleEntry"]] = relationship(
        back_populates="timetable", cascade="all, delete-orphan"
    )


class ScheduleEntry(Base):
    __tablename__ = "schedule_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    timetable_id: Mapped[int] = mapped_column(
        ForeignKey("timetables.id", ondelete="CASCADE"), index=True
    )
    course_assignment_id: Mapped[int] = mapped_column(
        ForeignKey("course_assignments.id", ondelete="CASCADE"), index=True
    )
    weekday: Mapped[int] = mapped_column(Integer)
    period_no: Mapped[int] = mapped_column(Integer)  # 连堂时为起始节次
    span: Mapped[int] = mapped_column(Integer, default=1)  # 占用连续节数(连堂 >1)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)  # H9 锁定不得移动
    # 本格位实际使用的场地;空 = 沿用配课的 room_id。
    # 排课引擎对「只指定场地类型」的配课逐格挑教室,结果存这里;调代课的教室异动亦然。
    room_id: Mapped[int | None] = mapped_column(
        ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True, index=True
    )

    timetable: Mapped[Timetable] = relationship(back_populates="entries")
    assignment: Mapped[CourseAssignment] = relationship(lazy="selectin")
    room: Mapped[Room | None] = relationship(lazy="selectin")

    @property
    def effective_room_id(self) -> int | None:
        """格位场地优先,未指定则沿用配课场地。"""
        return self.room_id if self.room_id is not None else self.assignment.room_id
