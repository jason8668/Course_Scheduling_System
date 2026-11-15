"""资产字典、参数与编码规则 model(学校资产管理系统一期 #17/#79/#81)。

字典与参数一律后台可维护、可配置,不写死在程序里。固定资产确认标准
与审批分级阈值放在 asset_params,数值本身待学校确认(待确认事项 #3/#4)。
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AssetDictionary(Base):
    """通用字典(#81):取得方式、资金来源、处置类型、资产状态等后台可维护。"""

    __tablename__ = "asset_dictionaries"
    __table_args__ = (
        UniqueConstraint("dict_type", "code", name="uq_asset_dict_type_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    #: 字典类型:acquire_method / funding_source / disposal_type / asset_status
    #: / borrow_status。
    dict_type: Mapped[str] = mapped_column(String(32), index=True)
    code: Mapped[str] = mapped_column(String(32))
    label: Mapped[str] = mapped_column(String(64))
    #: True = 系统内置值,不可删除(可停用);False = 学校自增。
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssetParam(Base):
    """可配置参数(#79/#81):确认标准、分级审批阈值、审批超时等。

    值一律存字串,由调用方按 value_type 转换;阈值数字本身可配置,
    记为待学校确认(待确认事项 #3/#4)。
    """

    __tablename__ = "asset_params"
    __table_args__ = (UniqueConstraint("key", name="uq_asset_params_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[str] = mapped_column(String(256), default="")
    value_type: Mapped[str] = mapped_column(String(16), default="string")
    description: Mapped[str] = mapped_column(String(256), default="")
    updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AssetCodeRule(Base):
    """资产编码规则(#17):前缀/年份/流水位做成可配置参数。

    默认规则:前缀 ZC + 年份(4位) + 分类段 + 4位流水,
    如 ZC2026A020001。同一时间只有一条 is_active 的规则。
    """

    __tablename__ = "asset_code_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), default="默认规则")
    prefix: Mapped[str] = mapped_column(String(16), default="ZC")
    include_year: Mapped[bool] = mapped_column(Boolean, default=True)
    include_category: Mapped[bool] = mapped_column(Boolean, default=True)
    sequence_width: Mapped[int] = mapped_column(Integer, default=4)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(String(256), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
