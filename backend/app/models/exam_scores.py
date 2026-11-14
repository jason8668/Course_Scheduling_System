"""阅卷与成绩录入模型(KW-30~35):阅卷分工、成绩设置、大题小分、成绩、补考。

成绩状态 status 四种:正常/缺考/作弊/免考,专门标记而非简单填 0。
缺考与免考 score 为空;作弊按成绩设置 cheating_score_mode 记 0 分或空。
补考成绩与正考成绩并列保存,处理口径 makeup_mode 只存配置:
separate 单独标注并列保存;override 覆盖、max 取高暂不改变正考分,
等学校定了口径再实现对应逻辑。
网上阅卷、扫描识别明确不做。
"""

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

MARKING_ROLES = ("阅卷组长", "阅卷教师")
MARKING_SCOPE_TYPES = ("按题", "按班")
SCORE_STATUSES = ("正常", "缺考", "作弊", "免考")
MAKEUP_SCORE_STATUSES = ("正常", "缺考", "免考")
ENTRY_MODES = ("total_only", "itemized")
MAKEUP_MODES = ("separate", "override", "max")
CHEATING_SCORE_MODES = ("zero", "null")


class ExamMarkingAssignment(Base):
    """阅卷分工登记(KW-30):按科目登记阅卷组长和阅卷教师分工。

    scope_type 按题/按班;scope_value 存题号(如"第 1 大题")或班级名(如"701"),
    由登记人填写,不做外键校验。只做分工登记与进度跟踪。
    """

    __tablename__ = "exam_marking_assignments"
    __table_args__ = (
        UniqueConstraint(
            "exam_id", "subject_id", "teacher_id",
            name="uq_exam_marking_assignments_exam_subject_teacher",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20), default="阅卷教师")  # 阅卷组长/阅卷教师
    scope_type: Mapped[str] = mapped_column(String(20), default="按班")  # 按题/按班
    scope_value: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ExamScoreSetting(Base):
    """成绩设置(KW-31/33/35):一次考试一条,未设过用默认值。

    entry_mode:total_only 只录总分 / itemized 录大题小分,总分自动等于小分之和。
    makeup_mode:separate 单独标注并列保存 / override 覆盖 / max 取高;
      override 与 max 只存配置,暂不改变正考分。
    cheating_score_mode:zero 作弊记 0 分 / null 作弊成绩为空。
    absent_counts:缺考是否计入平均分与及格率,默认 false 不计入;
      免考永不计入统计(不由本字段控制)。
    score_deadline:录分截止时间,可空;第 9 批录分截止提醒(KW-59)会读它。
    """

    __tablename__ = "exam_score_settings"
    __table_args__ = (
        UniqueConstraint("exam_id", name="uq_exam_score_settings_exam"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    entry_mode: Mapped[str] = mapped_column(String(20), default="total_only")
    makeup_mode: Mapped[str] = mapped_column(String(20), default="separate")
    cheating_score_mode: Mapped[str] = mapped_column(String(20), default="zero")
    absent_counts: Mapped[bool] = mapped_column(Boolean, default=False)
    score_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ExamScoreItem(Base):
    """大题小分设置(KW-31):itemized 模式下每科的大题清单与每题满分。"""

    __tablename__ = "exam_score_items"
    __table_args__ = (
        UniqueConstraint(
            "exam_id", "subject_id", "name",
            name="uq_exam_score_items_exam_subject_name",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))  # 如"第一大题"
    max_score: Mapped[float] = mapped_column(Float)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ExamScore(Base):
    """成绩(KW-31/33):一名学生一科一行。

    score 可空:缺考与免考为空;作弊按 cheating_score_mode 记 0 或空。
    submitted 为真表示已提交(第 6 批锁定前,提交后仍可由录入接口改分;
    锁定与改分审批是 KW-37/38,不在本批)。
    """

    __tablename__ = "exam_scores"
    __table_args__ = (
        UniqueConstraint(
            "exam_id", "subject_id", "student_id",
            name="uq_exam_scores_exam_subject_student",
        ),
    )

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
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="正常")  # 正常/缺考/作弊/免考
    submitted: Mapped[bool] = mapped_column(Boolean, default=False)
    submitted_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ExamScoreItemScore(Base):
    """大题小分成绩(KW-31):itemized 模式下每题的得分,总分等于小分之和。"""

    __tablename__ = "exam_score_item_scores"
    __table_args__ = (
        UniqueConstraint(
            "score_id", "item_id",
            name="uq_exam_score_item_scores_score_item",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    score_id: Mapped[int] = mapped_column(
        ForeignKey("exam_scores.id", ondelete="CASCADE"), index=True
    )
    item_id: Mapped[int] = mapped_column(
        ForeignKey("exam_score_items.id", ondelete="CASCADE"), index=True
    )
    value: Mapped[float] = mapped_column(Float)


class ExamMakeup(Base):
    """补考场次(KW-35):为补考单独建场次,成绩与正考并列保存。"""

    __tablename__ = "exam_makeups"

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))  # 如"数学补考"
    exam_date: Mapped[date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String(512), nullable=True)


class ExamMakeupScore(Base):
    """补考成绩(KW-35):一补考场次、一学生、一科一行。

    status 只有正常/缺考/免考三种,补考不设作弊标记(作弊按正考处理)。
    """

    __tablename__ = "exam_makeup_scores"
    __table_args__ = (
        UniqueConstraint(
            "makeup_id", "student_id", "subject_id",
            name="uq_exam_makeup_scores_makeup_student_subject",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    makeup_id: Mapped[int] = mapped_column(
        ForeignKey("exam_makeups.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="正常")  # 正常/缺考/免考
