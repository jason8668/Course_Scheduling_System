"""去掉家长/学生账号:删 parent_contacts、exam_account_links、
exam_report_settings 三表;删 exam_notification_settings.publish_notify_enabled、
exam_publish_settings.publish_order 两列;清 user_roles 里 parent/student 行与
因此无角色残留的 users 行。

数据处理(系统尚在内部测试,预期无真实家长/学生账号):
- parent_contacts 里的家长电话随表删除,不可恢复;
- exam_account_links 与 exam_report_settings 随表删除,不可恢复;
- user_roles 里 role=parent/student 的行删除;删后若某 users 行
  不剩任何角色,该 users 行一并删除(即纯学生/家长账号);
  同时有 admin/director/teacher 角色的账号不受影响。
降级(downgrade)只重建表结构与列,已删的数据无法恢复。

Revision ID: 0038_remove_family
Revises: 0037_exam_archive
"""

import sqlalchemy as sa

from alembic import op

revision = "0038_remove_family"
down_revision = "0037_exam_archive"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("parent_contacts")
    op.drop_table("exam_account_links")
    op.drop_table("exam_report_settings")
    op.drop_column("exam_notification_settings", "publish_notify_enabled")
    op.drop_column("exam_publish_settings", "publish_order")
    op.execute(sa.text("DELETE FROM user_roles WHERE role IN ('parent', 'student')"))
    op.execute(
        sa.text(
            "DELETE FROM users WHERE id NOT IN (SELECT user_id FROM user_roles)"
        )
    )


def downgrade() -> None:
    op.create_table(
        "parent_contacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("relation", sa.String(20), nullable=True),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_parent_contacts_student_id", "parent_contacts", ["student_id"]
    )
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
    op.add_column(
        "exam_notification_settings",
        sa.Column(
            "publish_notify_enabled", sa.Boolean(),
            server_default="1", nullable=False,
        ),
    )
    op.add_column(
        "exam_publish_settings",
        sa.Column(
            "publish_order", sa.String(20),
            server_default="teachers_first", nullable=False,
        ),
    )
