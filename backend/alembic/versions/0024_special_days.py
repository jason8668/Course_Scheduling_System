"""特殊日课表(规则 + 条目 + 特殊日提醒日志)。

Revision ID: 0024_special_days
Revises: 0023_teacher_reminder_prefs
"""

import sqlalchemy as sa

from alembic import op

revision = "0024_special_days"
down_revision = "0023_teacher_reminder_prefs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "special_day_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("semester_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("scope_type", sa.String(20), nullable=False),
        sa.Column("scope_id", sa.Integer(), nullable=True),
        sa.Column("recurrence", sa.String(20), nullable=False),
        sa.Column("single_date", sa.Date(), nullable=True),
        sa.Column("weekday", sa.Integer(), nullable=True),
        sa.Column("day_of_month", sa.Integer(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["semester_id"], ["semesters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_special_day_rules_semester_id", "special_day_rules", ["semester_id"])
    op.create_table(
        "special_day_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("class_unit_id", sa.Integer(), nullable=False),
        sa.Column("period_no", sa.Integer(), nullable=False),
        sa.Column("course_assignment_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["rule_id"], ["special_day_rules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["class_unit_id"], ["class_units.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_assignment_id"], ["course_assignments.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("rule_id", "class_unit_id", "period_no", name="uq_special_day_entry"),
    )
    op.create_index("ix_special_day_entries_rule_id", "special_day_entries", ["rule_id"])
    op.create_index("ix_special_day_entries_class_unit_id", "special_day_entries", ["class_unit_id"])
    op.create_table(
        "special_day_reminder_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("class_unit_id", sa.Integer(), nullable=False),
        sa.Column("period_no", sa.Integer(), nullable=False),
        sa.Column("class_date", sa.Date(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["rule_id"], ["special_day_rules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["class_unit_id"], ["class_units.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "rule_id", "class_unit_id", "period_no", "class_date", "teacher_id",
            name="uq_special_day_reminder",
        ),
    )
    op.create_index("ix_special_day_reminder_logs_rule_id", "special_day_reminder_logs", ["rule_id"])
    op.create_index("ix_special_day_reminder_logs_class_date", "special_day_reminder_logs", ["class_date"])


def downgrade() -> None:
    op.drop_table("special_day_reminder_logs")
    op.drop_table("special_day_entries")
    op.drop_table("special_day_rules")
