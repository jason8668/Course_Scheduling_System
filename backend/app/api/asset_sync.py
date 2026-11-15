"""同步执行与财务衔接 API(学校资产管理系统一期第 5 批 M13 #91~#104/#106、M15 #116)。

挂在 /api/asset 下。流程:待同步池 → 校验(#91) → 生成同步批次(#92,
批次号 TB-*,与勾选批次 GX-* 关联) → 二次确认(#94,confirm=true) →
按官方当期模板导出(#93,仅已勾选且校验通过的资产,扩展区不出现) →
官方导入成功后编号回填(#96,逐条冲突回告) → 结果确认(#97,失败退回
待同步池) → 已同步资产变更再同步清 pending_sync_change(#98)。

一期为模板交换,实时接口未开放:push() 仍明确拒绝(#106)。
"""

from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.asset_foundation import asset_writer, require_asset_roles
from app.core.auth import get_active_user
from app.core.db import get_db
from app.models.asset_card import AssetCard, SyncStatus
from app.models.asset_ledger import AssetSyncSelection
from app.models.asset_sync import AssetFieldMapping
from app.models.asset_sync_exec import (
    AssetSyncBatch,
    AssetSyncBatchItem,
    AssetSyncLog,
)
from app.models.user import Role, User
from app.schemas.asset_disposal_sync import (
    BackfillIn,
    BackfillResultItem,
    ConfirmIn,
    PendingChangeOut,
    ReconciliationCategoryOut,
    ReconciliationDiffOut,
    ReconciliationOut,
    SyncBatchCreate,
    SyncBatchItemOut,
    SyncBatchOut,
    SyncLogOut,
    SyncValidateItem,
    SyncValidateOut,
    UnsyncedStatOut,
)
from app.services import asset_ledger as ledger_svc
from app.services import asset_sync_exec as sync_svc
from app.services.asset_audit import log_asset_action
from app.services.asset_sync_adapter import (
    ADAPTER_BOUNDARY_NOTE,
    SYNC_EXECUTION_NOTE,
    get_adapter,
    template_version,
)

router = APIRouter(tags=["asset"])

sync_executor = require_asset_roles(Role.asset_admin)
sync_log_reader = require_asset_roles(Role.asset_admin, Role.asset_auditor)
finance_reader = require_asset_roles(Role.asset_finance, Role.asset_admin)
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _download_xlsx(data: bytes, filename: str) -> Response:
    quoted = quote(filename)
    disposition = f'attachment; filename="export.xlsx"; filename*=UTF-8\'\'{quoted}.xlsx'
    return Response(
        content=data, media_type=_XLSX_MIME,
        headers={"Content-Disposition": disposition},
    )


def _pool_cards(db: Session, selection_batch_no: str | None,
                asset_ids: list[int] | None) -> list[AssetCard]:
    """取待同步池中的资产(须 sync_status=待同步 且有 active 勾选记录)。"""
    q = db.query(AssetCard).join(
        AssetSyncSelection, AssetSyncSelection.asset_id == AssetCard.id,
    ).filter(
        AssetSyncSelection.status == "active",
        AssetCard.sync_status == SyncStatus.pending.value,
    )
    if selection_batch_no:
        q = q.filter(AssetSyncSelection.selection_batch_no == selection_batch_no)
    if asset_ids:
        q = q.filter(AssetCard.id.in_(asset_ids))
    return q.order_by(AssetCard.id).all()


def _batch_out(db: Session, batch: AssetSyncBatch,
               blocked: list[SyncValidateItem] | None = None) -> SyncBatchOut:
    items = db.query(AssetSyncBatchItem).filter_by(batch_id=batch.id).order_by(
        AssetSyncBatchItem.id).all()
    return SyncBatchOut(
        id=batch.id, batch_no=batch.batch_no,
        selection_batch_no=batch.selection_batch_no, status=batch.status,
        total_count=batch.total_count, total_value=batch.total_value,
        blocked_count=batch.blocked_count,
        items=[SyncBatchItemOut.model_validate(i) for i in items],
        blocked=blocked or [], created_at=batch.created_at,
    )


