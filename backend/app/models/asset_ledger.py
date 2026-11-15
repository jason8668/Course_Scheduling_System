"""台账/入库验收/手动勾选 models(学校资产管理系统一期第 2 批)。

新增表:
- asset_acceptances 验收单(#25):六类入库入口共用,验收不通过不建卡。
- asset_attachments 附件索引(#12):数据库只存索引/路径,不存文件本体。
- asset_sync_selections 勾选记录(#87/#88/#89/#90):一次勾选一行,取消后
  标记 cancelled 而非物理删除,供同步日志审计追溯。
- asset_batches 批次(#26/#90):入库批次与勾选批次共用批次号池,批次号
  唯一,类型字段区分 intake / sync_select。

asset_cards 新增列(本批,见迁移 0040):
batch_no 入库批次号(#26)、acceptance_id 验收单、is_booked/booked_at
正式入账标志(#27)、last_used_at 最近使用时间、is_idle/idle_reason
闲置标记(#14,仅由刷新任务写,不手工打标记)。
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class IntakeType:
    """六类入库入口(#19~#24)。acquire_method 由入口派生:
    gov_purchase/self_purchase → purchase(购置);
    donation → donation; transfer_in → transfer_in;
    self_built → self_built; inventory_surplus → inventory_surplus。
    """

    GOV_PURCHASE = "gov_purchase"          # #19 政府采购到货入库
    SELF_PURCHASE = "self_purchase"        # #20 自行采购入库
    DONATION = "donation"                  # #21 捐赠资产入库
    TRANSFER_IN = "transfer_in"            # #22 上级调拨入库
    SELF_BUILT = "self_built"              # #23 自建/在建转固入库
    INVENTORY_SURPLUS = "inventory_surplus"  # #24 盘盈补记入库

    ALL = frozenset({
        GOV_PURCHASE, SELF_PURCHASE, DONATION,
        TRANSFER_IN, SELF_BUILT, INVENTORY_SURPLUS,
    })

    LABELS = {
        GOV_PURCHASE: "政府采购到货",
        SELF_PURCHASE: "自行采购",
        DONATION: "捐赠",
        TRANSFER_IN: "上级调拨",
        SELF_BUILT: "自建/在建转固",
        INVENTORY_SURPLUS: "盘盈补记",
    }

    #: 入口 → 取得方式(字典 acquire_method 代码)。
    ACQUIRE_METHOD = {
        GOV_PURCHASE: "purchase",
        SELF_PURCHASE: "purchase",
        DONATION: "donation",
        TRANSFER_IN: "transfer_in",
        SELF_BUILT: "self_built",
        INVENTORY_SURPLUS: "inventory_surplus",
    }


class AcceptanceStatus:
    PENDING = "待验收"
    PASSED = "验收通过"
    FAILED = "验收不通过"
    CARDED = "已建卡"


class AssetAcceptance(Base):
    """验收单(#25)。"""

    __tablename__ = "asset_acceptances"
    __table_args__ = (
        UniqueConstraint("acceptance_no", name="uq_asset_acceptance_no"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    #: 验收单号,YS-YYYYMMDD-XXXX。
    acceptance_no: Mapped[str] = mapped_column(String(32), index=True)
    intake_type: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), default=AcceptanceStatus.PENDING)
    #: 来源凭证(JSON):采购合同与订单号、捐赠方与价值依据、调拨单号、
    #: 竣工决算附件、盘点单号等,按入口类型取用不同键,见 schemas。
    source_doc: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    #: 验收人员姓名清单(JSON list)。
    acceptors: Mapped[list | None] = mapped_column(JSON, nullable=True)
    accepted_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    comment: Mapped[str] = mapped_column(String(500), default="")
    #: 建卡后回填的入库批次号(与卡片 batch_no 一致)。
    batch_no: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AssetAttachment(Base):
    """附件索引(#12):数据库只存索引/路径,文件本体走系统现有附件存储,
    本表不存二进制。删除为软删除(留痕,审计日志另记)。"""

    __tablename__ = "asset_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("asset_cards.id", ondelete="CASCADE"), index=True
    )
    #: 附件类型:发票/合同/验收照片/设备照片/其他。
    file_type: Mapped[str] = mapped_column(String(16), default="其他")
    file_name: Mapped[str] = mapped_column(String(256))
    #: 存储路径/对象键(由调用方按系统现有附件存储方式传入)。
    file_path: Mapped[str] = mapped_column(String(512))
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    acceptance_id: Mapped[int | None] = mapped_column(
        ForeignKey("asset_acceptances.id", ondelete="SET NULL"), nullable=True
    )
    uploaded_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


#: 附件类型枚举(中文值)。
ATTACHMENT_TYPES = frozenset({"发票", "合同", "验收照片", "设备照片", "其他"})


class AssetBatch(Base):
    """批次号池(#26/#90):入库批次与勾选批次共用,批次号唯一。"""

    __tablename__ = "asset_batches"
    __table_args__ = (
        UniqueConstraint("batch_no", name="uq_asset_batches_no"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_no: Mapped[str] = mapped_column(String(32), index=True)
    #: intake 入库批次 / sync_select 勾选批次。
    batch_type: Mapped[str] = mapped_column(String(16))
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    total_value: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    note: Mapped[str] = mapped_column(String(256), default="")
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssetSyncSelection(Base):
    """勾选记录(#87/#88/#89/#90):一件资产一次勾选一行。

    取消勾选不删行,改 status=cancelled 并记 cancelled_by/at,同步日志
    审计追溯(#102)。同一资产同一时间只应有一行 active,服务层保证。
    """

    __tablename__ = "asset_sync_selections"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("asset_cards.id", ondelete="CASCADE"), index=True
    )
    #: 勾选批次号:一次勾选操作(单件或批量)共用一个批次号 GX-YYYYMMDD-XXXX。
    selection_batch_no: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    selected_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    selected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    cancelled_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
