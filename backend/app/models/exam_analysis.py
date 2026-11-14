"""成绩分析模型(KW-41~51):分析设置、科目阈值覆盖、目标生、等第档。

分析结果实时计算,不另存结果表;本文件只存配置类数据。
等第档 subject_id 可空,空表示总分档;科目档优先于总分档。
"""

from sqlalchemy import (
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

RANK_TIE_RULES = ("dense", "competition")


class ExamAnalysisSetting(Base):
    """成绩分析设置(KW-41~45):一次考试一条,未设过用默认值。

    rank_tie_rule:dense 同分同名次(默认)/competition 同分并列占位。
    segment_size:分数段粒度,默认 10 分。
    critical_total_line:总分临界线,可空;未设时只出单科临界。
    critical_margin:总分临界浮动分值,默认 5。
    subject_critical_margin:单科临界浮动分值,默认 5。
    """

    __tablename__ = "exam_analysis_settings"
    __table_args__ = (
        UniqueConstraint("exam_id", name="uq_exam_analysis_settings_exam"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    rank_tie_rule: Mapped[str] = mapped_column(String(20), default="dense")
    segment_size: Mapped[int] = mapped_column(Integer, default=10)
    critical_total_line: Mapped[float | None] = mapped_column(Float, nullable=True)
    critical_margin: Mapped[float] = mapped_column(Float, default=5)
    subject_critical_margin: Mapped[float] = mapped_column(Float, default=5)


class ExamSubjectThreshold(Base):
    """科目阈值覆盖(KW-43):本次考试单独设的及格线/优秀线。

    为空表示不覆盖,用科目分值设置(SubjectScoreSetting)的线。
    """

    __tablename__ = "exam_subject_thresholds"
    __table_args__ = (
        UniqueConstraint(
            "exam_id", "subject_id",
            name="uq_exam_subject_thresholds_exam_subject",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    pass_line: Mapped[float | None] = mapped_column(Float, nullable=True)
    excellent_line: Mapped[float | None] = mapped_column(Float, nullable=True)


class ExamTargetStudent(Base):
    """目标生(KW-46):目标总分由学校提供,系统只做跟踪对比。"""

    __tablename__ = "exam_target_students"
    __table_args__ = (
        UniqueConstraint(
            "exam_id", "student_id",
            name="uq_exam_target_students_exam_student",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    target_total: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(String(256), nullable=True)


class ExamGradeBand(Base):
    """等第档(KW-50):按分数线把分数转换为等第。

    subject_id 可空,空表示总分档;科目档优先于总分档。
    匹配规则:按 min_score 从高到低,分数大于等于 min_score 的第一档即为
    该分数的等第,max_score 只做展示,不参与匹配。
    默认档:A≥90、B≥80、C≥70、D≥60、E<60(满分 100 时)。
    """

    __tablename__ = "exam_grade_bands"
    __table_args__ = (
        UniqueConstraint(
            "exam_id", "subject_id", "grade_label",
            name="uq_exam_grade_bands_exam_subject_label",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[int | None] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    grade_label: Mapped[str] = mapped_column(String(8))
    min_score: Mapped[float] = mapped_column(Float)
    max_score: Mapped[float] = mapped_column(Float)


#: 默认等第档(满分 100 时):(等第, 下限, 上限)。
DEFAULT_GRADE_BANDS: tuple[tuple[str, float, float], ...] = (
    ("A", 90, 100),
    ("B", 80, 90),
    ("C", 70, 80),
    ("D", 60, 70),
    ("E", 0, 60),
)
