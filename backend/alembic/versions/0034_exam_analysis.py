"""成绩分析表(KW-41~51):分析设置、科目阈值覆盖、目标生、等第档。

Revision ID: 0034_exam_analysis
Revises: 0033_exam_publish
"""

import sqlalchemy as sa

from alembic import op

revision = "0034_exam_analysis"
down_revision = "0033_exam_publish"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exam_analysis_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("rank_tie_rule", sa.String(20), server_default="dense", nullable=False),
        sa.Column("segment_size", sa.Integer(), server_default="10", nullable=False),
        sa.Column("critical_total_line", sa.Float(), nullable=True),
        sa.Column("critical_margin", sa.Float(), server_default="5", nullable=False),
        sa.Column("subject_critical_margin", sa.Float(), server_default="5", nullable=False),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("exam_id", name="uq_exam_analysis_settings_exam"),
    )
    op.create_index(
        "ix_exam_analysis_settings_exam_id", "exam_analysis_settings", ["exam_id"]
    )
    op.create_table(
        "exam_subject_thresholds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("pass_line", sa.Float(), nullable=True),
        sa.Column("excellent_line", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "exam_id", "subject_id",
            name="uq_exam_subject_thresholds_exam_subject",
        ),
    )
    op.create_index(
        "ix_exam_subject_thresholds_exam_id", "exam_subject_thresholds", ["exam_id"]
    )
    op.create_table(
        "exam_target_students",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("target_total", sa.Float(), nullable=True),
        sa.Column("note", sa.String(256), nullable=True),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "exam_id", "student_id",
            name="uq_exam_target_students_exam_student",
        ),
    )
    op.create_index(
        "ix_exam_target_students_exam_id", "exam_target_students", ["exam_id"]
    )
    op.create_table(
        "exam_grade_bands",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=True),
        sa.Column("grade_label", sa.String(8), nullable=False),
        sa.Column("min_score", sa.Float(), nullable=False),
        sa.Column("max_score", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "exam_id", "subject_id", "grade_label",
            name="uq_exam_grade_bands_exam_subject_label",
        ),
    )
    op.create_index(
        "ix_exam_grade_bands_exam_id", "exam_grade_bands", ["exam_id"]
    )


def downgrade() -> None:
    op.drop_table("exam_grade_bands")
    op.drop_table("exam_target_students")
    op.drop_table("exam_subject_thresholds")
    op.drop_table("exam_analysis_settings")