def _get_batch_or_404(db: Session, batch_id: int) -> AssetSyncBatch:
    row = db.get(AssetSyncBatch, batch_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "同步批次不存在")
    return row


def _maybe_finish_batch(db: Session, batch: AssetSyncBatch) -> None:
    """批次内无待同步明细时置已确认。"""
    pending = db.query(AssetSyncBatchItem).filter_by(
        batch_id=batch.id, status="待同步").count()
    if pending == 0 and batch.status != "已确认":
        batch.status = "已确认"


# ── #91 同步前数据校验 ──────────────────────────────
@router.get("/sync/validate", response_model=SyncValidateOut)
def validate_sync(
    selection_batch_no: str | None = None,
    asset_ids: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """同步前校验(#91):必填字段、分类映射、价值与入账凭证、取得方式、
    特性字段;缺项进拦截清单,校验不通过不得同步。asset_ids 为逗号分隔。"""
    ids = [int(x) for x in asset_ids.split(",") if x.strip()] if asset_ids else None
    cards = _pool_cards(db, selection_batch_no, ids)
    problems = get_adapter().validate(db, cards)
    blocked_ids = {p["asset_id"] for p in problems}
    log_asset_action(
        db, user, "asset_sync_validate",
        target_type="sync_batch",
        detail=f"同步前校验 {len(cards)} 件,通过 {len(cards) - len(blocked_ids)} 件,"
               f"拦截 {len(blocked_ids)} 件",
    )
    db.commit()
    return SyncValidateOut(
        passed=[c.id for c in cards if c.id not in blocked_ids],
        blocked=[SyncValidateItem(**p) for p in problems],
        total=len(cards),
    )


# ── #92/#94 生成同步批次(二次确认) ──────────────────────────────
@router.post("/sync/batches", response_model=SyncBatchOut,
             status_code=status.HTTP_201_CREATED)
def create_sync_batch(
    body: SyncBatchCreate,
    db: Session = Depends(get_db),
    user: User = Depends(sync_executor),
):
    """生成同步批次(#92/#94):须 confirm=true(二次确认),否则 400;
    显示本次件数与总价值。一批次只含校验通过的资产,拦截资产留在待同步池。
    批次号 TB-*,与勾选批次 GX-* 通过 selection_batch_no 关联。"""
    if not body.confirm:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "同步执行须二次确认:请确认本次件数与总价值后传 confirm=true",
        )
    cards = _pool_cards(db, body.selection_batch_no, body.asset_ids)
    if not cards:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "待同步池中没有可执行的资产")
    problems = get_adapter().validate(db, cards)
    blocked_ids = {p["asset_id"] for p in problems}
    passed = [c for c in cards if c.id not in blocked_ids]
    if not passed:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"全部 {len(cards)} 件校验未通过,不得同步:"
            f"{'; '.join(p['reasons'][0] if p['reasons'] else '' for p in problems[:3])}",
        )
    selection_nos = sorted({
        s.selection_batch_no for s in db.query(AssetSyncSelection).filter(
            AssetSyncSelection.asset_id.in_([c.id for c in passed]),
            AssetSyncSelection.status == "active",
        ).all()
    })
    denial = sync_svc.check_execution_separation(db, user, selection_nos)
    if denial:
        log_asset_action(
            db, user, "asset_sync_execute_denied",
            target_type="sync_batch", detail=f"同步执行分岗拦截:{denial}",
        )
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, denial)
    batch_no = ledger_svc.next_batch_no(db, "TB", "sync_batch")
    total_value = sum(float(c.original_value or 0) for c in passed)
    batch = AssetSyncBatch(
        batch_no=batch_no,
        selection_batch_no=body.selection_batch_no or ",".join(selection_nos),
        status="已导出", total_count=len(passed), total_value=total_value,
        blocked_count=len(blocked_ids), created_by=user.id,
        executed_by=user.id, executed_at=datetime.now(),
        note="一期为模板交换,实时接口未开放",
    )
    db.add(batch)
    db.flush()
    for card in passed:
        db.add(AssetSyncBatchItem(
            batch_id=batch.id, asset_id=card.id,
            asset_code=card.asset_code, status="待同步",
        ))
        sel = db.query(AssetSyncSelection).filter_by(
            asset_id=card.id, status="active").first()
        if sel is not None:
            sel.status = "executed"
        sync_svc.log_sync(
            db, user, action="生成批次", batch_no=batch_no, asset=card,
            detail=f"资产 {card.asset_code} 进入同步批次 {batch_no}",
        )
    for p in problems:
        card = db.get(AssetCard, p["asset_id"])
        sync_svc.log_sync(
            db, user, action="校验", batch_no=batch_no, asset=card,
            result="拦截",
            detail=f"资产 {p['asset_code']} 校验拦截:{'; '.join(p['reasons'])}",
        )
    ledger_svc.record_batch(
        db, user, batch_no, "sync_batch", len(passed), total_value,
        note="同步执行批次",
    )
    log_asset_action(
        db, user, "asset_sync_batch_create",
        target_type="sync_batch", target_id=batch.id,
        detail=f"生成同步批次 {batch_no} {len(passed)} 件总价值{total_value:.2f}元,"
               f"拦截 {len(blocked_ids)} 件留池",
    )
    db.commit()
    db.refresh(batch)
    return _batch_out(db, batch, blocked=[SyncValidateItem(**p) for p in problems])


