"""资产分类字典 model(学校资产管理系统一期 #16)。

执行 GB/T 14885-2022 六大类。分类字典随官方口径升级可维护;上报分类
(is_reportable=True)学校不得自行改动代码与名称,只能由系统管理员维护
财务科目对照与排序/启用状态。校内管理标签以 is_reportable=False 的
分类行挂在官方分类之下。

种子数据见 app.services.asset_seed.SEED_CATEGORIES;一级分类代码与名称
以设计方案第 9 章为准,二级及以下为示例种子,须以学校当期官方模板核定
后冻结为 V1 版(待确认事项 #5)。
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

#: GB/T 14885-2022 六大类(设计方案 §9.1,功能点 #16)。
TOP_LEVEL_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("A01", "房屋和构筑物"),
    ("A02", "设备"),
    ("A03", "文物和陈列品"),
    ("A04", "图书和档案"),
    ("A05", "家具和用具"),
    ("A06", "特种动植物"),
)


class AssetCategory(Base):
    __tablename__ = "asset_categories"
    __table_args__ = (UniqueConstraint("code", name="uq_asset_categories_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    #: 分类代码,如 A01 / A0201 / A020101。层级以代码前缀表达。
    code: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[str] = mapped_column(String(64))
    #: 级别 1-4。
    level: Mapped[int] = mapped_column(Integer, default=1)
    parent_code: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    #: True = 上报分类(与官方口径一致,代码与名称锁定,学校不得自行改动)。
    is_reportable: Mapped[bool] = mapped_column(Boolean, default=True)
    #: 种子来源:gbt14885(六大类)/seed(示例种子,待官方模板核定)/school(校内标签)。
    origin: Mapped[str] = mapped_column(String(16), default="seed")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AssetCategoryFinanceMap(Base):
    """资产分类—财务科目对照表(#16)。

    对照关系做成可配置映射表,不写死在程序里。建卡选一次分类,实物口径
    与财务口径自动对应。财务科目口径以学校财务制度为准,种子为示意值,
    须财务核定后冻结。
    """

    __tablename__ = "asset_category_finance_map"
    __table_args__ = (
        UniqueConstraint(
            "category_code", "finance_subject_code",
            name="uq_asset_finance_map_cat_subject",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    category_code: Mapped[str] = mapped_column(
        ForeignKey("asset_categories.code", ondelete="CASCADE"), index=True
    )
    finance_subject_code: Mapped[str] = mapped_column(String(32))
    finance_subject_name: Mapped[str] = mapped_column(String(64))
    is_default: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str] = mapped_column(String(256), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
