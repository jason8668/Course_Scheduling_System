"""处置与报废 models(学校资产管理系统一期第 5 批 M8 #54~#58)。

- asset_disposal_orders 处置单:七类处置(报废/报损/丢失赔偿/无偿划转/
  出售出让/置换/捐赠转出),材料清单按类型可配置(参数 disposal.materials),
  缺材料不得提交。处置单本身不改资产状态:资产须先经 transition 转入
  待处置;鉴定结论"可继续使用"时处置单关闭、资产回在库/在用。
- asset_disposal_appraisals 技术鉴定单:处置前置,鉴定人员 asset_inspector。
- asset_disposal_packages 官方申报材料包:仅对已手动选择的处置单生成(#57/#99)。
- asset_disposal_recoveries 回收交接单:核销后生成,编号封存复用 B1 逻辑。

处置单号前缀 CZ-,鉴定单号 JD-,申报包号 SB-,回收交接单号 HS-。
处置审批走 B1 通用审批流 doc_type=处置单,金额取资产原值。
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


#: 七类处置类型(字典 disposal_type 已在 B1 播种,值与之一致)。
DISPOSAL_TYPES: dict[str, str] = {
    "scrap": "报废",
    "damage": "报损",
    "loss_compensation": "丢失赔偿",
    "free_transfer": "无偿划转",
    "sale": "出售出让",
    "exchange": "置换",
    "donation_out": "捐赠转出",
}

#: 处置单状态。
DISPOSAL_STATUSES = (
    "待鉴定", "待审批", "审批通过", "已退回", "已关闭",
    "待官方批复", "已批复", "已核销",
)


class AssetDisposalOrder(Base):
    """处置单(#54/#56/#57/#58)。"""

    __tablename__ = "asset_disposal_orders"
    __table_args__ = (
        UniqueConstraint("doc_no", name="uq_asset_disposal_doc_no"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    #: 处置单号 CZ-YYYYMMDD-XXXX。
    doc_no: Mapped[str] = mapped_column(String(32), index=True)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("asset_cards.id", ondelete="RESTRICT"), index=True
    )
    disposal_type: Mapped[str] = mapped_column(String(32), index=True)
    #: 处置原因/说明。
    reason: Mapped[str] = mapped_column(String(500), default="")
    #: 本单提交的材料清单(JSON list);创建时校验须覆盖按类型要求的材料。
    materials: Mapped[list] = mapped_column(JSON, default=list)
    #: 创建时按类型快照的应交材料清单(JSON list),供事后核对。
    materials_required: Mapped[list] = mapped_column(JSON, default=list)
    #: 处置前资产状态(鉴定"可继续使用"时据此回状态:在库/在用)。
    status_before: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="待鉴定", index=True)
    #: 通用审批流实例。
    approval_instance_id: Mapped[int | None] = mapped_column(
        ForeignKey("asset_approval_instances.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: 是否手动选择生成官方申报材料包(#57/#99);未选择只做校内审批。
    selected_for_official: Mapped[bool] = mapped_column(Boolean, default=False)
    selected_for_official_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    selected_for_official_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: 官方批复回填:批复文号与批复日期;未回填不得核销(#58)。
    official_reply_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    official_reply_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AssetDisposalAppraisal(Base):
    """处置前技术鉴定单(#55):一单一次鉴定,鉴定单留存。"""

    __tablename__ = "asset_disposal_appraisals"
    __table_args__ = (
        UniqueConstraint("disposal_id", name="uq_asset_appraisal_disposal"),
        UniqueConstraint("doc_no", name="uq_asset_appraisal_doc_no"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    #: 鉴定单号 JD-YYYYMMDD-XXXX。
    doc_no: Mapped[str] = mapped_column(String(32), index=True)
    disposal_id: Mapped[int] = mapped_column(
        ForeignKey("asset_disposal_orders.id", ondelete="CASCADE"), index=True
    )
    inspector_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    inspector_name: Mapped[str] = mapped_column(String(32), default="")
    #: 结论:可继续使用 / 建议处置 / 建议报废。
    conclusion: Mapped[str] = mapped_column(String(16), index=True)
    detail: Mapped[str] = mapped_column(String(1000), default="")
    appraised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssetDisposalPackage(Base):
    """官方申报材料包(#57):材料清单 + 资产卡数据 + 鉴定单 + 审批记录的
    汇总记录;文件本体为导出的 Excel 清单(接口返回下载),本表只存摘要。"""

    __tablename__ = "asset_disposal_packages"
    __table_args__ = (
        UniqueConstraint("package_no", name="uq_asset_disposal_package_no"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    #: 材料包号 SB-YYYYMMDD-XXXX。
    package_no: Mapped[str] = mapped_column(String(32), index=True)
    disposal_id: Mapped[int] = mapped_column(
        ForeignKey("asset_disposal_orders.id", ondelete="CASCADE"), index=True
    )
    #: 包内摘要(JSON):材料清单、资产卡关键字段、鉴定结论、审批记录。
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    asset_count: Mapped[int] = mapped_column(Integer, default=1)
    total_value: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="已生成", index=True)
    generated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssetDisposalRecovery(Base):
    """回收交接单(#58):核销后生成,回收单位、交接影像、残值收入凭证归档。"""

    __tablename__ = "asset_disposal_recoveries"
    __table_args__ = (
        UniqueConstraint("disposal_id", name="uq_asset_recovery_disposal"),
        UniqueConstraint("recovery_no", name="uq_asset_recovery_no"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    #: 回收交接单号 HS-YYYYMMDD-XXXX。
    recovery_no: Mapped[str] = mapped_column(String(32), index=True)
    disposal_id: Mapped[int] = mapped_column(
        ForeignKey("asset_disposal_orders.id", ondelete="CASCADE"), index=True
    )
    recovery_org: Mapped[str] = mapped_column(String(128), default="")
    #: 残值收入(元)。
    residual_income: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    #: 残值收入凭证号。
    voucher_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: 交接影像 URL 清单(JSON list)。
    photo_urls: Mapped[list] = mapped_column(JSON, default=list)
    #: 待交接 / 已交接。
    status: Mapped[str] = mapped_column(String(16), default="待交接", index=True)
    handover_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
