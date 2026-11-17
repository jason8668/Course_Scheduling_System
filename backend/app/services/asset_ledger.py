"""台账/入库验收/手动勾选共用服务(学校资产管理系统一期第 2 批)。

- 组合查询过滤器(#8):与台账导出、按条件批量勾选共用同一口径。
- 台账导出(#9):openpyxl 同步生成(复用课表导出模式),默认只含校内
  台账字段,扩展区备注等敏感/内部字段默认不导出,include_ext 才追加。
- 闲置识别(#14):规则全部来自 asset_params,不写死阈值。
- 批次号(#26/#90):RK 入库批次 / GX 勾选批次,日流水。
"""

import io
from collections import defaultdict
from datetime import UTC, datetime

from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.models.asset_card import AssetCard, AssetStatus, SyncStatus
from app.models.asset_config import AssetParam
from app.models.asset_ledger import AssetBatch
from app.models.user import User
from app.schemas.asset_ledger import AssetSearchParams

#: 允许排序的字段白名单(#8:拒绝非法排序字段,防注入)。
SORTABLE_FIELDS = {
    "id": AssetCard.id,
    "asset_code": AssetCard.asset_code,
    "name": AssetCard.name,
    "original_value": AssetCard.original_value,
    "acquired_date": AssetCard.acquired_date,
    "created_at": AssetCard.created_at,
    "category_code": AssetCard.category_code,
    "status": AssetCard.status,
    "sync_status": AssetCard.sync_status,
}


def build_asset_query(db: Session, params: AssetSearchParams):
    """组合查询(#8):分类/部门/保管人/房间/状态/价值区间/购置年份/
    资金来源/同步状态/入账/闲置/批次组合过滤,全部参数化。"""
    q = db.query(AssetCard)
    if params.category_code:
        q = q.filter(AssetCard.category_code.like(f"{params.category_code}%"))
    if params.manage_dept:
        q = q.filter_by(manage_dept=params.manage_dept)
    if params.use_dept:
        q = q.filter_by(use_dept=params.use_dept)
    if params.custodian_name:
        q = q.filter(AssetCard.custodian_name.like(f"%{params.custodian_name}%"))
    if params.custodian_user_id is not None:
        q = q.filter_by(custodian_user_id=params.custodian_user_id)
    if params.room_id is not None:
        q = q.filter_by(room_id=params.room_id)
    if params.room_name:
        q = q.filter(AssetCard.room_name.like(f"%{params.room_name}%"))
    if params.status:
        if params.status not in {s.value for s in AssetStatus}:
            raise ValueError(f"未知资产状态 {params.status}")
        q = q.filter_by(status=params.status)
    if params.sync_status:
        if params.sync_status not in {s.value for s in SyncStatus}:
            raise ValueError(f"未知同步状态 {params.sync_status}")
        q = q.filter_by(sync_status=params.sync_status)
    if params.acquire_method:
        q = q.filter_by(acquire_method=params.acquire_method)
    if params.funding_source:
        q = q.filter_by(funding_source=params.funding_source)
    if params.acquired_year is not None:
        # 按年区间过滤(不用数据库方言函数,跨 SQLite/Postgres 可用)。
        start = datetime(params.acquired_year, 1, 1, tzinfo=UTC)
        end = datetime(params.acquired_year + 1, 1, 1, tzinfo=UTC)
        q = q.filter(AssetCard.acquired_date >= start,
                     AssetCard.acquired_date < end)
    # 原值区间不在 SQL 里筛:original_value 是 Fernet 密文列(#84),
    # SQL 比较(>=/<=)比的是密文字符串,结果无意义;调用方在取回后
    # 用 apply_value_range 在 Python 侧解密后筛(见 query_assets)。
    if params.batch_no:
        q = q.filter_by(batch_no=params.batch_no)
    if params.is_booked is not None:
        q = q.filter_by(is_booked=params.is_booked)
    if params.is_idle is not None:
        q = q.filter_by(is_idle=params.is_idle)
    if params.q:
        like = f"%{params.q}%"
        q = q.filter(
            (AssetCard.name.like(like)) | (AssetCard.asset_code.like(like))
            | (AssetCard.official_code.like(like))
        )
    return q


def apply_value_range(cards: list[AssetCard], params: AssetSearchParams):
    """原值区间筛选(Python 侧):original_value 是 Fernet 密文列(#84),
    SQL 比较比的是密文字符串,结果无意义;解密后按数值筛。
    None 原值按 SQL 语义排除(NULL 比较结果为 NULL,不过滤条件)。"""
    out = list(cards)
    if params.min_value is not None:
        out = [c for c in out
               if c.original_value is not None
               and float(c.original_value) >= params.min_value]
    if params.max_value is not None:
        out = [c for c in out
               if c.original_value is not None
               and float(c.original_value) <= params.max_value]
    return out


