"""通用审批流 model(学校资产管理系统一期 #5/#79/#80)。

所有业务单据共用同一套审批流:流程定义(节点、会签/或签、金额门槛)
+ 流程实例 + 节点实例。不为每个单据各写一套审批。
超时提醒:实例带 deadline,超时只打 is_overdue 待办标记,不自动流转;
定时推送接入后续批次。
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
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ApprovalFlow(Base):
    """审批流定义:一个 doc_type 一条启用流,节点以 JSON 存配置。

    nodes 示例:
    [{"step": 1, "role": "asset_dept_admin", "mode": "any", "required_approvals": 1},
     {"step": 2, "role": "asset_admin", "mode": "all", "required_approvals": 2},
     {"step": 3, "role": "director", "mode": "any", "required_approvals": 1,
      "min_amount": 5000}]
    mode: any=或签(任一审批人通过即过),all=会签(须满 required_approvals 人)。
    min_amount: 金额门槛,单据金额低于该值时跳过本节点(#79 分级授权)。
    """

    __tablename__ = "asset_approval_flows"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: 单据类型:如 领用/借用/调拨/维修/处置/通用。
    doc_type: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(64))
    nodes: Mapped[list] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ApprovalInstance(Base):
    """审批流程实例:一份单据一次流程。"""

    __tablename__ = "asset_approval_instances"

    id: Mapped[int] = mapped_column(primary_key=True)
    flow_id: Mapped[int] = mapped_column(
        ForeignKey("asset_approval_flows.id", ondelete="RESTRICT"), index=True
    )
    doc_type: Mapped[str] = mapped_column(String(32), index=True)
    #: 通用单据引用:后续批次各单据表的主键。
    doc_id: Mapped[int] = mapped_column(Integer, index=True)
    doc_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    applicant_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    applicant_name: Mapped[str] = mapped_column(String(32), default="")
    amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    #: 进行中/已通过/已退回/已转交/已撤销。
    status: Mapped[str] = mapped_column(String(16), default="进行中", index=True)
    current_step: Mapped[int] = mapped_column(Integer, default=1)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: 超时待办标记(超时提醒配置 + 标记在本批,定时推送后续批次接入)。
    is_overdue: Mapped[bool] = mapped_column(Boolean, default=False)
    overdue_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ApprovalNode(Base):
    """节点实例:一步一节点,会签时 approvals 记已通过的审批人 id 列表。"""

    __tablename__ = "asset_approval_nodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    instance_id: Mapped[int] = mapped_column(
        ForeignKey("asset_approval_instances.id", ondelete="CASCADE"), index=True
    )
    step: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(32))
    mode: Mapped[str] = mapped_column(String(8), default="any")
    required_approvals: Mapped[int] = mapped_column(Integer, default=1)
    approvals: Mapped[list] = mapped_column(JSON, default=list)
    #: 待审批/已通过/已退回/已转交/已跳过。
    status: Mapped[str] = mapped_column(String(16), default="待审批")
    comment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    acted_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    acted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
