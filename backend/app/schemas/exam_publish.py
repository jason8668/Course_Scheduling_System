"""成绩发布与校对锁定 schema(KW-36~40)。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ── 发布设置 ──────────────────────────────
class PublishSettingsIn(BaseModel):
    proofreader_role: str = "subject_leader"
    approval_levels: int = 1
    publish_order: str = "teachers_first"
    objection_open: bool = True


class PublishSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    exam_id: int
    proofreader_role: str = "subject_leader"
    approval_levels: int = 1
    publish_order: str = "teachers_first"
    objection_open: bool = True


# ── 双人校对 ──────────────────────────────
class ProofreadingIn(BaseModel):
    subject_id: int
    class_unit_id: int | None = None
    note: str | None = None


class ProofreadingDecideIn(BaseModel):
    decision: str  # 通过/退回
    note: str | None = None


class ProofreadingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    exam_id: int
    subject_id: int
    subject_name: str = ""
    class_unit_id: int | None = None
    class_name: str | None = None
    submitted_by: int | None = None
    submitted_by_name: str = ""
    proofreader_id: int | None = None
    proofreader_name: str = ""
    status: str
    note: str | None = None


class ProofreadingListOut(BaseModel):
    items: list[ProofreadingOut]
    total: int


# ── 成绩锁定 ──────────────────────────────
class LockIn(BaseModel):
    subject_id: int
    class_unit_id: int | None = None


class LockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    exam_id: int
    subject_id: int
    subject_name: str = ""
    class_unit_id: int | None = None
    class_name: str | None = None
    locked_by: int | None = None
    locked_by_name: str = ""
    locked_at: datetime | None = None


class LockListOut(BaseModel):
    items: list[LockOut]
    total: int


# ── 改分审批 ──────────────────────────────
class ChangeRequestIn(BaseModel):
    score_id: int
    new_score: float | None = None
    reason: str = Field(min_length=1, max_length=512)


class ChangeRequestDecideIn(BaseModel):
    decision: str  # 通过/驳回
    note: str | None = None


class ChangeApprovalOut(BaseModel):
    level: int
    approver_name: str = ""
    decision: str
    note: str | None = None


class ChangeRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    exam_id: int
    score_id: int
    student_name: str = ""
    subject_name: str = ""
    old_score: float | None = None
    new_score: float | None = None
    reason: str
    status: str
    requested_by: int | None = None
    requested_by_name: str = ""
    approvals: list[ChangeApprovalOut] = []


class ChangeRequestListOut(BaseModel):
    items: list[ChangeRequestOut]
    total: int


# ── 发布批次 ──────────────────────────────
class PublishBatchIn(BaseModel):
    scope_type: str  # 年级/班级
    scope_value: int
    publish_at: datetime | None = None
    note: str | None = None


class PublishBatchWithdrawIn(BaseModel):
    note: str | None = None


class PublishBatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    exam_id: int
    scope_type: str
    scope_value: int
    publish_at: datetime | None = None
    status: str
    published_by: int | None = None
    published_by_name: str = ""
    note: str | None = None


class PublishBatchListOut(BaseModel):
    items: list[PublishBatchOut]
    total: int


class PublishDueOut(BaseModel):
    published: int


class PublishStatusBatchOut(BaseModel):
    scope_type: str
    scope_value: int
    status: str
    publish_at: datetime | None = None


class PublishStatusOut(BaseModel):
    exam_id: int
    batches: list[PublishStatusBatchOut]
    all_published: bool


# ── 成绩异议 ──────────────────────────────
class ObjectionIn(BaseModel):
    score_id: int
    content: str = Field(min_length=1, max_length=1024)


class ObjectionReplyIn(BaseModel):
    reply: str = Field(min_length=1, max_length=1024)


class ObjectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    exam_id: int
    score_id: int
    student_id: int
    student_name: str = ""
    subject_name: str = ""
    content: str
    status: str
    reply: str | None = None
    replied_by: int | None = None
    replied_by_name: str = ""
    raised_by_role: str = ""


class ObjectionListOut(BaseModel):
    items: list[ObjectionOut]
    total: int