def sort_cards(cards: list[AssetCard], sort_by: str, sort_dir: str):
    """Python 侧排序:供加密字段(original_value)用,解密后的数值排。
    None 的位置与 Postgres 默认一致:升序 NULLS LAST,降序 NULLS FIRST。
    其它字段也可走这里(取回后按属性值排),但一般仍走 SQL 的 apply_sort。"""
    if sort_by not in SORTABLE_FIELDS:
        raise ValueError(f"非法排序字段 {sort_by}")
    reverse = sort_dir == "desc"
    if sort_by == "original_value":
        key = lambda c: (c.original_value is None, float(c.original_value or 0))
    else:
        key = lambda c: (getattr(c, sort_by) is None, getattr(c, sort_by))
    return sorted(cards, key=key, reverse=reverse)


def query_assets(db: Session, params: AssetSearchParams) -> list[AssetCard]:
    """组合查询 + 排序后的全部卡片(未分页)。

    加密字段的筛选/排序在 Python 侧做:先由 build_asset_query 做其余
    SQL 过滤(校级台账千级,全量取回可接受),再 apply_value_range 筛
    原值区间,最后排序——original_value 用 sort_cards 按解密后的数值
    排,其它字段的 SQL 排序在取回前已生效、顺序保留。调用方按
    total=len(全部) 再切片分页,total 与分页语义不变。"""
    q = build_asset_query(db, params)
    if params.sort_by != "original_value":
        q = apply_sort(q, params.sort_by, params.sort_dir)
    cards = q.all()
    cards = apply_value_range(cards, params)
    if params.sort_by == "original_value":
        cards = sort_cards(cards, params.sort_by, params.sort_dir)
    return cards


def apply_sort(q, sort_by: str, sort_dir: str):
    """排序:非法字段抛 ValueError(调用方转 400)。

    原值(original_value)是 Fernet 密文列(#84),SQL ORDER BY 排的是
    密文字符串,顺序无意义:这里不加 SQL 排序,调用方须用 query_assets
    (取回后 sort_cards 按解密后的数值排)。"""
    if sort_by not in SORTABLE_FIELDS:
        raise ValueError(f"非法排序字段 {sort_by}")
    if sort_by == "original_value":
        return q
    col = SORTABLE_FIELDS[sort_by]
    return q.order_by(col.asc() if sort_dir == "asc" else col.desc())


#: 台账导出默认列(#9):只含校内台账字段,不含扩展区。
EXPORT_COLUMNS: list[tuple[str, str]] = [
    ("asset_code", "资产编号"),
    ("official_code", "官方编号"),
    ("label_code", "标签码"),
    ("name", "资产名称"),
    ("category_code", "分类代码"),
    ("spec_model", "规格型号"),
    ("unit", "单位"),
    ("acquire_method", "取得方式"),
    ("source", "来源"),
    ("supplier", "供应商"),
    ("original_value", "原值(元)"),
    ("funding_source", "资金来源"),
    ("voucher_no", "入账凭证号"),
    ("is_booked", "是否已入账"),
    ("status", "状态"),
    ("manage_dept", "管理部门"),
    ("use_dept", "使用部门"),
    ("custodian_name", "保管人"),
    ("campus", "校区"),
    ("building", "楼栋"),
    ("room_name", "房间"),
    ("borrow_status", "领用状态"),
    ("acquired_date", "购置日期"),
    ("sync_status", "同步状态"),
    ("batch_no", "入库批次"),
    ("is_idle", "是否闲置"),
]

#: 扩展区列(#9):默认不导出,include_ext=true 才追加。
EXPORT_EXT_COLUMNS: list[tuple[str, str]] = [
    ("ext_remark", "扩展区备注"),
    ("ext_warranty_until", "保修到期"),
    ("ext_maintenance_contract", "维保合同"),
    ("ext_school_tags", "校内标签"),
]


def _cell_value(card: AssetCard, key: str):
    if key == "is_booked":
        return "是" if card.is_booked else "否"
    if key == "is_idle":
        return "是" if card.is_idle else "否"
    if key == "acquired_date":
        return card.acquired_date.strftime("%Y-%m-%d") if card.acquired_date else ""
    if key.startswith("ext_"):
        ext = card.ext or {}
        value = ext.get(key[4:])
        if isinstance(value, list):
            return "、".join(str(v) for v in value)
        return value if value is not None else ""
    value = getattr(card, key, None)
    if isinstance(value, float):
        return float(value)
    return value if value is not None else ""


