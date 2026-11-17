"""手动勾选核心 API(学校资产管理系统一期第 2 批 #87~#90)。

挂在 /api/asset 下。本批只做勾选与池子管理,不做导出/回填(B5 #92~#97)。
勾选/取消单独授权:仅资产管理员及授权岗(require_asset_roles
asset_admin;admin 为超级用户一律通过)。sync.separation_of_duties
参数为分岗配置位,本批只做权限检查,不做执行分岗(执行在 B5)。
勾选校验:已同步/已核销/未回填凭证号(is_booked=False)的不得勾选,
逐条回告原因。取消勾选后 sync_status 回到 未同步,不影响校内台账,
不产生上报记录(#89)。
"""

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import get_active_user
from app.core.db import get_db
from app.models.asset_card import AssetCard, SyncStatus
from app.models.asset_ledger import AssetSyncSelection
from app.models.user import User
from app.schemas.asset_ledger import (
    BulkItemResult,
    BulkResultOut,
    SyncPoolItemOut,
    SyncPoolOut,
    SyncSelectByFilterIn,
    SyncSelectIn,
)
from app.services import asset_ledger as ledger_svc
from app.services.asset_audit import log_asset_action
from app.api.asset_foundation import require_asset_roles
from app.models.user import Role

router = APIRouter(tags=["asset"])

#: 同步勾选单独授权(#101):仅资产管理员及授权岗;admin 一律通过。
sync_selector = require_asset_roles(Role.asset_admin)


def _check_selectable(card: AssetCard) -> str | None:
    """勾选前逐条校验(#88):返回 None 表示可勾选,否则为拦截原因。"""
    if card.is_retired:
        return "资产已核销,不可勾选"
    if card.sync_status == SyncStatus.synced.value:
        return "资产已同步,无需重复勾选"
    if card.sync_status == SyncStatus.pending.value:
        return "资产已在待同步池,无需重复勾选"
    if card.sync_status == SyncStatus.syncing.value:
        return "资产正在同步中,不可勾选"
    if not card.is_booked:
        return "未回填入账凭证号,禁止同步"
    return None


def _do_select(db: Session, user: User, card: AssetCard,
               selection_batch_no: str) -> None:
    """单件勾选(#87):sync_status 未同步 → 待同步,写勾选记录 + 审计。"""
    before = {"sync_status": card.sync_status}
    card.sync_status = SyncStatus.pending.value
    db.add(AssetSyncSelection(
        asset_id=card.id, selection_batch_no=selection_batch_no,
        selected_by=user.id,
    ))
    db.flush()
    log_asset_action(
        db, user, "asset_sync_select",
        target_type="asset_card", target_id=card.id,
        detail=f"勾选同步 {card.asset_code} 批次{selection_batch_no}",
        before=before, after={"sync_status": SyncStatus.pending.value},
    )


def _select_many(db: Session, user: User, cards: list[AssetCard],
                 ) -> BulkResultOut:
    batch_no = ledger_svc.next_batch_no(db, "GX", "sync_select")
    succeeded: list[BulkItemResult] = []
    failed: list[BulkItemResult] = []
    total_value = 0.0
    for card in cards:
        reason = _check_selectable(card)
        if reason:
            failed.append(BulkItemResult(
                asset_id=card.id, asset_code=card.asset_code,
                ok=False, reason=reason))
            continue
        try:
            with db.begin_nested():
                _do_select(db, user, card, batch_no)
        except Exception as e:
            failed.append(BulkItemResult(
                asset_id=card.id, asset_code=card.asset_code,
                ok=False, reason=f"勾选失败:{e}"))
            continue
        total_value += float(card.original_value or 0)
        succeeded.append(BulkItemResult(
            asset_id=card.id, asset_code=card.asset_code, ok=True))
    if succeeded:
        ledger_svc.record_batch(
            db, user, batch_no, "sync_select", len(succeeded),
            total_value, note="手动勾选同步",
        )
    db.commit()
    return BulkResultOut(succeeded=succeeded, failed=failed, batch_no=batch_no)


# ── 单件勾选 #87 ──────────────────────────────
@router.post("/sync/select", response_model=BulkResultOut)
def select_for_sync(
    body: SyncSelectIn,
    db: Session = Depends(get_db),
    user: User = Depends(sync_selector),
):
    """单件勾选同步(#87):逐件勾选,记审计(谁、何时、勾选了哪件)。"""
    cards: list[AssetCard] = []
    failed: list[BulkItemResult] = []
    for asset_id in body.asset_ids:
        card = db.get(AssetCard, asset_id)
        if card is None:
            failed.append(BulkItemResult(asset_id=asset_id, ok=False, reason="资产不存在"))
        else:
            cards.append(card)
    result = _select_many(db, user, cards)
    result.failed = failed + result.failed
    return result


