"""同步执行服务(学校资产管理系统一期第 5 批 M13 #92/#97/#98/#101/#102/#103)。

- 同步日志:每次勾选/取消/执行/回填记入 asset_sync_logs,无删除接口。
- 分岗参数 sync.separation_of_duties(默认 true):勾选人与执行人不得同一人。
- 积压提醒:待同步池超过 sync.backlog_days(默认 14 天)未执行,只提醒
  (写 asset_reminders kind=同步待处理 + 钉钉推送),永不自动执行同步。
"""

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.asset_card import AssetCard, SyncStatus
from app.models.asset_config import AssetParam
from app.models.asset_ledger import AssetSyncSelection
from app.models.asset_sync_exec import AssetSyncLog
from app.models.user import Role, User, UserRole
from app.services import asset_circulation as circ_svc
from app.services import asset_notify as notify_svc


def log_sync(
    db: Session, user: User | None, *, action: str, batch_no: str | None = None,
    asset: AssetCard | None = None, result: str = "成功", detail: str = "",
) -> AssetSyncLog:
    """写一条同步日志(#102)。"""
    row = AssetSyncLog(
        action=action, batch_no=batch_no,
        asset_id=asset.id if asset else None,
        asset_code=asset.asset_code if asset else None,
        operator_id=user.id if user else None,
        operator_name=(user.display_name or user.username) if user else "",
        result=result, detail=detail,
    )
    db.add(row)
    db.flush()
    return row


def param_bool(db: Session, key: str, default: bool) -> bool:
    row = db.query(AssetParam).filter_by(key=key).first()
    if row is None:
        return default
    return str(row.value).strip().lower() in ("true", "1", "yes")


def param_int(db: Session, key: str, default: int) -> int:
    return circ_svc.param_int(db, key, default)


def check_execution_separation(
    db: Session, executor: User, selection_batch_nos: list[str],
) -> str | None:
    """分岗检查(#101):参数为 true 时,勾选人与执行人不得同一人。

    返回 None 表示通过,否则为拦截原因。
    """
    if not param_bool(db, "sync.separation_of_duties", True):
        return None
    rows = db.query(AssetSyncSelection).filter(
        AssetSyncSelection.selection_batch_no.in_(selection_batch_nos),
        AssetSyncSelection.status == "active",
    ).all()
    selectors = {r.selected_by for r in rows}
    if executor.id in selectors:
        return "同步勾选与执行分岗:勾选人不得执行本次同步,请换人执行"
    return None


def clear_pending_sync_change(db: Session, user: User, card: AssetCard) -> None:
    """同步执行成功后清掉 B3 的待同步变更标记(#98)。"""
    if not card.pending_sync_change:
        return
    card.pending_sync_change = False
    card.pending_sync_change_reason = None
    log_sync(
        db, user, action="待同步变更清除", asset=card,
        detail=f"资产 {card.asset_code} 变更已同步,清除待同步变更标记",
    )


def scan_sync_backlog(db: Session, user: User | None = None) -> dict:
    """待同步积压提醒(#103):只提醒,不自动执行同步。

    待同步池中勾选超过 sync.backlog_days(默认 14 天)未执行的资产,
    按勾选批次给每位资产管理员写一条 kind=同步待处理 提醒并钉钉推送。
    同一批次未读提醒已存在时不重复建(走 create_reminder 去重)。
    """
    threshold_days = param_int(db, "sync.backlog_days", 14)
    cutoff = datetime.now(UTC) - timedelta(days=threshold_days)
    stale = db.query(AssetSyncSelection).filter(
        AssetSyncSelection.status == "active",
        AssetSyncSelection.selected_at < cutoff,
    ).all()
    if not stale:
        return {"reminded_batches": [], "asset_count": 0, "threshold_days": threshold_days}
    batches: dict[str, list[AssetSyncSelection]] = {}
    for sel in stale:
        batches.setdefault(sel.selection_batch_no, []).append(sel)
    admin_ids = sorted({
        r.user_id for r in
        db.query(UserRole).filter_by(role=Role.asset_admin.value).all()
    })
    reminded: list[str] = []
    for batch_no, sels in batches.items():
        total_value = 0.0
        for sel in sels:
            card = db.get(AssetCard, sel.asset_id)
            if card is not None:
                total_value += float(card.original_value or 0)
        for admin_id in admin_ids:
            circ_svc.create_reminder(
                db, kind="同步待处理", user_id=admin_id,
                target_type="sync_selection_batch", target_id=None,
                title=f"待同步积压提醒:批次 {batch_no} 已 {threshold_days} 天未执行",
                content=f"待同步池批次 {batch_no} 有 {len(sels)} 件、"
                        f"总价值 {total_value:.2f} 元已超过 {threshold_days} 天未执行同步,"
                        f"请及时处理(只提醒,不自动执行)。",
                level="一般",
            )
        log_sync(
            db, user, action="积压提醒", batch_no=batch_no,
            detail=f"批次 {batch_no} {len(sels)} 件积压超 {threshold_days} 天,"
                   f"已提醒 {len(admin_ids)} 位资产管理员",
        )
        reminded.append(batch_no)
    if admin_ids:
        notify_svc.push_to_role(
            db, Role.asset_admin.value, "待同步积压提醒",
            f"{len(reminded)} 个同步批次已超过 {threshold_days} 天未执行,请及时处理。",
        )
    return {"reminded_batches": reminded, "asset_count": len(stale),
            "threshold_days": threshold_days}
