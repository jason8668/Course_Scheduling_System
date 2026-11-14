"""考场编排模型(KW-15~22):考场设置、编排规则、编排结果、编排锁定。

编排按科目分场:一次编排结果以 (exam_id, subject_id, student_id) 唯一,
同一考生同一科目只占一个座位;不同科目可分在不同考场。
座位号 seat_no 按考场内顺序从 1 开始编。
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

#: 编排方式(KW-16 清单原文,三选一,全年级统一):按班级整班入考场 /
#: 按成绩 S 型混排 / 随机混排。
ARRANGEMENT_MODES = ("whole_class", "s_shape", "random")
#: 考场类型:普通 / 特殊。
EXAM_ROOM_TYPES = ("普通", "特殊")
#: 默认编排方式与每考场人数上限(未设规则时用)。
DEFAULT_ARRANGEMENT_MODE = "whole_class"
DEFAULT_SCATTER_SAME_CLASS = True
DEFAULT_MAX_PER_ROOM = 30
#: S 型无成绩时的警告全文(前端原样展示,见 KW-17)。
S_SHAPE_NO_SCORE_WARNING = "暂无上次成绩，暂按学号顺序编排"


class ExamRoom(Base):
    """考场设置(KW-15):为一次考试选教室作考场。

    capacity 为空 = 取教室本身的 capacity;room_type 普通/特殊;
    is_special 为真表示特殊考生专用考场。
    """

    __tablename__ = "exam_rooms"
    __table_args__ = (
        UniqueConstraint("exam_id", "room_id", name="uq_exam_rooms_exam_room"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    room_id: Mapped[int] = mapped_column(
        ForeignKey("rooms.id", ondelete="CASCADE"), index=True
    )
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    room_type: Mapped[str] = mapped_column(String(20), default="普通")
    is_special: Mapped[bool] = mapped_column(Boolean, default=False)


class ExamArrangementRule(Base):
    """编排规则(KW-16):一次考试一条,未设时用默认值。"""

    __tablename__ = "exam_arrangement_rules"
    __table_args__ = (
        UniqueConstraint("exam_id", name="uq_exam_arrangement_rules_exam"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    mode: Mapped[str] = mapped_column(String(20), default=DEFAULT_ARRANGEMENT_MODE)
    scatter_same_class: Mapped[bool] = mapped_column(
        Boolean, default=DEFAULT_SCATTER_SAME_CLASS
    )
    max_per_room: Mapped[int] = mapped_column(Integer, default=DEFAULT_MAX_PER_ROOM)


class ExamRoomAssignment(Base):
    """编排结果(KW-17):某科某考场某考生的座位。"""

    __tablename__ = "exam_room_assignments"
    __table_args__ = (
        UniqueConstraint(
            "exam_id", "subject_id", "student_id",
            name="uq_exam_room_assignments_exam_subject_student",
        ),
        UniqueConstraint(
            "exam_id", "subject_id", "room_id", "seat_no",
            name="uq_exam_room_assignments_exam_subject_room_seat",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    room_id: Mapped[int] = mapped_column(
        ForeignKey("rooms.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    seat_no: Mapped[int] = mapped_column(Integer)


class ExamArrangementLock(Base):
    """编排锁定(KW-22):一次考试一条,锁定后自动编排与手动调整全部拒绝。"""

    __tablename__ = "exam_arrangement_locks"
    __table_args__ = (
        UniqueConstraint("exam_id", name="uq_exam_arrangement_locks_exam"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    locked_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    locked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    note: Mapped[str | None] = mapped_column(String(256), nullable=True)