# ── 批量勾选 #88 ──────────────────────────────
@router.post("/sync/select-by-filter", response_model=BulkResultOut)
def select_by_filter(
    body: SyncSelectByFilterIn,
    db: Session = Depends(get_db),
    user: User = Depends(sync_selector),
):
    """批量勾选同步(#88):按部门/分类/房间/入库批次/价值区间筛选后批量
    勾选;逐条校验,失败逐条回告原因。跨页选择由调用方传全部 id 或
    用本接口按条件全量勾选,前端另做全选本页/反选。"""
    from app.schemas.asset_ledger import AssetSearchParams

    params = AssetSearchParams(
        category_code=body.category_code, manage_dept=body.manage_dept,
        room_id=body.room_id, batch_no=body.batch_no,
        min_value=body.min_value, max_value=body.max_value,
        sync_status=body.sync_status, status=body.status, q=body.q,
        limit=5000, offset=0,
    )
    try:
        q = ledger_svc.build_asset_query(db, params)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    # 原值区间不在 SQL 里筛(密文列,见 asset_ledger.apply_value_range),
    # 取回后在 Python 侧解密后筛。
    return _select_many(db, user, ledger_svc.apply_value_range(q.all(), params))


# ── 取消/撤回勾选 #89 ──────────────────────────────
@router.post("/sync/unselect", response_model=BulkResultOut)
def unselect_for_sync(
    body: SyncSelectIn,
    db: Session = Depends(get_db),
    user: User = Depends(sync_selector),
):
    """取消/撤回勾选(#89):未执行同步前可随时取消,sync_status 回到
    未同步,不影响校内台账,不产生上报记录。"""
    succeeded: list[BulkItemResult] = []
    failed: list[BulkItemResult] = []
    for asset_id in body.asset_ids:
        card = db.get(AssetCard, asset_id)
        if card is None:
            failed.append(BulkItemResult(asset_id=asset_id, ok=False, reason="资产不存在"))
            continue
        if card.sync_status != SyncStatus.pending.value:
            failed.append(BulkItemResult(
                asset_id=asset_id, asset_code=card.asset_code,
                ok=False, reason=f"资产同步状态为{card.sync_status},不在待同步池"))
            continue
        before = {"sync_status": card.sync_status}
        card.sync_status = SyncStatus.unsynced.value
        sel = db.query(AssetSyncSelection).filter_by(
            asset_id=card.id, status="active").first()
        if sel is not None:
            from datetime import UTC, datetime

            sel.status = "cancelled"
            sel.cancelled_by = user.id
            sel.cancelled_at = datetime.now(UTC)
        log_asset_action(
            db, user, "asset_sync_unselect",
            target_type="asset_card", target_id=card.id,
            detail=f"取消勾选 {card.asset_code} 回到未同步",
            before=before, after={"sync_status": SyncStatus.unsynced.value},
        )
        succeeded.append(BulkItemResult(
            asset_id=card.id, asset_code=card.asset_code, ok=True))
    db.commit()
    return BulkResultOut(succeeded=succeeded, failed=failed)


# ── 待同步清单管理 #90 ──────────────────────────────
@router.get("/sync/pool", response_model=SyncPoolOut)
def get_sync_pool(
    selection_batch_no: str | None = None,
    manage_dept: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """待同步池(#90):清单、件数、总价值、勾选人、勾选时间,按勾选批次分组。"""
    q = db.query(AssetSyncSelection, AssetCard).join(
        AssetCard, AssetSyncSelection.asset_id == AssetCard.id
    ).filter(AssetSyncSelection.status == "active")
    if selection_batch_no:
        q = q.filter(AssetSyncSelection.selection_batch_no == selection_batch_no)
    if manage_dept:
        q = q.filter(AssetCard.manage_dept == manage_dept)
    rows = q.order_by(AssetSyncSelection.selected_at.desc()).all()
    items: list[SyncPoolItemOut] = []
    total_value = 0.0
    groups: dict[str, dict] = defaultdict(lambda: {"count": 0, "total_value": 0.0})
    for sel, card in rows:
        value = float(card.original_value or 0)
        total_value += value
        groups[sel.selection_batch_no]["count"] += 1
        groups[sel.selection_batch_no]["total_value"] += value
        items.append(SyncPoolItemOut(
            asset_id=card.id, asset_code=card.asset_code, name=card.name,
            category_code=card.category_code, manage_dept=card.manage_dept,
            original_value=card.original_value, sync_status=card.sync_status,
            selected_by=sel.selected_by, selected_at=sel.selected_at,
            selection_batch_no=sel.selection_batch_no,
        ))
    return SyncPoolOut(
        items=items, total=len(items), total_value=total_value,
        groups={k: {"count": v["count"], "total_value": v["total_value"]}
                for k, v in groups.items()},
    )
