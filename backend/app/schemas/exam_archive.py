"""考试归档与历史对比、备份导出 schema(KW-65~67)。"""

from datetime import datetime

from pydantic import BaseModel, Field


class ArchiveIn(BaseModel):
    """归档请求:备注可选。"""

    note: str | None = Field(default=None, max_length=512)


class ArchiveOut(BaseModel):
    """归档记录:manifest 为快照字典。"""

    archive_id: int
    exam_id: int
    archived_by: int | None
    archived_at: datetime | None
    manifest: dict
    note: str | None = None


class ArchiveItemOut(BaseModel):
    """历史档案列表项:未归档的考试 archived_at/archived_by 为空。"""

    exam_id: int
    exam_name: str
    exam_type: str
    semester_id: int
    status: str
    archived_at: datetime | None = None
    archived_by: int | None = None


class ArchiveListOut(BaseModel):
    items: list[ArchiveItemOut]
    total: int


class CompareExamOut(BaseModel):
    id: int
    name: str


class CompareSubjectOut(BaseModel):
    subject_id: int
    subject_name: str
    avg_a: float | None = None
    avg_b: float | None = None
    delta_avg: float | None = None
    pass_rate_a: float | None = None
    pass_rate_b: float | None = None
    delta_pass_rate: float | None = None
    excellent_rate_a: float | None = None
    excellent_rate_b: float | None = None
    delta_excellent_rate: float | None = None


class CompareOut(BaseModel):
    exam_a: CompareExamOut
    exam_b: CompareExamOut
    subjects: list[CompareSubjectOut]
    total_avg_a: float | None = None
    total_avg_b: float | None = None
    delta_total_avg: float | None = None
    message: str | None = None
