"""对接字段映射配置 model(学校资产管理系统一期 #104,M13 边界)。

校内字段→官方字段映射表,后台可维护,不写死程序。分类代码直接映射,
特性字段按分类模板启用。映射适用于已勾选同步的资产。
官方模板版本以学校当期模板为准;学校提供模板版本后冻结为 V1 版
(待确认事项 #5)。本批只建映射配置表与适配层占位,不写任何真实
官方接口调用(浙江省资产云未向单个学校开放实时 API)。
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AssetFieldMapping(Base):
    __tablename__ = "asset_field_mappings"
    __table_args__ = (
        UniqueConstraint(
            "local_field", "official_template_version",
            name="uq_asset_field_map_local_version",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    #: 校内字段名,如 asset_code / name / category_code。
    local_field: Mapped[str] = mapped_column(String(64), index=True)
    #: 官方模板字段名,如 资产编号 / 资产名称 / 资产分类代码。
    official_field: Mapped[str] = mapped_column(String(64))
    #: 官方模板版本;学校提供当期模板后冻结。种子值"当期模板"为占位。
    official_template_version: Mapped[str] = mapped_column(String(32), default="当期模板")
    #: 值域转换/校验规则说明,如"金额单位:元;资金来源代码值域转换"。
    transform_rule: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str] = mapped_column(String(256), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
