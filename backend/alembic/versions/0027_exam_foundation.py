"""考务地基表(KW-01~07):学生、异动、家长、学科分值、考号规则。

Revision ID: 0027_exam_foundation
Revises: 0026_teacher_swaps
"""

import sqlalchemy as sa

from alembic import op

revision = "0027_exam_foundation"
down_revision = "0026_teacher_swaps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "students",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("semester_id", sa.Integer(), nullable=False),
        sa.Column("class_unit_id", sa.Integer(), nullable=False),
        sa.Column("student_no", sa.String(32), nullable=False),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("gender", sa.String(8), nullable=True),
        sa.Column("status", sa.String(20), server_default="在读", nullable=False),
        sa.Column("exam_no", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["semester_id"], ["semesters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["class_unit_id"], ["class_units.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("semester_id", "student_no", name="uq_students_semester_no"),
    )
    op.create_index("ix_students_semester_id", "students", ["semester_id"])
    op.create_index("ix_students_class_unit_id", "students", ["class_unit_id"])
    op.create_table(
        "student_status_changes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("change_type", sa.String(20), nullable=False),
        sa.Column("from_class_unit_id", sa.Integer(), nullable=True),
        sa.Column("to_class_unit_id", sa.Integer(), nullable=True),
        sa.Column("from_status", sa.String(20), nullable=True),
        sa.Column("to_status", sa.String(20), nullable=True),
        sa.Column("note", sa.String(256), nullable=True),
        sa.Column("changed_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["from_class_unit_id"], ["class_units.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["to_class_unit_id"], ["class_units.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["changed_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_student_status_changes_student_id", "student_status_changes", ["student_id"])
    op.create_table(
        "parent_contacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("relation", sa.String(20), nullable=True),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_parent_contacts_student_id", "parent_contacts", ["student_id"])
    op.create_table(
        "subject_score_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("semester_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("full_score", sa.Float(), server_default="100", nullable=False),
        sa.Column("pass_line", sa.Float(), server_default="60", nullable=False),
        sa.Column("excellent_line", sa.Float(), server_default="85", nullable=False),
        sa.Column("counts_toward_total", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("conversion_ratio", sa.Float(), server_default="1.0", nullable=False),
        sa.ForeignKeyConstraint(["semester_id"], ["semesters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "semester_id", "subject_id",
            name="uq_subject_score_settings_semester_subject",
        ),
    )
    op.create_index("ix_subject_score_settings_semester_id", "subject_score_settings", ["semester_id"])
    op.create_index("ix_subject_score_settings_subject_id", "subject_score_settings", ["subject_id"])
    op.create_table(
        "exam_number_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("semester_id", sa.Integer(), nullable=False),
        sa.Column("grade", sa.Integer(), nullable=True),
        sa.Column("rule_type", sa.String(20), server_default="by_student_no", nullable=False),
        sa.ForeignKeyConstraint(["semester_id"], ["semesters.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "semester_id", "grade", name="uq_exam_number_rules_semester_grade"
        ),
    )
    op.create_index("ix_exam_number_rules_semester_id", "exam_number_rules", ["semester_id"])


def downgrade() -> None:
    op.drop_table("exam_number_rules")
    op.drop_table("subject_score_settings")
    op.drop_table("parent_contacts")
    op.drop_table("student_status_changes")
    op.drop_table("students")
