"""考试管理表(KW-08~14):考试、参试年级、考试科目、参试名单、状态流转、命题信息、特殊考生安排。

Revision ID: 0029_exam_management
Revises: 0028_exam_scopes
"""

import sqlalchemy as sa

from alembic import op

revision = "0029_exam_management"
down_revision = "0028_exam_scopes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exams",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("semester_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("exam_type", sa.String(20), nullable=False),
        sa.Column("description", sa.String(512), nullable=True),
        sa.Column("status", sa.String(20), server_default="草稿", nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["semester_id"], ["semesters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_exams_semester_id", "exams", ["semester_id"])
    op.create_table(
        "exam_grades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("grade", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("exam_id", "grade", name="uq_exam_grades_exam_grade"),
    )
    op.create_index("ix_exam_grades_exam_id", "exam_grades", ["exam_id"])
    op.create_table(
        "exam_subjects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("exam_date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("full_score", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("exam_id", "subject_id", name="uq_exam_subjects_exam_subject"),
    )
    op.create_index("ix_exam_subjects_exam_id", "exam_subjects", ["exam_id"])
    op.create_index("ix_exam_subjects_subject_id", "exam_subjects", ["subject_id"])
    op.create_table(
        "exam_participants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("class_unit_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), server_default="正常", nullable=False),
        sa.Column("note", sa.String(256), nullable=True),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["class_unit_id"], ["class_units.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("exam_id", "student_id", name="uq_exam_participants_exam_student"),
    )
    op.create_index("ix_exam_participants_exam_id", "exam_participants", ["exam_id"])
    op.create_index("ix_exam_participants_student_id", "exam_participants", ["student_id"])
    op.create_index("ix_exam_participants_class_unit_id", "exam_participants", ["class_unit_id"])
    op.create_table(
        "exam_status_changes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("from_status", sa.String(20), nullable=True),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("changed_by", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["changed_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_exam_status_changes_exam_id", "exam_status_changes", ["exam_id"])
    op.create_table(
        "exam_paper_infos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("setter_teacher_id", sa.Integer(), nullable=True),
        sa.Column("reviewer_teacher_id", sa.Integer(), nullable=True),
        sa.Column("paper_count", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["setter_teacher_id"], ["teachers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewer_teacher_id"], ["teachers.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("exam_id", "subject_id", name="uq_exam_paper_infos_exam_subject"),
    )
    op.create_index("ix_exam_paper_infos_exam_id", "exam_paper_infos", ["exam_id"])
    op.create_index("ix_exam_paper_infos_subject_id", "exam_paper_infos", ["subject_id"])
    op.create_table(
        "exam_special_arrangements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("arrangement_type", sa.String(20), nullable=False),
        sa.Column("detail", sa.String(512), nullable=True),
        sa.Column("status", sa.String(20), server_default="已登记", nullable=False),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_exam_special_arrangements_exam_id", "exam_special_arrangements", ["exam_id"])
    op.create_index("ix_exam_special_arrangements_student_id", "exam_special_arrangements", ["student_id"])


def downgrade() -> None:
    op.drop_table("exam_special_arrangements")
    op.drop_table("exam_paper_infos")
    op.drop_table("exam_status_changes")
    op.drop_table("exam_participants")
    op.drop_table("exam_subjects")
    op.drop_table("exam_grades")
    op.drop_table("exams")
