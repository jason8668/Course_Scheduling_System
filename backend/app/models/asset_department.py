"""部门字典 model(学校资产管理系统一期补半成品 #76)。

组织架构四级(校区/楼栋/部门/房间)中的部门一级。部门原先是资产卡上
的自由字符串(manage_dept / use_dept),口径靠人工对齐,同义写法
(“教务处”vs“教务”)会漏数;本字典收敛口径,资产卡以 manage_dept_id /
use_dept_id 外键指向字典行,原字符串列保留作兼容与回滚。
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class AssetDepartment(Base):
    """部门字典行。parent_id 自引用,部门下可再分科室/教研组。"""

    __tablename__ = "asset_departments"
    __table_args__ = (
        UniqueConstraint("name", name="uq_asset_departments_name"),
        UniqueConstraint("code", name="uq_asset_departments_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    #: 部门名称,全校唯一,如“教务处”。
    name: Mapped[str] = mapped_column(String(64))
    #: 部门代码,可空唯一,如“JW01”;不填则只按名称认部门。
    code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: 上级部门 id,可空;顶级部门为 None。
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("asset_departments.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    parent: Mapped["AssetDepartment | None"] = relationship(
        "AssetDepartment", remote_side=[id], back_populates="children",
    )
    children: Mapped[list["AssetDepartment"]] = relationship(
        "AssetDepartment", back_populates="parent",
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
