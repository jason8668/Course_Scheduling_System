"""监考安排模型(KW-23~29):监考规则、教师池、监考安排、巡考、考风考纪记录。

监考按 (考试, 科目, 考场) 分场:每场每考场安排若干监考教师,
唯一约束 (exam_id, subject_id, room_id, teacher_id) 保证同一教师
同一场同一考场只排一次;主监/副监暂不区分,role 统一为“监考”,
留 role 字段以后扩展。
考风考纪记录只做记录与汇总展示,不写入学生状态异动、不记入德育评价。
"""

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

#: 监考角色:暂不区分主监/副监,统一为“监考”,留字段以后扩展。
INVIGILATION_ROLE = "监考"
#: 考风考纪类型。
DISCIPLINE_TYPES = ("违纪", "作弊", "其他")
#: 监考规则默认值。
DEFAULT_AVOID_OWN_CLASS = True
DEFAULT_AVOID_OWN_SUBJECT = True
DEFAULT_INVIGILATORS_PER_ROOM = 2


class ExamInvigilationRule(Base):
    """监考规则(KW-23):一次考试一条,未设时用默认值。

    avoid_own_class:班主任避监本班;avoid_own_subject:任课教师避监本学科;
    invigilators_per_room:每考场监考人数。
    """

    __tablename__ = "exam_invigilation_rules"
    __table_args__ = (
        UniqueConstraint("exam_id", name="uq_exam_invigilation_rules_exam"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    avoid_own_class: Mapped[bool] = mapped_column(
        Boolean, default=DEFAULT_AVOID_OWN_CLASS
    )
    avoid_own_subject: Mapped[bool] = mapped_column(
        Boolean, default=DEFAULT_AVOID_OWN_SUBJECT
    )
    invigilators_per_room: Mapped[int] = mapped_column(
        Integer, default=DEFAULT_INVIGILATORS_PER_ROOM
    )


class ExamInvigilatorPool(Base):
    """监考教师池(KW-23):每场考试的教师可监考范围。

    未建池(无任何行)时默认本学期全部在职教师都可监考;建池后以
    eligible 为准,停用的教师不再自动排入,手工指定时也会被拒绝。
    """

    __tablename__ = "exam_invigilator_pools"
    __table_args__ = (
        UniqueConstraint(
            "exam_id", "teacher_id",
            name="uq_exam_invigilator_pools_exam_teacher",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), index=True
    )
    eligible: Mapped[bool] = mapped_column(Boolean, default=True)


class ExamInvigilation(Base):
    """监考安排(KW-24/25):某科某考场某教师的一次监考。"""

    __tablename__ = "exam_invigilations"
    __table_args__ = (
        UniqueConstraint(
            "exam_id", "subject_id", "room_id", "teacher_id",
            name="uq_exam_invigilations_exam_subject_room_teacher",
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
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20), default=INVIGILATION_ROLE)


class ExamPatrol(Base):
    """巡考安排(KW-26):某日某巡考人员的负责范围。

    scope 为自由文本,例如“2楼东侧”或考场名清单;Room 表无楼层字段,
    楼层/范围不做结构化校验。
    """

    __tablename__ = "exam_patrols"

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    exam_date: Mapped[date] = mapped_column(Date)
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), index=True
    )
    scope: Mapped[str] = mapped_column(String(256))
    note: Mapped[str | None] = mapped_column(String(256), nullable=True)


class ExamDiscipline(Base):
    """考风考纪记录(KW-29):监考教师登记的违纪/作弊事件。

    只做记录与汇总展示,不写入学生状态异动、不记入德育评价。
    """

    __tablename__ = "exam_disciplines"

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(20))  # 违纪/作弊/其他
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    handling: Mapped[str | None] = mapped_column(String(512), nullable=True)
    recorded_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
