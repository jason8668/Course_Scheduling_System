"""成绩单与查询模型(KW-52~56):家长版成绩单显示设置、学生/家长账号关联。

家长版是否显示排名由学校定,清单备注默认不显示年级排名:
ExamReportSetting 两项默认均为 false,教务可在成绩单设置里改。
学生/家长账号本身复用 User 表(Role.student / Role.parent),
关联关系存在 ExamAccountLink(一名学生可关联多名家长,一名家长
可关联多名子女;学生本人 relation 为"本人")。
"""

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ExamReportSetting(Base):
    """家长版成绩单显示设置(KW-53):一次考试一条,未设过用默认值。

    parent_show_grade_rank:家长版是否显示年级排名,默认 false;
    parent_show_class_rank:家长版是否显示班级排名,默认 false。
    """

    __tablename__ = "exam_report_settings"
    __table_args__ = (
        UniqueConstraint("exam_id", name="uq_exam_report_settings_exam"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    parent_show_grade_rank: Mapped[bool] = mapped_column(
        Boolean, default=False
    )
    parent_show_class_rank: Mapped[bool] = mapped_column(
        Boolean, default=False
    )


class ExamAccountLink(Base):
    """学生/家长账号关联(KW-55):账号(User)与学生档案的关联。

    relation:学生本人为"本人",家长为父亲/母亲/其他(取自家长联系
    信息,空则记"其他")。同一手机号多子女只建一个家长账号,
    关联多名学生;唯一约束 (user_id, student_id) 保证幂等。
    """

    __tablename__ = "exam_account_links"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "student_id",
            name="uq_exam_account_links_user_student",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    relation: Mapped[str] = mapped_column(String(20), default="本人")
