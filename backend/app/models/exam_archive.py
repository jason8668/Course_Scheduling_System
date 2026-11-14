"""考试归档模型(KW-65):一考一档,归档后只读。

一张考试最多一条归档记录(exam_id 唯一);manifest 为归档时快照的
JSON 文本:参试人数、编排人数、监考人次、成绩条数、发布批次、
各科均分与总分均分。归档本身不复制业务数据,归档包按需生成下载。
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ExamArchive(Base):
    """考试归档记录(KW-65):考试状态到“已发布成绩”后方可归档。"""

    __tablename__ = "exam_archives"
    __table_args__ = (
        UniqueConstraint("exam_id", name="uq_exam_archives_exam"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    archived_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    archived_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    manifest: Mapped[str] = mapped_column(Text, default="{}")
    note: Mapped[str | None] = mapped_column(String(512), nullable=True)
