"""配课领域 model:排课单位、配课、配课教师、连堂规则。

排课单位(scheduling_unit)是支撑五学制的核心抽象(architecture.md D1):
- `single`:单一班级的课(小学包班=导师在自己班的大量 single 配课)
- `group`:跑班群组(多班联排,群组内配课由求解器强制排在同一时段)
- `alternate`:单双周组(v1.3.0;一个班,单周一笔、双周一笔,同一格隔周轮流上)

配课(course_assignment)挂在排课单位上,而非直接挂班级,故单班与跑班共用一套 schema。
"""

import enum

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.basedata import ClassUnit, Room, Subject, Teacher


class SchedulingUnitType(enum.StrEnum):
    single = "single"  # 单一班级
    group = "group"    # 跑班群组(多班联排)
    alternate = "alternate"  # 单双周组(同一格单周、双周轮流上不同的课)


# 「同一格一起排」的单位:跑班群组与单双周组的配课都要排在同一个时段
BUNDLE_UNIT_TYPES = frozenset({SchedulingUnitType.group.value, SchedulingUnitType.alternate.value})


class SchedulingUnit(Base):
    __tablename__ = "scheduling_units"

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    unit_type: Mapped[str] = mapped_column(String(10), default=SchedulingUnitType.single.value)
    name: Mapped[str] = mapped_column(String(64))  # single=班名;group=群组名(如「高二多元选修」)

    members: Mapped[list["SchedulingUnitMember"]] = relationship(
        back_populates="scheduling_unit", cascade="all, delete-orphan", lazy="selectin"
    )
    assignments: Mapped[list["CourseAssignment"]] = relationship(
        back_populates="scheduling_unit", cascade="all, delete-orphan", lazy="selectin"
    )


class SchedulingUnitMember(Base):
    __tablename__ = "scheduling_unit_members"
    __table_args__ = (
        UniqueConstraint(
            "scheduling_unit_id", "class_unit_id", name="uq_scheduling_unit_members_pair"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    scheduling_unit_id: Mapped[int] = mapped_column(
        ForeignKey("scheduling_units.id", ondelete="CASCADE"), index=True
    )
    class_unit_id: Mapped[int] = mapped_column(
        ForeignKey("class_units.id", ondelete="CASCADE"), index=True
    )

    scheduling_unit: Mapped[SchedulingUnit] = relationship(back_populates="members")
    class_unit: Mapped[ClassUnit] = relationship(lazy="selectin")


class CourseAssignment(Base):
    __tablename__ = "course_assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    # semester_id 为去正规化栏位,方便以学期为范围查询(随排课单位同属一学期)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    scheduling_unit_id: Mapped[int] = mapped_column(
        ForeignKey("scheduling_units.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    periods_per_week: Mapped[int] = mapped_column(Integer)  # 每周节数
    # 场地需求:类型(普通/专科/实习工场/户外)或指定场地;lock_room 表是否绑死该场地
    required_room_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    room_id: Mapped[int | None] = mapped_column(
        ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True, index=True
    )
    lock_room: Mapped[bool] = mapped_column(Boolean, default=False)
    # 单双周(v1.3.0):None = 每周都上;"odd" / "even" = 只上单周 / 双周(只出现在单双周组)
    week_parity: Mapped[str | None] = mapped_column(String(4), nullable=True, default=None)

    scheduling_unit: Mapped[SchedulingUnit] = relationship(back_populates="assignments")
    subject: Mapped[Subject] = relationship(lazy="selectin")
    room: Mapped[Room | None] = relationship(lazy="selectin")
    teachers: Mapped[list["AssignmentTeacher"]] = relationship(
        back_populates="assignment", cascade="all, delete-orphan", lazy="selectin"
    )
    block_rules: Mapped[list["BlockRule"]] = relationship(
        back_populates="assignment", cascade="all, delete-orphan", lazy="selectin"
    )


class AssignmentTeacher(Base):
    __tablename__ = "assignment_teachers"
    __table_args__ = (
        UniqueConstraint(
            "course_assignment_id", "teacher_id", name="uq_assignment_teachers_pair"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    course_assignment_id: Mapped[int] = mapped_column(
        ForeignKey("course_assignments.id", ondelete="CASCADE"), index=True
    )
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), index=True
    )
    is_lead: Mapped[bool] = mapped_column(Boolean, default=True)  # 主教(False=协同)

    assignment: Mapped[CourseAssignment] = relationship(back_populates="teachers")
    teacher: Mapped[Teacher] = relationship(lazy="selectin")


class BlockRule(Base):
    __tablename__ = "block_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_assignment_id: Mapped[int] = mapped_column(
        ForeignKey("course_assignments.id", ondelete="CASCADE"), index=True
    )
    block_size: Mapped[int] = mapped_column(Integer)      # 连堂长度(2-4)
    count_per_week: Mapped[int] = mapped_column(Integer)  # 每周次数

    assignment: Mapped[CourseAssignment] = relationship(back_populates="block_rules")
