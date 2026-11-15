"""处置与报废共用服务(学校资产管理系统一期第 5 批 M8 #54~#58)。

- 材料清单按类型可配置:参数 disposal.materials(JSON:类型代码 → 材料清单),
  未配置时用本模块默认值(演示口径,须学校确认后冻结)。
- 单据号:处置单 CZ-、鉴定单 JD-、申报包 SB-、回收交接单 HS-,
  均为前缀 + YYYYMMDD + 4 位流水。
- 处置金额口径:审批金额取资产原值(original_value),见汇报口径清单。
"""

import json
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.asset_approval import ApprovalInstance
from app.models.asset_card import AssetCard, AssetStatus
from app.models.asset_config import AssetParam
from app.models.asset_disposal import (
    DISPOSAL_TYPES,
    AssetDisposalOrder,
    AssetDisposalRecovery,
)
from app.models.user import User
from app.services import asset_foundation as asset_svc
from app.services.asset_audit import log_asset_action

#: 七类处置按类型要求的材料清单默认值(可配置,见 get_disposal_materials)。
DEFAULT_DISPOSAL_MATERIALS: dict[str, list[str]] = {
    "scrap": ["技术鉴定单", "资产卡片", "购置凭证"],
    "damage": ["技术鉴定单", "报损说明", "资产卡片"],
    "loss_compensation": ["丢失情况说明", "赔偿凭证/协议", "资产卡片"],
    "free_transfer": ["划转协议", "接收单位函", "资产卡片"],
    "sale": ["评估报告", "出售方案", "资产卡片"],
    "exchange": ["置换协议", "评估报告", "资产卡片"],
    "donation_out": ["捐赠协议", "接收单位函", "资产卡片"],
}

#: 鉴定结论。
APPRAISAL_CONCLUSIONS = ("可继续使用", "建议处置", "建议报废")


def get_disposal_materials(db: Session, disposal_type: str) -> list[str]:
    """取某处置类型应交材料清单:参数 disposal.materials 优先,未配用默认值。"""
    row = db.query(AssetParam).filter_by(key="disposal.materials").first()
    if row is not None and row.value:
        try:
            data = json.loads(row.value)
            if isinstance(data, dict) and disposal_type in data:
                return [str(x) for x in data[disposal_type]]
        except (ValueError, TypeError):
            pass
    return list(DEFAULT_DISPOSAL_MATERIALS.get(disposal_type, []))


def disposal_type_label(code: str) -> str:
    return DISPOSAL_TYPES.get(code, code)


def next_disposal_no(db: Session, table, prefix: str) -> str:
    """单据号:前缀 + YYYYMMDD + 4 位流水(按当日已建单数递增)。"""
    day = datetime.now(UTC).strftime("%Y%m%d")
    like = f"{prefix}{day}%"
    count = db.query(table).filter(table.doc_no.like(like)).count() \
        if hasattr(table, "doc_no") else 0
    return f"{prefix}{day}{count + 1:04d}"


def next_package_no(db: Session, table) -> str:
    day = datetime.now(UTC).strftime("%Y%m%d")
    like = f"SB-{day}%"
    count = db.query(table).filter(table.package_no.like(like)).count()
    return f"SB-{day}{count + 1:04d}"


def next_recovery_no(db: Session, table) -> str:
    day = datetime.now(UTC).strftime("%Y%m%d")
    like = f"HS-{day}%"
    count = db.query(table).filter(table.recovery_no.like(like)).count()
    return f"HS-{day}{count + 1:04d}"


def sync_disposal_approval_status(db: Session, inst: ApprovalInstance) -> None:
    """审批流回写处置单状态(#56):实例 已通过 → 审批通过;已退回 → 已退回。"""
    if inst.doc_type != "处置单":
        return
    order = db.get(AssetDisposalOrder, inst.doc_id)
    if order is None or order.status not in ("待审批",):
        return
    if inst.status == "已通过":
        order.status = "审批通过"
    elif inst.status == "已退回":
        order.status = "已退回"


def finalize_retire(
    db: Session, user: User, order: AssetDisposalOrder, card: AssetCard,
) -> AssetDisposalRecovery:
    """核销收尾(#58):资产经 transition 入已核销(编号封存),处置单置已核销,
    生成回收交接单骨架(待交接,回收单位等由回收端点补填)。

    调用方须先校验官方批复已回填;本函数只做状态收尾,不做批复校验。
    """
    asset_svc.transition_asset(
        db, user, card, AssetStatus.retired.value,
        doc_type="处置单", doc_no=order.doc_no,
    )
    order.status = "已核销"
    existing = db.query(AssetDisposalRecovery).filter_by(
        disposal_id=order.id).first()
    if existing is not None:
        return existing
    recovery = AssetDisposalRecovery(
        recovery_no=next_recovery_no(db, AssetDisposalRecovery),
        disposal_id=order.id, status="待交接", created_by=user.id,
    )
    db.add(recovery)
    db.flush()
    log_asset_action(
        db, user, "asset_disposal_retire",
        target_type="disposal_order", target_id=order.id,
        detail=f"核销处置 {order.doc_no} 资产{card.asset_code} "
               f"批复{order.official_reply_no or ''} 编号封存,回收交接单{recovery.recovery_no}",
    )
    return recovery
