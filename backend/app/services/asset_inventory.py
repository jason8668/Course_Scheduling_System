"""第 4 批共用服务:保修状态、盘点方案号、范围匹配、五类差异比对、
盘盈补记(#24 入口复用)、盘点到期扫描。

- 保修状态解析与 B3 scan_warranty 同一口径:ext.warranty_until 支持
  ISO 日期时间与 YYYY-MM-DD 两种写法,无法解析视为无保修信息。
- 差异比对是纯计算:只重建本任务下 待处理 的差异,已处理 的差异保留
  且其资产不再参与重建,避免处理完的差异被重复生成。
- 盘盈补记复用 #24 入口逻辑:建 inventory_surplus 验收单(已核实即
  验收依据,状态直接记验收通过) + 同一 create_asset_card 建卡,
  与 POST /acceptances → confirm → create-cards 同一建卡标准,
  sync_status 强制 未同步。
"""

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.asset_card import AssetCard, SyncStatus
from app.models.asset_circulation import AssetReminder
from app.models.asset_inventory import (
    AssetInventoryDifference,
    AssetInventoryPlan,
    AssetInventoryRecord,
    AssetInventoryTask,
    InventoryDiffStatus,
    InventoryDiffType,
)
from app.models.asset_ledger import AcceptanceStatus, AssetAcceptance, IntakeType
from app.models.user import User
from app.services import asset_foundation as asset_svc
from app.services.asset_audit import log_asset_action
from app.services.asset_circulation import create_reminder, param_int
from app.services.asset_ledger import next_batch_no

logger = logging.getLogger(__name__)


