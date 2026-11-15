"""第 5 批 schemas:处置报废(M8 #54~#58)与同步执行/财务衔接(M13/M15)。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ── 处置单 #54 ──
class DisposalCreate(BaseModel):
    asset_id: int
    disposal_type: str = Field(min_length=1, max_length=32)
    reason: str = ""
    materials: list[str] = []


class DisposalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    doc_no: str
    asset_id: int
    disposal_type: str
    reason: str = ""
    materials: list[str] = []
    materials_required: list[str] = []
    status_before: str | None = None
    status: str
    approval_instance_id: int | None = None
    selected_for_official: bool = False
    official_reply_no: str | None = None
    official_reply_at: datetime | None = None
    created_at: datetime | None = None


class AppraisalCreate(BaseModel):
    conclusion: str
    detail: str = ""


class AppraisalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    doc_no: str
    disposal_id: int
    inspector_id: int | None = None
    inspector_name: str = ""
    conclusion: str
    detail: str = ""
    appraised_at: datetime | None = None


class OfficialReplyIn(BaseModel):
    reply_no: str = Field(min_length=1, max_length=64)


class RecoveryIn(BaseModel):
    recovery_org: str = Field(min_length=1, max_length=128)
    residual_income: float | None = Field(default=None, ge=0)
    voucher_no: str | None = None
    photo_urls: list[str] = []


class RecoveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    recovery_no: str
    disposal_id: int
    recovery_org: str = ""
    residual_income: float | None = None
    voucher_no: str | None = None
    photo_urls: list[str] = []
    status: str
    handover_at: datetime | None = None


class PackageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    package_no: str
    disposal_id: int
    asset_count: int
    total_value: float | None = None
    status: str
    generated_at: datetime | None = None


# ── 同步执行 #91~#97 ──
class SyncValidateItem(BaseModel):
    asset_id: int
    asset_code: str
    missing: list[str] = []
    reasons: list[str] = []


class SyncValidateOut(BaseModel):
    passed: list[int] = []
    blocked: list[SyncValidateItem] = []
    total: int = 0


class SyncBatchCreate(BaseModel):
    selection_batch_no: str | None = None
    asset_ids: list[int] | None = None
    confirm: bool = False


class SyncBatchItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    asset_id: int
    asset_code: str
    status: str
    fail_reason: str = ""
    official_code: str | None = None


class SyncBatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    batch_no: str
    selection_batch_no: str | None = None
    status: str
    total_count: int
    total_value: float | None = None
    blocked_count: int
    items: list[SyncBatchItemOut] = []
    blocked: list[SyncValidateItem] = []
    created_at: datetime | None = None


class BackfillItem(BaseModel):
    asset_id: int
    official_code: str = Field(min_length=1, max_length=32)


class BackfillIn(BaseModel):
    items: list[BackfillItem] = []


class BackfillResultItem(BaseModel):
    asset_id: int
    asset_code: str | None = None
    ok: bool
    reason: str = ""
    official_code: str | None = None


class ConfirmItem(BaseModel):
    asset_id: int
    ok: bool
    reason: str = ""


class ConfirmIn(BaseModel):
    results: list[ConfirmItem] = []


class PendingChangeOut(BaseModel):
    asset_id: int
    asset_code: str
    name: str
    sync_status: str
    pending_sync_change_reason: str | None = None


class UnsyncedStatOut(BaseModel):
    category_code: str
    count: int
    total_value: float


class SyncLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    action: str
    batch_no: str | None = None
    asset_id: int | None = None
    asset_code: str | None = None
    operator_id: int | None = None
    operator_name: str = ""
    result: str
    detail: str = ""
    created_at: datetime | None = None


# ── 财务衔接 #116 ──
class ReconciliationCategoryOut(BaseModel):
    category_code: str
    synced_count: int
    synced_original_value: float
    synced_net_value: float
    all_count: int
    all_original_value: float
    all_accumulated_depreciation: float
    all_net_value: float


class ReconciliationDiffOut(BaseModel):
    asset_id: int
    asset_code: str
    name: str
    category_code: str
    sync_status: str
    voucher_no: str | None = None
    original_value: float | None = None
    accumulated_depreciation: float | None = None
    net_value: float | None = None
    expected_net_value: float | None = None
    reason: str


class ReconciliationOut(BaseModel):
    month: str
    categories: list[ReconciliationCategoryOut] = []
    differences: list[ReconciliationDiffOut] = []
    note: str = ""