@router.get("/sync/batches", response_model=list[SyncBatchOut])
def list_sync_batches(
    batch_status: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    q = db.query(AssetSyncBatch).order_by(AssetSyncBatch.id.desc())
    if batch_status:
        q = q.filter_by(status=batch_status)
    return [_batch_out(db, b) for b in q.all()]


@router.get("/sync/batches/{batch_id}", response_model=SyncBatchOut)
def get_sync_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    return _batch_out(db, _get_batch_or_404(db, batch_id))


# ── #93 按官方模板导出所选资产 ──────────────────────────────
@router.get("/sync/batches/{batch_id}/export")
def export_sync_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(sync_executor),
):
    """按官方当期模板导出(#93):仅本批次已勾选且校验通过的资产;
    扩展区(never_sync)不得出现在导出文件中;未勾选资产不出现。"""
    batch = _get_batch_or_404(db, batch_id)
    items = db.query(AssetSyncBatchItem).filter_by(batch_id=batch.id).all()
    cards = []
    for item in items:
        card = db.get(AssetCard, item.asset_id)
        if card is not None and not card.is_retired:
            cards.append(card)
    data = get_adapter().export_template(db, cards)
    sync_svc.log_sync(
        db, user, action="执行导出", batch_no=batch.batch_no,
        detail=f"按官方当期模板导出 {len(cards)} 件(批次 {batch.batch_no})",
    )
    log_asset_action(
        db, user, "asset_sync_export",
        target_type="sync_batch", target_id=batch.id,
        detail=f"导出同步批次 {batch.batch_no} {len(cards)} 件",
    )
    db.commit()
    return _download_xlsx(data, f"同步批次-{batch.batch_no}")


