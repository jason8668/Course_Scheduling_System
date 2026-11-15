"""领用/借用/调拨/移交/工作台 models(学校资产管理系统一期第 3 批)。

覆盖 #30~#35(M4 领用借用归还)、#37/#39/#40(M5 调拨移交)、
#1/#2/#3/#6/#7(M1 工作台与待办,提醒记录表)。

约定:
- 单据号前缀:领用单 LY-、借用单 JY-、预约单 YY-、归还单 GH-、
  团体保管单 TB-、调拨单 DB-、移交单 YJ-、维修占位单 WX-,
  均为 前缀+YYYYMMDD+4 位流水(同一前缀同一天内递增)。
- 状态转移一律经 services.asset_foundation.transition_asset(与 B1
  transition 端点同一服务函数),并带 doc_type/doc_no;调拨/移交本身
  不改变资产状态(只改保管人/部门/位置),故不调用 transition——
  状态无变化时调用 transition 会被状态机拦截,见汇报。
- 已同步资产调拨后打待同步变更标记:asset_cards.pending_sync_change
  (Boolean)+pending_sync_change_reason,供 B5 #98 手动勾选再同步。
- 维修单模型在 B4;本批只建最小占位表 asset_repair_orders(状态
  待处理,来源 归还验收/报修),B4 在此表上扩展派单/费用/结果字段,
  不另建维修表。
- 提醒记录表 asset_reminders 是 #3 提醒中心的数据源;钉钉推送只记
  是否已推送(is_dingtalk_sent),推送失败只记日志不阻塞业务。
- 演示数据:本批不写任何种子单据;测试用"示例资产"等占位名称。
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class IssueStatus:
    APPLYING = "申请中"
    PENDING_ISSUE = "待发放"
    ISSUED = "已发放"
    CONFIRMED = "已确认"
    REJECTED = "已退回"
    CANCELLED = "已撤销"


class BorrowStatusDoc:
    BORROWING = "借用中"
    RETURNED = "已归还"
    OVERDUE = "已逾期"


class ReservationStatus:
    PENDING = "待领用"
    CHECKED_OUT = "已领用"
    RELEASED = "已释放"
    CANCELLED = "已取消"


class ReturnResult:
    GOOD = "完好"
    DAMAGED = "损坏"


class ReturnStatus:
    PENDING = "待验收"
    DONE = "已完成"
    TO_REPAIR = "已转维修"


class TransferStatus:
    PENDING_IN = "待调入确认"
    PENDING_APPROVAL = "待审批"
    PENDING_FINISH = "待完成"
    DONE = "已完成"
    REJECTED = "已退回"


class HandoverStatus:
    PENDING = "待移交"
    PARTIAL = "部分确认"
    DONE = "已完成"


class RepairPlaceholderStatus:
    PENDING = "待处理"


class RepairStatus:
    """维修工单状态(B4 #43):报修 → 派单/送修 → 登记结果 → 报修人确认关闭。

    超阈值(approval.repair_threshold,默认 5000 元)登记结果后先入
    待审批,审批通过才进待确认;审批退回则工单停在待审批,须重新登记。
    """

    PENDING = "待处理"
    DISPATCHED = "已派单"
    REPAIRING = "维修中"
    PENDING_APPROVAL = "待审批"
    PENDING_CONFIRM = "待确认"
    CLOSED = "已关闭"


def _doc_no_column() -> Mapped[str]:
    return mapped_column(String(32), index=True)


class AssetIssueOrder(Base):
    """领用单(#30):长期领用。申请 → 审批(通用审批流,doc_type=领用单)
    → 发放确认(状态 在库→在用) → 扫码确认(写 last_used_at)。"""

    __tablename__ = "asset_issue_orders"
    __table_args__ = (UniqueConstraint("doc_no", name="uq_asset_issue_doc_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    doc_no: Mapped[str] = _doc_no_column()
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("asset_cards.id", ondelete="RESTRICT"), index=True
    )
    applicant_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    applicant_name: Mapped[str] = mapped_column(String(32), default="")
    use_dept: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(16), default=IssueStatus.APPLYING, index=True)
    approval_instance_id: Mapped[int | None] = mapped_column(
        ForeignKey("asset_approval_instances.id", ondelete="SET NULL"), nullable=True
    )
    issued_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AssetBorrowOrder(Base):
    """借用单(#32):短期按天借用。借用人=申请人,到期前提醒、逾期升级。"""

    __tablename__ = "asset_borrow_orders"
    __table_args__ = (UniqueConstraint("doc_no", name="uq_asset_borrow_doc_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    doc_no: Mapped[str] = _doc_no_column()
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("asset_cards.id", ondelete="RESTRICT"), index=True
    )
    borrower_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    borrower_name: Mapped[str] = mapped_column(String(32), default="")
    reason: Mapped[str] = mapped_column(String(500), default="")
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(16), default=BorrowStatusDoc.BORROWING, index=True)
    is_overdue: Mapped[bool] = mapped_column(Boolean, default=False)
    overdue_days: Mapped[int] = mapped_column(Integer, default=0)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    reminded_before_due: Mapped[bool] = mapped_column(Boolean, default=False)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AssetReservation(Base):
    """公用资产预约单(#33):按时段预约,同一资产同一时段只一个有效预约。"""

    __tablename__ = "asset_reservations"
    __table_args__ = (UniqueConstraint("doc_no", name="uq_asset_reservation_doc_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    doc_no: Mapped[str] = _doc_no_column()
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("asset_cards.id", ondelete="RESTRICT"), index=True
    )
    reserver_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    reserver_name: Mapped[str] = mapped_column(String(32), default="")
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    purpose: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(16), default=ReservationStatus.PENDING, index=True)
    borrow_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("asset_borrow_orders.id", ondelete="SET NULL"), nullable=True
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AssetReturnOrder(Base):
    """归还单(#34):扫码归还验收。完好→回在库;损坏→转维修中+维修占位单。"""

    __tablename__ = "asset_return_orders"
    __table_args__ = (UniqueConstraint("doc_no", name="uq_asset_return_doc_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    doc_no: Mapped[str] = _doc_no_column()
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("asset_cards.id", ondelete="RESTRICT"), index=True
    )
    #: 来源单据类型:借用单/领用单。
    source_doc_type: Mapped[str] = mapped_column(String(16), default="借用单")
    source_doc_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    returner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    returner_name: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(16), default=ReturnStatus.PENDING, index=True)
    result: Mapped[str | None] = mapped_column(String(16), nullable=True)
    damage_note: Mapped[str] = mapped_column(String(500), default="")
    repair_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("asset_repair_orders.id", ondelete="SET NULL"), nullable=True
    )
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AssetGroupCustody(Base):
    """团体保管单(#35):班级/团体为保管单位、责任教师负责,不给学生开账号。"""

    __tablename__ = "asset_group_custodies"
    __table_args__ = (UniqueConstraint("doc_no", name="uq_asset_group_custody_doc_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    doc_no: Mapped[str] = _doc_no_column()
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("asset_cards.id", ondelete="RESTRICT"), index=True
    )
    #: 团体类型:班级/团体。
    group_type: Mapped[str] = mapped_column(String(16), default="班级")
    group_name: Mapped[str] = mapped_column(String(64))
    #: 复用智慧教务班级(class_units.id),可空;团体无对应班级时只记名称。
    group_ref_id: Mapped[int | None] = mapped_column(
        ForeignKey("class_units.id", ondelete="SET NULL"), nullable=True
    )
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    teacher_name: Mapped[str] = mapped_column(String(32), default="")
    note: Mapped[str] = mapped_column(String(500), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AssetTransferOrder(Base):
    """调拨单(#37):调出部门发起 → 调入部门确认 → 审批(金额超阈值到总务)
    → 完成(责任与位置同步变更)。"""

    __tablename__ = "asset_transfer_orders"
    __table_args__ = (UniqueConstraint("doc_no", name="uq_asset_transfer_doc_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    doc_no: Mapped[str] = _doc_no_column()
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("asset_cards.id", ondelete="RESTRICT"), index=True
    )
    from_dept: Mapped[str | None] = mapped_column(String(64), nullable=True)
    to_dept: Mapped[str] = mapped_column(String(64))
    to_custodian_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    to_custodian_name: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_room_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str] = mapped_column(String(500), default="")
    amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=TransferStatus.PENDING_IN, index=True)
    approval_instance_id: Mapped[int | None] = mapped_column(
        ForeignKey("asset_approval_instances.id", ondelete="SET NULL"), nullable=True
    )
    in_confirmed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    in_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AssetHandoverOrder(Base):
    """移交单(#39/#40):人员变动时按人员汇总其名下全部资产生成;
    扫码逐件确认接收人;完成前原保管人责任不解除。"""

    __tablename__ = "asset_handover_orders"
    __table_args__ = (UniqueConstraint("doc_no", name="uq_asset_handover_doc_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    doc_no: Mapped[str] = _doc_no_column()
    from_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    from_user_name: Mapped[str] = mapped_column(String(32), default="")
    to_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    to_user_name: Mapped[str] = mapped_column(String(32), default="")
    #: 变动原因:离职/调岗/退休。
    reason_type: Mapped[str] = mapped_column(String(16), default="离职")
    status: Mapped[str] = mapped_column(String(16), default=HandoverStatus.PENDING, index=True)
    is_overdue: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AssetHandoverItem(Base):
    """移交单明细:一件资产一行,逐件扫码确认。"""

    __tablename__ = "asset_handover_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    handover_id: Mapped[int] = mapped_column(
        ForeignKey("asset_handover_orders.id", ondelete="CASCADE"), index=True
    )
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("asset_cards.id", ondelete="RESTRICT"), index=True
    )
    asset_code: Mapped[str] = mapped_column(String(32), default="")
    #: 待确认/已确认。
    status: Mapped[str] = mapped_column(String(16), default="待确认", index=True)
    confirmed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssetRepairOrder(Base):
    """维修工单(B3 占位,B4 #42/#43/#44 在此表上扩展,不另建维修表)。

    流程:报修(待处理) → 管理员派单/送修(已派单/维修中,资产经 transition
    入维修中,修前状态记 pre_repair_status) → 登记维修方/费用/结果
    (待确认;费用 ≥ approval.repair_threshold 时先入待审批走通用审批流)
    → 报修人确认(已关闭,费用累计进资产卡 total_repair_cost,资产按
    修前状态转回在库/在用)。
    """

    __tablename__ = "asset_repair_orders"
    __table_args__ = (UniqueConstraint("doc_no", name="uq_asset_repair_doc_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    doc_no: Mapped[str] = _doc_no_column()
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("asset_cards.id", ondelete="RESTRICT"), index=True
    )
    #: 来源:归还验收/报修。
    source: Mapped[str] = mapped_column(String(16), default="归还验收")
    source_doc_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reporter_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reporter_name: Mapped[str] = mapped_column(String(32), default="")
    description: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(
        String(16), default=RepairPlaceholderStatus.PENDING, index=True
    )
    # ── B4 #42/#43 扩展字段 ──
    #: 故障拍照(图片地址,移动端拍照上传后回填)。
    photo_url: Mapped[str | None] = mapped_column(String(256), nullable=True)
    #: 派单对象(维修人员/送修接收人)。
    assignee_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    assignee_name: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: 维修方(厂商/维修单位名称)。
    vendor: Mapped[str] = mapped_column(String(128), default="")
    #: 维修费用(元);关闭时累计进资产卡 total_repair_cost。
    cost: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    #: 维修结果(处理经过与结果描述)。
    result: Mapped[str] = mapped_column(String(500), default="")
    #: 送修前资产状态(修好后按此转回:在库/在用;其他值一律回在库)。
    pre_repair_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    #: 超阈值维修的审批实例(通用审批流,doc_type=维修单)。
    approval_instance_id: Mapped[int | None] = mapped_column(
        ForeignKey("asset_approval_instances.id", ondelete="SET NULL"), nullable=True
    )
    confirmed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AssetReminder(Base):
    """提醒记录(#3):借用逾期/到期、审批超时、保修到期、移交预警、
    同步待处理等提醒集中展示的数据源。"""

    __tablename__ = "asset_reminders"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: 提醒类型:借用逾期/借用到期/审批超时/保修到期/移交预警/同步待处理。
    kind: Mapped[str] = mapped_column(String(16), index=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: 关联对象:borrow_order/approval_instance/asset_card/handover_order。
    target_type: Mapped[str] = mapped_column(String(32), default="")
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(128))
    content: Mapped[str] = mapped_column(String(500), default="")
    #: 一般/紧急/逾期。
    level: Mapped[str] = mapped_column(String(16), default="一般", index=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    is_dingtalk_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
