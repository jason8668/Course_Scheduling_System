"""资产卡 model(学校资产管理系统一期 #10/#11/#15/#85/#86)。

资产卡四区 + 校内扩展区。扩展区字段一律打上 never_sync 标记,导出
上报时排除(字段名以 ext_ 前缀 + JSON 栏位双重隔离)。
一物一卡一码:一件资产一张卡、一个编号(asset_code)、一个二维码标签码
(label_code = 校内编号 + 校验位);编号终身不变,核销后封存不复用。
"""

import enum
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


class AssetStatus(enum.StrEnum):
    """资产状态(#15)。只能由业务单据驱动,禁止手工直接改状态。"""

    in_stock = "在库"
    in_use = "在用"
    lent = "借出"
    repairing = "维修中"
    pending_disposal = "待处置"
    retired = "已核销"


class SyncStatus(enum.StrEnum):
    """同步状态(#86)。默认 未同步(#85),系统任何地方不得自动同步。

    同步中 仅由后续批次的同步执行使用,本批只定义枚举值,不产生该状态。
    """

    unsynced = "未同步"
    pending = "待同步"
    syncing = "同步中"
    synced = "已同步"
    failed = "同步失败"
    cancelled = "已取消同步"


class BorrowStatus(enum.StrEnum):
    """领用/借用状态(使用信息区)。"""

    not_issued = "未领用"
    issued = "已领用"
    lent = "借出"
    returned = "已归还"


class AssetCard(Base):
    __tablename__ = "asset_cards"
    __table_args__ = (
        UniqueConstraint("asset_code", name="uq_asset_cards_code"),
        UniqueConstraint("label_code", name="uq_asset_cards_label"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    # ── 基本信息区 ──
    #: 校内编号,终身不变。按可配置编码规则生成(#17)。
    asset_code: Mapped[str] = mapped_column(String(32), index=True)
    #: 官方编号,初始为空;官方导入成功后回填,双号索引查询(#17/#96)。
    official_code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    #: 二维码标签码 = 校内编号 + 校验位(#11)。
    label_code: Mapped[str] = mapped_column(String(40), index=True)
    name: Mapped[str] = mapped_column(String(128))
    category_code: Mapped[str] = mapped_column(
        ForeignKey("asset_categories.code", ondelete="RESTRICT"), index=True
    )
    spec_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    unit: Mapped[str] = mapped_column(String(16), default="件")
    acquired_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: 取得方式,值域见 asset_dictionaries(acquire_method)。
    acquire_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    supplier: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # ── 财务信息区 ──
    original_value: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    #: 资金来源,值域见 asset_dictionaries(funding_source)。
    funding_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    voucher_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    depreciation_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    depreciation_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    accumulated_depreciation: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    net_value: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)

    # ── 使用信息区 ──
    status: Mapped[str] = mapped_column(String(16), default=AssetStatus.in_stock.value, index=True)
    manage_dept: Mapped[str | None] = mapped_column(String(64), nullable=True)
    use_dept: Mapped[str | None] = mapped_column(String(64), nullable=True)
    custodian_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: 保管人姓名快照(保管人离职删号后仍可追溯)。
    custodian_name: Mapped[str | None] = mapped_column(String(32), nullable=True)
    campus: Mapped[str | None] = mapped_column(String(32), nullable=True)
    building: Mapped[str | None] = mapped_column(String(32), nullable=True)
    room_id: Mapped[int | None] = mapped_column(
        ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True, index=True
    )
    room_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    borrow_status: Mapped[str] = mapped_column(
        String(16), default=BorrowStatus.not_issued.value
    )

    # ── 特性信息区 ──
    #: 按分类模板启用的特性字段(JSON):房屋面积与权证号、车辆车牌与行驶证、
    #: 信息化设备序列号/IP、仪器精度等级等。模板见 services.asset_foundation。
    attributes: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # ── 校内扩展区(never_sync:导出上报时排除) ──
    #: 扩展区 JSON,键一律为校内字段:photo_url、warranty_until、maintenance_contract、
    #: school_tags、room_package、remark 等。绝不进入上报导出。
    ext: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # ── 同步状态(#85/#86) ──
    sync_status: Mapped[str] = mapped_column(
        String(16), default=SyncStatus.unsynced.value, index=True
    )
    #: 待同步变更标记(#37/#98,第 3 批):已同步资产发生调拨等变更后置 True,
    #: 仅作提示,不自动同步;B5 手动勾选再同步后由同步执行清掉。
    pending_sync_change: Mapped[bool] = mapped_column(Boolean, default=False)
    pending_sync_change_reason: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )

    # ── 核销封存(#11) ──
    is_retired: Mapped[bool] = mapped_column(Boolean, default=False)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── 第 2 批:入库批次/验收/入账/闲置(#26/#27/#14) ──
    #: 入库批次号,如 RK20261115-0001;批量建卡时同一批共用。
    batch_no: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    #: 验收单(本批建卡的来源验收单)。
    acceptance_id: Mapped[int | None] = mapped_column(
        ForeignKey("asset_acceptances.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: 正式入账标志(#27):财务回填入账凭证号后才为 True;未回填禁止同步。
    is_booked: Mapped[bool] = mapped_column(Boolean, default=False)
    booked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: 最近使用时间(领用/借用/盘点时更新,供闲置识别参考)。
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: 闲置标记(#14):仅由刷新任务计算写入,不手工打标记。
    is_idle: Mapped[bool] = mapped_column(Boolean, default=False)
    idle_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # ── 第 4 批:维修费用累计(#43) ──
    #: 累计维修费(元):工单报修人确认关闭时把本次费用累加进来,供后续
    #: 维修经济性分析查询;经济性预警本身是二期 #46,本批只累计、不预警。
    total_repair_cost: Mapped[float] = mapped_column(
        Numeric(14, 2), default=0, server_default="0"
    )

    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AssetRoomExtension(Base):
    """房间扩展表(#76):补齐现有教室表没有的楼栋与房间资产包归属。

    复用智慧教务 rooms 表,不另建组织表;一间教室一行扩展,存放地点
    以 campus-楼栋-房间 四级表达,房间资产包归属(如实验室仪器包、
    宿舍成套家具)记在这里。
    """

    __tablename__ = "asset_room_extensions"
    __table_args__ = (UniqueConstraint("room_id", name="uq_asset_room_ext_room"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(
        ForeignKey("rooms.id", ondelete="CASCADE"), index=True
    )
    campus: Mapped[str | None] = mapped_column(String(32), nullable=True)
    building: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: 房间资产包归属,如"化学实验室仪器包 / 3号宿舍楼成套家具"。
    asset_package: Mapped[str | None] = mapped_column(String(128), nullable=True)
    note: Mapped[str] = mapped_column(String(256), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
