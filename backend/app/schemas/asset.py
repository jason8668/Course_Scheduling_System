"""资产地基批 schema(学校资产管理系统一期)。

路由前缀 /api/asset。状态/同步状态一律用中文枚举值,与模型一致。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ── 分类字典 #16 ──
class AssetCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    level: int
    parent_code: str | None = None
    is_reportable: bool
    origin: str
    is_active: bool
    sort_order: int


class AssetCategoryCreate(BaseModel):
    code: str = Field(min_length=1, max_length=16)
    name: str = Field(min_length=1, max_length=64)
    level: int = Field(ge=1, le=4)
    parent_code: str | None = None
    # 只允许新建校内标签(is_reportable=False);上报分类不得自行新增。
    is_reportable: bool = False
    origin: str = "school"


class AssetCategoryUpdate(BaseModel):
    # 上报分类的代码与名称锁定:本 schema 根本不接受这两个字段。
    is_active: bool | None = None
    sort_order: int | None = None


class FinanceMapOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    category_code: str
    finance_subject_code: str
    finance_subject_name: str
    is_default: bool
    note: str = ""


class FinanceMapIn(BaseModel):
    finance_subject_code: str = Field(min_length=1, max_length=32)
    finance_subject_name: str = Field(min_length=1, max_length=64)
    is_default: bool = True
    note: str = ""


# ── 编码规则 #17 ──
class AssetCodeRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    prefix: str
    include_year: bool
    include_category: bool
    sequence_width: int
    is_active: bool
    note: str = ""


class AssetCodeRuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    prefix: str = Field(min_length=1, max_length=16)
    include_year: bool = True
    include_category: bool = True
    sequence_width: int = Field(ge=2, le=8, default=4)
    note: str = ""


# ── 资产卡 #10/#11/#15/#85/#86 ──
class AssetCardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    asset_code: str
    official_code: str | None = None
    label_code: str
    name: str
    category_code: str
    spec_model: str | None = None
    unit: str
    acquired_date: datetime | None = None
    acquire_method: str | None = None
    source: str | None = None
    supplier: str | None = None
    original_value: float | None = None
    funding_source: str | None = None
    voucher_no: str | None = None
    depreciation_method: str | None = None
    depreciation_years: int | None = None
    accumulated_depreciation: float | None = None
    net_value: float | None = None
    status: str
    manage_dept: str | None = None
    use_dept: str | None = None
    custodian_user_id: int | None = None
    custodian_name: str | None = None
    campus: str | None = None
    building: str | None = None
    room_id: int | None = None
    room_name: str | None = None
    borrow_status: str
    attributes: dict | None = None
    # 校内扩展区(never_sync)。
    ext: dict | None = None
    sync_status: str
    is_retired: bool
    retired_at: datetime | None = None
    created_at: datetime | None = None
    # ── 第 2 批:入库批次/验收/入账/闲置(#26/#27/#14) ──
    batch_no: str | None = None
    acceptance_id: int | None = None
    is_booked: bool = False
    booked_at: datetime | None = None
    last_used_at: datetime | None = None
    is_idle: bool = False
    idle_reason: str | None = None
    # ── 第 3 批:待同步变更标记(#37/#98,供 B5 手动勾选再同步) ──
    pending_sync_change: bool = False
    pending_sync_change_reason: str | None = None


class AssetCardCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    category_code: str = Field(min_length=1, max_length=16)
    asset_code: str | None = None
    spec_model: str | None = None
    unit: str = "件"
    acquired_date: datetime | None = None
    acquire_method: str | None = None
    source: str | None = None
    supplier: str | None = None
    original_value: float | None = Field(default=None, ge=0)
    funding_source: str | None = None
    voucher_no: str | None = None
    depreciation_method: str | None = None
    depreciation_years: int | None = Field(default=None, ge=0)
    accumulated_depreciation: float | None = Field(default=None, ge=0)
    net_value: float | None = Field(default=None, ge=0)
    manage_dept: str | None = None
    use_dept: str | None = None
    custodian_user_id: int | None = None
    custodian_name: str | None = None
    campus: str | None = None
    building: str | None = None
    room_id: int | None = None
    room_name: str | None = None
    borrow_status: str = "未领用"
    attributes: dict | None = None
    ext: dict | None = None


class AssetCardUpdate(BaseModel):
    # 禁止经此端点改:编号(asset_code)、状态(status)、同步状态(sync_status)。
    name: str | None = None
    spec_model: str | None = None
    unit: str | None = None
    acquired_date: datetime | None = None
    acquire_method: str | None = None
    source: str | None = None
    supplier: str | None = None
    original_value: float | None = Field(default=None, ge=0)
    funding_source: str | None = None
    voucher_no: str | None = None
    depreciation_method: str | None = None
    depreciation_years: int | None = Field(default=None, ge=0)
    accumulated_depreciation: float | None = Field(default=None, ge=0)
    net_value: float | None = Field(default=None, ge=0)
    manage_dept: str | None = None
    use_dept: str | None = None
    custodian_user_id: int | None = None
    custodian_name: str | None = None
    campus: str | None = None
    building: str | None = None
    room_id: int | None = None
    room_name: str | None = None
    borrow_status: str | None = None
    attributes: dict | None = None
    ext: dict | None = None
    # 官方编号回填(#96):只允许在同步回填场景由资产管理员填,本批不自动回填。
    official_code: str | None = None


class AssetCardListOut(BaseModel):
    items: list[AssetCardOut]
    total: int


class AssetTransitionIn(BaseModel):
    to_status: str = Field(min_length=1, max_length=16)
    doc_type: str = Field(min_length=1, max_length=32)
    doc_no: str = Field(min_length=1, max_length=64)


class LabelVerifyOut(BaseModel):
    asset_code: str
    label_code: str
    valid: bool


# ── 房间扩展 #76 ──
class AssetRoomExtensionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    room_id: int
    campus: str | None = None
    building: str | None = None
    asset_package: str | None = None
    note: str = ""


class AssetRoomExtensionIn(BaseModel):
    room_id: int
    campus: str | None = None
    building: str | None = None
    asset_package: str | None = None
    note: str = ""


# ── 字典与参数 #81 ──
class AssetDictionaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    dict_type: str
    code: str
    label: str
    is_system: bool
    is_active: bool
    sort_order: int


class AssetDictionaryIn(BaseModel):
    dict_type: str = Field(min_length=1, max_length=32)
    code: str = Field(min_length=1, max_length=32)
    label: str = Field(min_length=1, max_length=64)
    sort_order: int = 0


class AssetParamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    key: str
    value: str
    value_type: str
    description: str = ""


class AssetParamIn(BaseModel):
    value: str = Field(max_length=256)


# ── 审批流 #5/#79/#80 ──
class ApprovalFlowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    doc_type: str
    name: str
    nodes: list = []
    is_active: bool


class ApprovalFlowIn(BaseModel):
    doc_type: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=64)
    nodes: list = Field(min_length=1)


class ApprovalNodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    step: int
    role: str
    mode: str
    required_approvals: int
    approvals: list = []
    status: str
    comment: str | None = None
    acted_by: int | None = None


class ApprovalInstanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    flow_id: int
    doc_type: str
    doc_id: int
    doc_no: str | None = None
    applicant_id: int
    applicant_name: str
    amount: float | None = None
    status: str
    current_step: int
    deadline: datetime | None = None
    is_overdue: bool
    nodes: list[ApprovalNodeOut] = []


class ApprovalInstanceIn(BaseModel):
    doc_type: str = Field(min_length=1, max_length=32)
    doc_id: int
    doc_no: str | None = None
    amount: float | None = Field(default=None, ge=0)
    flow_id: int | None = None


class ApprovalActIn(BaseModel):
    action: str = Field(pattern="^(approve|reject)$")
    comment: str | None = None


class ApprovalTransferIn(BaseModel):
    to_role: str = Field(min_length=1, max_length=32)
    comment: str | None = None


# ── 字段映射 #104 ──
class AssetFieldMappingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    local_field: str
    official_field: str
    official_template_version: str
    transform_rule: str | None = None
    is_required: bool
    sort_order: int
    is_active: bool
    note: str = ""


class AssetFieldMappingIn(BaseModel):
    local_field: str = Field(min_length=1, max_length=64)
    official_field: str = Field(min_length=1, max_length=64)
    official_template_version: str = "当期模板"
    transform_rule: str | None = None
    is_required: bool = False
    sort_order: int = 0
    note: str = ""


class AssetFieldMappingUpdate(BaseModel):
    official_field: str | None = None
    transform_rule: str | None = None
    is_required: bool | None = None
    is_active: bool | None = None
    note: str | None = None


# ── 对接适配层占位 #106 ──
class SyncAdapterOut(BaseModel):
    adapter: str
    available: list[str]
    live_api: bool
    note: str
