"""第 3 批 schemas:领用/借用/预约/归还/团体保管/调拨/移交/提醒/履历。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class IssueCreate(BaseModel):
    asset_id: int
    use_dept: str | None = None
    reason: str = Field(default="", max_length=500)
    flow_id: int | None = None


class IssueOut(_Out):
    id: int
    doc_no: str
    asset_id: int
    applicant_id: int
    applicant_name: str
    use_dept: str | None = None
    reason: str
    status: str
    approval_instance_id: int | None = None
    issued_by: int | None = None
    issued_at: datetime | None = None
    confirmed_at: datetime | None = None
    created_at: datetime | None = None


class ScanIn(BaseModel):
    label_code: str = Field(min_length=1, max_length=40)


class BorrowCreate(BaseModel):
    asset_id: int
    reason: str = Field(default="", max_length=500)
    due_at: datetime


class BorrowOut(_Out):
    id: int
    doc_no: str
    asset_id: int
    borrower_id: int
    borrower_name: str
    reason: str
    due_at: datetime
    status: str
    is_overdue: bool
    overdue_days: int
    escalated: bool
    reminded_before_due: bool
    returned_at: datetime | None = None
    created_at: datetime | None = None


class ReservationCreate(BaseModel):
    asset_id: int
    start_at: datetime
    end_at: datetime
    purpose: str = Field(default="", max_length=500)


class ReservationOut(_Out):
    id: int
    doc_no: str
    asset_id: int
    reserver_id: int
    reserver_name: str
    start_at: datetime
    end_at: datetime
    purpose: str
    status: str
    borrow_order_id: int | None = None
    released_at: datetime | None = None
    created_at: datetime | None = None


class ReturnCreate(BaseModel):
    asset_id: int
    source_doc_type: str = "借用单"
    source_doc_id: int | None = None


class ReturnScanIn(BaseModel):
    label_code: str = Field(min_length=1, max_length=40)
    result: str = Field(pattern="^(完好|损坏)$")
    damage_note: str = Field(default="", max_length=500)


class ReturnOut(_Out):
    id: int
    doc_no: str
    asset_id: int
    source_doc_type: str
    source_doc_id: int | None = None
    returner_id: int
    returner_name: str
    status: str
    result: str | None = None
    damage_note: str
    repair_order_id: int | None = None
    scanned_at: datetime | None = None
    created_at: datetime | None = None


class RepairOut(_Out):
    id: int
    doc_no: str
    asset_id: int
    source: str
    source_doc_no: str | None = None
    reporter_id: int | None = None
    reporter_name: str
    description: str
    status: str
    # ── 第 4 批扩展字段(#43):派单/维修方/费用/结果/报修人确认 ──
    photo_url: str | None = None
    assignee_id: int | None = None
    assignee_name: str | None = None
    vendor: str = ""
    cost: float | None = None
    result: str = ""
    pre_repair_status: str | None = None
    approval_instance_id: int | None = None
    confirmed_by: int | None = None
    confirmed_at: datetime | None = None
    closed_at: datetime | None = None
    created_at: datetime | None = None


class GroupCustodyCreate(BaseModel):
    asset_id: int
    group_type: str = Field(default="班级", pattern="^(班级|团体)$")
    group_name: str = Field(min_length=1, max_length=64)
    group_ref_id: int | None = None
    teacher_id: int
    note: str = Field(default="", max_length=500)


class GroupCustodyOut(_Out):
    id: int
    doc_no: str
    asset_id: int
    group_type: str
    group_name: str
    group_ref_id: int | None = None
    teacher_id: int
    teacher_name: str
    note: str
    is_active: bool
    created_at: datetime | None = None


class TransferCreate(BaseModel):
    asset_id: int
    to_dept: str = Field(min_length=1, max_length=64)
    to_custodian_id: int | None = None
    to_room_name: str | None = None
    reason: str = Field(default="", max_length=500)
    flow_id: int | None = None


class TransferOut(_Out):
    id: int
    doc_no: str
    asset_id: int
    from_dept: str | None = None
    to_dept: str
    to_custodian_id: int | None = None
    to_custodian_name: str | None = None
    to_room_name: str | None = None
    reason: str
    amount: float | None = None
    status: str
    approval_instance_id: int | None = None
    in_confirmed_by: int | None = None
    in_confirmed_at: datetime | None = None
    created_at: datetime | None = None


class HandoverGenerate(BaseModel):
    from_user_id: int
    to_user_id: int
    reason_type: str = Field(default="离职", pattern="^(离职|调岗|退休)$")


class HandoverItemOut(_Out):
    id: int
    handover_id: int
    asset_id: int
    asset_code: str
    status: str
    confirmed_by: int | None = None
    confirmed_at: datetime | None = None


class HandoverOut(_Out):
    id: int
    doc_no: str
    from_user_id: int
    from_user_name: str
    to_user_id: int
    to_user_name: str
    reason_type: str
    status: str
    is_overdue: bool
    created_at: datetime | None = None
    items: list[HandoverItemOut] = []


class HandoverItemConfirmIn(BaseModel):
    label_code: str = Field(min_length=1, max_length=40)


class ReminderOut(_Out):
    id: int
    kind: str
    user_id: int | None = None
    target_type: str
    target_id: int | None = None
    title: str
    content: str
    level: str
    is_read: bool
    is_dingtalk_sent: bool
    created_at: datetime | None = None


class TodoOut(BaseModel):
    kind: str
    title: str
    detail: str = ""
    target_type: str = ""
    target_id: int | None = None
    due_at: datetime | None = None
    urgency: str
    urgency_rank: int


class PortalHintsOut(BaseModel):
    """Portal 首页资产提示汇总(资产一期复核)。

    全部为真实计数,无数据为 0;角色不可见的字段为 None,前端只渲染
    非 None 项,不猜角色、不编数字。
    - 我的(所有人):名下资产、借用逾期/7 天内将到期、本人报修未关闭。
    - 管理(admin/asset_admin):待审批、全校借用逾期、维修待确认、
      进行中盘点方案/未完成盘点任务、处置待办、待同步池件数。
    - 领导(director/admin):闲置件数与原值合计、待处置单按状态汇总。
    """

    my_assets_total: int
    my_borrow_overdue: int
    my_borrow_due_soon: int
    my_repair_open: int
    my_repair_pending_confirm: int
    admin_pending_approval: int | None = None
    admin_borrow_overdue: int | None = None
    admin_repair_pending_confirm: int | None = None
    admin_inventory_open_plans: int | None = None
    admin_inventory_open_tasks: int | None = None
    admin_disposal_open: int | None = None
    admin_sync_pending: int | None = None
    leader_idle_count: int | None = None
    leader_idle_value: float | None = None
    leader_disposal_open: int | None = None
    leader_disposal_by_status: dict[str, int] | None = None


class TimelineEntryOut(BaseModel):
    time: datetime | None = None
    type: str
    title: str
    detail: str = ""
    doc_no: str | None = None
    actor: str = ""
