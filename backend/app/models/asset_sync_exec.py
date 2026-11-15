"""同步执行 models(学校资产管理系统一期第 5 批 M13 #92/#97/#102)。

- asset_sync_batches 同步批次:批次号 TB-* 新建体系,与勾选批次 GX-*
  通过 selection_batch_no 关联(一批勾选可分批执行;一批次只含校验通过
  的资产,拦截资产留在待同步池)。
- asset_sync_batch_items 批次明细:逐件结果(待同步/已同步/同步失败)。
- asset_sync_logs 同步日志:勾选/取消/执行/回填全程留痕,无删除接口。
"""

from datetime import datetime

from sqlalchemy import (
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


class AssetSyncBatch(Base):
    """同步批次(#92):一次执行打包一个批次,操作人、时间全程留痕。"""

    __tablename__ = "asset_sync_batches"
    __table_args__ = (
        UniqueConstraint("batch_no", name="uq_asset_sync_batch_no"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    #: 同步批次号 TB-YYYYMMDD-XXXX。
    batch_no: Mapped[str] = mapped_column(String(32), index=True)
    #: 来源勾选批次号 GX-*。
    selection_batch_no: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    #: 待确认 / 已导出 / 已确认。
    status: Mapped[str] = mapped_column(String(16), default="待确认", index=True)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    total_value: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    #: 校验拦截件数(拦截资产留在待同步池)。
    blocked_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    executed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AssetSyncBatchItem(Base):
    """同步批次明细(#97):逐件确认成功/失败,失败标注原因。"""

    __tablename__ = "asset_sync_batch_items"
    __table_args__ = (
        UniqueConstraint("batch_id", "asset_id", name="uq_sync_batch_item"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("asset_sync_batches.id", ondelete="CASCADE"), index=True
    )
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("asset_cards.id", ondelete="RESTRICT"), index=True
    )
    asset_code: Mapped[str] = mapped_column(String(32), default="")
    #: 待同步 / 已同步 / 同步失败。
    status: Mapped[str] = mapped_column(String(16), default="待同步", index=True)
    fail_reason: Mapped[str] = mapped_column(String(500), default="")
    #: 本件回填的官方编号。
    official_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AssetSyncLog(Base):
    """同步日志(#102):谁、何时、哪些资产、批次号、结果;不可删除。"""

    __tablename__ = "asset_sync_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: 动作:勾选同步/取消勾选/校验/生成批次/执行导出/编号回填/结果确认/
    #: 待同步变更清除/积压提醒。
    action: Mapped[str] = mapped_column(String(32), index=True)
    batch_no: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("asset_cards.id", ondelete="SET NULL"), nullable=True, index=True
    )
    asset_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    operator_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    operator_name: Mapped[str] = mapped_column(String(32), default="")
    #: 成功/失败/拦截。
    result: Mapped[str] = mapped_column(String(16), default="成功")
    detail: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
