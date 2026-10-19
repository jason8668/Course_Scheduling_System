"""基础资料 model:教师、科目、场地、班级、教师时段规则。

皆隶属于某学期(semester_id 范围,见 D3 学期快照)。
"""

import enum
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Integer,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.user import User


class RoomType(enum.StrEnum):
    normal = "normal"      # 普通教室
    special = "special"    # 专科教室
    workshop = "workshop"  # 实习工场
    outdoor = "outdoor"    # 户外


class ClassTrack(enum.StrEnum):
    elementary = "elementary"      # 小学
    junior_high = "junior_high"    # 初中
    senior_high = "senior_high"    # 普通型高中
    comprehensive = "comprehensive"  # 综合型高中
    vocational = "vocational"      # 技术型高中


class TeacherRuleType(enum.StrEnum):
    unavailable = "unavailable"  # 不可排(硬约束)
    avoid = "avoid"              # 尽量避开(软约束)
    prefer = "prefer"            # 偏好(软约束)


# ── 多对多关联表 ──────────────────────
teacher_subjects = Table(
    "teacher_subjects",
    Base.metadata,
    Column("teacher_id", ForeignKey("teachers.id", ondelete="CASCADE"), primary_key=True),
    Column("subject_id", ForeignKey("subjects.id", ondelete="CASCADE"), primary_key=True),
)

room_subjects = Table(
    "room_subjects",
    Base.metadata,
    Column("room_id", ForeignKey("rooms.id", ondelete="CASCADE"), primary_key=True),
    Column("subject_id", ForeignKey("subjects.id", ondelete="CASCADE"), primary_key=True),
)


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    domain: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 领域/群别
    required_room_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    default_block_size: Mapped[int] = mapped_column(Integer, default=1)  # 默认连堂长度(1=不连堂)
    # 主科(国英数等):排课引擎的软约束 S5 会尽量把主科排在上午
    is_major: Mapped[bool] = mapped_column(Boolean, default=False)


class Teacher(Base):
    __tablename__ = "teachers"
    # 一个帐号在同一学期至多绑定一位教师(user_id 为空时不受限,见 M2-0)
    __table_args__ = (
        UniqueConstraint("semester_id", "user_id", name="uq_teachers_semester_user"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(32))
    id_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)  # 身分证末四码(软性识别)
    base_periods: Mapped[int] = mapped_column(Integer, default=0)  # 基本课时
    admin_title: Mapped[str | None] = mapped_column(String(32), nullable=True)  # 行政职称
    admin_reduction: Mapped[int] = mapped_column(Integer, default=0)  # 行政减课节数
    is_external: Mapped[bool] = mapped_column(Boolean, default=False)  # 外聘/业界师资
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # 在职
    # 联络信息(皆选填,供调代课通知与人工联络;挂教师因外聘师资可能无系统帐号)
    email: Mapped[str | None] = mapped_column(String(128), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    line_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 绑定的登录帐号(空=无帐号,如外聘师资);帐号删除时设为 NULL 保留教师主档
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    subjects: Mapped[list[Subject]] = relationship(secondary=teacher_subjects, lazy="selectin")
    time_rules: Mapped[list["TeacherTimeRule"]] = relationship(
        back_populates="teacher", cascade="all, delete-orphan", lazy="selectin"
    )
    user: Mapped["User | None"] = relationship(lazy="selectin")


class TeacherTimeRule(Base):
    __tablename__ = "teacher_time_rules"
    __table_args__ = (
        UniqueConstraint("teacher_id", "weekday", "period_no", name="uq_teacher_time_rules_cell"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), index=True
    )
    weekday: Mapped[int] = mapped_column(Integer)
    period_no: Mapped[int] = mapped_column(Integer)
    rule_type: Mapped[str] = mapped_column(String(20))

    teacher: Mapped[Teacher] = relationship(back_populates="time_rules")


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    room_type: Mapped[str] = mapped_column(String(20), default=RoomType.normal.value)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)

    subjects: Mapped[list[Subject]] = relationship(secondary=room_subjects, lazy="selectin")


class ClassUnit(Base):
    __tablename__ = "class_units"
    # 同学期班名唯一(M6-5):冲突讯息、课表、导出全都以班名指称班级,
    # 同学期两个「301」会让组长在界面上分不出是哪一班。
    __table_args__ = (
        UniqueConstraint("semester_id", "name", name="uq_class_units_semester_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    grade: Mapped[int] = mapped_column(Integer)       # 年级
    name: Mapped[str] = mapped_column(String(32))     # 班名
    track: Mapped[str] = mapped_column(String(20))    # 学制标签
    department: Mapped[str | None] = mapped_column(String(32), nullable=True)  # 群科(技高)
    student_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 人数
    homeroom_teacher_id: Mapped[int | None] = mapped_column(
        ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # 所属节次表(空=用学期默认表);支援完全中学/附设小学部等多套节次表情境
    period_table_id: Mapped[int | None] = mapped_column(
        ForeignKey("period_tables.id", ondelete="SET NULL"), nullable=True, index=True
    )

    homeroom_teacher: Mapped[Teacher | None] = relationship(lazy="selectin")
