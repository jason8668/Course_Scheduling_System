"""学校资产管理系统一期第 5 批(处置报废 #54~#58 + 对接导出/编号回填/财务衔接)。

- 新建处置单/鉴定单/申报材料包/回收交接单四张表。
- 新建同步批次/批次明细/同步日志三张表。
- 种子处置审批流(部门初审 → 资产管理员 → 金额 ≥5000 元时分管领导,
  与通用/维修流同一节点结构;金额口径为资产原值)。
- 新增可配置参数:disposal.materials(七类处置材料清单 JSON)、
  sync.backlog_days(待同步积压提醒阈值,默认 14 天)。
- 不改已有迁移与已有表语义;不写任何真实官方接口调用;不含学校真实数据。

Revision ID: 0043_asset_disposal_sync
Revises: 0042_asset_repair_inventory
"""

import json

import sqlalchemy as sa

from alembic import op

revision = "0043_asset_disposal_sync"
down_revision = "0042_asset_repair_inventory"
branch_labels = None
depends_on = None

_DISPOSAL_MATERIALS = {
    "scrap": ["技术鉴定单", "资产卡片", "购置凭证"],
    "damage": ["技术鉴定单", "报损说明", "资产卡片"],
    "loss_compensation": ["丢失情况说明", "赔偿凭证/协议", "资产卡片"],
    "free_transfer": ["划转协议", "接收单位函", "资产卡片"],
    "sale": ["评估报告", "出售方案", "资产卡片"],
    "exchange": ["置换协议", "评估报告", "资产卡片"],
    "donation_out": ["捐赠协议", "接收单位函", "资产卡片"],
}