# ── #96 官方编号批量回填 ──────────────────────────────
@router.post("/sync/batches/{batch_id}/backfill", response_model=list[BackfillResultItem])
def backfill_official_codes(
    batch_id: int,
    body: BackfillIn,
    db: Session = Depends(get_db),
    user: User = Depends(sync_executor),
):
    """官方编号批量回填(#96):逐条校验,官方编号重复、与他人资产冲突时
    逐条回告,冲突件不回填;未同步资产不回填;回填后 sync_status → 已同步,
    建立双号索引(asset_code ↔ official_code)。"""
    batch = _get_batch_or_404(db, batch_id)
    results: list[BackfillResultItem] = []
    seen: set[str] = set()
    for item_in in body.items:
        item = db.query(AssetSyncBatchItem).filter_by(
            batch_id=batch.id, asset_id=item_in.asset_id).first()
        if item is None:
            results.append(BackfillResultItem(
                asset_id=item_in.asset_id, ok=False,
                reason="该资产不在本同步批次中", official_code=item_in.official_code))
            continue
        card = db.get(AssetCard, item_in.asset_id)
        if card is None:
            results.append(BackfillResultItem(
                asset_id=item_in.asset_id, ok=False, reason="资产不存在",
                official_code=item_in.official_code))
            continue
        if item_in.official_code in seen:
            results.append(BackfillResultItem(
                asset_id=card.id, asset_code=card.asset_code, ok=False,
                reason=f"官方编号 {item_in.official_code} 在本批次内重复",
                official_code=item_in.official_code))
            continue
        conflict = db.query(AssetCard).filter(
            AssetCard.official_code == item_in.official_code,
            AssetCard.id != card.id,
        ).first()
        if conflict is not None:
            results.append(BackfillResultItem(
                asset_id=card.id, asset_code=card.asset_code, ok=False,
                reason=f"官方编号 {item_in.official_code} 已被资产 "
                       f"{conflict.asset_code} 占用",
                official_code=item_in.official_code))
            sync_svc.log_sync(
                db, user, action="编号回填", batch_no=batch.batch_no, asset=card,
                result="失败",
                detail=f"官方编号 {item_in.official_code} 冲突,未回填",
            )
            continue
        seen.add(item_in.official_code)
        card.official_code = item_in.official_code
        card.sync_status = SyncStatus.synced.value
        item.official_code = item_in.official_code
        item.status = "已同步"
        sync_svc.clear_pending_sync_change(db, user, card)
        sync_svc.log_sync(
            db, user, action="编号回填", batch_no=batch.batch_no, asset=card,
            detail=f"回填官方编号 {item_in.official_code},双号索引建立",
        )
        results.append(BackfillResultItem(
            asset_id=card.id, asset_code=card.asset_code, ok=True,
            official_code=item_in.official_code))
    _maybe_finish_batch(db, batch)
    log_asset_action(
        db, user, "asset_sync_backfill",
        target_type="sync_batch", target_id=batch.id,
        detail=f"编号回填批次 {batch.batch_no} "
               f"成功 {sum(1 for r in results if r.ok)} 件,"
               f"失败 {sum(1 for r in results if not r.ok)} 件",
    )
    db.commit()
    return results


# ── #97 同步结果确认 ──────────────────────────────
@router.post("/sync/batches/{batch_id}/confirm", response_model=SyncBatchOut)
def confirm_sync_batch(
    batch_id: int,
    body: ConfirmIn,
    db: Session = Depends(get_db),
    user: User = Depends(sync_executor),
):
    """逐批确认同步成功/失败(#97):失败资产标注原因、退回待同步池
    (sync_status → 同步失败,修正后可重新勾选;重新勾选时 同步失败 → 待同步)。"""
    batch = _get_batch_or_404(db, batch_id)
    for result in body.results:
        item = db.query(AssetSyncBatchItem).filter_by(
            batch_id=batch.id, asset_id=result.asset_id).first()
        if item is None:
            continue
        card = db.get(AssetCard, result.asset_id)
        if card is None:
            continue
        if result.ok:
            item.status = "已同步"
            card.sync_status = SyncStatus.synced.value
            sync_svc.clear_pending_sync_change(db, user, card)
            sync_svc.log_sync(
                db, user, action="结果确认", batch_no=batch.batch_no, asset=card,
                detail="同步成功确认",
            )
        else:
            item.status = "同步失败"
            item.fail_reason = result.reason or "同步失败"
            card.sync_status = SyncStatus.failed.value
            sync_svc.log_sync(
                db, user, action="结果确认", batch_no=batch.batch_no, asset=card,
                result="失败",
                detail=f"同步失败退回待同步池:{item.fail_reason}",
            )
    _maybe_finish_batch(db, batch)
    log_asset_action(
        db, user, "asset_sync_confirm",
        target_type="sync_batch", target_id=batch.id,
        detail=f"同步结果确认批次 {batch.batch_no}",
    )
    db.commit()
    db.refresh(batch)
    return _batch_out(db, batch)


