"""考务教研组长任命表(KW-62)。

Revision ID: 0028_exam_scopes
Revises: 0027_exam_foundation
"""

import sqlalchemy as sa

from alembic import op

revision = "0028_exam_scopes"
down_revision = "0027_exam_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subject_leaders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("semester_id", sa.Integer(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["semester_id"], ["semesters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "semester_id", "teacher_id", "subject_id",
            name="uq_subject_leaders_semester_teacher_subject",
        ),
    )
    op.create_index("ix_subject_leaders_semester_id", "subject_leaders", ["semester_id"])
    op.create_index("ix_subject_leaders_teacher_id", "subject_leaders", ["teacher_id"])
    op.create_index("ix_subject_leaders_subject_id", "subject_leaders", ["subject_id"])


def downgrade() -> None:
    op.drop_table("subject_leaders")
