"""考务派生角色支撑模型(KW-62):教研组长任命表。

只放 SubjectLeader 一个模型。考务角色是派生角色,不新增 Role 枚举值,
映射关系见 app/services/exam_scopes.py 的模块 docstring:

- 教研组长 = teacher 且在本表中有本科目记录(按学期任命)。
- 学生/家长在本批没有登录账号,不建学生/家长账号模型。
"""

from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class SubjectLeader(Base):
    """教研组长任命:某学期某教师负责某一科目。

    同一学期同一教师同一科目只允许一行;任一外键删除时级联删除本行。
    """

    __tablename__ = "subject_leaders"
    __table_args__ = (
        UniqueConstraint(
            "semester_id", "teacher_id", "subject_id",
            name="uq_subject_leaders_semester_teacher_subject",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
