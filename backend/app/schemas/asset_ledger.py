"""台账/入库验收/手动勾选 schemas(学校资产管理系统一期第 2 批)。

状态/同步状态一律用中文枚举值,与模型一致。取得方式用字典
acquire_method 代码;入库入口用 intake_type 代码(见 IntakeType)。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ── 通用逐条结果(#13/#26/#88:批量操作逐条回告,不整体回滚) ──
class BulkItemResult(BaseModel):
    asset_id: int | None = None
    asset_code: str | None = None
    ok: bool
    reason: str = ""


class BulkResultOut(BaseModel):
    succeeded: list[BulkItemResult] = []
    failed: list[BulkItemResult] = []
    batch_no: str | None = None


# ── 台账组合查询 #8 ──
class AssetSearchParams(BaseModel):
    category_code: str | None = None
    manage_dept: str | None = None
    use_dept: str | None = None
    custodian_name: str | None = None
    custodian_user_id: int | None = None
    room_id: int | None = None
    room_name: str | None = None
    status: str | None = None
    sync_status: str | None = None
    acquire_method: str | None = None
    funding_source: str | None = None
    acquired_year: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    batch_no: str | None = None
    is_booked: bool | None = None
    is_idle: bool | None = None
    q: str | None = None
    sort_by: str = "id"
    sort_dir: str = "desc"
    limit: int = 50
    offset: int = 0


# ── 附件 #12 ──
class AssetAttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    asset_id: int
    file_type: str
    file_name: str
    file_path: str
    file_size: int | None = None
    acceptance_id: int | None = None
    uploaded_by: int | None = None
    created_at: datetime | None = None


class AssetAttachmentIn(BaseModel):
    file_type: str = Field(default="其他", max_length=16)
    file_name: str = Field(min_length=1, max_length=256)
    # 存储路径/对象键:调用方按系统现有附件存储方式传入,本表只存索引。
    file_path: str = Field(min_length=1, max_length=512)
    file_size: int | None = Field(default=None, ge=0)
    acceptance_id: int | None = None


# ── 批量维护 #13 ──
class AssetBulkUpdateIn(BaseModel):
    asset_ids: list[int] = Field(min_length=1)
    custodian_user_id: int | None = None
    custodian_name: str | None = None
    room_id: int | None = None
    room_name: str | None = None
    manage_dept: str | None = None
    use_dept: str | None = None
    # atomic=true 时任一失败则整批回滚;默认 false,逐条处理不整体回滚。
    atomic: bool = False


# ── 标签 #28 ──
class AssetLabelOut(BaseModel):
    asset_id: int
    asset_code: str
    label_code: str
    name: str
    manage_dept: str | None = None
    valid: bool


# ── 闲置识别 #14 ──
class AssetIdleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    asset_code: str
    name: str
    category_code: str
    manage_dept: str | None = None
    custodian_name: str | None = None
    status: str
    original_value: float | None = None
    acquired_date: datetime | None = None
    last_used_at: datetime | None = None
    idle_reason: str | None = None


class IdleRefreshOut(BaseModel):
    threshold_days: int
    idle_count: int
    idle_ids: list[int] = []


# ── 验收单 #25 ──
class AcceptanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    acceptance_no: str
    intake_type: str
    status: str
    source_doc: dict | None = None
    acceptors: list | None = None
    accepted_by: int | None = None
    accepted_at: datetime | None = None
    comment: str = ""
    batch_no: str | None = None
    created_at: datetime | None = None


class AcceptanceIn(BaseModel):
    intake_type: str = Field(min_length=1, max_length=32)
    # 来源凭证:gov/self_purchase 用 contract_no/order_no;donation 用
    # donor/value_basis;transfer_in 用 transfer_no;self_built 用
    # completion_doc;inventory_surplus 用 inventory_no。
    source_doc: dict | None = None
    acceptors: list[str] | None = None
    comment: str = ""


class AcceptanceConfirmIn(BaseModel):
    # result: 通过 / 不通过;不通过的资产不得建卡(#25)。
    result: str = Field(pattern="^(通过|不通过)$")
    acceptors: list[str] | None = None
    comment: str = ""


# ── 建卡(验收后) #19~#24/#26 ──
class IntakeCardItem(BaseModel):
    """单件建卡项:复用 AssetCardCreate 的字段子集,资产编号可空(自动生成)。"""

    name: str = Field(min_length=1, max_length=128)
    category_code: str = Field(min_length=1, max_length=16)
    asset_code: str | None = None
    spec_model: str | None = None
    unit: str = "件"
    acquired_date: datetime | None = None
    source: str | None = None
    supplier: str | None = None
    original_value: float | None = Field(default=None, ge=0)
    funding_source: str | None = None
    manage_dept: str | None = None
    use_dept: str | None = None
    custodian_user_id: int | None = None
    custodian_name: str | None = None
    campus: str | None = None
    building: str | None = None
    room_id: int | None = None
    room_name: str | None = None
    attributes: dict | None = None
    ext: dict | None = None


class IntakeCreateCardsIn(BaseModel):
    items: list[IntakeCardItem] = Field(min_length=1)
    batch_no: str | None = None


class IntakeBulkCreateIn(BaseModel):
    """批量建卡(#26):同一模板建 quantity 件,名称自动加 -01/-02 后缀。"""

    template: IntakeCardItem
    quantity: int = Field(ge=1, le=500)
    batch_no: str | None = None


# ── 待入账 #27 ──
class BookingConfirmIn(BaseModel):
    voucher_no: str = Field(min_length=1, max_length=64)


class BookingPendingOut(BaseModel):
    items: list[dict] = []
    total: int
    total_value: float


# ── 手动勾选 #87/#88/#89/#90 ──
class SyncSelectIn(BaseModel):
    asset_ids: list[int] = Field(min_length=1)


class SyncSelectByFilterIn(BaseModel):
    """按筛选条件批量勾选:与台账查询同口径,仅对符合条件的资产逐条校验。"""

    category_code: str | None = None
    manage_dept: str | None = None
    room_id: int | None = None
    batch_no: str | None = None
    min_value: float | None = None
    max_value: float | None = None
    sync_status: str | None = None
    status: str | None = None
    q: str | None = None


class SyncPoolItemOut(BaseModel):
    asset_id: int
    asset_code: str
    name: str
    category_code: str
    manage_dept: str | None = None
    original_value: float | None = None
    sync_status: str
    selected_by: int | None = None
    selected_at: datetime | None = None
    selection_batch_no: str | None = None


class SyncPoolOut(BaseModel):
    items: list[SyncPoolItemOut] = []
    total: int
    total_value: float
    # 按勾选批次分组:批次号 → {count, total_value}。
    groups: dict[str, dict] = {}
