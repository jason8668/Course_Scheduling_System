"""盘点清查 models(学校资产管理系统一期第 4 批 #48/#49/#51/#52)。

- 盘点方案(AssetInventoryPlan):全校盘点/抽盘/专项盘点,方案号 PD-。
- 盘点任务(AssetInventoryTask):按部门/房间/分类拆分,分派到人,有截止时间。
- 盘点记录(AssetInventoryRecord):每次扫码/补录一行;范围外扫码不计入,
  不建记录(只记审计);离线暂存由移动端先存本地、联网后调同一扫码接口
  续传,is_offline 标记该条是离线补传。
- 差异清单(AssetInventoryDifference):五类差异 正常/盘亏/盘盈/位置不符/
  保管人不符;盘盈的资产卡不存在,asset_id 可空,补建卡后回填。
- 盘点结果不自动同步到官方(#52):差异是否涉及已同步资产只记
  involves_synced 标志,供 B5 #98/#100 手动勾选时参考。
- 演示数据:本批不写任何种子单据;测试用"示例资产"等占位名称。
"""

from datetime import datetime

from sqlalchemy import (
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


class InventoryPlanType:
    FULL = "全校盘点"
    SAMPLE = "抽盘"
    SPECIAL = "专项盘点"


class InventoryPlanStatus:
    DRAFT = "草稿"
    IN_PROGRESS = "进行中"
    CLOSED = "已关闭"


class InventoryTaskStatus:
    PENDING = "待盘点"
    IN_PROGRESS = "进行中"
    DONE = "已完成"


class InventoryDiffType:
    NORMAL = "正常"
    SHORTAGE = "盘亏"
    SURPLUS = "盘盈"
    LOCATION_MISMATCH = "位置不符"
    CUSTODIAN_MISMATCH = "保管人不符"


class InventoryDiffStatus:
    PENDING = "待处理"
    RESOLVED = "已处理"


class AssetInventoryPlan(Base):
    """盘点方案(#48):一次盘点一个方案,下挂多个拆分任务。"""

    __tablename__ = "asset_inventory_plans"
    __table_args__ = (UniqueConstraint("plan_no", name="uq_asset_inventory_plan_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    #: 方案号 PD-YYYYMMDD-XXXX。
    plan_no: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(128))
    #: 全校盘点/抽盘/专项盘点。
    plan_type: Mapped[str] = mapped_column(String(16), default=InventoryPlanType.FULL)
    note: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(
        String(16), default=InventoryPlanStatus.DRAFT, index=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AssetInventoryTask(Base):
    """盘点任务(#48):方案按部门/房间/分类拆分,分派到人,有截止时间。

    范围字段全空 = 全校范围(不限部门/房间/分类);任一字段有值即按该
    字段过滤,多字段为"且"关系。
    """

    __tablename__ = "asset_inventory_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("asset_inventory_plans.id", ondelete="CASCADE"), index=True
    )
    assignee_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    assignee_name: Mapped[str] = mapped_column(String(32), default="")
    scope_dept: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scope_room_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scope_category_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(
        String(16), default=InventoryTaskStatus.PENDING, index=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AssetInventoryRecord(Base):
    """盘点记录(#49):一次扫码/补录一行。

    source:扫码/补录;status:已记录(扫码)/待核实(未贴标补录)。
    范围外扫码不建记录(不静默计入),只记审计。
    """

    __tablename__ = "asset_inventory_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("asset_inventory_tasks.id", ondelete="CASCADE"), index=True
    )
    #: 未贴标补录时为空(资产卡不存在)。
    asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("asset_cards.id", ondelete="SET NULL"), nullable=True, index=True
    )
    label_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: 扫码/补录。
    source: Mapped[str] = mapped_column(String(16), default="扫码")
    #: 已记录/待核实。
    status: Mapped[str] = mapped_column(String(16), default="已记录", index=True)
    #: 现场实盘位置/保管人(与台账比对用)。
    room_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    custodian_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    custodian_name: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: 补录资产的名称/描述/拍照(未贴标资产现场补录拍照)。
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str] = mapped_column(String(500), default="")
    photo_url: Mapped[str | None] = mapped_column(String(256), nullable=True)
    #: 离线暂存后弱网续传的记录为 True(移动端先存本地、联网后调同一接口)。
    is_offline: Mapped[bool] = mapped_column(Boolean, default=False)
    scanned_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AssetInventoryDifference(Base):
    """差异清单(#51/#52):五类差异,按任务/部门/分类查看。

    involves_synced:差异资产是否为已同步资产(只作标注,不自动同步)。
    盘盈补建卡后 acceptance_id 回填 #24 验收单,asset_id 回填新卡。
    """

    __tablename__ = "asset_inventory_differences"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("asset_inventory_plans.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[int] = mapped_column(
        ForeignKey("asset_inventory_tasks.id", ondelete="CASCADE"), index=True
    )
    #: 盘盈(台账无此资产)时为空,补建卡后回填。
    asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("asset_cards.id", ondelete="SET NULL"), nullable=True, index=True
    )
    asset_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    asset_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: 正常/盘亏/盘盈/位置不符/保管人不符。
    diff_type: Mapped[str] = mapped_column(String(16), index=True)
    #: 待处理/已处理(有说明但未走处理动作的仍为待处理,关闭时凭说明放行)。
    status: Mapped[str] = mapped_column(
        String(16), default=InventoryDiffStatus.PENDING, index=True
    )
    detail: Mapped[str] = mapped_column(String(500), default="")
    #: 处理动作/说明:盘亏查责任/盘盈补建卡/位置更正/保管人更正/说明。
    resolution: Mapped[str] = mapped_column(String(500), default="")
    #: 是否涉及已同步资产(只标注,盘点结果不自动同步,见 B5 #98/#100)。
    involves_synced: Mapped[bool] = mapped_column(Boolean, default=False)
    acceptance_id: Mapped[int | None] = mapped_column(
        ForeignKey("asset_acceptances.id", ondelete="SET NULL"), nullable=True
    )
    resolved_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
