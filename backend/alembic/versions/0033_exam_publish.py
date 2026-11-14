"""成绩发布与校对锁定表(KW-36~40):发布设置、双人校对、成绩锁定、改分审批、发布批次、成绩异议。

Revision ID: 0033_exam_publish
Revises: 0032_exam_scores
"""

import sqlalchemy as sa

from alembic import op

revision = "0033_exam_publish"
down_revision = "0032_exam_scores"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exam_publish_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("proofreader_role", sa.String(20), server_default="subject_leader", nullable=False),
        sa.Column("approval_levels", sa.Integer(), server_default="1", nullable=False),
        sa.Column("publish_order", sa.String(20), server_default="teachers_first", nullable=False),
        sa.Column("objection_open", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("exam_id", name="uq_exam_publish_settings_exam"),
    )
    op.create_index(
        "ix_exam_publish_settings_exam_id", "exam_publish_settings", ["exam_id"]
    )
    op.create_table(
        "exam_proofreadings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("class_unit_id", sa.Integer(), nullable=True),
        sa.Column("submitted_by", sa.Integer(), nullable=True),
        sa.Column("proofreader_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), server_default="待校对", nullable=False),
        sa.Column("note", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["class_unit_id"], ["class_units.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["submitted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["proofreader_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_exam_proofreadings_exam_id", "exam_proofreadings", ["exam_id"]
    )
    op.create_table(
        "exam_score_locks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("class_unit_id", sa.Integer(), nullable=True),
        sa.Column("locked_by", sa.Integer(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["class_unit_id"], ["class_units.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["locked_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "exam_id", "subject_id", "class_unit_id",
            name="uq_exam_score_locks_exam_subject_class",
        ),
    )
    op.create_index(
        "ix_exam_score_locks_exam_id", "exam_score_locks", ["exam_id"]
    )
    op.create_table(
        "exam_score_change_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("score_id", sa.Integer(), nullable=False),
        sa.Column("old_score", sa.Float(), nullable=True),
        sa.Column("new_score", sa.Float(), nullable=True),
        sa.Column("reason", sa.String(512), nullable=False),
        sa.Column("status", sa.String(20), server_default="待审批", nullable=False),
        sa.Column("requested_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["score_id"], ["exam_scores.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_exam_score_change_requests_exam_id",
        "exam_score_change_requests", ["exam_id"],
    )
    op.create_table(
        "exam_score_change_approvals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("approver_id", sa.Integer(), nullable=True),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("note", sa.String(512), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["request_id"], ["exam_score_change_requests.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["approver_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "request_id", "level",
            name="uq_exam_score_change_approvals_request_level",
        ),
    )
    op.create_index(
        "ix_exam_score_change_approvals_request_id",
        "exam_score_change_approvals", ["request_id"],
    )
    op.create_table(
        "exam_publish_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("scope_type", sa.String(20), nullable=False),
        sa.Column("scope_value", sa.Integer(), nullable=False),
        sa.Column("publish_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), server_default="待发布", nullable=False),
        sa.Column("published_by", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["published_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_exam_publish_batches_exam_id", "exam_publish_batches", ["exam_id"]
    )
    op.create_table(
        "exam_objections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("score_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.String(1024), nullable=False),
        sa.Column("status", sa.String(20), server_default="待复核", nullable=False),
        sa.Column("reply", sa.String(1024), nullable=True),
        sa.Column("replied_by", sa.Integer(), nullable=True),
        sa.Column("raised_by_role", sa.String(20), server_default="教师", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["score_id"], ["exam_scores.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["replied_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_exam_objections_exam_id", "exam_objections", ["exam_id"]
    )


def downgrade() -> None:
    op.drop_table("exam_objections")
    op.drop_table("exam_publish_batches")
    op.drop_table("exam_score_change_approvals")
    op.drop_table("exam_score_change_requests")
    op.drop_table("exam_score_locks")
    op.drop_table("exam_proofreadings")
    op.drop_table("exam_publish_settings")
