"""批次 #4:校历活动表(school_calendar_events)。

Revision ID: 0019_school_calendar
Revises: 0018_alternate_weeks
"""

import sqlalchemy as sa

from alembic import op

revision = "0019_school_calendar"
down_revision = "0018_alternate_weeks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "school_calendar_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "semester_id", sa.Integer(),
            sa.ForeignKey("semesters.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False),
        sa.Column("scope_id", sa.Integer(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("period_start", sa.Integer(), nullable=True),
        sa.Column("period_end", sa.Integer(), nullable=True),
        sa.Column("weekly_recurring", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column(
            "created_by", sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index(
        "ix_school_calendar_events_semester_id",
        "school_calendar_events",
        ["semester_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_school_calendar_events_semester_id", table_name="school_calendar_events"
    )
    op.drop_table("school_calendar_events")