# ── #98 待同步变更清单 ──────────────────────────────
@router.get("/sync/pending-changes", response_model=list[PendingChangeOut])
def list_pending_changes(
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """已同步资产变更手动再同步(#98):只提示待同步变更,不自动推送;
    须重新勾选并确认后才同步变更。"""
    cards = db.query(AssetCard).filter_by(pending_sync_change=True).order_by(
        AssetCard.id).all()
    return [PendingChangeOut(
        asset_id=c.id, asset_code=c.asset_code, name=c.name,
        sync_status=c.sync_status,
        pending_sync_change_reason=c.pending_sync_change_reason,
    ) for c in cards]


# ── #100 未同步资产单独统计 ──────────────────────────────
@router.get("/sync/unsynced-stats", response_model=list[UnsyncedStatOut])
def unsynced_stats(
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """未同步资产隔离管理(#100):未同步资产仅校内管理,不进入上报文件、
    不计入月报/年报上报口径;本端点按分类汇总件数/总价值供校内统计。"""
    from sqlalchemy import func as _func

    rows = db.query(
        AssetCard.category_code,
        _func.count(AssetCard.id),
        _func.coalesce(_func.sum(AssetCard.original_value), 0),
    ).filter(AssetCard.sync_status == SyncStatus.unsynced.value).group_by(
        AssetCard.category_code).order_by(AssetCard.category_code).all()
    return [UnsyncedStatOut(
        category_code=r[0], count=r[1], total_value=float(r[2] or 0),
    ) for r in rows]


# ── #102 同步日志查询(只读,无删除) ──────────────────────────────
@router.get("/sync/logs", response_model=list[SyncLogOut])
def list_sync_logs(
    batch_no: str | None = None,
    asset_id: int | None = None,
    operator_id: int | None = None,
    action: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(sync_log_reader),
):
    """同步日志(#102):按批次/资产/操作人/动作筛选;日志不可删除,无删除接口。"""
    q = db.query(AssetSyncLog).order_by(AssetSyncLog.id.desc())
    if batch_no:
        q = q.filter_by(batch_no=batch_no)
    if asset_id is not None:
        q = q.filter_by(asset_id=asset_id)
    if operator_id is not None:
        q = q.filter_by(operator_id=operator_id)
    if action:
        q = q.filter_by(action=action)
    return q.limit(limit).all()


# ── #103 待同步积压提醒(只提醒,不执行) ──────────────────────────────
@router.post("/sync/scan-backlog", response_model=dict)
def scan_backlog(
    db: Session = Depends(get_db),
    user: User = Depends(sync_executor),
):
    """待同步积压提醒(#103):手动触发的扫描端点,未挂定时 worker。
    积压阈值参数 sync.backlog_days(默认 14 天);只提醒,不自动执行同步。"""
    result = sync_svc.scan_sync_backlog(db, user)
    log_asset_action(
        db, user, "asset_sync_backlog_scan",
        target_type="sync_backlog",
        detail=f"积压提醒扫描:提醒批次 {result['reminded_batches']},"
               f"{result['asset_count']} 件",
    )
    db.commit()
    return result


# ── #106 对接边界说明 ──────────────────────────────
@router.get("/sync/boundary", response_model=dict)
def get_sync_boundary(
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """对接边界说明(#106):官方账号、权限、模板版本与开放政策由财政/
    主管部门决定;模板变更运维期免费适配,不承诺未开放接口在特定期限内开通。"""
    return {
        "live_api": False,
        "adapter": "template_export",
        "template_version": template_version(db),
        "boundary_note": ADAPTER_BOUNDARY_NOTE,
        "execution_note": SYNC_EXECUTION_NOTE,
        "mapping_count": db.query(AssetFieldMapping).filter_by(
            is_active=True).count(),
    }


# ── #116 财务衔接:月度对账清单(只读) ──────────────────────────────
def _reconciliation(db: Session, month: str) -> ReconciliationOut:
    from sqlalchemy import func as _func

    cards = db.query(AssetCard).filter(AssetCard.is_retired.is_(False)).all()
    by_cat: dict[str, dict] = {}
    differences: list[ReconciliationDiffOut] = []
    for card in cards:
        entry = by_cat.setdefault(card.category_code, {
            "synced_count": 0, "synced_original_value": 0.0,
            "synced_net_value": 0.0, "all_count": 0,
            "all_original_value": 0.0, "all_accumulated_depreciation": 0.0,
            "all_net_value": 0.0,
        })
        original = float(card.original_value or 0)
        accum = float(card.accumulated_depreciation or 0)
        net = float(card.net_value) if card.net_value is not None else None
        entry["all_count"] += 1
        entry["all_original_value"] += original
        entry["all_accumulated_depreciation"] += accum
        entry["all_net_value"] += net if net is not None else original - accum
        if card.sync_status == SyncStatus.synced.value:
            entry["synced_count"] += 1
            entry["synced_original_value"] += original
            entry["synced_net_value"] += net if net is not None else original - accum
        expected = round(original - accum, 2)
        if net is not None and abs(round(net, 2) - expected) > 0.01:
            differences.append(ReconciliationDiffOut(
                asset_id=card.id, asset_code=card.asset_code, name=card.name,
                category_code=card.category_code, sync_status=card.sync_status,
                voucher_no=card.voucher_no, original_value=original,
                accumulated_depreciation=accum, net_value=net,
                expected_net_value=expected,
                reason="净值与原值-累计折旧不符",
            ))
        elif not card.is_booked:
            differences.append(ReconciliationDiffOut(
                asset_id=card.id, asset_code=card.asset_code, name=card.name,
                category_code=card.category_code, sync_status=card.sync_status,
                voucher_no=card.voucher_no, original_value=original,
                accumulated_depreciation=accum, net_value=net,
                expected_net_value=expected,
                reason="未回填入账凭证号",
            ))
        elif card.original_value is None:
            differences.append(ReconciliationDiffOut(
                asset_id=card.id, asset_code=card.asset_code, name=card.name,
                category_code=card.category_code, sync_status=card.sync_status,
                voucher_no=card.voucher_no, original_value=None,
                accumulated_depreciation=accum, net_value=net,
                expected_net_value=expected,
                reason="原值缺失",
            ))
    categories = [ReconciliationCategoryOut(
        category_code=code, **values,
    ) for code, values in sorted(by_cat.items())]
    return ReconciliationOut(
        month=month, categories=categories,
        differences=differences[:500],
        note="与财务以对账清单衔接,不做财务核算与凭证生成;本清单只读,不写财务系统。"
             "月报/年报上报口径只统计已同步资产(synced_* 列),未同步资产只在校内口径统计。",
    )


@router.get("/finance/reconciliation", response_model=ReconciliationOut)
def get_reconciliation(
    month: str = Query(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(finance_reader),
):
    """月度对账清单(#116):按分类汇总原值、折旧、净值(以资产卡财务信息区为准),
    差异逐条定位到卡片与凭证号。month 格式 YYYY-MM,缺省为当月。"""
    month = month or datetime.now().strftime("%Y-%m")
    return _reconciliation(db, month)


@router.get("/finance/reconciliation/export")
def export_reconciliation(
    month: str = Query(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(finance_reader),
):
    """导出月度对账清单 Excel(#116)。"""
    from openpyxl import Workbook

    month = month or datetime.now().strftime("%Y-%m")
    data = _reconciliation(db, month)
    wb = Workbook()
    ws = wb.active
    ws.title = "对账清单"
    ws.append(["分类代码", "已同步件数", "已同步原值", "已同步净值",
               "校内件数", "校内原值", "累计折旧", "校内净值"])
    for cat in data.categories:
        ws.append([cat.category_code, cat.synced_count, cat.synced_original_value,
                   cat.synced_net_value, cat.all_count, cat.all_original_value,
                   cat.all_accumulated_depreciation, cat.all_net_value])
    ws2 = wb.create_sheet("差异清单")
    ws2.append(["资产编号", "名称", "分类", "同步状态", "凭证号",
                "原值", "累计折旧", "净值", "应为净值", "差异原因"])
    for diff in data.differences:
        ws2.append([diff.asset_code, diff.name, diff.category_code,
                    diff.sync_status, diff.voucher_no or "",
                    diff.original_value, diff.accumulated_depreciation,
                    diff.net_value, diff.expected_net_value, diff.reason])
    import io

    buf = io.BytesIO()
    wb.save(buf)
    return _download_xlsx(buf.getvalue(), f"月度对账清单-{month}")
