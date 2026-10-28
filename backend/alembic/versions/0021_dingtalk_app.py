"""批次 #19:钉钉企业内部应用个人上课提醒。

Revision ID: 0021_dingtalk_app
Revises: 0020_user_grade_scopes
"""

import sqlalchemy as sa

from alembic import op

revision = "0021_dingtalk_app"
down_revision = "0020_user_grade_scopes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "teachers",
        sa.Column("dingtalk_userid", sa.String(64), nullable=True),
    )
    op.create_table(
        "class_reminder_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "entry_id",
            sa.Integer(),
            sa.ForeignKey("schedule_entries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("class_date", sa.Date(), nullable=False),
        sa.Column(
            "teacher_id",
            sa.Integer(),
            sa.ForeignKey("teachers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "sent_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("entry_id", "class_date", "teacher_id", name="uq_class_reminder"),
    )
    op.create_index("ix_class_reminder_logs_entry_id", "class_reminder_logs", ["entry_id"])
    op.create_index("ix_class_reminder_logs_class_date", "class_reminder_logs", ["class_date"])
    op.create_index("ix_class_reminder_logs_teacher_id", "class_reminder_logs", ["teacher_id"])


def downgrade() -> None:
    op.drop_index("ix_class_reminder_logs_teacher_id", table_name="class_reminder_logs")
    op.drop_index("ix_class_reminder_logs_class_date", table_name="class_reminder_logs")
    op.drop_index("ix_class_reminder_logs_entry_id", table_name="class_reminder_logs")
    op.drop_table("class_reminder_logs")
    op.drop_column("teachers", "dingtalk_userid")
