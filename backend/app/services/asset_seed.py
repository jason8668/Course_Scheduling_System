"""资产地基批种子数据(学校资产管理系统一期 #16/#17/#79/#81/#104)。

供两处使用:
1. Alembic 迁移 0039(内嵌同一份字面值,迁移自包含,不 import 本模块);
2. 测试环境 seed_asset_foundation(db)(测试用 create_all 建表,不跑迁移)。

演示数据说明:一级分类代码与名称以设计方案 §9.1(GB/T 14885-2022
六大类)为准;二级及以下分类代码、财务科目对照码、映射模板版本为
示例种子,须以学校当期官方模板核定后冻结为 V1 版(待确认事项 #5)。
种子里不含任何学校真实数据。
"""

from sqlalchemy.orm import Session

from app.models.asset_approval import ApprovalFlow
from app.models.asset_category import AssetCategory, AssetCategoryFinanceMap
from app.models.asset_config import AssetCodeRule, AssetDictionary, AssetParam
from app.models.asset_sync import AssetFieldMapping

#: (code, name, level, parent_code, origin)
SEED_CATEGORIES: tuple[tuple[str, str, int, str | None, str], ...] = (
    # 一级:GB/T 14885-2022 六大类(设计方案 §9.1)
    ("A01", "房屋和构筑物", 1, None, "gbt14885"),
    ("A02", "设备", 1, None, "gbt14885"),
    ("A03", "文物和陈列品", 1, None, "gbt14885"),
    ("A04", "图书和档案", 1, None, "gbt14885"),
    ("A05", "家具和用具", 1, None, "gbt14885"),
    ("A06", "特种动植物", 1, None, "gbt14885"),
    # 二级及以下:示例种子,待官方模板核定后冻结
    ("A0101", "房屋", 2, "A01", "seed"),
    ("A0102", "构筑物", 2, "A01", "seed"),
    ("A0201", "计算机设备", 2, "A02", "seed"),
    ("A0202", "教学仪器设备", 2, "A02", "seed"),
    ("A0203", "办公设备", 2, "A02", "seed"),
    ("A0204", "车辆", 2, "A02", "seed"),
    ("A0205", "安防消防设备", 2, "A02", "seed"),
    ("A0301", "文物", 2, "A03", "seed"),
    ("A0302", "陈列品", 2, "A03", "seed"),
    ("A0401", "图书", 2, "A04", "seed"),
    ("A0402", "档案", 2, "A04", "seed"),
    ("A0501", "课桌椅家具", 2, "A05", "seed"),
    ("A0502", "办公家具", 2, "A05", "seed"),
    ("A0503", "宿舍家具", 2, "A05", "seed"),
    ("A0601", "实验动植物", 2, "A06", "seed"),
    ("A0602", "校园树木", 2, "A06", "seed"),
    # 三级示例
    ("A020101", "台式计算机", 3, "A0201", "seed"),
    ("A020102", "便携式计算机", 3, "A0201", "seed"),
    ("A020103", "网络设备", 3, "A0201", "seed"),
    ("A020104", "打印设备", 3, "A0201", "seed"),
    # 四级示例
    ("A02010101", "台式一体机", 4, "A020101", "seed"),
    ("A02010102", "台式分体机", 4, "A020101", "seed"),
)

#: (category_code, finance_subject_code, finance_subject_name)
#: 财务科目对照种子为示意值,须学校财务核定后冻结。
SEED_FINANCE_MAPS: tuple[tuple[str, str, str], ...] = (
    ("A01", "house_building", "房屋及建筑物"),
    ("A02", "general_equipment", "通用设备"),
    ("A02", "special_equipment", "专用设备"),
    ("A03", "cultural_relic", "文物和陈列品"),
    ("A04", "books_archives", "图书和档案"),
    ("A05", "furniture", "家具和用具"),
    ("A06", "bio_asset", "特种动植物"),
)

#: (dict_type, code, label)
SEED_DICTIONARIES: tuple[tuple[str, str, str], ...] = (
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
)

