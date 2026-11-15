"""资产地基服务(学校资产管理系统一期 #10/#11/#15/#17/#85/#86)。

- 编码生成(#17):按可配置规则生成校内编号;标签码 = 编号 + 校验位。
- 状态机(#15):状态只能由业务单据驱动;非法转移拦截;无直接改状态端点。
- 建卡(#10/#85):建卡时同步状态默认 未同步,系统任何地方不得自动同步。
- 特性模板校验(#10):按分类启用的模板校验特性字段(沿代码层级继承)。
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.asset_card import AssetCard, AssetStatus, SyncStatus
from app.models.asset_category import AssetCategory
from app.models.asset_config import AssetCodeRule
from app.models.user import User
from app.services.asset_audit import log_asset_action

#: 校验位字符表(0-9A-Z,36 进制)。
_CHECK_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _char_value(ch: str) -> int:
    if ch.isdigit():
        return int(ch)
    return ord(ch.upper()) - ord("A") + 10


def compute_check_digit(asset_code: str) -> str:
    """标签码校验位:加权和 mod 36。纯函数,可独立测试。"""
    total = sum(_char_value(c) * (i + 1) for i, c in enumerate(asset_code) if c.isalnum())
    return _CHECK_ALPHABET[total % 36]


def make_label_code(asset_code: str) -> str:
    """标签码 = 校内编号 + 校验位(#11)。"""
    return f"{asset_code}{compute_check_digit(asset_code)}"


def verify_label_code(label_code: str) -> bool:
    """校验标签码:最后一位须等于前面编号算出的校验位。"""
    if len(label_code) < 2:
        return False
    return compute_check_digit(label_code[:-1]) == label_code[-1]


def get_active_code_rule(db: Session) -> AssetCodeRule | None:
    return db.query(AssetCodeRule).filter_by(is_active=True).first()


def generate_asset_code(
    db: Session,
    category_code: str,
    *,
    acquired_date: datetime | None = None,
    rule: AssetCodeRule | None = None,
) -> str:
    """按编码规则生成校内编号(#17)。

    默认规则:前缀 + 年份 + 分类段 + 流水,如 ZC2026A020001。
    流水按同一前缀段已建卡数 +1,零填充到 sequence_width 位。
    流水位耗尽(超过 10**width-1)时抛错,不静默截断。
    """
    rule = rule or get_active_code_rule(db)
    if rule is None:
        raise ValueError("未配置启用的资产编码规则")
    year = (acquired_date or datetime.now(UTC)).strftime("%Y")
    segment = ""
    if rule.include_year:
        segment += year
    if rule.include_category:
        segment += category_code
    prefix = f"{rule.prefix}{segment}"
    like = f"{prefix}%"
    count = db.query(AssetCard).filter(AssetCard.asset_code.like(like)).count()
    seq = count + 1
    if seq >= 10 ** rule.sequence_width:
        raise ValueError(f"编码流水位已耗尽(前缀 {prefix},位宽 {rule.sequence_width})")
    return f"{prefix}{seq:0{rule.sequence_width}d}"


#: 状态机合法转移表(#15)。已核销为终态,无出边。
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    AssetStatus.in_stock.value: {
        AssetStatus.in_use.value, AssetStatus.lent.value,
        AssetStatus.repairing.value, AssetStatus.pending_disposal.value,
    },
    AssetStatus.in_use.value: {
        AssetStatus.in_stock.value, AssetStatus.lent.value,
        AssetStatus.repairing.value, AssetStatus.pending_disposal.value,
    },
    AssetStatus.lent.value: {AssetStatus.in_use.value, AssetStatus.in_stock.value},
    AssetStatus.repairing.value: {
        AssetStatus.in_stock.value, AssetStatus.in_use.value,
        AssetStatus.pending_disposal.value,
    },
    AssetStatus.pending_disposal.value: {
        AssetStatus.retired.value, AssetStatus.in_stock.value,
    },
    AssetStatus.retired.value: set(),
}


def validate_transition(from_status: str, to_status: str) -> None:
    """状态机校验:非法转移抛 ValueError(拦截,供 API 转 400)。"""
    if to_status not in {s.value for s in AssetStatus}:
        raise ValueError(f"未知资产状态 {to_status}")
    if to_status not in ALLOWED_TRANSITIONS.get(from_status, set()):
        raise ValueError(f"非法状态转移:{from_status} → {to_status}")


