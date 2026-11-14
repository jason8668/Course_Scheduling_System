"""成绩单与查询表(KW-52~56):家长版成绩单显示设置、学生/家长账号关联。

Revision ID: 0035_exam_reports
Revises: 0034_exam_analysis
"""

import sqlalchemy as sa

from alembic import op

revision = "0035_exam_reports"
down_revision = "0034_exam_analysis"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exam_report_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column(
            "parent_show_grade_rank", sa.Boolean(),
            server_default="0", nullable=False,
        ),
        sa.Column(
            "parent_show_class_rank", sa.Boolean(),
            server_default="0", nullable=False,
        ),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("exam_id", name="uq_exam_report_settings_exam"),
    )
    op.create_index(
        "ix_exam_report_settings_exam_id", "exam_report_settings", ["exam_id"]
    )
    op.create_table(
        "exam_account_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("semester_id", sa.Integer(), nullable=False),
        sa.Column("relation", sa.String(20), server_default="本人", nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["semester_id"], ["semesters.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "user_id", "student_id",
            name="uq_exam_account_links_user_student",
        ),
    )
    op.create_index(
        "ix_exam_account_links_user_id", "exam_account_links", ["user_id"]
    )
    op.create_index(
        "ix_exam_account_links_student_id", "exam_account_links", ["student_id"]
    )
    op.create_index(
        "ix_exam_account_links_semester_id", "exam_account_links", ["semester_id"]
    )


def downgrade() -> None:
    op.drop_table("exam_account_links")
    op.drop_table("exam_report_settings")
