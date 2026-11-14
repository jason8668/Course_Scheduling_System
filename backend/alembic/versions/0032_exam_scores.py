"""阅卷与成绩录入表(KW-30~35):阅卷分工、成绩设置、大题小分、成绩、补考。

Revision ID: 0032_exam_scores
Revises: 0031_exam_invigilation
"""

import sqlalchemy as sa

from alembic import op

revision = "0032_exam_scores"
down_revision = "0031_exam_invigilation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exam_marking_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(20), server_default="阅卷教师", nullable=False),
        sa.Column("scope_type", sa.String(20), server_default="按班", nullable=False),
        sa.Column("scope_value", sa.String(64), nullable=True),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "exam_id", "subject_id", "teacher_id",
            name="uq_exam_marking_assignments_exam_subject_teacher",
        ),
    )
    op.create_index(
        "ix_exam_marking_assignments_exam_id", "exam_marking_assignments", ["exam_id"]
    )
    op.create_table(
        "exam_score_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("entry_mode", sa.String(20), server_default="total_only", nullable=False),
        sa.Column("makeup_mode", sa.String(20), server_default="separate", nullable=False),
        sa.Column("cheating_score_mode", sa.String(20), server_default="zero", nullable=False),
        sa.Column("absent_counts", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("score_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("exam_id", name="uq_exam_score_settings_exam"),
    )
    op.create_index(
        "ix_exam_score_settings_exam_id", "exam_score_settings", ["exam_id"]
    )
    op.create_table(
        "exam_score_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("max_score", sa.Float(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "exam_id", "subject_id", "name",
            name="uq_exam_score_items_exam_subject_name",
        ),
    )
    op.create_index(
        "ix_exam_score_items_exam_id", "exam_score_items", ["exam_id"]
    )
    op.create_table(
        "exam_scores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("status", sa.String(20), server_default="正常", nullable=False),
        sa.Column("submitted", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("submitted_by", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["submitted_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "exam_id", "subject_id", "student_id",
            name="uq_exam_scores_exam_subject_student",
        ),
    )
    op.create_index("ix_exam_scores_exam_id", "exam_scores", ["exam_id"])
    op.create_index("ix_exam_scores_student_id", "exam_scores", ["student_id"])
    op.create_table(
        "exam_score_item_scores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("score_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["score_id"], ["exam_scores.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["item_id"], ["exam_score_items.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "score_id", "item_id",
            name="uq_exam_score_item_scores_score_item",
        ),
    )
    op.create_index(
        "ix_exam_score_item_scores_score_id", "exam_score_item_scores", ["score_id"]
    )
    op.create_table(
        "exam_makeups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("exam_date", sa.Date(), nullable=False),
        sa.Column("note", sa.String(512), nullable=True),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_exam_makeups_exam_id", "exam_makeups", ["exam_id"])
    op.create_table(
        "exam_makeup_scores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("makeup_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("status", sa.String(20), server_default="正常", nullable=False),
        sa.ForeignKeyConstraint(["makeup_id"], ["exam_makeups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "makeup_id", "student_id", "subject_id",
            name="uq_exam_makeup_scores_makeup_student_subject",
        ),
    )
    op.create_index(
        "ix_exam_makeup_scores_makeup_id", "exam_makeup_scores", ["makeup_id"]
    )


def downgrade() -> None:
    op.drop_table("exam_makeup_scores")
    op.drop_table("exam_makeups")
    op.drop_table("exam_score_item_scores")
    op.drop_table("exam_scores")
    op.drop_table("exam_score_items")
    op.drop_table("exam_score_settings")
    op.drop_table("exam_marking_assignments")
