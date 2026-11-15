"""学校资产管理系统一期地基批(#5/#10/#11/#15/#16/#17/#76/#78/#79/#80/#81/#82/#85/#86/#104)。

新建资产分类字典、资产卡、字典/参数/编码规则、通用审批流、字段映射
等表,并写入种子数据(与 app.services.asset_seed 同一份字面值,迁移
自包含,不 import 应用代码)。
一级分类以 GB/T 14885-2022 六大类为准;二级及以下分类、财务科目对照
码、映射模板版本为示例种子,须以学校当期官方模板核定后冻结为 V1 版。
不写任何真实官方接口调用,不含学校真实数据。

Revision ID: 0039_asset_foundation
Revises: 0038_remove_family
"""

import sqlalchemy as sa

from alembic import op

revision = "0039_asset_foundation"
down_revision = "0038_remove_family"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "asset_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("level", sa.Integer(), server_default="1", nullable=False),
        sa.Column("parent_code", sa.String(16), nullable=True),
        sa.Column("is_reportable", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("origin", sa.String(16), server_default="seed", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.UniqueConstraint("code", name="uq_asset_categories_code"),
    )
    op.create_index("ix_asset_categories_code", "asset_categories", ["code"])
    op.create_index("ix_asset_categories_parent_code", "asset_categories", ["parent_code"])

    op.create_table(
        "asset_category_finance_map",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("category_code", sa.String(16), nullable=False),
        sa.Column("finance_subject_code", sa.String(32), nullable=False),
        sa.Column("finance_subject_name", sa.String(64), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("note", sa.String(256), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["category_code"], ["asset_categories.code"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "category_code", "finance_subject_code",
            name="uq_asset_finance_map_cat_subject",
        ),
    )
    op.create_index("ix_asset_category_finance_map_category_code", "asset_category_finance_map", ["category_code"])

    op.create_table(
        "asset_code_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(64), server_default="默认规则", nullable=False),
        sa.Column("prefix", sa.String(16), server_default="ZC", nullable=False),
        sa.Column("include_year", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("include_category", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("sequence_width", sa.Integer(), server_default="4", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("note", sa.String(256), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "asset_dictionaries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dict_type", sa.String(32), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("dict_type", "code", name="uq_asset_dict_type_code"),
    )
    op.create_index("ix_asset_dictionaries_dict_type", "asset_dictionaries", ["dict_type"])

    op.create_table(
        "asset_params",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("value", sa.String(256), server_default="", nullable=False),
        sa.Column("value_type", sa.String(16), server_default="string", nullable=False),
        sa.Column("description", sa.String(256), server_default="", nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.UniqueConstraint("key", name="uq_asset_params_key"),
    )
    op.create_index("ix_asset_params_key", "asset_params", ["key"])

    op.create_table(
        "asset_cards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_code", sa.String(32), nullable=False),
        sa.Column("official_code", sa.String(32), nullable=True),
        sa.Column("label_code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("category_code", sa.String(16), nullable=False),
        sa.Column("spec_model", sa.String(128), nullable=True),
        sa.Column("unit", sa.String(16), server_default="件", nullable=False),
        sa.Column("acquired_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acquire_method", sa.String(32), nullable=True),
        sa.Column("source", sa.String(128), nullable=True),
        sa.Column("supplier", sa.String(128), nullable=True),
        sa.Column("original_value", sa.Numeric(14, 2), nullable=True),
        sa.Column("funding_source", sa.String(32), nullable=True),
        sa.Column("voucher_no", sa.String(64), nullable=True),
        sa.Column("depreciation_method", sa.String(32), nullable=True),
        sa.Column("depreciation_years", sa.Integer(), nullable=True),
        sa.Column("accumulated_depreciation", sa.Numeric(14, 2), nullable=True),
        sa.Column("net_value", sa.Numeric(14, 2), nullable=True),
        sa.Column("status", sa.String(16), server_default="在库", nullable=False),
        sa.Column("manage_dept", sa.String(64), nullable=True),
        sa.Column("use_dept", sa.String(64), nullable=True),
        sa.Column("custodian_user_id", sa.Integer(), nullable=True),
        sa.Column("custodian_name", sa.String(32), nullable=True),
        sa.Column("campus", sa.String(32), nullable=True),
        sa.Column("building", sa.String(32), nullable=True),
        sa.Column("room_id", sa.Integer(), nullable=True),
        sa.Column("room_name", sa.String(64), nullable=True),
        sa.Column("borrow_status", sa.String(16), server_default="未领用", nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=True),
        sa.Column("ext", sa.JSON(), nullable=True),
        sa.Column("sync_status", sa.String(16), server_default="未同步", nullable=False),
        sa.Column("is_retired", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["category_code"], ["asset_categories.code"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["custodian_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("asset_code", name="uq_asset_cards_code"),
        sa.UniqueConstraint("label_code", name="uq_asset_cards_label"),
    )
    op.create_index("ix_asset_cards_asset_code", "asset_cards", ["asset_code"])
    op.create_index("ix_asset_cards_official_code", "asset_cards", ["official_code"])
    op.create_index("ix_asset_cards_label_code", "asset_cards", ["label_code"])
    op.create_index("ix_asset_cards_category_code", "asset_cards", ["category_code"])
    op.create_index("ix_asset_cards_status", "asset_cards", ["status"])
    op.create_index("ix_asset_cards_sync_status", "asset_cards", ["sync_status"])
    op.create_index("ix_asset_cards_custodian_user_id", "asset_cards", ["custodian_user_id"])
    op.create_index("ix_asset_cards_room_id", "asset_cards", ["room_id"])

    op.create_table(
        "asset_room_extensions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("room_id", sa.Integer(), nullable=False),
        sa.Column("campus", sa.String(32), nullable=True),
        sa.Column("building", sa.String(32), nullable=True),
        sa.Column("asset_package", sa.String(128), nullable=True),
        sa.Column("note", sa.String(256), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("room_id", name="uq_asset_room_ext_room"),
    )
    op.create_index("ix_asset_room_extensions_room_id", "asset_room_extensions", ["room_id"])

    op.create_table(
        "asset_approval_flows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("doc_type", sa.String(32), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("nodes", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index("ix_asset_approval_flows_doc_type", "asset_approval_flows", ["doc_type"])

    op.create_table(
        "asset_approval_instances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("flow_id", sa.Integer(), nullable=False),
        sa.Column("doc_type", sa.String(32), nullable=False),
        sa.Column("doc_id", sa.Integer(), nullable=False),
        sa.Column("doc_no", sa.String(64), nullable=True),
        sa.Column("applicant_id", sa.Integer(), nullable=False),
        sa.Column("applicant_name", sa.String(32), server_default="", nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("status", sa.String(16), server_default="进行中", nullable=False),
        sa.Column("current_step", sa.Integer(), server_default="1", nullable=False),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_overdue", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("overdue_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["flow_id"], ["asset_approval_flows.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["applicant_id"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_asset_approval_instances_flow_id", "asset_approval_instances", ["flow_id"])
    op.create_index("ix_asset_approval_instances_doc_type", "asset_approval_instances", ["doc_type"])
    op.create_index("ix_asset_approval_instances_doc_id", "asset_approval_instances", ["doc_id"])
    op.create_index("ix_asset_approval_instances_applicant_id", "asset_approval_instances", ["applicant_id"])
    op.create_index("ix_asset_approval_instances_status", "asset_approval_instances", ["status"])

    op.create_table(
        "asset_approval_nodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instance_id", sa.Integer(), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("mode", sa.String(8), server_default="any", nullable=False),
        sa.Column("required_approvals", sa.Integer(), server_default="1", nullable=False),
        sa.Column("approvals", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("status", sa.String(16), server_default="待审批", nullable=False),
        sa.Column("comment", sa.String(500), nullable=True),
        sa.Column("acted_by", sa.Integer(), nullable=True),
        sa.Column("acted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["instance_id"], ["asset_approval_instances.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["acted_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_asset_approval_nodes_instance_id", "asset_approval_nodes", ["instance_id"])

    op.create_table(
        "asset_field_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("local_field", sa.String(64), nullable=False),
        sa.Column("official_field", sa.String(64), nullable=False),
        sa.Column("official_template_version", sa.String(32), server_default="当期模板", nullable=False),
        sa.Column("transform_rule", sa.String(256), nullable=True),
        sa.Column("is_required", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("note", sa.String(256), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "local_field", "official_template_version",
            name="uq_asset_field_map_local_version",
        ),
    )
    op.create_index("ix_asset_field_mappings_local_field", "asset_field_mappings", ["local_field"])

    _seed()


def _seed() -> None:
    """种子数据(与 app.services.asset_seed 同一份字面值)。"""
    conn = op.get_bind()
    categories = sa.table(
        "asset_categories",
        sa.column("code", sa.String), sa.column("name", sa.String),
        sa.column("level", sa.Integer), sa.column("parent_code", sa.String),
        sa.column("is_reportable", sa.Boolean), sa.column("origin", sa.String),
        sa.column("is_active", sa.Boolean), sa.column("sort_order", sa.Integer),
    )
    rows = [
        ("A01", "房屋和构筑物", 1, None, True, "gbt14885"),
        ("A02", "设备", 1, None, True, "gbt14885"),
        ("A03", "文物和陈列品", 1, None, True, "gbt14885"),
        ("A04", "图书和档案", 1, None, True, "gbt14885"),
        ("A05", "家具和用具", 1, None, True, "gbt14885"),
        ("A06", "特种动植物", 1, None, True, "gbt14885"),
        ("A0101", "房屋", 2, "A01", True, "seed"),
        ("A0102", "构筑物", 2, "A01", True, "seed"),
        ("A0201", "计算机设备", 2, "A02", True, "seed"),
        ("A0202", "教学仪器设备", 2, "A02", True, "seed"),
        ("A0203", "办公设备", 2, "A02", True, "seed"),
        ("A0204", "车辆", 2, "A02", True, "seed"),
        ("A0205", "安防消防设备", 2, "A02", True, "seed"),
        ("A0301", "文物", 2, "A03", True, "seed"),
        ("A0302", "陈列品", 2, "A03", True, "seed"),
        ("A0401", "图书", 2, "A04", True, "seed"),
        ("A0402", "档案", 2, "A04", True, "seed"),
        ("A0501", "课桌椅家具", 2, "A05", True, "seed"),
        ("A0502", "办公家具", 2, "A05", True, "seed"),
        ("A0503", "宿舍家具", 2, "A05", True, "seed"),
        ("A0601", "实验动植物", 2, "A06", True, "seed"),
        ("A0602", "校园树木", 2, "A06", True, "seed"),
        ("A020101", "台式计算机", 3, "A0201", True, "seed"),
        ("A020102", "便携式计算机", 3, "A0201", True, "seed"),
        ("A020103", "网络设备", 3, "A0201", True, "seed"),
        ("A020104", "打印设备", 3, "A0201", True, "seed"),
        ("A02010101", "台式一体机", 4, "A020101", True, "seed"),
        ("A02010102", "台式分体机", 4, "A020101", True, "seed"),
    ]
    op.bulk_insert(categories, [
        {"code": c, "name": n, "level": lv, "parent_code": p,
         "is_reportable": r, "origin": o, "is_active": True, "sort_order": i}
        for i, (c, n, lv, p, r, o) in enumerate(rows)
    ])

    finance_maps = sa.table(
        "asset_category_finance_map",
        sa.column("category_code", sa.String),
        sa.column("finance_subject_code", sa.String),
        sa.column("finance_subject_name", sa.String),
        sa.column("is_default", sa.Boolean), sa.column("note", sa.String),
    )
    op.bulk_insert(finance_maps, [
        {"category_code": c, "finance_subject_code": s, "finance_subject_name": n,
         "is_default": True, "note": ""}
        for c, s, n in [
            ("A01", "house_building", "房屋及建筑物"),
            ("A02", "general_equipment", "通用设备"),
            ("A02", "special_equipment", "专用设备"),
            ("A03", "cultural_relic", "文物和陈列品"),
            ("A04", "books_archives", "图书和档案"),
            ("A05", "furniture", "家具和用具"),
            ("A06", "bio_asset", "特种动植物"),
        ]
    ])

    dictionaries = sa.table(
        "asset_dictionaries",
        sa.column("dict_type", sa.String), sa.column("code", sa.String),
        sa.column("label", sa.String), sa.column("is_system", sa.Boolean),
        sa.column("is_active", sa.Boolean), sa.column("sort_order", sa.Integer),
    )
    op.bulk_insert(dictionaries, [
        {"dict_type": t, "code": c, "label": label, "is_system": True,
         "is_active": True, "sort_order": i}
        for i, (t, c, label) in enumerate([
            ("acquire_method", "purchase", "购置"),
            ("acquire_method", "transfer_in", "调拨"),
            ("acquire_method", "donation", "捐赠"),
            ("acquire_method", "self_built", "自建"),
            ("acquire_method", "inventory_surplus", "盘盈"),
            ("funding_source", "fiscal", "财政拨款"),
            ("funding_source", "self_raised", "自筹"),
            ("funding_source", "donation", "捐赠"),
            ("funding_source", "other", "其他"),
            ("disposal_type", "scrap", "报废"),
            ("disposal_type", "damage", "报损"),
            ("disposal_type", "loss_compensation", "丢失赔偿"),
            ("disposal_type", "free_transfer", "无偿划转"),
            ("disposal_type", "sale", "出售出让"),
            ("disposal_type", "exchange", "置换"),
            ("disposal_type", "donation_out", "捐赠转出"),
            ("asset_status", "in_stock", "在库"),
            ("asset_status", "in_use", "在用"),
            ("asset_status", "lent", "借出"),
            ("asset_status", "repairing", "维修中"),
            ("asset_status", "pending_disposal", "待处置"),
            ("asset_status", "retired", "已核销"),
            ("borrow_status", "not_issued", "未领用"),
            ("borrow_status", "issued", "已领用"),
            ("borrow_status", "lent", "借出"),
            ("borrow_status", "returned", "已归还"),
        ])
    ])

    params = sa.table(
        "asset_params",
        sa.column("key", sa.String), sa.column("value", sa.String),
        sa.column("value_type", sa.String), sa.column("description", sa.String),
    )
    op.bulk_insert(params, [
        {"key": k, "value": v, "value_type": t, "description": d}
        for k, v, t, d in [
            ("fixed_asset.min_value", "1000", "number",
             "固定资产确认标准:单位价值(元)下限,现行口径 1000 元以上"),
            ("fixed_asset.min_years", "1", "number",
             "固定资产确认标准:使用期限(年)下限,现行口径超过 1 年"),
            ("approval.transfer_threshold", "5000", "number",
             "分级授权建议初始值:调拨超 5000 元上升到总务"),
            ("approval.repair_threshold", "5000", "number",
             "分级授权建议初始值:维修超 5000 元上升到总务"),
            ("approval.disposal_threshold", "0", "number",
             "分级授权建议初始值:处置金额高于 0 即上升到分管领导/校长办公会"),
            ("approval.timeout_hours", "72", "number",
             "审批超时提醒:节点超过该小时数未处理即标记超时待办"),
            ("sync.separation_of_duties", "true", "boolean",
             "同步勾选与执行建议分岗(待确认事项 #10)"),
        ]
    ])

    mappings = sa.table(
        "asset_field_mappings",
        sa.column("local_field", sa.String), sa.column("official_field", sa.String),
        sa.column("official_template_version", sa.String),
        sa.column("transform_rule", sa.String), sa.column("is_required", sa.Boolean),
        sa.column("sort_order", sa.Integer), sa.column("is_active", sa.Boolean),
        sa.column("note", sa.String),
    )
    op.bulk_insert(mappings, [
        {"local_field": local, "official_field": off,
         "official_template_version": "当期模板", "transform_rule": rule,
         "is_required": req, "sort_order": i, "is_active": True, "note": ""}
        for i, (local, off, rule, req) in enumerate([
            ("asset_code", "资产编号", None, True),
            ("name", "资产名称", None, True),
            ("category_code", "资产分类代码", "直接映射;选分类时即限定官方代码集", True),
            ("spec_model", "规格型号", None, False),
            ("original_value", "资产原值", "金额单位:元", True),
            ("funding_source", "资金来源", "资金来源代码值域转换", True),
            ("acquire_method", "取得方式", "购置/调拨/捐赠/自建等代码值域映射", True),
            ("acquired_date", "取得日期", None, True),
            ("manage_dept", "管理部门", "部门按官方单位组织口径映射", False),
            ("use_dept", "使用部门", "部门按官方单位组织口径映射", False),
            ("custodian_name", "保管人", "保管人为校内颗粒度,导出时按官方口径归集", False),
            ("voucher_no", "会计凭证号", "与财务入账清单核对后才允许导出", False),
            ("official_code", "官方资产编号", "官方导入成功后回填方向", False),
        ])
    ])

    code_rules = sa.table(
        "asset_code_rules",
        sa.column("name", sa.String), sa.column("prefix", sa.String),
        sa.column("include_year", sa.Boolean), sa.column("include_category", sa.Boolean),
        sa.column("sequence_width", sa.Integer), sa.column("is_active", sa.Boolean),
        sa.column("note", sa.String),
    )
    op.bulk_insert(code_rules, [
        {"name": "默认规则", "prefix": "ZC", "include_year": True,
         "include_category": True, "sequence_width": 4, "is_active": True,
         "note": "前缀 ZC + 年份 + 分类段 + 4 位流水,如 ZC2026A020001"},
    ])

    flows = sa.table(
        "asset_approval_flows",
        sa.column("doc_type", sa.String), sa.column("name", sa.String),
        sa.column("nodes", sa.JSON), sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(flows, [
        {"doc_type": "通用", "name": "通用审批流", "is_active": True, "nodes": [
            {"step": 1, "role": "asset_dept_admin", "mode": "any", "required_approvals": 1},
            {"step": 2, "role": "asset_admin", "mode": "any", "required_approvals": 1},
            {"step": 3, "role": "director", "mode": "any", "required_approvals": 1,
             "min_amount": 5000},
        ]},
    ])
    del conn


def downgrade() -> None:
    op.drop_table("asset_field_mappings")
    op.drop_table("asset_approval_nodes")
    op.drop_table("asset_approval_instances")
    op.drop_table("asset_approval_flows")
    op.drop_table("asset_room_extensions")
    op.drop_table("asset_cards")
    op.drop_table("asset_params")
    op.drop_table("asset_dictionaries")
    op.drop_table("asset_code_rules")
    op.drop_table("asset_category_finance_map")
    op.drop_table("asset_categories")
