"""考场编排表(KW-15~22):考场设置、编排规则、编排结果、编排锁定。

Revision ID: 0030_exam_arrangement
Revises: 0029_exam_management
"""

import sqlalchemy as sa

from alembic import op

revision = "0030_exam_arrangement"
down_revision = "0029_exam_management"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exam_rooms",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("room_id", sa.Integer(), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=True),
        sa.Column("room_type", sa.String(20), server_default="普通", nullable=False),
        sa.Column("is_special", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("exam_id", "room_id", name="uq_exam_rooms_exam_room"),
    )
    op.create_index("ix_exam_rooms_exam_id", "exam_rooms", ["exam_id"])
    op.create_index("ix_exam_rooms_room_id", "exam_rooms", ["room_id"])
    op.create_table(
        "exam_arrangement_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(20), server_default="whole_class", nullable=False),
        sa.Column("scatter_same_class", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("max_per_room", sa.Integer(), server_default="30", nullable=False),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("exam_id", name="uq_exam_arrangement_rules_exam"),
    )
    op.create_index(
        "ix_exam_arrangement_rules_exam_id", "exam_arrangement_rules", ["exam_id"]
    )
    op.create_table(
        "exam_room_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("room_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("seat_no", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "exam_id", "subject_id", "student_id",
            name="uq_exam_room_assignments_exam_subject_student",
        ),
        sa.UniqueConstraint(
            "exam_id", "subject_id", "room_id", "seat_no",
            name="uq_exam_room_assignments_exam_subject_room_seat",
        ),
    )
    op.create_index(
        "ix_exam_room_assignments_exam_id", "exam_room_assignments", ["exam_id"]
    )
    op.create_index(
        "ix_exam_room_assignments_subject_id",
        "exam_room_assignments", ["subject_id"],
    )
    op.create_index(
        "ix_exam_room_assignments_room_id", "exam_room_assignments", ["room_id"]
    )
    op.create_index(
        "ix_exam_room_assignments_student_id",
        "exam_room_assignments", ["student_id"],
    )
    op.create_table(
        "exam_arrangement_locks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("locked_by", sa.Integer(), nullable=True),
        sa.Column(
            "locked_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("note", sa.String(256), nullable=True),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["locked_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("exam_id", name="uq_exam_arrangement_locks_exam"),
    )
    op.create_index(
        "ix_exam_arrangement_locks_exam_id", "exam_arrangement_locks", ["exam_id"]
    )


def downgrade() -> None:
    op.drop_table("exam_arrangement_locks")
    op.drop_table("exam_room_assignments")
    op.drop_table("exam_arrangement_rules")
    op.drop_table("exam_rooms")
