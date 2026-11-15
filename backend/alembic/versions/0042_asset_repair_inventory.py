"""学校资产管理系统一期第 4 批(维修保养 #42~#44 + 盘点清查 #48/#49/#51/#52)。

- asset_repair_orders 扩展派单/维修方/费用/结果/报修人确认字段(B3 约定,
  不另建维修表);asset_cards 加累计维修费 total_repair_cost(#43)。
- 新建盘点方案/任务/记录/差异清单四张表。
- 种子维修单审批流(部门初审 → 资产管理员 → 金额 ≥5000 元时分管领导,
  与通用流同一节点结构,阈值参数 approval.repair_threshold 已在 0039 播种)。
- 不改已有迁移与已有表语义;不写任何真实官方接口调用;不含学校真实数据。

Revision ID: 0042_asset_repair_inventory
Revises: 0041_asset_circulation
"""

import sqlalchemy as sa

from alembic import op

revision = "0042_asset_repair_inventory"
down_revision = "0041_asset_circulation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 维修占位表扩展(B4 #43,在原表上加字段) ──
    op.add_column("asset_repair_orders", sa.Column("photo_url", sa.String(256), nullable=True))
    op.add_column("asset_repair_orders", sa.Column("assignee_id", sa.Integer(), nullable=True))
    op.add_column("asset_repair_orders", sa.Column("assignee_name", sa.String(32), nullable=True))
    op.add_column("asset_repair_orders", sa.Column("vendor", sa.String(128), server_default="", nullable=False))
    op.add_column("asset_repair_orders", sa.Column("cost", sa.Numeric(14, 2), nullable=True))
    op.add_column("asset_repair_orders", sa.Column("result", sa.String(500), server_default="", nullable=False))
    op.add_column("asset_repair_orders", sa.Column("pre_repair_status", sa.String(16), nullable=True))
    op.add_column("asset_repair_orders", sa.Column("approval_instance_id", sa.Integer(), nullable=True))
    op.add_column("asset_repair_orders", sa.Column("confirmed_by", sa.Integer(), nullable=True))
    op.add_column("asset_repair_orders", sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("asset_repair_orders", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("fk_repair_assignee", "asset_repair_orders", "users", ["assignee_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_repair_approval", "asset_repair_orders", "asset_approval_instances", ["approval_instance_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_repair_confirmed_by", "asset_repair_orders", "users", ["confirmed_by"], ["id"], ondelete="SET NULL")

    # ── 资产卡累计维修费(#43) ──
    op.add_column("asset_cards", sa.Column("total_repair_cost", sa.Numeric(14, 2), server_default="0", nullable=False))

    # ── 盘点方案(#48) ──
    op.create_table(
        "asset_inventory_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_no", sa.String(32), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("plan_type", sa.String(16), server_default="全校盘点", nullable=False),
        sa.Column("note", sa.String(500), server_default="", nullable=False),
        sa.Column("status", sa.String(16), server_default="草稿", nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("plan_no", name="uq_asset_inventory_plan_no"),
    )
    op.create_index("ix_asset_inventory_plans_plan_no", "asset_inventory_plans", ["plan_no"])
    op.create_index("ix_asset_inventory_plans_status", "asset_inventory_plans", ["status"])

    # ── 盘点任务(#48) ──
    op.create_table(
        "asset_inventory_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("assignee_id", sa.Integer(), nullable=False),
        sa.Column("assignee_name", sa.String(32), server_default="", nullable=False),
        sa.Column("scope_dept", sa.String(64), nullable=True),
        sa.Column("scope_room_name", sa.String(64), nullable=True),
        sa.Column("scope_category_code", sa.String(16), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), server_default="待盘点", nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["asset_inventory_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assignee_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_asset_inventory_tasks_plan_id", "asset_inventory_tasks", ["plan_id"])
    op.create_index("ix_asset_inventory_tasks_assignee_id", "asset_inventory_tasks", ["assignee_id"])
    op.create_index("ix_asset_inventory_tasks_status", "asset_inventory_tasks", ["status"])

    # ── 盘点记录(#49) ──
    op.create_table(
        "asset_inventory_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("label_code", sa.String(40), nullable=True),
        sa.Column("source", sa.String(16), server_default="扫码", nullable=False),
        sa.Column("status", sa.String(16), server_default="已记录", nullable=False),
        sa.Column("room_name", sa.String(64), nullable=True),
        sa.Column("custodian_id", sa.Integer(), nullable=True),
        sa.Column("custodian_name", sa.String(32), nullable=True),
        sa.Column("name", sa.String(128), nullable=True),
        sa.Column("description", sa.String(500), server_default="", nullable=False),
        sa.Column("photo_url", sa.String(256), nullable=True),
        sa.Column("is_offline", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("scanned_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["asset_inventory_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["asset_cards.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["custodian_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["scanned_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_asset_inventory_records_task_id", "asset_inventory_records", ["task_id"])
    op.create_index("ix_asset_inventory_records_asset_id", "asset_inventory_records", ["asset_id"])

    # ── 差异清单(#51/#52) ──
    op.create_table(
        "asset_inventory_differences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("asset_code", sa.String(32), nullable=True),
        sa.Column("asset_name", sa.String(128), nullable=True),
        sa.Column("diff_type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), server_default="待处理", nullable=False),
        sa.Column("detail", sa.String(500), server_default="", nullable=False),
        sa.Column("resolution", sa.String(500), server_default="", nullable=False),
        sa.Column("involves_synced", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("acceptance_id", sa.Integer(), nullable=True),
        sa.Column("resolved_by", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["asset_inventory_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["asset_inventory_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["asset_cards.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["acceptance_id"], ["asset_acceptances.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_asset_inventory_differences_plan_id", "asset_inventory_differences", ["plan_id"])
    op.create_index("ix_asset_inventory_differences_task_id", "asset_inventory_differences", ["task_id"])
    op.create_index("ix_asset_inventory_differences_diff_type", "asset_inventory_differences", ["diff_type"])

    _seed_repair_flow()


def _seed_repair_flow() -> None:
    conn = op.get_bind()
    conn.execute(sa.text(
        "INSERT INTO asset_approval_flows (doc_type, name, nodes, is_active) "
        "SELECT '维修单', '维修审批流', :nodes, 1 "
        "WHERE NOT EXISTS (SELECT 1 FROM asset_approval_flows "
        "WHERE doc_type = '维修单' AND is_active = 1)"
    ), {"nodes": '[{"step": 1, "role": "asset_dept_admin", "mode": "any", "required_approvals": 1},'
                 ' {"step": 2, "role": "asset_admin", "mode": "any", "required_approvals": 1},'
                 ' {"step": 3, "role": "director", "mode": "any", "required_approvals": 1, "min_amount": 5000}]'})


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text(
        "DELETE FROM asset_approval_flows WHERE doc_type = '维修单'"))
    op.drop_table("asset_inventory_differences")
    op.drop_table("asset_inventory_records")
    op.drop_table("asset_inventory_tasks")
    op.drop_table("asset_inventory_plans")
    op.drop_column("asset_cards", "total_repair_cost")
    op.drop_constraint("fk_repair_confirmed_by", "asset_repair_orders", type_="foreignkey")
    op.drop_constraint("fk_repair_approval", "asset_repair_orders", type_="foreignkey")
    op.drop_constraint("fk_repair_assignee", "asset_repair_orders", type_="foreignkey")
    op.drop_column("asset_repair_orders", "closed_at")
    op.drop_column("asset_repair_orders", "confirmed_at")
    op.drop_column("asset_repair_orders", "confirmed_by")
    op.drop_column("asset_repair_orders", "approval_instance_id")
    op.drop_column("asset_repair_orders", "pre_repair_status")
    op.drop_column("asset_repair_orders", "result")
    op.drop_column("asset_repair_orders", "cost")
    op.drop_column("asset_repair_orders", "vendor")
    op.drop_column("asset_repair_orders", "assignee_name")
    op.drop_column("asset_repair_orders", "assignee_id")
    op.drop_column("asset_repair_orders", "photo_url")