def transition_asset(
    db: Session,
    user: User,
    asset: AssetCard,
    to_status: str,
    *,
    doc_type: str,
    doc_no: str,
) -> AssetCard:
    """由业务单据驱动的状态转移(#15)。

    必须带单据类型与单号(doc_type/doc_no),无单据不转移;转移写审计。
    转到 已核销 时同步封存编号(is_retired + retired_at)。
    """
    if not doc_type or not doc_no:
        raise ValueError("状态转移必须由业务单据驱动,请提供单据类型与单号")
    if asset.is_retired:
        raise ValueError("资产已核销封存,状态不可再变更")
    validate_transition(asset.status, to_status)
    before = {"status": asset.status}
    asset.status = to_status
    if to_status == AssetStatus.retired.value:
        asset.is_retired = True
        asset.retired_at = datetime.now(UTC)
    db.flush()
    log_asset_action(
        db, user, "asset_status_transition",
        target_type="asset_card", target_id=asset.id,
        detail=f"状态转移 单据{doc_type}#{doc_no}",
        before=before, after={"status": to_status},
    )
    return asset


#: 特性信息模板(#10):按分类启用的必填特性字段。
#: 键为分类代码;校验时沿代码层级向上继承(如 A02010101 继承 A0201)。
#: required 必填,optional 选填。模板本身后续批次可做成后台配置表。
ATTRIBUTE_TEMPLATES: dict[str, dict[str, list[str]]] = {
    "A0101": {"required": ["area_sqm", "certificate_no"], "optional": []},
    "A0201": {"required": ["serial_no"], "optional": ["ip_address"]},
    "A0204": {"required": ["plate_no", "license_no"], "optional": []},
    "A0202": {"required": [], "optional": ["precision_grade"]},
}

#: 特性字段中文名(报错信息用)。
ATTRIBUTE_LABELS: dict[str, str] = {
    "area_sqm": "面积(㎡)",
    "certificate_no": "权证号",
    "serial_no": "序列号",
    "ip_address": "IP 地址",
    "plate_no": "车牌号",
    "license_no": "行驶证号",
    "precision_grade": "精度等级",
}


def attribute_template_for(category_code: str) -> dict[str, list[str]] | None:
    """取分类的特性模板:精确匹配不到时沿父级代码逐级向上找。"""
    code = category_code
    while code:
        if code in ATTRIBUTE_TEMPLATES:
            return ATTRIBUTE_TEMPLATES[code]
        code = code[:-2] if len(code) > 3 else ""
    return None


def validate_attributes(category_code: str, attributes: dict | None) -> None:
    """按分类模板校验特性字段:缺必填项抛 ValueError。"""
    template = attribute_template_for(category_code)
    if template is None:
        return
    attrs = attributes or {}
    missing = [f for f in template["required"] if not attrs.get(f)]
    if missing:
        names = "、".join(ATTRIBUTE_LABELS.get(f, f) for f in missing)
        raise ValueError(f"分类 {category_code} 须填写特性字段:{names}")


def create_asset_card(
    db: Session,
    user: User,
    *,
    name: str,
    category_code: str,
    asset_code: str | None = None,
    **fields,
) -> AssetCard:
    """建卡(#10/#11/#85)。

    - 分类须存在且为上报分类;
    - 编号未给则按规则自动生成;给定编号若与已封存(已核销)卡重复,
      明确拒绝复用(#11);
    - 同步状态强制默认 未同步,调用方传入的 sync_status 一律忽略(#85);
    - 特性字段按分类模板校验。
    """
    category = db.query(AssetCategory).filter_by(code=category_code).first()
    if category is None:
        raise ValueError(f"分类代码不存在:{category_code}")
    if not category.is_reportable:
        raise ValueError(f"分类 {category_code} 不是上报分类,不可建卡")
    attributes = fields.get("attributes")
    validate_attributes(category_code, attributes)
    if asset_code:
        clash = db.query(AssetCard).filter_by(asset_code=asset_code).first()
        if clash is not None:
            if clash.is_retired:
                raise ValueError(f"编号 {asset_code} 已核销封存,不可复用")
            raise ValueError(f"编号 {asset_code} 已存在")
    else:
        asset_code = generate_asset_code(db, category_code)
    # 扩展区字段只接受白名单键,防止上报字段混入扩展区。
    ext = fields.pop("ext", None) or {}
    allowed_ext = {"photo_url", "warranty_until", "maintenance_contract",
                   "school_tags", "room_package", "remark"}
    ext = {k: v for k, v in ext.items() if k in allowed_ext}
    card = AssetCard(
        asset_code=asset_code,
        label_code=make_label_code(asset_code),
        name=name,
        category_code=category_code,
        sync_status=SyncStatus.unsynced.value,
        attributes=attributes,
        ext=ext,
        created_by=user.id,
        **{k: v for k, v in fields.items() if k != "attributes"},
    )
    db.add(card)
    db.flush()
    log_asset_action(
        db, user, "asset_card_create",
        target_type="asset_card", target_id=card.id,
        detail=f"建卡 {card.asset_code} {name} 分类{category_code}",
    )
    return card
