"""老师自主调课(不走请假,对方同意即生效,事后补登同款)。

Revision ID: 0026_teacher_swaps
Revises: 0025_duty_roster
"""

import sqlalchemy as sa

from alembic import op

revision = "0026_teacher_swaps"
down_revision = "0025_duty_roster"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "teacher_swaps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("semester_id", sa.Integer(), nullable=False),
        sa.Column("requester_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("note", sa.String(256), nullable=True),
        sa.Column("class_date", sa.Date(), nullable=False),
        sa.Column("period_no", sa.Integer(), nullable=False),
        sa.Column("class_unit_id", sa.Integer(), nullable=False),
        sa.Column("course_assignment_id", sa.Integer(), nullable=False),
        sa.Column("original_teacher_id", sa.Integer(), nullable=False),
        sa.Column("handler_teacher_id", sa.Integer(), nullable=False),
        sa.Column("makeup_date", sa.Date(), nullable=True),
        sa.Column("makeup_period_no", sa.Integer(), nullable=True),
        sa.Column("makeup_class_unit_id", sa.Integer(), nullable=True),
        sa.Column("makeup_assignment_id", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["semester_id"], ["semesters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requester_id"], ["teachers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["class_unit_id"], ["class_units.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_assignment_id"], ["course_assignments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["original_teacher_id"], ["teachers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["handler_teacher_id"], ["teachers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["makeup_class_unit_id"], ["class_units.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["makeup_assignment_id"], ["course_assignments.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_teacher_swaps_semester_id", "teacher_swaps", ["semester_id"])
    op.create_index("ix_teacher_swaps_class_date", "teacher_swaps", ["class_date"])
    op.create_table(
        "teacher_swap_reminder_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("swap_id", sa.Integer(), nullable=False),
        sa.Column("class_unit_id", sa.Integer(), nullable=False),
        sa.Column("period_no", sa.Integer(), nullable=False),
        sa.Column("class_date", sa.Date(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["swap_id"], ["teacher_swaps.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["class_unit_id"], ["class_units.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "swap_id", "class_unit_id", "period_no", "class_date", "teacher_id",
            name="uq_teacher_swap_reminder",
        ),
    )
    op.create_index("ix_teacher_swap_reminder_logs_swap_id", "teacher_swap_reminder_logs", ["swap_id"])


def downgrade() -> None:
    op.drop_table("teacher_swap_reminder_logs")
    op.drop_table("teacher_swaps")
