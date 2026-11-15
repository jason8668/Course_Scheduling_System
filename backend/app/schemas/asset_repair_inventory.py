"""第 4 批 schemas:维修工单(#42/#43)与盘点清查(#48/#49/#51/#52)。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ── 维修 #42/#43 ──────────────────────────────
class RepairCreate(BaseModel):
    """扫码报修:二选一,label_code 优先。"""

    label_code: str | None = None
    asset_id: int | None = None
    description: str = Field(default="", max_length=500)
    photo_url: str | None = Field(default=None, max_length=256)


class RepairScanOut(BaseModel):
    """扫码报修回显:设备信息、存放地点、保修状态与保内提示。"""

    asset_id: int
    asset_code: str
    name: str
    status: str
    room_name: str | None = None
    custodian_name: str | None = None
    warranty_until: str | None = None
    in_warranty: bool = False
    warranty_hint: str = ""
    repair_order_id: int | None = None
    doc_no: str | None = None
    created: bool = False


class RepairDispatchIn(BaseModel):
    assignee_id: int | None = None
    assignee_name: str | None = Field(default=None, max_length=32)
    vendor: str = Field(default="", max_length=128)
    #: True = 同时送修(资产经 transition 转维修中);False = 只派单不送修。
    send_to_repair: bool = False


class RepairRecordIn(BaseModel):
    vendor: str = Field(default="", max_length=128)
    cost: float = Field(ge=0)
    result: str = Field(default="", max_length=500)


class RepairCostSummaryOut(BaseModel):
    asset_id: int
    total_cost: float
    closed_count: int
    open_count: int
    threshold: float


# ── 盘点 #48 ──────────────────────────────
class InventoryPlanCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    plan_type: str = Field(default="全校盘点", pattern="^(全校盘点|抽盘|专项盘点)$")
    note: str = Field(default="", max_length=500)


class InventoryPlanOut(_Out):
    id: int
    plan_no: str
    name: str
    plan_type: str
    note: str
    status: str
    created_at: datetime | None = None


class InventoryTaskCreate(BaseModel):
    assignee_id: int
    assignee_name: str | None = Field(default=None, max_length=32)
    scope_dept: str | None = Field(default=None, max_length=64)
    scope_room_name: str | None = Field(default=None, max_length=64)
    scope_category_code: str | None = Field(default=None, max_length=16)
    due_at: datetime


class InventoryTaskOut(_Out):
    id: int
    plan_id: int
    assignee_id: int
    assignee_name: str
    scope_dept: str | None = None
    scope_room_name: str | None = None
    scope_category_code: str | None = None
    due_at: datetime | None = None
    status: str
    created_at: datetime | None = None


class InventoryPlanDetailOut(InventoryPlanOut):
    tasks: list[InventoryTaskOut] = []
    diff_counts: dict[str, int] = {}


# ── 盘点 #49 ──────────────────────────────
class InventoryScanIn(BaseModel):
    label_code: str = Field(min_length=1, max_length=40)
    room_name: str | None = Field(default=None, max_length=64)
    custodian_id: int | None = None
    custodian_name: str | None = Field(default=None, max_length=32)
    photo_url: str | None = Field(default=None, max_length=256)
    #: 离线暂存后弱网续传的记录为 True。
    is_offline: bool = False


class InventoryScanOut(BaseModel):
    in_scope: bool
    message: str
    record_id: int | None = None
    asset_id: int | None = None
    asset_code: str | None = None


class InventoryUnlabelledIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    category_code: str | None = Field(default=None, max_length=16)
    description: str = Field(default="", max_length=500)
    photo_url: str | None = Field(default=None, max_length=256)
    room_name: str | None = Field(default=None, max_length=64)
    custodian_name: str | None = Field(default=None, max_length=32)
    is_offline: bool = False


class InventoryRecordOut(_Out):
    id: int
    task_id: int
    asset_id: int | None = None
    label_code: str | None = None
    source: str
    status: str
    room_name: str | None = None
    custodian_name: str | None = None
    name: str | None = None
    description: str
    photo_url: str | None = None
    is_offline: bool
    created_at: datetime | None = None


# ── 差异 #51/#52 ──────────────────────────────
class InventoryDifferenceOut(_Out):
    id: int
    plan_id: int
    task_id: int
    asset_id: int | None = None
    asset_code: str | None = None
    asset_name: str | None = None
    diff_type: str
    status: str
    detail: str
    resolution: str
    involves_synced: bool
    acceptance_id: int | None = None
    created_at: datetime | None = None


class InventoryResolveIn(BaseModel):
    """处理动作:shortage 盘亏查责任 / surplus_create 盘盈补建卡 /
    correct_location 位置更正 / correct_custodian 保管人更正 / note 说明。"""

    action: str = Field(pattern="^(shortage|surplus_create|correct_location|correct_custodian|note)$")
    resolution: str = Field(default="", max_length=500)
    # 盘盈补建卡用(走 #24 盘盈补记入库入口):
    name: str | None = Field(default=None, max_length=128)
    category_code: str | None = Field(default=None, max_length=16)
    original_value: float | None = Field(default=None, ge=0)
    room_name: str | None = Field(default=None, max_length=64)
    custodian_id: int | None = None
    custodian_name: str | None = Field(default=None, max_length=32)
    # 位置/保管人更正用(不传则取盘点记录的实盘值):
    new_room_name: str | None = Field(default=None, max_length=64)
    new_custodian_id: int | None = None
    new_custodian_name: str | None = Field(default=None, max_length=32)


class InventoryCloseIn(BaseModel):
    confirm_note: str = Field(default="", max_length=500)


class InventoryReportOut(BaseModel):
    plan_id: int
    plan_no: str
    status: str
    total_expected: int
    total_scanned: int
    diff_counts: dict[str, int]
    unresolved: int
    #: 涉及已同步资产的差异(只标注,盘点结果不自动同步)。
    synced_differences: list[InventoryDifferenceOut] = []
    note: str = ""
