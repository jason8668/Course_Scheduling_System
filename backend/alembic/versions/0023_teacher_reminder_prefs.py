"""教师个人上课提醒自配置(「我的」页开关与提前分钟)。

Revision ID: 0023_teacher_reminder_prefs
Revises: 0022_teacher_grades
"""

import sqlalchemy as sa

from alembic import op

revision = "0023_teacher_reminder_prefs"
down_revision = "0022_teacher_grades"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "teachers",
        sa.Column(
            "reminder_enabled", sa.Boolean(), server_default=sa.true(), nullable=False
        ),
    )
    op.add_column(
        "teachers", sa.Column("reminder_lead_minutes", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("teachers", "reminder_lead_minutes")
    op.drop_column("teachers", "reminder_enabled")
