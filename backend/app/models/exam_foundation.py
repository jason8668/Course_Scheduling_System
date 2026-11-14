"""考务地基模型(KW-01~07):学生档案、异动记录、家长联系、学科分值、考号规则。

学生直接复用现有班级数据(ClassUnit),不另建班级主数据。
所有表都按 semester_id 快照,与基础资料同一口径。
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

STUDENT_STATUSES = ("在读", "休学", "毕业")
STUDENT_GENDERS = ("男", "女")
CHANGE_TYPES = ("转班", "休学", "复学", "毕业", "入学")
RULE_TYPES = ("by_student_no", "sequential", "s_shape")


class Student(Base):
    """学生档案(KW-01)。

    唯一标识默认用学号:同一学期内 (semester_id, student_no) 唯一。
    身份证号口径学校未定,不做身份证号唯一键。
    """

    __tablename__ = "students"
    __table_args__ = (
        UniqueConstraint("semester_id", "student_no", name="uq_students_semester_no"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    class_unit_id: Mapped[int] = mapped_column(
        ForeignKey("class_units.id", ondelete="CASCADE"), index=True
    )
    student_no: Mapped[str] = mapped_column(String(32))  # 学号,必填
    name: Mapped[str] = mapped_column(String(32))
    gender: Mapped[str | None] = mapped_column(String(8), nullable=True)  # 男/女,可空
    status: Mapped[str] = mapped_column(String(20), default="在读")  # 在读/休学/毕业
    exam_no: Mapped[str | None] = mapped_column(String(32), nullable=True)  # 考号,可空

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    parents: Mapped[list["ParentContact"]] = relationship(
        back_populates="student", cascade="all, delete-orphan", lazy="selectin"
    )
    status_changes: Mapped[list["StudentStatusChange"]] = relationship(
        back_populates="student", cascade="all, delete-orphan", lazy="selectin"
    )


class StudentStatusChange(Base):
    """学生状态与异动记录(KW-04)。

    转班 = 改 Student.class_unit_id + 写一条转班记录;历史考试成绩归原班
    由后续批次在成绩行上存班级快照实现,本批只保证异动记录本身完整。
    异动默认教务直接维护,不走审批(学校未定是否审批,见汇报)。
    """

    __tablename__ = "student_status_changes"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    change_type: Mapped[str] = mapped_column(String(20))  # 转班/休学/复学/毕业/入学
    from_class_unit_id: Mapped[int | None] = mapped_column(
        ForeignKey("class_units.id", ondelete="SET NULL"), nullable=True
    )
    to_class_unit_id: Mapped[int | None] = mapped_column(
        ForeignKey("class_units.id", ondelete="SET NULL"), nullable=True
    )
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    note: Mapped[str | None] = mapped_column(String(256), nullable=True)
    changed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    student: Mapped["Student"] = relationship(back_populates="status_changes")


class ParentContact(Base):
    """家长联系信息(KW-05):一名学生可多位家长。"""

    __tablename__ = "parent_contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(32))
    relation: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 如 父亲/母亲
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)

    student: Mapped["Student"] = relationship(back_populates="parents")


class SubjectScoreSetting(Base):
    """学科分值设置(KW-06)。

    默认值只是初始值(满分 100、及格 60、优秀 85、计入总分、折算 1.0),
    学校可在页面上改。总分构成口径(哪些科目计入总分、是否含体育/实验)
    学校还没定,做成可配置项(counts_toward_total / conversion_ratio),
    不写死。
    """

    __tablename__ = "subject_score_settings"
    __table_args__ = (
        UniqueConstraint(
            "semester_id", "subject_id", name="uq_subject_score_settings_semester_subject"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    full_score: Mapped[float] = mapped_column(Float, default=100)
    pass_line: Mapped[float] = mapped_column(Float, default=60)
    excellent_line: Mapped[float] = mapped_column(Float, default=85)
    counts_toward_total: Mapped[bool] = mapped_column(Boolean, default=True)
    conversion_ratio: Mapped[float] = mapped_column(Float, default=1.0)


class ExamNumberRule(Base):
    """考号编排规则(KW-07):按 (semester_id, grade) 存规则。

    grade 为空表示全校通用规则。rule_type 三种:
    by_student_no(按学号直接使用)、sequential(按年级流水编排)、
    s_shape(按上次成绩 S 型编排)。
    """

    __tablename__ = "exam_number_rules"
    __table_args__ = (
        UniqueConstraint("semester_id", "grade", name="uq_exam_number_rules_semester_grade"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    grade: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 空 = 全校通用
    rule_type: Mapped[str] = mapped_column(String(20), default="by_student_no")
