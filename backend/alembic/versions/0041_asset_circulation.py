"""学校资产管理系统一期第 3 批(领用借用 + 调拨移交 + 个人工作台)。

新建领用单、借用单、预约单、归还单、团体保管单、调拨单、移交单
及明细、维修占位单、提醒记录表;asset_cards 加待同步变更标记列
(pending_sync_change / pending_sync_change_reason,供 B5 #98)。
种子参数与领用/调拨审批流用 NOT EXISTS 守卫插入(幂等,种子已跑过
的库不重复)。不改已有迁移与已有表语义;不写任何真实官方接口调用;
不含学校真实数据。

Revision ID: 0041_asset_circulation
Revises: 0040_asset_ledger_intake
"""

import sqlalchemy as sa

from alembic import op

revision = "0041_asset_circulation"
down_revision = "0040_asset_ledger_intake"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "asset_issue_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("doc_no", sa.String(32), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("applicant_id", sa.Integer(), nullable=False),
        sa.Column("applicant_name", sa.String(32), server_default="", nullable=False),
        sa.Column("use_dept", sa.String(64), nullable=True),
        sa.Column("reason", sa.String(500), server_default="", nullable=False),
        sa.Column("status", sa.String(16), server_default="申请中", nullable=False),
        sa.Column("approval_instance_id", sa.Integer(), nullable=True),
        sa.Column("issued_by", sa.Integer(), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["asset_cards.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["applicant_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approval_instance_id"], ["asset_approval_instances.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["issued_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("doc_no", name="uq_asset_issue_doc_no"),
    )
    op.create_index("ix_asset_issue_orders_doc_no", "asset_issue_orders", ["doc_no"])
    op.create_index("ix_asset_issue_orders_asset_id", "asset_issue_orders", ["asset_id"])
    op.create_index("ix_asset_issue_orders_applicant_id", "asset_issue_orders", ["applicant_id"])
    op.create_index("ix_asset_issue_orders_status", "asset_issue_orders", ["status"])

    op.create_table(
        "asset_borrow_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("doc_no", sa.String(32), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("borrower_id", sa.Integer(), nullable=False),
        sa.Column("borrower_name", sa.String(32), server_default="", nullable=False),
        sa.Column("reason", sa.String(500), server_default="", nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), server_default="借用中", nullable=False),
        sa.Column("is_overdue", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("overdue_days", sa.Integer(), server_default="0", nullable=False),
        sa.Column("escalated", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("reminded_before_due", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("returned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["asset_cards.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["borrower_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("doc_no", name="uq_asset_borrow_doc_no"),
    )
    op.create_index("ix_asset_borrow_orders_doc_no", "asset_borrow_orders", ["doc_no"])
    op.create_index("ix_asset_borrow_orders_asset_id", "asset_borrow_orders", ["asset_id"])
    op.create_index("ix_asset_borrow_orders_borrower_id", "asset_borrow_orders", ["borrower_id"])
    op.create_index("ix_asset_borrow_orders_status", "asset_borrow_orders", ["status"])
    op.create_index("ix_asset_borrow_orders_due_at", "asset_borrow_orders", ["due_at"])

    op.create_table(
        "asset_reservations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("doc_no", sa.String(32), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("reserver_id", sa.Integer(), nullable=False),
        sa.Column("reserver_name", sa.String(32), server_default="", nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purpose", sa.String(500), server_default="", nullable=False),
        sa.Column("status", sa.String(16), server_default="待领用", nullable=False),
        sa.Column("borrow_order_id", sa.Integer(), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["asset_cards.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reserver_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["borrow_order_id"], ["asset_borrow_orders.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("doc_no", name="uq_asset_reservation_doc_no"),
    )
    op.create_index("ix_asset_reservations_doc_no", "asset_reservations", ["doc_no"])
    op.create_index("ix_asset_reservations_asset_id", "asset_reservations", ["asset_id"])
    op.create_index("ix_asset_reservations_status", "asset_reservations", ["status"])

    op.create_table(
        "asset_repair_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("doc_no", sa.String(32), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(16), server_default="归还验收", nullable=False),
        sa.Column("source_doc_no", sa.String(32), nullable=True),
        sa.Column("reporter_id", sa.Integer(), nullable=True),
        sa.Column("reporter_name", sa.String(32), server_default="", nullable=False),
        sa.Column("description", sa.String(500), server_default="", nullable=False),
        sa.Column("status", sa.String(16), server_default="待处理", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["asset_cards.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reporter_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("doc_no", name="uq_asset_repair_doc_no"),
    )
    op.create_index("ix_asset_repair_orders_doc_no", "asset_repair_orders", ["doc_no"])
    op.create_index("ix_asset_repair_orders_asset_id", "asset_repair_orders", ["asset_id"])

    op.create_table(
        "asset_return_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("doc_no", sa.String(32), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("source_doc_type", sa.String(16), server_default="借用单", nullable=False),
        sa.Column("source_doc_id", sa.Integer(), nullable=True),
        sa.Column("returner_id", sa.Integer(), nullable=False),
        sa.Column("returner_name", sa.String(32), server_default="", nullable=False),
        sa.Column("status", sa.String(16), server_default="待验收", nullable=False),
        sa.Column("result", sa.String(16), nullable=True),
        sa.Column("damage_note", sa.String(500), server_default="", nullable=False),
        sa.Column("repair_order_id", sa.Integer(), nullable=True),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["asset_cards.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["returner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["repair_order_id"], ["asset_repair_orders.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("doc_no", name="uq_asset_return_doc_no"),
    )
    op.create_index("ix_asset_return_orders_doc_no", "asset_return_orders", ["doc_no"])
    op.create_index("ix_asset_return_orders_asset_id", "asset_return_orders", ["asset_id"])
    op.create_index("ix_asset_return_orders_status", "asset_return_orders", ["status"])

    op.create_table(
        "asset_group_custodies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("doc_no", sa.String(32), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("group_type", sa.String(16), server_default="班级", nullable=False),
        sa.Column("group_name", sa.String(64), nullable=False),
        sa.Column("group_ref_id", sa.Integer(), nullable=True),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("teacher_name", sa.String(32), server_default="", nullable=False),
        sa.Column("note", sa.String(500), server_default="", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["asset_cards.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["group_ref_id"], ["class_units.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["teacher_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("doc_no", name="uq_asset_group_custody_doc_no"),
    )
    op.create_index("ix_asset_group_custodies_doc_no", "asset_group_custodies", ["doc_no"])
    op.create_index("ix_asset_group_custodies_asset_id", "asset_group_custodies", ["asset_id"])

    op.create_table(
        "asset_transfer_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("doc_no", sa.String(32), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("from_dept", sa.String(64), nullable=True),
        sa.Column("to_dept", sa.String(64), nullable=False),
        sa.Column("to_custodian_id", sa.Integer(), nullable=True),
        sa.Column("to_custodian_name", sa.String(32), nullable=True),
        sa.Column("to_room_name", sa.String(64), nullable=True),
        sa.Column("reason", sa.String(500), server_default="", nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("status", sa.String(16), server_default="待调入确认", nullable=False),
        sa.Column("approval_instance_id", sa.Integer(), nullable=True),
        sa.Column("in_confirmed_by", sa.Integer(), nullable=True),
        sa.Column("in_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["asset_cards.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["to_custodian_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approval_instance_id"], ["asset_approval_instances.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["in_confirmed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("doc_no", name="uq_asset_transfer_doc_no"),
    )
    op.create_index("ix_asset_transfer_orders_doc_no", "asset_transfer_orders", ["doc_no"])
    op.create_index("ix_asset_transfer_orders_asset_id", "asset_transfer_orders", ["asset_id"])
    op.create_index("ix_asset_transfer_orders_status", "asset_transfer_orders", ["status"])

    op.create_table(
        "asset_handover_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("doc_no", sa.String(32), nullable=False),
        sa.Column("from_user_id", sa.Integer(), nullable=False),
        sa.Column("from_user_name", sa.String(32), server_default="", nullable=False),
        sa.Column("to_user_id", sa.Integer(), nullable=False),
        sa.Column("to_user_name", sa.String(32), server_default="", nullable=False),
        sa.Column("reason_type", sa.String(16), server_default="离职", nullable=False),
        sa.Column("status", sa.String(16), server_default="待移交", nullable=False),
        sa.Column("is_overdue", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["from_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["to_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("doc_no", name="uq_asset_handover_doc_no"),
    )
    op.create_index("ix_asset_handover_orders_doc_no", "asset_handover_orders", ["doc_no"])
    op.create_index("ix_asset_handover_orders_status", "asset_handover_orders", ["status"])

    op.create_table(
        "asset_handover_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("handover_id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("asset_code", sa.String(32), server_default="", nullable=False),
        sa.Column("status", sa.String(16), server_default="待确认", nullable=False),
        sa.Column("confirmed_by", sa.Integer(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["handover_id"], ["asset_handover_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["asset_cards.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["confirmed_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_asset_handover_items_handover_id", "asset_handover_items", ["handover_id"])
    op.create_index("ix_asset_handover_items_asset_id", "asset_handover_items", ["asset_id"])

    op.create_table(
        "asset_reminders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("target_type", sa.String(32), server_default="", nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("content", sa.String(500), server_default="", nullable=False),
        sa.Column("level", sa.String(16), server_default="一般", nullable=False),
        sa.Column("is_read", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_dingtalk_sent", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_asset_reminders_kind", "asset_reminders", ["kind"])
    op.create_index("ix_asset_reminders_user_id", "asset_reminders", ["user_id"])
    op.create_index("ix_asset_reminders_target_id", "asset_reminders", ["target_id"])

    op.add_column("asset_cards", sa.Column("pending_sync_change", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("asset_cards", sa.Column("pending_sync_change_reason", sa.String(128), nullable=True))

    _seed_params_and_flows()


def _seed_params_and_flows() -> None:
    conn = op.get_bind()
    params = [
        ("asset.borrow.reminder_days_before", "1", "number",
         "借用到期提醒:到期前多少天提醒(天),默认 1 天,可配置(#32)"),
        ("asset.borrow.overdue_escalation_days", "3", "number",
         "借用逾期升级:逾期满多少天升级提醒到资产管理员(天),默认 3 天,可配置(#32)"),
        ("asset.handover.overdue_days", "7", "number",
         "未办结移交预警:超多少天预警(天),默认 7 天,可配置(#40)"),
        ("asset.warranty.reminder_days", "30", "number",
         "保修到期提醒:到期前多少天提醒(天),默认 30 天,可配置(#3)"),
    ]
    for key, value, vtype, desc in params:
        # Postgres 要求同一参数在 SELECT 列表和 WHERE 里推断出的类型一致:
        # :key 不加 CAST 时 SELECT 侧推成 text、WHERE 侧按 key 列推成
        # varchar,报 AmbiguousParameter(inconsistent types deduced for
        # parameter $1, text versus character varying),迁移直接失败、
        # api 容器起不来(SQLite 不校验类型,所以本地测试没暴露)。
        # 各参数按目标列显式 CAST,与列定义一致(key 64/value 256/
        # value_type 16/description 256);CAST 在 SQLite 里也是合法的。
        conn.execute(sa.text(
            "INSERT INTO asset_params (key, value, value_type, description) "
            "SELECT CAST(:key AS varchar(64)), CAST(:value AS varchar(256)), "
            "CAST(:vtype AS varchar(16)), CAST(:desc AS varchar(256)) "
            "WHERE NOT EXISTS (SELECT 1 FROM asset_params WHERE key = :key)"
        ), {"key": key, "value": value, "vtype": vtype, "desc": desc})
    flows = [
        ("领用单", "领用审批流",
         '[{"step": 1, "role": "asset_dept_admin", "mode": "any", "required_approvals": 1},'
         ' {"step": 2, "role": "asset_admin", "mode": "any", "required_approvals": 1},'
         ' {"step": 3, "role": "director", "mode": "any", "required_approvals": 1, "min_amount": 5000}]'),
        ("调拨单", "调拨审批流",
         '[{"step": 1, "role": "asset_dept_admin", "mode": "any", "required_approvals": 1},'
         ' {"step": 2, "role": "asset_admin", "mode": "any", "required_approvals": 1},'
         ' {"step": 3, "role": "director", "mode": "any", "required_approvals": 1, "min_amount": 5000}]'),
    ]
    for doc_type, name, nodes in flows:
        # 与上面同理: :doc_type 在 SELECT 侧和 WHERE 侧各出现一次,
        # 不 CAST 会在 Postgres 上报同样的 AmbiguousParameter。
        # doc_type 列是 varchar(32), name 列是 varchar(64);
        # :nodes 只在 SELECT 出现一次,由目标 JSON 列推断,不用 CAST。
        conn.execute(sa.text(
            "INSERT INTO asset_approval_flows (doc_type, name, nodes, is_active) "
            "SELECT CAST(:doc_type AS varchar(32)), CAST(:name AS varchar(64)), :nodes, true "
            "WHERE NOT EXISTS (SELECT 1 FROM asset_approval_flows "
            "WHERE doc_type = :doc_type AND is_active = true)"
        ), {"doc_type": doc_type, "name": name, "nodes": nodes})


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text(
        "DELETE FROM asset_params WHERE key IN "
        "('asset.borrow.reminder_days_before','asset.borrow.overdue_escalation_days',"
        "'asset.handover.overdue_days','asset.warranty.reminder_days')"
    ))
    conn.execute(sa.text(
        "DELETE FROM asset_approval_flows WHERE doc_type IN ('领用单','调拨单')"
    ))
    op.drop_column("asset_cards", "pending_sync_change_reason")
    op.drop_column("asset_cards", "pending_sync_change")
    op.drop_table("asset_reminders")
    op.drop_table("asset_handover_items")
    op.drop_table("asset_handover_orders")
    op.drop_table("asset_transfer_orders")
    op.drop_table("asset_group_custodies")
    op.drop_table("asset_return_orders")
    op.drop_table("asset_repair_orders")
    op.drop_table("asset_reservations")
    op.drop_table("asset_borrow_orders")
    op.drop_table("asset_issue_orders")