#: (key, value, value_type, description)
#: 阈值数字为建议初始值,待学校确认(待确认事项 #3/#4)。
SEED_PARAMS: tuple[tuple[str, str, str, str], ...] = (
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
    ("sync.backlog_days", "14", "number",
     "待同步积压提醒阈值(天):待同步池超过该天数未执行时提醒资产管理员,"
     "只提醒不自动执行(#103)"),
    ("disposal.materials", "{\"scrap\": [\"技术鉴定单\", \"资产卡片\", \"购置凭证\"], "
     "\"damage\": [\"技术鉴定单\", \"报损说明\", \"资产卡片\"], "
     "\"loss_compensation\": [\"丢失情况说明\", \"赔偿凭证/协议\", \"资产卡片\"], "
     "\"free_transfer\": [\"划转协议\", \"接收单位函\", \"资产卡片\"], "
     "\"sale\": [\"评估报告\", \"出售方案\", \"资产卡片\"], "
     "\"exchange\": [\"置换协议\", \"评估报告\", \"资产卡片\"], "
     "\"donation_out\": [\"捐赠协议\", \"接收单位函\", \"资产卡片\"]}", "json",
     "七类处置按类型应交材料清单,缺材料不得提交(#54)"),
    ("asset.idle.days_threshold", "180", "number",
     "闲置识别:长期未使用天数阈值(天),默认 180 天,可配置(#14)"),
    ("asset.idle.no_custodian", "true", "boolean",
     "闲置识别:无领用人/保管人是否计入闲置(#14)"),
    ("asset.borrow.reminder_days_before", "1", "number",
     "借用到期提醒:到期前多少天提醒(天),默认 1 天,可配置(#32)"),
    ("asset.borrow.overdue_escalation_days", "3", "number",
     "借用逾期升级:逾期满多少天升级提醒到资产管理员(天),默认 3 天,可配置(#32)"),
    ("asset.handover.overdue_days", "7", "number",
     "未办结移交预警:超多少天预警(天),默认 7 天,可配置(#40)"),
    ("asset.warranty.reminder_days", "30", "number",
     "保修到期提醒:到期前多少天提醒(天),默认 30 天,可配置(#3)"),
    ("asset.idle.over_config_std", "", "string",
     "闲置识别:超配置标准,格式如 A0203:5,A0501:20(同一分类+管理部门件数上限),"
     "为空表示不启用该规则(#14)"),
)

#: (local_field, official_field, transform_rule, is_required)
SEED_FIELD_MAPPINGS: tuple[tuple[str, str, str | None, bool], ...] = (
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
)

#: 通用审批流种子节点(#5):部门初审 → 资产管理员审核 → 金额 ≥5000 元时分管领导。
SEED_DEFAULT_FLOW_NODES: list[dict] = [
    {"step": 1, "role": "asset_dept_admin", "mode": "any", "required_approvals": 1},
    {"step": 2, "role": "asset_admin", "mode": "any", "required_approvals": 1},
    {"step": 3, "role": "director", "mode": "any", "required_approvals": 1,
     "min_amount": 5000},
]


def seed_asset_foundation(db: Session) -> dict[str, int]:
    """写入地基批种子数据(幂等:已存在则跳过)。回传各表新增行数。"""
    counts = {"categories": 0, "finance_maps": 0, "dictionaries": 0,
              "params": 0, "field_mappings": 0, "code_rules": 0, "flows": 0}
    for i, (code, name, level, parent, origin) in enumerate(SEED_CATEGORIES):
        if not db.query(AssetCategory).filter_by(code=code).first():
            db.add(AssetCategory(
                code=code, name=name, level=level, parent_code=parent,
                is_reportable=True, origin=origin, sort_order=i,
            ))
            counts["categories"] += 1
    for code, subj_code, subj_name in SEED_FINANCE_MAPS:
        if not db.query(AssetCategoryFinanceMap).filter_by(
            category_code=code, finance_subject_code=subj_code
        ).first():
            db.add(AssetCategoryFinanceMap(
                category_code=code, finance_subject_code=subj_code,
                finance_subject_name=subj_name, is_default=True,
            ))
            counts["finance_maps"] += 1
    for i, (dtype, code, label) in enumerate(SEED_DICTIONARIES):
        if not db.query(AssetDictionary).filter_by(dict_type=dtype, code=code).first():
            db.add(AssetDictionary(
                dict_type=dtype, code=code, label=label,
                is_system=True, sort_order=i,
            ))
            counts["dictionaries"] += 1
    for key, value, vtype, desc in SEED_PARAMS:
        if not db.query(AssetParam).filter_by(key=key).first():
            db.add(AssetParam(key=key, value=value, value_type=vtype, description=desc))
            counts["params"] += 1
    for i, (local, official, rule, required) in enumerate(SEED_FIELD_MAPPINGS):
        if not db.query(AssetFieldMapping).filter_by(local_field=local).first():
            db.add(AssetFieldMapping(
                local_field=local, official_field=official,
                official_template_version="当期模板",
                transform_rule=rule, is_required=required, sort_order=i,
            ))
            counts["field_mappings"] += 1
    if not db.query(AssetCodeRule).filter_by(is_active=True).first():
        db.add(AssetCodeRule(
            name="默认规则", prefix="ZC", include_year=True,
            include_category=True, sequence_width=4, is_active=True,
            note="前缀 ZC + 年份 + 分类段 + 4 位流水,如 ZC2026A020001",
        ))
        counts["code_rules"] += 1
    if not db.query(ApprovalFlow).filter_by(doc_type="通用", is_active=True).first():
        db.add(ApprovalFlow(
            doc_type="通用", name="通用审批流", nodes=SEED_DEFAULT_FLOW_NODES,
        ))
        counts["flows"] += 1
    if not db.query(ApprovalFlow).filter_by(doc_type="处置单", is_active=True).first():
        db.add(ApprovalFlow(
            doc_type="处置单", name="处置审批流", nodes=SEED_DEFAULT_FLOW_NODES,
        ))
        counts["flows"] += 1
    db.flush()
    return counts
