"""考试管理模型(KW-08~14):考试、参试年级、考试科目、参试名单、状态流转、命题信息、特殊考生安排。

考试状态流转:草稿→已发布→进行中→成绩处理中→已发布成绩→已归档,只允许按顺序前进;
回退只允许 admin/director 且记审计(见 app/services/exam.py)。
参试名单按参试年级从在读学生生成,生成时快照班级;唯一约束 (exam_id, student_id) 保证幂等。
"""

from datetime import date, datetime, time

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

EXAM_TYPES = ("周测", "月考", "期中", "期末", "模拟考", "联考")
EXAM_STATUSES = ("草稿", "已发布", "进行中", "成绩处理中", "已发布成绩", "已归档")
# 状态顺序表:索引即流转顺序,前进只允许走到下一位。
EXAM_STATUS_ORDER = list(EXAM_STATUSES)
PARTICIPANT_STATUSES = ("正常", "缺考", "免考")
ARRANGEMENT_TYPES = ("单独考场", "延长时限", "放大字号试卷", "其他")
ARRANGEMENT_STATUSES = ("已登记", "已安排")


class Exam(Base):
    """考试(KW-08):新建后状态为草稿,草稿可反复改。"""

    __tablename__ = "exams"

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    exam_type: Mapped[str] = mapped_column(String(20))  # 周测/月考/期中/期末/模拟考/联考
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="草稿")
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ExamGrade(Base):
    """参试年级(KW-08):多选,一年级一行。"""

    __tablename__ = "exam_grades"
    __table_args__ = (
        UniqueConstraint("exam_id", "grade", name="uq_exam_grades_exam_grade"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    grade: Mapped[int] = mapped_column(Integer)


class ExamSubject(Base):
    """考试科目与日程(KW-09):每科设考试日期与起止时间,时长由起止算出。

    full_score 可空,空 = 用科目分值设置(SubjectScoreSetting)。
    """

    __tablename__ = "exam_subjects"
    __table_args__ = (
        UniqueConstraint("exam_id", "subject_id", name="uq_exam_subjects_exam_subject"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    exam_date: Mapped[date] = mapped_column(Date)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    full_score: Mapped[float | None] = mapped_column(Float, nullable=True)


class ExamParticipant(Base):
    """参试名单(KW-10):按参试年级从在读学生生成,可个别增删,支持预标记缺考/免考。

    class_unit_id 为生成时快照的班级;学生转班后历史考试名单不被改写。
    """

    __tablename__ = "exam_participants"
    __table_args__ = (
        UniqueConstraint("exam_id", "student_id", name="uq_exam_participants_exam_student"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    class_unit_id: Mapped[int] = mapped_column(
        ForeignKey("class_units.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="正常")  # 正常/缺考/免考
    note: Mapped[str | None] = mapped_column(String(256), nullable=True)


class ExamStatusChange(Base):
    """考试状态变更记录(KW-11):每次流转写一条,回退也留痕。"""

    __tablename__ = "exam_status_changes"

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20))
    changed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExamPaperInfo(Base):
    """命题与试卷信息登记(KW-13):按科目登记命题教师、审题教师、试卷份数。

    只登记信息,不做题库组卷。
    """

    __tablename__ = "exam_paper_infos"
    __table_args__ = (
        UniqueConstraint("exam_id", "subject_id", name="uq_exam_paper_infos_exam_subject"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    setter_teacher_id: Mapped[int | None] = mapped_column(
        ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True
    )
    reviewer_teacher_id: Mapped[int | None] = mapped_column(
        ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True
    )
    paper_count: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ExamSpecialArrangement(Base):
    """特殊考生安排(KW-14):单独考场、延长时限、放大字号试卷、其他。

    涉及学生隐私,读接口按可见范围过滤(仅教务与相关监考可见);
    编排时第 3 批会读这张表预留。
    """

    __tablename__ = "exam_special_arrangements"

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    arrangement_type: Mapped[str] = mapped_column(String(20))  # 单独考场/延长时限/放大字号试卷/其他
    detail: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="已登记")  # 已登记/已安排
