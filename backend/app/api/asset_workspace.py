"""个人工作台 API(学校资产管理系统一期第 3 批 #1/#2/#3/#6/#7)。

挂在 /api/asset 下。
- #1 我的待办:只返回与当前登录人有关的待办(审批节点角色、
  保管人、借用人等维度);紧急程度规则:逾期(0) > 当天到期(1) >
  待审批(2) > 其他(3,含借用将到期、待移交、一般提醒)。
- #2 我的资产:本人名下领用/保管的全部资产;报修入口创建维修占位单
  (B4 实现工单),归还/移交链到对应单据创建。
- #3 提醒中心:提醒记录表查询;保修到期按 warranty_until 计算,
  盘点任务提醒在 B4 接入后自动出现(同一提醒表/同一查询端点)。
- #6 履历时间轴:GET /assets/{id}/timeline。
- 扫描端点均为手动触发(POST /workspace/scan-*),未接入定时 worker;
  系统现有 worker 模式见 app/workers/scheduler.py,后续批次挂定时
  任务时复用 services.asset_circulation 的同名扫描函数。
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.asset_circulation import _display, _get_card_or_404
from app.api.asset_foundation import asset_writer
from app.core.auth import get_active_user
from app.core.db import get_db
from app.models.asset_approval import ApprovalInstance, ApprovalNode
from app.models.asset_card import AssetCard, AssetStatus, SyncStatus
from app.models.asset_circulation import (
    AssetBorrowOrder,
    AssetHandoverOrder,
    AssetReminder,
    AssetRepairOrder,
    BorrowStatusDoc,
    HandoverStatus,
    RepairPlaceholderStatus,
    RepairStatus,
)
from app.models.asset_disposal import AssetDisposalOrder
from app.models.asset_inventory import (
    AssetInventoryPlan,
    AssetInventoryTask,
    InventoryPlanStatus,
    InventoryTaskStatus,
)
from app.models.user import Role, User
from app.schemas.asset import AssetCardOut
from app.schemas.asset_circulation import (
    PortalHintsOut,
    ReminderOut,
    TimelineEntryOut,
    TodoOut,
)
from app.services import asset_approval as approval_svc
from app.services import asset_circulation as circ_svc
from app.services.asset_audit import log_asset_action

router = APIRouter(tags=["asset"])


def _todo(kind, title, detail="", target_type="", target_id=None,
          due_at=None, urgency="", rank=3):
    return TodoOut(
        kind=kind, title=title, detail=detail,
        target_type=target_type, target_id=target_id,
        due_at=due_at, urgency=urgency, urgency_rank=rank,
    )


# ── #1 我的待办汇总 ──────────────────────────────
@router.get("/workspace/todos", response_model=list[TodoOut])
def list_my_todos(
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """我的待办汇总(#1):只返回与当前登录人有关的待办,按紧急程度排序:
    逾期 > 当天到期 > 待审批 > 其他。"""
    todos: list[TodoOut] = []
    now = datetime.now(UTC)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=0)

    # 待审批:当前节点角色含本人角色、且本人不是申请人(岗位分离)。
    roles = user.role_names
    instances = db.query(ApprovalInstance).filter_by(status="进行中").all()
    for inst in instances:
        if inst.applicant_id == user.id:
            continue
        node = db.query(ApprovalNode).filter_by(
            instance_id=inst.id, step=inst.current_step, status="待审批").first()
        if node is None:
            continue
        if node.role not in roles and Role.admin.value not in roles:
            continue
        todos.append(_todo(
            "待审批", f"待审批:{inst.doc_type}#{inst.doc_no or inst.doc_id}",
            detail=f"当前节点:{node.role} 申请人:{inst.applicant_name}",
            target_type="approval_instance", target_id=inst.id,
            due_at=inst.deadline, urgency="待审批", rank=2,
        ))

    # 借用到期/逾期:借用人是本人。
    borrows = db.query(AssetBorrowOrder).filter_by(borrower_id=user.id).filter(
        AssetBorrowOrder.status.in_(
            [BorrowStatusDoc.BORROWING, BorrowStatusDoc.OVERDUE])).all()
    for order in borrows:
        due = order.due_at
        if due.tzinfo is None:
            due = due.replace(tzinfo=UTC)
        card = db.get(AssetCard, order.asset_id)
        label = card.asset_code if card else f"资产#{order.asset_id}"
        if due < now:
            days = (now - due).days
            todos.append(_todo(
                "借用逾期", f"借用已逾期 {days} 天:{label}",
                detail=f"借用单 {order.doc_no}",
                target_type="borrow_order", target_id=order.id,
                due_at=due, urgency="逾期", rank=0,
            ))
        elif due <= today_end:
            todos.append(_todo(
                "借用当天到期", f"借用今天到期:{label}",
                detail=f"借用单 {order.doc_no}",
                target_type="borrow_order", target_id=order.id,
                due_at=due, urgency="当天到期", rank=1,
            ))
        else:
            todos.append(_todo(
                "借用到期", f"借用将到期:{label}",
                detail=f"借用单 {order.doc_no} 到期 {due.strftime('%Y-%m-%d')}",
                target_type="borrow_order", target_id=order.id,
                due_at=due, urgency="将到期", rank=3,
            ))

    # 待移交确认:本人是接收人或移交人。
    handovers = db.query(AssetHandoverOrder).filter(
        AssetHandoverOrder.status.in_(
            [HandoverStatus.PENDING, HandoverStatus.PARTIAL]),
        (AssetHandoverOrder.to_user_id == user.id) |
        (AssetHandoverOrder.from_user_id == user.id),
    ).all()
    for order in handovers:
        todos.append(_todo(
            "待移交确认", f"移交单待确认:{order.doc_no}",
            detail=f"{order.from_user_name} → {order.to_user_name}",
            target_type="handover_order", target_id=order.id,
            due_at=order.created_at, urgency="待移交", rank=3,
        ))

    # 未读提醒(借用类已由借用单覆盖,这里只取其余类型,避免重复)。
    reminders = db.query(AssetReminder).filter_by(
        user_id=user.id, is_read=False).filter(
        AssetReminder.kind.notin_(["借用逾期", "借用到期"])).all()
    for rem in reminders:
        rank = 0 if rem.level == "逾期" else (2 if rem.level == "紧急" else 3)
        todos.append(_todo(
            rem.kind, rem.title, detail=rem.content,
            target_type=rem.target_type, target_id=rem.target_id,
            due_at=rem.created_at, urgency=rem.level, rank=rank,
        ))

    todos.sort(key=lambda t: (t.urgency_rank, t.due_at or datetime.max.replace(tzinfo=UTC)))
    return todos


# ── #2 我的资产 ──────────────────────────────
@router.get("/workspace/my-assets", response_model=dict)
def list_my_assets(
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """我的资产(#2):本人名下领用/保管的全部资产 + 本人正在借用的资产
    (去重)。返回卡片列表,前端据状态展示报修/移交/归还入口。"""
    owned = db.query(AssetCard).filter_by(
        custodian_user_id=user.id, is_retired=False).all()
    borrowed_ids = {
        b.asset_id for b in db.query(AssetBorrowOrder).filter_by(
            borrower_id=user.id).filter(
            AssetBorrowOrder.status.in_(
                [BorrowStatusDoc.BORROWING, BorrowStatusDoc.OVERDUE])).all()
    }
    seen = {c.id for c in owned}
    for asset_id in borrowed_ids:
        if asset_id not in seen:
            card = db.get(AssetCard, asset_id)
            if card is not None and not card.is_retired:
                owned.append(card)
                seen.add(asset_id)
    owned.sort(key=lambda c: c.id)
    return {"items": [AssetCardOut.model_validate(c) for c in owned],
            "total": len(owned)}


@router.post("/workspace/my-assets/{asset_id}/report-repair",
             response_model=dict)
def report_repair_from_workspace(
    asset_id: int,
    body: dict | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """报修入口(#2):先链到维修占位单(B4 实现工单;占位单状态恒为
    待处理,B4 在此表上扩展派单/费用/结果字段)。"""
    card = _get_card_or_404(db, asset_id)
    if card.is_retired:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "资产已核销,不可报修")
    if card.custodian_user_id != user.id and \
            Role.asset_admin.value not in user.role_names and \
            Role.admin.value not in user.role_names:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "仅保管人或资产管理员可报修")
    existing = db.query(AssetRepairOrder).filter_by(
        asset_id=card.id, status=RepairPlaceholderStatus.PENDING).first()
    if existing is not None:
        return {"repair_order_id": existing.id, "doc_no": existing.doc_no,
                "created": False, "note": "已有待处理维修占位单(B4 接入工单)"}
    doc_no = circ_svc.next_doc_no(db, "维修单")
    row = AssetRepairOrder(
        doc_no=doc_no, asset_id=card.id, source="报修",
        reporter_id=user.id, reporter_name=_display(user),
        description=(body or {}).get("description") or "我的资产报修",
        status=RepairPlaceholderStatus.PENDING,
    )
    db.add(row)
    db.flush()
    log_asset_action(
        db, user, "asset_repair_placeholder_create",
        target_type="repair_order", target_id=row.id,
        detail=f"我的资产报修占位单 {doc_no} 资产{card.asset_code}(B4 接入工单)",
    )
    db.commit()
    return {"repair_order_id": row.id, "doc_no": doc_no,
            "created": True, "note": "维修占位单已创建,工单流程由 B4 实现"}


# ── #3 消息与提醒中心 ──────────────────────────────
@router.get("/workspace/reminders", response_model=list[ReminderOut])
def list_my_reminders(
    kind: str | None = None,
    is_read: bool | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """消息与提醒中心(#3):只返回本人的提醒(资产管理员另见
    user_id 为空的升级提醒,见 /workspace/reminders/admin)。"""
    q = db.query(AssetReminder).filter_by(user_id=user.id)
    if kind:
        q = q.filter_by(kind=kind)
    if is_read is not None:
        q = q.filter_by(is_read=is_read)
    return q.order_by(AssetReminder.id.desc()).limit(200).all()


@router.get("/workspace/reminders/admin", response_model=list[ReminderOut])
def list_admin_reminders(
    kind: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """资产管理员看的升级/公共提醒(user_id 为空的提醒,如借用逾期升级)。"""
    q = db.query(AssetReminder).filter(AssetReminder.user_id.is_(None))
    if kind:
        q = q.filter_by(kind=kind)
    return q.order_by(AssetReminder.id.desc()).limit(200).all()


@router.post("/workspace/reminders/{reminder_id}/read", response_model=ReminderOut)
def mark_reminder_read(
    reminder_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    row = db.get(AssetReminder, reminder_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "提醒不存在")
    if row.user_id is not None and row.user_id != user.id and \
            Role.admin.value not in user.role_names and \
            Role.asset_admin.value not in user.role_names:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅本人可标记已读")
    row.is_read = True
    db.commit()
    return row


# ── #6 履历时间轴 ──────────────────────────────
@router.get("/assets/{asset_id}/timeline", response_model=list[TimelineEntryOut])
def get_asset_timeline(
    asset_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """资产履历时间轴(#6):审计日志 + 各业务单据,按时间倒序。"""
    _get_card_or_404(db, asset_id)
    entries = circ_svc.build_timeline(db, asset_id)
    return [TimelineEntryOut(
        time=e["time"], type=e["type"], title=e["title"],
        detail=e["detail"], doc_no=e["doc_no"], actor=e["actor"],
    ) for e in entries]


# ── #40 未办结移交预警清单 ──────────────────────────────
@router.get("/workspace/handover-warnings", response_model=dict)
def list_handover_warnings(
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """未办结移交预警清单(#40):已打 is_overdue 或超阈值未办结的移交单。"""
    threshold = circ_svc.param_int(db, "asset.handover.overdue_days", 7)
    now = datetime.now(UTC)
    rows = db.query(AssetHandoverOrder).filter(
        AssetHandoverOrder.status.in_(
            [HandoverStatus.PENDING, HandoverStatus.PARTIAL])).all()
    out = []
    for order in rows:
        created = order.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        days = (now - created).days
        if order.is_overdue or days >= threshold:
            from app.schemas.asset_circulation import HandoverOut

            data = HandoverOut.model_validate(order).model_dump()
            data["overdue_days"] = days
            out.append(data)
    out.sort(key=lambda r: -r["overdue_days"])
    return {"items": out, "total": len(out), "threshold_days": threshold}


# ── 扫描端点(手动触发;后续批次挂定时任务复用同一服务函数) ──
@router.post("/workspace/scan-overdue", response_model=dict)
def scan_overdue(
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """借用逾期扫描(#32):到期前提醒 + 逾期标记 + 升级;钉钉推送失败不阻塞。"""
    result = circ_svc.scan_borrow_overdue(db, user)
    db.commit()
    return result


@router.post("/workspace/scan-handover-warnings", response_model=dict)
def scan_handover(
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """移交预警扫描(#40)。"""
    result = circ_svc.scan_handover_warnings(db, user)
    db.commit()
    return result


@router.post("/workspace/scan-warranty", response_model=dict)
def scan_warranty(
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """保修到期提醒扫描(#3)。"""
    result = circ_svc.scan_warranty(db, user)
    db.commit()
    return result


@router.post("/workspace/scan-approval-overdue", response_model=dict)
def scan_approval_overdue(
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """审批超时扫描(#3/#5):先打超时标记,再写超时提醒。"""
    marked = approval_svc.mark_overdue(db, user)
    result = circ_svc.scan_approval_overdue_reminders(db, user)
    log_asset_action(
        db, user, "asset_workspace_scan",
        target_type="approval_overdue",
        detail=f"审批超时扫描:新标记 {len(marked)} 个,提醒 {len(result['reminded_instances'])} 个",
    )
    db.commit()
    return {"marked": marked, **result}


# ── Portal 首页资产提示 ──────────────────────────────
#: “借用将到期”口径:到期日在未来 7 天内(含今天);已逾期单另计,不重叠。
DUE_SOON_DAYS = 7
#: 处置待办(管理口径):仍在校内流转、等人工推进的状态。
DISPOSAL_TODO_STATUSES = ("待鉴定", "待审批", "待官方批复")
#: 待处置汇总(领导口径):尚未终结的处置单状态。
DISPOSAL_OPEN_STATUSES = ("待鉴定", "待审批", "审批通过", "待官方批复", "已批复")


@router.get("/workspace/portal-hints", response_model=PortalHintsOut)
def get_portal_hints(
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """Portal 首页资产提示汇总:一次返回各角色可见的资产待办数,全部
    真实计数,无数据为 0,角色不可见的字段为 None。

    我的口径复用本模块 /workspace/todos 与 /workspace/my-assets 的
    同一查询(待审批数直接数 todos 里 kind=待审批的条数);管理/领导
    口径是全校汇总,前端只渲染非 None 项。钉钉提醒沿用现有提醒表与
    扫描端点,本端点只读汇总,不写提醒、不发钉钉。"""
    roles = user.role_names
    is_admin_side = Role.admin.value in roles or Role.asset_admin.value in roles
    is_leader_side = Role.director.value in roles or Role.admin.value in roles
    now = datetime.now(UTC)
    soon_end = now + timedelta(days=DUE_SOON_DAYS)

    # 我的:与工作台同一查询,避免两处口径漂移。
    todos = list_my_todos(db, user)
    my_assets = list_my_assets(db, user)
    my_borrow_overdue = sum(1 for t in todos if t.kind == "借用逾期")
    my_borrow_due_soon = 0
    for t in todos:
        if t.kind in ("借用当天到期", "借用到期") and t.due_at is not None:
            due = t.due_at if t.due_at.tzinfo is not None else t.due_at.replace(tzinfo=UTC)
            if due <= soon_end:
                my_borrow_due_soon += 1
    my_repairs = db.query(AssetRepairOrder).filter(
        AssetRepairOrder.reporter_id == user.id,
        AssetRepairOrder.status != RepairStatus.CLOSED).all()
    out = PortalHintsOut(
        my_assets_total=my_assets["total"],
        my_borrow_overdue=my_borrow_overdue,
        my_borrow_due_soon=my_borrow_due_soon,
        my_repair_open=len(my_repairs),
        my_repair_pending_confirm=sum(
            1 for r in my_repairs if r.status == RepairStatus.PENDING_CONFIRM),
    )

    if is_admin_side:
        out.admin_pending_approval = sum(1 for t in todos if t.kind == "待审批")
        # 逾期口径与 /workspace/todos 一致:状态未归还且到期日已过(不只
        # 依赖扫描打上的 已逾期 标记,扫描未跑时也不漏数)。
        _open_borrows = db.query(AssetBorrowOrder).filter(
            AssetBorrowOrder.status.in_(
                [BorrowStatusDoc.BORROWING, BorrowStatusDoc.OVERDUE])).all()
        out.admin_borrow_overdue = sum(
            1 for b in _open_borrows
            if (b.due_at if b.due_at.tzinfo is not None
                else b.due_at.replace(tzinfo=UTC)) < now)
        out.admin_repair_pending_confirm = db.query(AssetRepairOrder).filter_by(
            status=RepairStatus.PENDING_CONFIRM).count()
        out.admin_inventory_open_plans = db.query(AssetInventoryPlan).filter_by(
            status=InventoryPlanStatus.IN_PROGRESS).count()
        out.admin_inventory_open_tasks = db.query(AssetInventoryTask).filter(
            AssetInventoryTask.status.in_(
                [InventoryTaskStatus.PENDING, InventoryTaskStatus.IN_PROGRESS])
        ).count()
        out.admin_disposal_open = db.query(AssetDisposalOrder).filter(
            AssetDisposalOrder.status.in_(DISPOSAL_TODO_STATUSES)).count()
        out.admin_sync_pending = db.query(AssetCard).filter(
            AssetCard.sync_status == SyncStatus.pending.value,
            AssetCard.is_retired.is_(False)).count()

    if is_leader_side:
        idle_cards = db.query(AssetCard).filter(
            AssetCard.is_idle.is_(True),
            AssetCard.is_retired.is_(False)).all()
        out.leader_idle_count = len(idle_cards)
        out.leader_idle_value = round(
            sum(float(c.original_value or 0) for c in idle_cards), 2)
        by_status = {
            s: db.query(AssetDisposalOrder).filter_by(status=s).count()
            for s in DISPOSAL_OPEN_STATUSES
        }
        out.leader_disposal_by_status = by_status
        out.leader_disposal_open = sum(by_status.values())

    return out
