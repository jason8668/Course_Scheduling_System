"""官方对接适配层(学校资产管理系统一期 M13 #91/#93/#104/#106)。

浙江省资产云没有向单个学校开放的实时 API,本模块不写任何真实官方接口
调用,不伪造官方响应。

三层对接路径(设计方案 §10):
- 第一层 标准对齐:分类/编码/字段已在地基实现;
- 第二层 模板交换:按官方当期模板导出已勾选资产(本批实现 #93);
- 第三层 接口适配:本模块预留;主管部门开放接口后,只需实现一个
  新的 SyncAdapter 子类并配置映射,业务系统不动。

校验(#91)与导出(#93)均与映射配置表 asset_field_mappings 联动:
缺映射的必填字段进拦截清单并提示;扩展区(ext / never_sync 键)绝不
出现在导出文件中。模板版本取映射表 official_template_version,
种子为"当期模板"占位,不编造官方版本号。
"""

import io
from typing import Protocol

from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.models.asset_card import AssetCard
from app.models.asset_category import AssetCategory
from app.models.asset_sync import AssetFieldMapping
from app.services import asset_foundation as asset_svc


class SyncAdapter(Protocol):
    """对接适配器接口。实现方只处理已勾选同步的资产,绝不自动同步。"""

    name: str

    def validate(self, db: Session, assets: list[AssetCard]) -> list[dict]:
        """同步前校验:回传每件资产的缺项清单,通过的为空。"""
        ...

    def export_template(self, db: Session, assets: list[AssetCard]) -> bytes:
        """按官方当期模板导出已勾选资产。"""
        ...

    def push(self, db: Session, assets: list[AssetCard]) -> dict:
        """实时接口推送:官方接口未开放前必须拒绝,不得伪造成功。"""
        ...


def active_mappings(db: Session) -> list[AssetFieldMapping]:
    """取启用的字段映射(按 sort_order 排,即导出列序)。"""
    return db.query(AssetFieldMapping).filter_by(is_active=True).order_by(
        AssetFieldMapping.sort_order).all()


def template_version(db: Session) -> str:
    """当期官方模板版本(映射表上的版本;种子"当期模板"为占位)。"""
    rows = active_mappings(db)
    return rows[0].official_template_version if rows else "当期模板"


class TemplateExportAdapter:
    """模板导出适配器(B5 实现 export_template)。

    一期同步执行 = 模板导出 + 学校在官方系统导入 + 编号回填(手动同步
    规则第 6-7 步),不走实时接口。
    """

    name = "template_export"

    def validate(self, db: Session, assets: list[AssetCard]) -> list[dict]:
        """同步前校验(#91/#104):每件资产返回缺项清单,通过的为空。

        校验项:必填字段(映射表 is_required)、分类映射(分类须在字典中)、
        价值与入账凭证(原值必填、须已入账且有凭证号)、取得方式、特性字段
        (按分类模板)。缺映射的必填字段进拦截清单并提示"缺映射"。
        每条问题形如 {"asset_id","asset_code","missing":[字段名],
        "reasons":[中文原因]}。
        """
        mappings = active_mappings(db)
        by_local = {m.local_field: m for m in mappings}
        # 设计上必填的校内字段(种子映射 is_required 的并集):映射被停用/
        # 删除时,字段本身仍必填,须进拦截清单并提示"缺映射",不能静默放行。
        required = ["asset_code", "name", "category_code", "original_value",
                    "funding_source", "acquire_method", "acquired_date"]
        problems: list[dict] = []
        for asset in assets:
            missing: list[str] = []
            reasons: list[str] = []
            for field in required:
                if field not in by_local:
                    missing.append(field)
                    reasons.append(f"字段 {field} 缺少官方映射配置")
                    continue
                value = getattr(asset, field, None)
                if value in (None, "", []):
                    missing.append(field)
                    reasons.append(f"必填字段 {field} 为空")
            if asset.category_code and not db.query(AssetCategory).filter_by(
                code=asset.category_code, is_active=True,
            ).first():
                missing.append("category_code")
                reasons.append(f"分类代码 {asset.category_code} 无映射/不在分类字典中")
            if asset.original_value is None:
                if "original_value" not in missing:
                    missing.append("original_value")
                reasons.append("资产原值为空")
            elif float(asset.original_value or 0) < 0:
                missing.append("original_value")
                reasons.append("资产原值为负数")
            if not asset.is_booked or not asset.voucher_no:
                missing.append("voucher_no")
                reasons.append("未回填入账凭证号,禁止同步")
            if not asset.acquire_method:
                if "acquire_method" not in missing:
                    missing.append("acquire_method")
                reasons.append("取得方式为空")
            template = asset_svc.attribute_template_for(asset.category_code or "")
            if template:
                attrs = asset.attributes or {}
                for key in template.get("required", []):
                    if attrs.get(key) in (None, ""):
                        missing.append(f"attributes.{key}")
                        label = asset_svc.ATTRIBUTE_LABELS.get(key, key)
                        reasons.append(f"特性字段缺失:{label}")
            if asset.is_retired:
                missing.append("is_retired")
                reasons.append("资产已核销,不可同步")
            if missing:
                problems.append({
                    "asset_id": asset.id, "asset_code": asset.asset_code,
                    "missing": sorted(set(missing)), "reasons": reasons,
                })
        return problems

    def export_template(self, db: Session, assets: list[AssetCard]) -> bytes:
        """按官方当期模板导出已勾选资产(#93)。

        列 = 启用映射的 official_field(按 sort_order);行 = 传入的资产
        (调用方只传校验通过的已勾选资产)。扩展区(ext / never_sync 键)
        不在映射表中,故绝不出现在导出文件中。
        """
        mappings = active_mappings(db)
        wb = Workbook()
        ws = wb.active
        ws.title = "资产导入"
        headers = [m.official_field for m in mappings]
        ws.append(headers)
        for asset in assets:
            row: list[object] = []
            for m in mappings:
                value = getattr(asset, m.local_field, None)
                if hasattr(value, "strftime"):
                    value = value.strftime("%Y-%m-%d")
                elif isinstance(value, dict):
                    value = ""  # JSON 栏位不直接进模板
                row.append(value if value is not None else "")
            ws.append(row)
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def push(self, db: Session, assets: list[AssetCard]) -> dict:
        """官方实时接口未向单个学校开放,拒绝推送,不伪造调用。"""
        raise NotImplementedError(
            "浙江省官方资产系统未向单个学校开放实时 API,不可直连推送; "
            "一期请走模板导出 + 官方系统导入"
        )


def get_adapter(name: str = "template_export") -> TemplateExportAdapter:
    """取适配器。当前只有模板导出一种;新适配器开放后在此注册。"""
    if name == "template_export":
        return TemplateExportAdapter()
    raise ValueError(f"未知对接适配器 {name}")


#: 对接边界声明,供 API /sync/adapter 回传与文档引用。
ADAPTER_BOUNDARY_NOTE = (
    "官方系统的账号、权限、模板版本与开放政策由财政及主管部门决定; "
    "本项目承诺运维期内模板变更免费适配,不承诺未开放的直连接口在"
    "特定期限内开通(设计方案 §10.2)。"
)

#: 同步执行页显著提示(#106)。
SYNC_EXECUTION_NOTE = (
    "一期为模板交换,实时接口未开放:本次同步只生成官方当期模板导入文件,"
    "由学校在官方系统导入;官方导入成功后须在本系统批量回填官方编号。"
)