def upgrade() -> None:
    # ── 处置单(#54/#56/#57/#58) ──
    op.create_table(
        "asset_disposal_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("doc_no", sa.String(32), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("disposal_type", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(500), server_default="", nullable=False),
        sa.Column("materials", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("materials_required", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("status_before", sa.String(16), nullable=True),
        sa.Column("status", sa.String(16), server_default="待鉴定", nullable=False),
        sa.Column("approval_instance_id", sa.Integer(), nullable=True),
        sa.Column("selected_for_official", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("selected_for_official_by", sa.Integer(), nullable=True),
        sa.Column("selected_for_official_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("official_reply_no", sa.String(64), nullable=True),
        sa.Column("official_reply_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["asset_cards.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approval_instance_id"], ["asset_approval_instances.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["selected_for_official_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("doc_no", name="uq_asset_disposal_doc_no"),
    )
    op.create_index("ix_asset_disposal_orders_doc_no", "asset_disposal_orders", ["doc_no"])
    op.create_index("ix_asset_disposal_orders_asset_id", "asset_disposal_orders", ["asset_id"])
    op.create_index("ix_asset_disposal_orders_status", "asset_disposal_orders", ["status"])

    # ── 技术鉴定单(#55) ──
    op.create_table(
        "asset_disposal_appraisals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("doc_no", sa.String(32), nullable=False),
        sa.Column("disposal_id", sa.Integer(), nullable=False),
        sa.Column("inspector_id", sa.Integer(), nullable=True),
        sa.Column("inspector_name", sa.String(32), server_default="", nullable=False),
        sa.Column("conclusion", sa.String(16), nullable=False),
        sa.Column("detail", sa.String(1000), server_default="", nullable=False),
        sa.Column("appraised_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["disposal_id"], ["asset_disposal_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["inspector_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("disposal_id", name="uq_asset_appraisal_disposal"),
        sa.UniqueConstraint("doc_no", name="uq_asset_appraisal_doc_no"),
    )
    op.create_index("ix_asset_disposal_appraisals_doc_no", "asset_disposal_appraisals", ["doc_no"])

    # ── 官方申报材料包(#57) ──
    op.create_table(
        "asset_disposal_packages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("package_no", sa.String(32), nullable=False),
        sa.Column("disposal_id", sa.Integer(), nullable=False),
        sa.Column("summary", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("asset_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("total_value", sa.Numeric(14, 2), nullable=True),
        sa.Column("status", sa.String(16), server_default="已生成", nullable=False),
        sa.Column("generated_by", sa.Integer(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["disposal_id"], ["asset_disposal_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["generated_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("package_no", name="uq_asset_disposal_package_no"),
    )
    op.create_index("ix_asset_disposal_packages_package_no", "asset_disposal_packages", ["package_no"])

    # ── 回收交接单(#58) ──
    op.create_table(
        "asset_disposal_recoveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("recovery_no", sa.String(32), nullable=False),
        sa.Column("disposal_id", sa.Integer(), nullable=False),
        sa.Column("recovery_org", sa.String(128), server_default="", nullable=False),
        sa.Column("residual_income", sa.Numeric(14, 2), nullable=True),
        sa.Column("voucher_no", sa.String(64), nullable=True),
        sa.Column("photo_urls", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("status", sa.String(16), server_default="待交接", nullable=False),
        sa.Column("handover_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["disposal_id"], ["asset_disposal_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("disposal_id", name="uq_asset_recovery_disposal"),
        sa.UniqueConstraint("recovery_no", name="uq_asset_recovery_no"),
    )
    op.create_index("ix_asset_disposal_recoveries_recovery_no", "asset_disposal_recoveries", ["recovery_no"])

    # ── 同步批次(#92) ──
    op.create_table(
        "asset_sync_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_no", sa.String(32), nullable=False),
        sa.Column("selection_batch_no", sa.String(32), nullable=True),
        sa.Column("status", sa.String(16), server_default="待确认", nullable=False),
        sa.Column("total_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_value", sa.Numeric(14, 2), nullable=True),
        sa.Column("blocked_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("executed_by", sa.Integer(), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.String(500), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["executed_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("batch_no", name="uq_asset_sync_batch_no"),
    )
    op.create_index("ix_asset_sync_batches_batch_no", "asset_sync_batches", ["batch_no"])
    op.create_index("ix_asset_sync_batches_status", "asset_sync_batches", ["status"])

    # ── 同步批次明细(#97) ──
    op.create_table(
        "asset_sync_batch_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("asset_code", sa.String(32), server_default="", nullable=False),
        sa.Column("status", sa.String(16), server_default="待同步", nullable=False),
        sa.Column("fail_reason", sa.String(500), server_default="", nullable=False),
        sa.Column("official_code", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["asset_sync_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["asset_cards.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("batch_id", "asset_id", name="uq_sync_batch_item"),
    )
    op.create_index("ix_asset_sync_batch_items_batch_id", "asset_sync_batch_items", ["batch_id"])
    op.create_index("ix_asset_sync_batch_items_asset_id", "asset_sync_batch_items", ["asset_id"])

    # ── 同步日志(#102,无删除接口) ──
    op.create_table(
        "asset_sync_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("batch_no", sa.String(32), nullable=True),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("asset_code", sa.String(32), nullable=True),
        sa.Column("operator_id", sa.Integer(), nullable=True),
        sa.Column("operator_name", sa.String(32), server_default="", nullable=False),
        sa.Column("result", sa.String(16), server_default="成功", nullable=False),
        sa.Column("detail", sa.String(500), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["asset_cards.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["operator_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_asset_sync_logs_batch_no", "asset_sync_logs", ["batch_no"])
    op.create_index("ix_asset_sync_logs_asset_id", "asset_sync_logs", ["asset_id"])
    op.create_index("ix_asset_sync_logs_action", "asset_sync_logs", ["action"])

    _seed_disposal_flow()
    _seed_params()


def _seed_disposal_flow() -> None:
    conn = op.get_bind()
    conn.execute(sa.text(
        "INSERT INTO asset_approval_flows (doc_type, name, nodes, is_active) "
        "SELECT '处置单', '处置审批流', :nodes, 1 "
        "WHERE NOT EXISTS (SELECT 1 FROM asset_approval_flows "
        "WHERE doc_type = '处置单' AND is_active = 1)"
    ), {"nodes": '[{"step": 1, "role": "asset_dept_admin", "mode": "any", "required_approvals": 1},'
                 ' {"step": 2, "role": "asset_admin", "mode": "any", "required_approvals": 1},'
                 ' {"step": 3, "role": "director", "mode": "any", "required_approvals": 1, "min_amount": 5000}]'})


def _seed_params() -> None:
    conn = op.get_bind()
    conn.execute(sa.text(
        "INSERT INTO asset_params (key, value, value_type, description) "
        "SELECT 'disposal.materials', :value, 'json', "
        "'七类处置按类型应交材料清单(JSON:类型代码 → 材料清单),缺材料不得提交' "
        "WHERE NOT EXISTS (SELECT 1 FROM asset_params WHERE key = 'disposal.materials')"
    ), {"value": json.dumps(_DISPOSAL_MATERIALS, ensure_ascii=False)})
    conn.execute(sa.text(
        "INSERT INTO asset_params (key, value, value_type, description) "
        "SELECT 'sync.backlog_days', '14', 'number', "
        "'待同步积压提醒阈值(天):待同步池超过该天数未执行时提醒资产管理员,只提醒不自动执行' "
        "WHERE NOT EXISTS (SELECT 1 FROM asset_params WHERE key = 'sync.backlog_days')"
    ))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text(
        "DELETE FROM asset_approval_flows WHERE doc_type = '处置单'"))
    conn.execute(sa.text(
        "DELETE FROM asset_params WHERE key IN ('disposal.materials', 'sync.backlog_days')"))
    op.drop_table("asset_sync_logs")
    op.drop_table("asset_sync_batch_items")
    op.drop_table("asset_sync_batches")
    op.drop_table("asset_disposal_recoveries")
    op.drop_table("asset_disposal_packages")
    op.drop_table("asset_disposal_appraisals")
    op.drop_table("asset_disposal_orders")
