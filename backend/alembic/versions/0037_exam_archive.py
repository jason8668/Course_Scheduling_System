"""考试归档表(KW-65):一考一档记录。

Revision ID: 0037_exam_archive
Revises: 0036_exam_notifications
"""

import sqlalchemy as sa

from alembic import op

revision = "0037_exam_archive"
down_revision = "0036_exam_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exam_archives",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("archived_by", sa.Integer(), nullable=True),
        sa.Column(
            "archived_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("manifest", sa.Text(), server_default="{}", nullable=False),
        sa.Column("note", sa.String(512), nullable=True),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["archived_by"], ["users.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("exam_id", name="uq_exam_archives_exam"),
    )
    op.create_index(
        "ix_exam_archives_exam_id", "exam_archives", ["exam_id"],
    )


def downgrade() -> None:
    op.drop_table("exam_archives")
