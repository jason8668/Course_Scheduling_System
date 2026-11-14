"""考务通知表(KW-57~61):考试通知开关、通知发送记录。

Revision ID: 0036_exam_notifications
Revises: 0035_exam_reports
"""

import sqlalchemy as sa

from alembic import op

revision = "0036_exam_notifications"
down_revision = "0035_exam_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exam_notification_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column(
            "schedule_notify_enabled", sa.Boolean(),
            server_default="1", nullable=False,
        ),
        sa.Column(
            "invigilation_remind_enabled", sa.Boolean(),
            server_default="1", nullable=False,
        ),
        sa.Column(
            "score_deadline_remind_enabled", sa.Boolean(),
            server_default="1", nullable=False,
        ),
        sa.Column(
            "publish_notify_enabled", sa.Boolean(),
            server_default="1", nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "exam_id", name="uq_exam_notification_settings_exam"
        ),
    )
    op.create_index(
        "ix_exam_notification_settings_exam_id",
        "exam_notification_settings", ["exam_id"],
    )
    op.create_table(
        "exam_notification_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("notification_type", sa.String(20), nullable=False),
        sa.Column("recipient_user_id", sa.Integer(), nullable=True),
        sa.Column("recipient_name", sa.String(64), server_default="", nullable=False),
        sa.Column("channel", sa.String(10), server_default="站内", nullable=False),
        sa.Column("status", sa.String(10), server_default="待发送", nullable=False),
        sa.Column("message", sa.Text(), server_default="", nullable=False),
        sa.Column("error", sa.String(512), nullable=True),
        sa.Column("related_type", sa.String(40), nullable=True),
        sa.Column("related_id", sa.Integer(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["recipient_user_id"], ["users.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_exam_notification_logs_exam_id",
        "exam_notification_logs", ["exam_id"],
    )
    op.create_index(
        "ix_exam_notification_logs_notification_type",
        "exam_notification_logs", ["notification_type"],
    )
    op.create_index(
        "ix_exam_notification_logs_recipient_user_id",
        "exam_notification_logs", ["recipient_user_id"],
    )
    op.create_index(
        "ix_exam_notification_logs_status",
        "exam_notification_logs", ["status"],
    )


def downgrade() -> None:
    op.drop_table("exam_notification_logs")
    op.drop_table("exam_notification_settings")
