"""监考安排表(KW-23~29):监考规则、教师池、监考安排、巡考、考风考纪记录。

Revision ID: 0031_exam_invigilation
Revises: 0030_exam_arrangement
"""

import sqlalchemy as sa

from alembic import op

revision = "0031_exam_invigilation"
down_revision = "0030_exam_arrangement"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exam_invigilation_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("avoid_own_class", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("avoid_own_subject", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("invigilators_per_room", sa.Integer(), server_default="2", nullable=False),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("exam_id", name="uq_exam_invigilation_rules_exam"),
    )
    op.create_index(
        "ix_exam_invigilation_rules_exam_id", "exam_invigilation_rules", ["exam_id"]
    )
    op.create_table(
        "exam_invigilator_pools",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("eligible", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "exam_id", "teacher_id",
            name="uq_exam_invigilator_pools_exam_teacher",
        ),
    )
    op.create_index(
        "ix_exam_invigilator_pools_exam_id", "exam_invigilator_pools", ["exam_id"]
    )
    op.create_index(
        "ix_exam_invigilator_pools_teacher_id",
        "exam_invigilator_pools", ["teacher_id"],
    )
    op.create_table(
        "exam_invigilations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("room_id", sa.Integer(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(20), server_default="监考", nullable=False),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "exam_id", "subject_id", "room_id", "teacher_id",
            name="uq_exam_invigilations_exam_subject_room_teacher",
        ),
    )
    op.create_index(
        "ix_exam_invigilations_exam_id", "exam_invigilations", ["exam_id"]
    )
    op.create_index(
        "ix_exam_invigilations_subject_id", "exam_invigilations", ["subject_id"]
    )
    op.create_index(
        "ix_exam_invigilations_room_id", "exam_invigilations", ["room_id"]
    )
    op.create_index(
        "ix_exam_invigilations_teacher_id", "exam_invigilations", ["teacher_id"]
    )
    op.create_table(
        "exam_patrols",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("exam_date", sa.Date(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(256), nullable=False),
        sa.Column("note", sa.String(256), nullable=True),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_exam_patrols_exam_id", "exam_patrols", ["exam_id"])
    op.create_index("ix_exam_patrols_teacher_id", "exam_patrols", ["teacher_id"])
    op.create_table(
        "exam_disciplines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("description", sa.String(512), nullable=True),
        sa.Column("handling", sa.String(512), nullable=True),
        sa.Column("recorded_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_exam_disciplines_exam_id", "exam_disciplines", ["exam_id"]
    )
    op.create_index(
        "ix_exam_disciplines_subject_id", "exam_disciplines", ["subject_id"]
    )
    op.create_index(
        "ix_exam_disciplines_student_id", "exam_disciplines", ["student_id"]
    )


def downgrade() -> None:
    op.drop_table("exam_disciplines")
    op.drop_table("exam_patrols")
    op.drop_table("exam_invigilations")
    op.drop_table("exam_invigilator_pools")
    op.drop_table("exam_invigilation_rules")
