"""行政值日(每周轮值 + 某天覆盖 + 换班申请 + 提醒日志)。

Revision ID: 0025_duty_roster
Revises: 0024_special_days
"""

import sqlalchemy as sa

from alembic import op

revision = "0025_duty_roster"
down_revision = "0024_special_days"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "duty_patterns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("semester_id", sa.Integer(), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["semester_id"], ["semesters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("semester_id", "weekday", name="uq_duty_pattern"),
    )
    op.create_index("ix_duty_patterns_semester_id", "duty_patterns", ["semester_id"])
    op.create_table(
        "duty_overrides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("semester_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["semester_id"], ["semesters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("semester_id", "date", name="uq_duty_override"),
    )
    op.create_index("ix_duty_overrides_semester_id", "duty_overrides", ["semester_id"])
    op.create_index("ix_duty_overrides_date", "duty_overrides", ["date"])
    op.create_table(
        "duty_swap_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("semester_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("from_teacher_id", sa.Integer(), nullable=False),
        sa.Column("to_teacher_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["semester_id"], ["semesters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["from_teacher_id"], ["teachers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_teacher_id"], ["teachers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        # 注意:不在此建唯一键——同一天同一发起人被拒绝后可再发起,
        # 唯一键会挡住再发起(曾留的 latent bug,0026 之前已修掉)。
        # 同一日期待处理重复由 API 层查 pending 挡,不是数据库唯一键。
    )
    op.create_index("ix_duty_swap_requests_semester_id", "duty_swap_requests", ["semester_id"])
    op.create_index("ix_duty_swap_requests_date", "duty_swap_requests", ["date"])
    op.create_table(
        "duty_reminder_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("semester_id", sa.Integer(), nullable=False),
        sa.Column("duty_date", sa.Date(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["semester_id"], ["semesters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "semester_id", "duty_date", "teacher_id", "kind", name="uq_duty_reminder",
        ),
    )
    op.create_index("ix_duty_reminder_logs_semester_id", "duty_reminder_logs", ["semester_id"])
    op.create_index("ix_duty_reminder_logs_duty_date", "duty_reminder_logs", ["duty_date"])


def downgrade() -> None:
    op.drop_table("duty_reminder_logs")
    op.drop_table("duty_swap_requests")
    op.drop_table("duty_overrides")
    op.drop_table("duty_patterns")
