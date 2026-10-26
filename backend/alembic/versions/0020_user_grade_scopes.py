"""批次 #17:帐号—年级对应表(user_grade_scopes)。

Revision ID: 0020_user_grade_scopes
Revises: 0019_school_calendar
"""

import sqlalchemy as sa

from alembic import op

revision = "0020_user_grade_scopes"
down_revision = "0019_school_calendar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_grade_scopes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("grade", sa.Integer(), nullable=False),
        sa.UniqueConstraint("user_id", "grade", name="uq_user_grade_scope"),
    )
    op.create_index(
        "ix_user_grade_scopes_user_id",
        "user_grade_scopes",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_grade_scopes_user_id", table_name="user_grade_scopes"
    )
    op.drop_table("user_grade_scopes")
