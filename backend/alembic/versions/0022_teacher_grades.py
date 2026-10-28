"""教师所属年级(档案多选)。

Revision ID: 0022_teacher_grades
Revises: 0021_dingtalk_app
"""

import sqlalchemy as sa

from alembic import op

revision = "0022_teacher_grades"
down_revision = "0021_dingtalk_app"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "teacher_grades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "teacher_id",
            sa.Integer(),
            sa.ForeignKey("teachers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("grade", sa.Integer(), nullable=False),
        sa.UniqueConstraint("teacher_id", "grade", name="uq_teacher_grades"),
    )
    op.create_index("ix_teacher_grades_teacher_id", "teacher_grades", ["teacher_id"])


def downgrade() -> None:
    op.drop_index("ix_teacher_grades_teacher_id", table_name="teacher_grades")
    op.drop_table("teacher_grades")