def ledger_to_xlsx(cards: list[AssetCard], *, include_ext: bool = False) -> bytes:
    """台账导出(#9):openpyxl 同步生成,与课表导出同一模式。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "资产台账"
    columns = list(EXPORT_COLUMNS)
    if include_ext:
        columns += EXPORT_EXT_COLUMNS
    ws.append([label for _, label in columns])
    for card in cards:
        ws.append([_cell_value(card, key) for key, _ in columns])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _param_value(db: Session, key: str, default: str) -> str:
    row = db.query(AssetParam).filter_by(key=key).first()
    return row.value if row is not None else default


def parse_over_config_std(raw: str) -> dict[str, int]:
    """解析超配置标准(#14):"A0203:5,A0501:20" → {分类:上限}。"""
    std: dict[str, int] = {}
    for part in (raw or "").split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        code, limit = part.split(":", 1)
        try:
            std[code.strip()] = int(limit.strip())
        except ValueError:
            continue
    return std


def compute_idle(db: Session, *, threshold_days: int | None = None) -> list[AssetCard]:
    """闲置识别刷新(#14):规则全部可配置,不手工打标记。

    规则(任一命中即闲置):
    A. 无领用人:asset.idle.no_custodian=true 且保管人为空且未领用;
    B. 长期未使用:距 last_used_at(无则购置日期,无则建卡时间)超过
       asset.idle.days_threshold 天(默认 180);
    C. 超配置标准:asset.idle.over_config_std 形如"分类:上限",同一分类+
       管理部门件数超上限时,超出部分(按建卡时间倒序,新卡先算)记闲置。
    已核销资产不参与;命中规则消失的资产清除标记。
    """
    if threshold_days is None:
        try:
            threshold_days = int(_param_value(db, "asset.idle.days_threshold", "180"))
        except ValueError:
            threshold_days = 180
    no_custodian = _param_value(db, "asset.idle.no_custodian", "true").lower() == "true"
    over_std = parse_over_config_std(_param_value(db, "asset.idle.over_config_std", ""))
    now = datetime.now(UTC)
    cards = db.query(AssetCard).filter_by(is_retired=False).all()
    reasons: dict[int, str] = {}
    for card in cards:
        if no_custodian and not card.custodian_name and not card.custodian_user_id \
                and card.borrow_status == "未领用":
            reasons[card.id] = "无领用人"
            continue
        ref = card.last_used_at or card.acquired_date or card.created_at
        if ref is not None:
            ref_aware = ref if ref.tzinfo else ref.replace(tzinfo=UTC)
            if (now - ref_aware).days > threshold_days:
                reasons[card.id] = f"长期未使用超过{threshold_days}天"
    if over_std:
        groups: dict[tuple[str, str], list[AssetCard]] = defaultdict(list)
        for card in cards:
            groups[(card.category_code, card.manage_dept or "")].append(card)
        for (category, _dept), members in groups.items():
            limit = over_std.get(category)
            if limit is None or len(members) <= limit:
                continue
            surplus = sorted(
                members,
                key=lambda c: (c.created_at or now, c.id), reverse=True,
            )
            for card in surplus[: len(members) - limit]:
                reasons.setdefault(card.id, f"超配置标准(分类{category}上限{limit}件)")
    idle_cards: list[AssetCard] = []
    for card in cards:
        reason = reasons.get(card.id)
        if reason:
            card.is_idle = True
            card.idle_reason = reason
            idle_cards.append(card)
        elif card.is_idle:
            card.is_idle = False
            card.idle_reason = None
    db.flush()
    return idle_cards


def next_batch_no(db: Session, prefix: str, batch_type: str) -> str:
    """生成批次号:前缀 + 日期 + 当日流水,如 RK20261115-0001。"""
    today = datetime.now(UTC).strftime("%Y%m%d")
    count = db.query(AssetBatch).filter(
        AssetBatch.batch_no.like(f"{prefix}{today}%")
    ).count()
    return f"{prefix}{today}-{count + 1:04d}"


def record_batch(db: Session, user: User, batch_no: str, batch_type: str,
                 total_count: int, total_value: float | None = None,
                 note: str = "") -> AssetBatch:
    row = db.query(AssetBatch).filter_by(batch_no=batch_no).first()
    if row is None:
        row = AssetBatch(
            batch_no=batch_no, batch_type=batch_type,
            total_count=total_count, total_value=total_value,
            note=note, created_by=user.id,
        )
        db.add(row)
    else:
        row.total_count = total_count
        row.total_value = total_value
    db.flush()
    return row