def parse_warranty_until(raw: object) -> datetime | None:
    """解析 ext.warranty_until:ISO 或 YYYY-MM-DD,解析失败返回 None。"""
    if not raw:
        return None
    try:
        until = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        try:
            until = datetime.strptime(str(raw), "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            return None
    if until.tzinfo is None:
        until = until.replace(tzinfo=UTC)
    return until


def warranty_info(card: AssetCard) -> dict:
    """保修状态(#42):保修截止日、是否保内、保内提示文案。"""
    until = parse_warranty_until((card.ext or {}).get("warranty_until"))
    if until is None:
        return {"warranty_until": None, "in_warranty": False,
                "warranty_hint": "未登记保修截止日,无法判断保内状态"}
    in_warranty = until.date() >= datetime.now(UTC).date()
    hint = (f"保内故障,请走厂商保修(保修至 {until.strftime('%Y-%m-%d')})"
            if in_warranty
            else f"已过保(保修至 {until.strftime('%Y-%m-%d')}),按校内维修流程处理")
    return {"warranty_until": until.strftime("%Y-%m-%d"),
            "in_warranty": in_warranty, "warranty_hint": hint}


def repair_threshold(db: Session) -> float:
    """超阈值维修审批门槛(#43):参数 approval.repair_threshold,默认 5000 元。"""
    return float(param_int(db, "approval.repair_threshold", 5000))


def next_plan_no(db: Session) -> str:
    """盘点方案号:PD-YYYYMMDD-XXXX。"""
    day = datetime.now(UTC).strftime("%Y%m%d")
    like = f"PD-{day}%"
    count = db.query(AssetInventoryPlan).filter(
        AssetInventoryPlan.plan_no.like(like)).count()
    return f"PD-{day}-{count + 1:04d}"


def task_matches_card(task: AssetInventoryTask, card: AssetCard) -> bool:
    """任务范围匹配(#48/#49):部门/房间/分类均为"且",空字段不限。

    部门按管理部门或使用部门任一匹配;分类按代码前缀匹配(支持按分类段抽盘)。
    """
    if task.scope_dept and task.scope_dept not in (
            card.manage_dept, card.use_dept):
        return False
    if task.scope_room_name and card.room_name != task.scope_room_name:
        return False
    if task.scope_category_code and not card.category_code.startswith(
            task.scope_category_code):
        return False
    return True


def expected_cards(db: Session, task: AssetInventoryTask) -> list[AssetCard]:
    """任务应盘台账:未核销且在范围内的全部资产卡。"""
    cards = db.query(AssetCard).filter_by(is_retired=False).all()
    return [c for c in cards if task_matches_card(task, c)]


def compute_diffs(db: Session, task: AssetInventoryTask) -> dict[str, int]:
    """五类差异自动比对(#51):重建本任务下 待处理 的差异。

    正常/位置不符/保管人不符:已扫且在台账范围内,按实盘位置与保管人比对
    (位置优先于保管人,一件资产只记一类差异);盘亏:应盘未扫;
    盘盈:未贴标补录记录(台账无此资产,待核实)。
    已处理的差异保留,其资产不再参与重建。
    """
    resolved_asset_ids = {
        d.asset_id for d in db.query(AssetInventoryDifference).filter_by(
            task_id=task.id, status=InventoryDiffStatus.RESOLVED).all()
        if d.asset_id is not None
    }
    db.query(AssetInventoryDifference).filter_by(
        task_id=task.id, status=InventoryDiffStatus.PENDING).delete(
        synchronize_session=False)
    db.flush()
    expected = [c for c in expected_cards(db, task)
                if c.id not in resolved_asset_ids]
    records = db.query(AssetInventoryRecord).filter_by(task_id=task.id).all()
    scanned: dict[int, AssetInventoryRecord] = {}
    for rec in records:
        if rec.asset_id is not None and rec.asset_id not in scanned:
            scanned[rec.asset_id] = rec
    counts = {t: 0 for t in (
        InventoryDiffType.NORMAL, InventoryDiffType.SHORTAGE,
        InventoryDiffType.SURPLUS, InventoryDiffType.LOCATION_MISMATCH,
        InventoryDiffType.CUSTODIAN_MISMATCH)}

    def _add(card: AssetCard | None, diff_type: str, detail: str,
             asset_code: str | None = None, asset_name: str | None = None):
        row = AssetInventoryDifference(
            plan_id=task.plan_id, task_id=task.id,
            asset_id=card.id if card else None,
            asset_code=asset_code or (card.asset_code if card else None),
            asset_name=asset_name or (card.name if card else None),
            diff_type=diff_type, detail=detail,
            involves_synced=bool(
                card and card.sync_status == SyncStatus.synced.value),
        )
        db.add(row)
        counts[diff_type] += 1

    for card in expected:
        rec = scanned.get(card.id)
        if rec is None:
            _add(card, InventoryDiffType.SHORTAGE,
                 f"台账有、实盘无:未扫到 {card.asset_code}")
            continue
        if rec.room_name and card.room_name and rec.room_name != card.room_name:
            _add(card, InventoryDiffType.LOCATION_MISMATCH,
                 f"实盘位置 {rec.room_name} 与台账 {card.room_name} 不符")
        elif (rec.custodian_id is not None and card.custodian_user_id is not None
                and rec.custodian_id != card.custodian_user_id):
            _add(card, InventoryDiffType.CUSTODIAN_MISMATCH,
                 f"实盘保管人 {rec.custodian_name or ''} 与台账 "
                 f"{card.custodian_name or ''} 不符")
        else:
            _add(card, InventoryDiffType.NORMAL, "实盘与台账一致")
    for rec in records:
        if rec.asset_id is None:
            _add(None, InventoryDiffType.SURPLUS,
                 f"实盘有、台账无:未贴标补录 {rec.name or ''}({rec.description or ''})",
                 asset_code=None, asset_name=rec.name)
    db.flush()
    return counts


def create_surplus_card(
    db: Session, user: User, *, plan_no: str, diff_id: int,
    name: str, category_code: str, original_value: float | None = None,
    room_name: str | None = None, custodian_id: int | None = None,
    custodian_name: str | None = None,
) -> tuple[AssetCard, AssetAcceptance]:
    """盘盈补记(#52 走 #24 入口):建盘盈验收单 + 同一 create_asset_card 建卡。

    验收单 intake_type=inventory_surplus,source_doc 记盘点方案号与差异 id;
    盘点已核实即验收依据,验收状态直接记通过;建卡后 sync_status 强制
    未同步(进入待同步池,手动勾选才同步)。
    """
    acceptance = AssetAcceptance(
        acceptance_no=_next_acceptance_no(db),
        intake_type=IntakeType.INVENTORY_SURPLUS,
        status=AcceptanceStatus.PASSED,
        source_doc={"inventory_no": plan_no, "inventory_diff_id": diff_id},
        accepted_by=user.id, accepted_at=datetime.now(UTC),
        comment="盘点盘盈补记(差异已核实)",
        created_by=user.id,
    )
    db.add(acceptance)
    db.flush()
    batch_no = next_batch_no(db, "RK", "intake")
    card = asset_svc.create_asset_card(
        db, user, name=name, category_code=category_code,
        acquire_method=IntakeType.ACQUIRE_METHOD[IntakeType.INVENTORY_SURPLUS],
        acceptance_id=acceptance.id, batch_no=batch_no,
        original_value=original_value, room_name=room_name,
        custodian_user_id=custodian_id, custodian_name=custodian_name,
    )
    acceptance.status = AcceptanceStatus.CARDED
    acceptance.batch_no = batch_no
    log_asset_action(
        db, user, "asset_inventory_diff_resolve",
        target_type="inventory_difference", target_id=diff_id,
        detail=f"盘盈补建卡 {card.asset_code} 验收单{acceptance.acceptance_no} "
               f"盘点方案{plan_no}(#24 盘盈补记入口)",
    )
    db.flush()
    return card, acceptance


def _next_acceptance_no(db: Session) -> str:
    today = datetime.now(UTC).strftime("%Y%m%d")
    count = db.query(AssetAcceptance).filter(
        AssetAcceptance.acceptance_no.like(f"YS{today}%")).count()
    return f"YS{today}-{count + 1:04d}"


def scan_inventory_due(db: Session, user: User | None = None) -> dict:
    """盘点到期提醒(#48,手动触发扫描,未挂定时 worker):已过截止时间
    仍未完成的任务,给盘点人写 盘点任务 提醒(逾期)并钉钉推送。"""
    from app.services import asset_notify as notify_svc

    now = datetime.now(UTC)
    rows = db.query(AssetInventoryTask).filter(
        AssetInventoryTask.due_at < now,
        AssetInventoryTask.status != "已完成").all()
    reminded: list[int] = []
    for task in rows:
        plan = db.get(AssetInventoryPlan, task.plan_id)
        row = create_reminder(
            db, kind="盘点任务", user_id=task.assignee_id,
            target_type="inventory_task", target_id=task.id,
            title=f"盘点任务已逾期:{plan.plan_no if plan else ''}",
            content=f"盘点任务(方案 {plan.plan_no if plan else ''})"
                    f"已过截止时间 {task.due_at.strftime('%Y-%m-%d')},请尽快完成盘点。",
            level="逾期",
        )
        if row is not None:
            reminded.append(task.id)
            notify_svc.push_to_user(
                db, task.assignee_id, f"盘点任务已逾期:{plan.plan_no if plan else ''}",
                f"盘点任务已过截止时间,请尽快完成盘点。")
    db.flush()
    return {"reminded_tasks": sorted(set(reminded))}
