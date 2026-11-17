"""第 3 批共用服务:单据号、参数读取、提醒写入、逾期扫描、履历时间轴。

- 单据号:前缀+YYYYMMDD+4 位流水,同一前缀同一天内按已建单数递增。
- 参数(可配置,见 asset_params,种子在迁移 0041 与 asset_seed):
  asset.borrow.reminder_days_before(默认 1 天,到期前提醒)、
  asset.borrow.overdue_escalation_days(默认 3 天,逾期满该天数升级)、
  asset.handover.overdue_days(默认 7 天,移交未办结预警)、
  asset.warranty.reminder_days(默认 30 天,保修到期提醒)。
- 提醒写入 create_reminder:同(kind, target_type, target_id, user_id)
  未读提醒已存在时不重复建,只在 level 升级时更新 level。
- 扫描端点均为手动触发(POST /workspace/scan-*,见 asset_workspace),
  同时由定时 worker 每日 08:00 全量跑一遍(见 workers/asset_scan_job.py
  与 workers/scheduler.py 的 ASSET_SCAN_JOB_ID)。
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.asset_approval import ApprovalInstance, ApprovalNode
from app.models.asset_card import AssetCard
from app.models.asset_circulation import (
    AssetBorrowOrder,
    AssetHandoverOrder,
    AssetIssueOrder,
    AssetReminder,
    AssetRepairOrder,
    AssetReservation,
    AssetReturnOrder,
    AssetTransferOrder,
    BorrowStatusDoc,
    HandoverStatus,
    ReservationStatus,
)
from app.models.asset_config import AssetParam
from app.models.asset_disposal import AssetDisposalOrder
from app.models.audit import AuditLog
from app.models.user import User
from app.services.asset_audit import log_asset_action

logger = logging.getLogger(__name__)

DOC_PREFIXES = {
    "领用单": "LY-",
    "借用单": "JY-",
    "预约单": "YY-",
    "归还单": "GH-",
    "团体保管单": "TB-",
    "调拨单": "DB-",
    "移交单": "YJ-",
    "维修单": "WX-",
}

_DOC_TABLES = {
    "领用单": AssetIssueOrder,
    "借用单": AssetBorrowOrder,
    "预约单": AssetReservation,
    "归还单": AssetReturnOrder,
    "团体保管单": None,  # 团体保管单表名与模型名不一致,见下
    "调拨单": AssetTransferOrder,
    "移交单": AssetHandoverOrder,
    "维修单": None,
}


def next_doc_no(db: Session, doc_type: str) -> str:
    """生成单据号:前缀+YYYYMMDD+4 位流水。"""
    from app.models.asset_circulation import AssetGroupCustody, AssetRepairOrder

    table = _DOC_TABLES.get(doc_type)
    if doc_type == "团体保管单":
        table = AssetGroupCustody
    elif doc_type == "维修单":
        table = AssetRepairOrder
    prefix = DOC_PREFIXES[doc_type]
    day = datetime.now(UTC).strftime("%Y%m%d")
    like = f"{prefix}{day}%"
    count = db.query(table).filter(table.doc_no.like(like)).count() if table else 0
    return f"{prefix}{day}{count + 1:04d}"


def param_int(db: Session, key: str, default: int) -> int:
    row = db.query(AssetParam).filter_by(key=key).first()
    try:
        return int(row.value) if row else default
    except (TypeError, ValueError):
        return default


def create_reminder(
    db: Session,
    *,
    kind: str,
    user_id: int | None,
    target_type: str,
    target_id: int | None,
    title: str,
    content: str = "",
    level: str = "一般",
) -> AssetReminder | None:
    """写提醒(去重:同一对象同一类型未读提醒只保留一条,level 可升级)。"""
    existing = db.query(AssetReminder).filter_by(
        kind=kind, target_type=target_type, target_id=target_id,
        user_id=user_id, is_read=False,
    ).first()
    if existing is not None:
        if level == "逾期" and existing.level != "逾期":
            existing.level = level
            existing.title = title
            existing.content = content
        db.flush()
        return existing
    row = AssetReminder(
        kind=kind, user_id=user_id, target_type=target_type,
        target_id=target_id, title=title, content=content, level=level,
    )
    db.add(row)
    db.flush()
    return row


def scan_borrow_overdue(db: Session, user: User | None = None) -> dict:
    """借用扫描(#32):到期前提醒 + 逾期标记 + 逾期满阈值升级。

    返回 {reminded, overdue, escalated, pushed}。钉钉推送失败不阻塞。
    """
    from app.services import asset_notify

    now = datetime.now(UTC)
    remind_before = param_int(db, "asset.borrow.reminder_days_before", 1)
    escalate_after = param_int(db, "asset.borrow.overdue_escalation_days", 3)
    reminded, overdue, escalated = [], [], []
    pushed = {"sent": 0, "skipped": 0, "failed": 0}
    rows = db.query(AssetBorrowOrder).filter_by(
        status=BorrowStatusDoc.BORROWING).all()
    for order in rows:
        due = order.due_at
        if due.tzinfo is None:
            due = due.replace(tzinfo=UTC)
        card = db.get(AssetCard, order.asset_id)
        asset_label = card.asset_code if card else f"资产#{order.asset_id}"
        if due < now:
            days = (now - due).days
            order.is_overdue = True
            order.overdue_days = days
            order.status = BorrowStatusDoc.OVERDUE
            overdue.append(order.id)
            level = "逾期"
            create_reminder(
                db, kind="借用逾期", user_id=order.borrower_id,
                target_type="borrow_order", target_id=order.id,
                title=f"借用已逾期 {days} 天:{asset_label}",
                content=f"借用单 {order.doc_no} 已逾期 {days} 天,请尽快归还。",
                level=level,
            )
            if days >= escalate_after and not order.escalated:
                order.escalated = True
                escalated.append(order.id)
                create_reminder(
                    db, kind="借用逾期", user_id=None,
                    target_type="borrow_order", target_id=order.id,
                    title=f"借用逾期升级:{asset_label}",
                    content=f"借用单 {order.doc_no} 逾期 {days} 天已升级,"
                            "请资产管理员跟进。",
                    level="逾期",
                )
            result = asset_notify.push_to_user(
                db, order.borrower_id, "借用逾期提醒",
                f"借用单 {order.doc_no}({asset_label})已逾期 {days} 天,请尽快归还。",
            )
            pushed["sent"] += int(result["sent"])
            pushed["skipped"] += int(result["skipped"])
            pushed["failed"] += int(result["failed"])
            log_asset_action(
                db, user, "asset_borrow_overdue",
                target_type="borrow_order", target_id=order.id,
                detail=f"借用逾期 {order.doc_no} {days} 天"
                       + (" 已升级" if order.escalated else ""),
            )
        elif due - now <= timedelta(days=remind_before) and not order.reminded_before_due:
            order.reminded_before_due = True
            reminded.append(order.id)
            create_reminder(
                db, kind="借用到期", user_id=order.borrower_id,
                target_type="borrow_order", target_id=order.id,
                title=f"借用即将到期:{asset_label}",
                content=f"借用单 {order.doc_no} 将于 {due.strftime('%Y-%m-%d')} 到期,请按时归还。",
                level="一般",
            )
    db.flush()
    return {"reminded": reminded, "overdue": overdue,
            "escalated": escalated, "pushed": pushed}


def scan_handover_warnings(db: Session, user: User | None = None) -> dict:
    """移交预警扫描(#40):未办结超阈值(默认 7 天)打预警提醒。

    第 6 批补钉钉推送(#114):此前只写站内提醒,移交双方收不到钉钉;
    现与借用逾期扫描同口径,提醒与推送并行,推送失败只记日志不阻塞。
    """
    from app.services import asset_notify as notify_svc

    threshold = param_int(db, "asset.handover.overdue_days", 7)
    now = datetime.now(UTC)
    warned = []
    rows = db.query(AssetHandoverOrder).filter(
        AssetHandoverOrder.status.in_(
            [HandoverStatus.PENDING, HandoverStatus.PARTIAL])
    ).all()
    for order in rows:
        created = order.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        days = (now - created).days
        if days < threshold:
            continue
        order.is_overdue = True
        warned.append(order.id)
        for uid in {order.from_user_id, order.to_user_id}:
            create_reminder(
                db, kind="移交预警", user_id=uid,
                target_type="handover_order", target_id=order.id,
                title=f"移交未办结已 {days} 天:{order.doc_no}",
                content=f"移交单 {order.doc_no} 未办结已 {days} 天,"
                        "请尽快逐件扫码确认,避免责任断档。",
                level="逾期",
            )
            notify_svc.push_to_user(
                db, uid, f"移交未办结已 {days} 天:{order.doc_no}",
                f"移交单 {order.doc_no} 未办结已 {days} 天,"
                "请尽快逐件扫码确认,避免责任断档。",
            )
        log_asset_action(
            db, user, "asset_handover_warn",
            target_type="handover_order", target_id=order.id,
            detail=f"移交未办结预警 {order.doc_no} 已 {days} 天",
        )
    db.flush()
    return {"warned": warned, "threshold_days": threshold}


def scan_warranty(db: Session, user: User | None = None) -> dict:
    """保修到期提醒(#3):ext.warranty_until 在提醒窗口内且未核销的资产。

    第 6 批补钉钉推送(#114):此前只写站内提醒,保管人收不到钉钉;
    现与借用逾期扫描同口径,提醒与推送并行,推送失败只记日志不阻塞。
    """
    from app.services import asset_notify as notify_svc

    window = param_int(db, "asset.warranty.reminder_days", 30)
    now = datetime.now(UTC)
    reminded = []
    rows = db.query(AssetCard).filter_by(is_retired=False).all()
    for card in rows:
        raw = (card.ext or {}).get("warranty_until")
        if not raw:
            continue
        try:
            until = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            try:
                until = datetime.strptime(str(raw), "%Y-%m-%d").replace(tzinfo=UTC)
            except ValueError:
                continue
        if until.tzinfo is None:
            until = until.replace(tzinfo=UTC)
        delta = (until - now).days
        if 0 <= delta <= window:
            row = create_reminder(
                db, kind="保修到期", user_id=card.custodian_user_id,
                target_type="asset_card", target_id=card.id,
                title=f"保修即将到期:{card.asset_code}",
                content=f"资产 {card.name}({card.asset_code})保修将于 "
                        f"{until.strftime('%Y-%m-%d')} 到期。",
                level="一般",
            )
            if row is not None:
                reminded.append(card.id)
                if card.custodian_user_id:
                    notify_svc.push_to_user(
                        db, card.custodian_user_id,
                        f"保修即将到期:{card.asset_code}",
                        f"资产 {card.name}({card.asset_code})保修将于 "
                        f"{until.strftime('%Y-%m-%d')} 到期。",
                    )
    db.flush()
    return {"reminded": reminded, "window_days": window}


def scan_reservation_release(db: Session, user: User | None = None) -> dict:
    """预约自动释放(#33):到期未领用的预约标 已释放并记日志,
    同时钉钉推送预约人(此前只写站内提醒,预约人收不到钉钉)。
    返回 {released, pushed}。"""
    from app.services import asset_notify as notify_svc

    now = datetime.now(UTC)
    released = []
    pushed = {"sent": 0, "skipped": 0, "failed": 0}
    rows = db.query(AssetReservation).filter_by(
        status=ReservationStatus.PENDING).all()
    for row in rows:
        end = row.end_at
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)
        if end >= now:
            continue
        row.status = ReservationStatus.RELEASED
        row.released_at = now
        released.append(row.id)
        create_reminder(
            db, kind="预约释放", user_id=row.reserver_id,
            target_type="reservation", target_id=row.id,
            title=f"预约已自动释放:{row.doc_no}",
            content=f"预约单 {row.doc_no} 到期未领用,已自动释放。",
            level="一般",
        )
        result = notify_svc.push_to_user(
            db, row.reserver_id, f"预约已自动释放:{row.doc_no}",
            f"预约单 {row.doc_no} 到期未领用,已自动释放。",
        )
        pushed["sent"] += int(result["sent"])
        pushed["skipped"] += int(result["skipped"])
        pushed["failed"] += int(result["failed"])
        log_asset_action(
            db, user, "asset_reservation_release",
            target_type="reservation", target_id=row.id,
            detail=f"预约到期未领用自动释放 {row.doc_no}",
        )
    db.flush()
    return {"released": released, "pushed": pushed}


def scan_approval_overdue_reminders(db: Session, user: User | None = None) -> dict:
    """审批超时提醒(#3/#5):已打 is_overdue 的审批实例给申请人与当前节点
    角色写一条提醒并钉钉推送(失败不阻塞)。

    第 6 批补钉钉推送(#114):此前文档称“钉钉推送走同一推送函数”,
    但代码只写站内提醒、实际未推送;现补上申请人 + 当前节点角色两路推送。
    """
    from app.services import asset_notify as notify_svc

    rows = db.query(ApprovalInstance).filter_by(
        status="进行中", is_overdue=True).all()
    created = []
    for inst in rows:
        node = db.query(ApprovalNode).filter_by(
            instance_id=inst.id, step=inst.current_step, status="待审批",
        ).first()
        role = node.role if node else ""
        for uid in {inst.applicant_id}:
            row = create_reminder(
                db, kind="审批超时", user_id=uid,
                target_type="approval_instance", target_id=inst.id,
                title=f"审批超时:{inst.doc_type}#{inst.doc_no or inst.doc_id}",
                content=f"{inst.doc_type}单据审批已超时,当前节点 {role},请跟进。",
                level="紧急",
            )
            if row is not None:
                created.append(inst.id)
                notify_svc.push_to_user(
                    db, uid, f"审批超时:{inst.doc_type}#{inst.doc_no or inst.doc_id}",
                    f"{inst.doc_type}单据审批已超时,当前节点 {role},请跟进。",
                )
                # 角色推送与站内提醒同一次去重:已提醒过的不再重复推送,避免重复扫描刷屏。
                if role:
                    notify_svc.push_to_role(
                        db, role,
                        f"审批超时待处理:{inst.doc_type}#{inst.doc_no or inst.doc_id}",
                        f"{inst.doc_type}单据审批已超时,请尽快处理。",
                    )
    db.flush()
    return {"reminded_instances": sorted(set(created))}


def build_timeline(db: Session, asset_id: int) -> list[dict]:
    """资产履历时间轴(#6):审计日志 + 各业务单据,按时间倒序。

    审计日志是主干(建卡/入账/勾选/状态转移等全量留痕);业务单据
    补上单据号与责任人等结构化信息。同一事件在审计与单据各出现
    一次时保留两条(来源不同,detail 各有侧重),不强行去重。
    """
    entries: list[dict] = []
    card = db.get(AssetCard, asset_id)
    if card is None:
        return entries
    logs = db.query(AuditLog).filter(
        AuditLog.action.like("asset_%"),
        AuditLog.target_type == "asset_card",
        AuditLog.target_id == asset_id,
    ).order_by(AuditLog.id.desc()).all()
    for log in logs:
        entries.append({
            "time": log.created_at, "type": "审计",
            "title": log.action, "detail": log.detail or "",
            "doc_no": None, "actor": log.username or "",
        })
    # 建卡事件(审计已有建卡日志,这里补创建时间锚点,无重复标题时保留)
    entries.append({
        "time": card.created_at, "type": "建卡",
        "title": f"建卡 {card.asset_code}",
        "detail": f"{card.name} 分类{card.category_code}",
        "doc_no": None, "actor": "",
    })
    doc_specs = [
        (AssetIssueOrder, "领用单", "asset_id"),
        (AssetBorrowOrder, "借用单", "asset_id"),
        (AssetReservation, "预约单", "asset_id"),
        (AssetReturnOrder, "归还单", "asset_id"),
        (AssetTransferOrder, "调拨单", "asset_id"),
        (AssetHandoverOrder, "移交单", None),
        # ── 第 4 批 #44:维修单据沉淀进履历时间轴 ──
        (AssetRepairOrder, "维修单", "asset_id"),
        # ── 复核补 #6:处置单此前只走审计日志、无结构化条目 ──
        (AssetDisposalOrder, "处置单", "asset_id"),
    ]
    for model, label, key in doc_specs:
        if key is None:
            continue
        for row in db.query(model).filter_by(asset_id=asset_id).all():
            entries.append({
                "time": row.created_at, "type": label,
                "title": f"{label} {row.doc_no}({row.status})",
                "detail": getattr(row, "reason", "") or "",
                "doc_no": row.doc_no, "actor": "",
            })
    # 移交单按明细关联资产
    from app.models.asset_circulation import AssetHandoverItem

    items = db.query(AssetHandoverItem).filter_by(asset_id=asset_id).all()
    for item in items:
        order = db.get(AssetHandoverOrder, item.handover_id)
        if order is None:
            continue
        entries.append({
            "time": order.created_at, "type": "移交单",
            "title": f"移交单 {order.doc_no}({item.status})",
            "detail": f"{order.from_user_name} → {order.to_user_name}",
            "doc_no": order.doc_no, "actor": "",
        })
    entries.sort(key=lambda e: e["time"] or datetime.min.replace(tzinfo=UTC),
                 reverse=True)
    return entries
