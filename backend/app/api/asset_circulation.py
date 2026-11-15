"""领用/借用/预约/归还/团体保管 API(学校资产管理系统一期第 3 批 #30~#35)。

挂在 /api/asset 下。状态转移一律经 services.asset_foundation
transition_asset(与 B1 transition 端点同一服务函数),并带单据类型
与单号;未入账(is_booked=False)的资产不得领用/借用/预约/团体保管。
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.asset_foundation import _get_card_or_404, asset_writer, require_asset_roles
from app.core.auth import get_active_user
from app.core.db import get_db
from app.models.asset_card import AssetCard, AssetStatus, BorrowStatus
from app.models.asset_circulation import (
    AssetBorrowOrder,
    AssetGroupCustody,
    AssetIssueOrder,
    AssetRepairOrder,
    AssetReservation,
    AssetReturnOrder,
    BorrowStatusDoc,
    IssueStatus,
    RepairPlaceholderStatus,
    ReservationStatus,
    ReturnResult,
    ReturnStatus,
)
from app.models.asset_approval import ApprovalInstance
from app.models.basedata import ClassUnit
from app.models.user import Role, User
from app.schemas.asset_circulation import (
    BorrowCreate,
    BorrowOut,
    GroupCustodyCreate,
    GroupCustodyOut,
    IssueCreate,
    IssueOut,
    RepairOut,
    ReservationCreate,
    ReservationOut,
    ReturnCreate,
    ReturnOut,
    ReturnScanIn,
    ScanIn,
)
from app.services import asset_approval as approval_svc
from app.services import asset_circulation as circ_svc
from app.services import asset_foundation as asset_svc
from app.services import asset_notify as notify_svc
from app.services.asset_audit import log_asset_action

router = APIRouter(tags=["asset"])


def _display(user: User) -> str:
    return user.display_name or user.username


def _require_booked(card: AssetCard) -> None:
    if not card.is_booked:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"资产 {card.asset_code} 未入账(未回填入账凭证号),不得领用/借用",
        )
    if card.is_retired:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"资产 {card.asset_code} 已核销封存")


def _transition(
    db: Session, user: User, card: AssetCard, to_status: str,
    doc_type: str, doc_no: str,
) -> None:
    try:
        asset_svc.transition_asset(
            db, user, card, to_status, doc_type=doc_type, doc_no=doc_no)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


def _sync_issue_status(db: Session, order: AssetIssueOrder) -> None:
    """领用单状态跟随审批实例:已退回→已退回;已通过且仍在申请中→待发放。"""
    if order.approval_instance_id is None or order.status not in (
            IssueStatus.APPLYING, IssueStatus.PENDING_ISSUE):
        return
    inst = db.get(ApprovalInstance, order.approval_instance_id)
    if inst is None:
        return
    if inst.status == "已退回" and order.status == IssueStatus.APPLYING:
        order.status = IssueStatus.REJECTED
    elif inst.status == "已通过" and order.status == IssueStatus.APPLYING:
        order.status = IssueStatus.PENDING_ISSUE


def _issue_out(db: Session, order: AssetIssueOrder) -> IssueOut:
    _sync_issue_status(db, order)
    return IssueOut.model_validate(order)


# ── 领用 #30/#31 ──────────────────────────────
@router.post("/issues", response_model=IssueOut, status_code=status.HTTP_201_CREATED)
def create_issue(
    body: IssueCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """长期领用申请(#30):申请 → 审批(领用单审批流) → 发放 → 扫码确认。
    未入账资产不得领用;在库资产方可申请。"""
    card = _get_card_or_404(db, body.asset_id)
    _require_booked(card)
    if card.status != AssetStatus.in_stock.value:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"资产 {card.asset_code} 当前状态 {card.status},仅在库资产可领用",
        )
    doc_no = circ_svc.next_doc_no(db, "领用单")
    order = AssetIssueOrder(
        doc_no=doc_no, asset_id=card.id,
        applicant_id=user.id, applicant_name=_display(user),
        use_dept=body.use_dept, reason=body.reason,
        status=IssueStatus.APPLYING,
    )
    db.add(order)
    db.flush()
    from app.models.asset_approval import ApprovalFlow

    flow = None
    if body.flow_id is not None:
        flow = db.get(ApprovalFlow, body.flow_id)
        if flow is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "审批流不存在")
    try:
        inst = approval_svc.create_instance(
            db, user, doc_type="领用单", doc_id=order.id, doc_no=doc_no,
            amount=float(card.original_value) if card.original_value is not None else None,
            flow=flow,
        )
    except approval_svc.ApprovalError as e:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    order.approval_instance_id = inst.id
    db.flush()
    log_asset_action(
        db, user, "asset_issue_create",
        target_type="issue_order", target_id=order.id,
        detail=f"领用申请 {doc_no} 资产{card.asset_code} 申请人{_display(user)}",
    )
    # 审批待办钉钉推送(#7):推给当前节点角色;失败只记日志不阻塞。
    from app.models.asset_approval import ApprovalNode

    current = db.query(ApprovalNode).filter_by(
        instance_id=inst.id, step=inst.current_step, status="待审批").first()
    if current is not None:
        notify_svc.push_to_role(
            db, current.role, "资产领用待审批",
            f"领用单 {doc_no}({card.asset_code})待您审批。",
        )
    db.commit()
    return _issue_out(db, order)


@router.get("/issues", response_model=list[IssueOut])
def list_issues(
    status_: str | None = Query(default=None, alias="status"),
    applicant_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    q = db.query(AssetIssueOrder)
    if status_:
        q = q.filter_by(status=status_)
    if applicant_id is not None:
        q = q.filter_by(applicant_id=applicant_id)
    elif Role.admin.value not in user.role_names and \
            Role.asset_admin.value not in user.role_names:
        q = q.filter_by(applicant_id=user.id)
    rows = q.order_by(AssetIssueOrder.id.desc()).limit(200).all()
    return [_issue_out(db, r) for r in rows]


@router.get("/issues/{order_id}", response_model=IssueOut)
def get_issue(
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    order = db.get(AssetIssueOrder, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "领用单不存在")
    return _issue_out(db, order)


@router.post("/issues/{order_id}/issue", response_model=IssueOut)
def issue_asset(
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """发放确认(#30):审批通过后资产管理员发放,状态 在库→在用,
    保管人/使用部门随单变更,写 last_used_at。"""
    order = db.get(AssetIssueOrder, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "领用单不存在")
    _sync_issue_status(db, order)
    if order.status != IssueStatus.PENDING_ISSUE:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"领用单当前状态 {order.status},须审批通过(待发放)后方可发放",
        )
    card = _get_card_or_404(db, order.asset_id)
    _transition(db, user, card, AssetStatus.in_use.value, "领用单", order.doc_no)
    card.custodian_user_id = order.applicant_id
    card.custodian_name = order.applicant_name
    if order.use_dept:
        card.use_dept = order.use_dept
    card.borrow_status = BorrowStatus.issued.value
    card.last_used_at = datetime.now(UTC)
    order.status = IssueStatus.ISSUED
    order.issued_by = user.id
    order.issued_at = datetime.now(UTC)
    log_asset_action(
        db, user, "asset_issue_issue",
        target_type="issue_order", target_id=order.id,
        detail=f"领用发放 {order.doc_no} 资产{card.asset_code} "
               f"保管人→{order.applicant_name}",
        before={"status": AssetStatus.in_stock.value},
        after={"status": AssetStatus.in_use.value},
    )
    db.commit()
    return _issue_out(db, order)


@router.post("/issues/{order_id}/confirm-scan", response_model=IssueOut)
def confirm_issue_scan(
    order_id: int,
    body: ScanIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """领用确认(扫码)(#31):领用人扫标签码确认接收;须领用人与领用单
    一致,写 last_used_at。"""
    order = db.get(AssetIssueOrder, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "领用单不存在")
    if user.id != order.applicant_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "扫码确认须由领用人本人操作")
    if order.status != IssueStatus.ISSUED:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"领用单当前状态 {order.status},须发放后方可扫码确认",
        )
    card = _get_card_or_404(db, order.asset_id)
    if body.label_code != card.label_code:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "标签码与领用资产不符")
    card.last_used_at = datetime.now(UTC)
    order.status = IssueStatus.CONFIRMED
    order.confirmed_at = datetime.now(UTC)
    log_asset_action(
        db, user, "asset_issue_confirm",
        target_type="issue_order", target_id=order.id,
        detail=f"领用扫码确认 {order.doc_no} 资产{card.asset_code}",
    )
    db.commit()
    return _issue_out(db, order)


@router.post("/issues/{order_id}/cancel", response_model=IssueOut)
def cancel_issue(
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    order = db.get(AssetIssueOrder, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "领用单不存在")
    if user.id != order.applicant_id and Role.admin.value not in user.role_names:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅申请人或管理员可撤销")
    _sync_issue_status(db, order)
    if order.status != IssueStatus.APPLYING:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"领用单当前状态 {order.status},不可撤销")
    order.status = IssueStatus.CANCELLED
    db.commit()
    return _issue_out(db, order)


# ── 借用 #32 ──────────────────────────────
@router.post("/borrows", response_model=BorrowOut, status_code=status.HTTP_201_CREATED)
def create_borrow(
    body: BorrowCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """短期借用(#32):按天借用,填事由与归还时间;借用期间状态
    在库/在用→借出。同一资产同一时间只允许一笔进行中的借用。"""
    card = _get_card_or_404(db, body.asset_id)
    _require_booked(card)
    if card.status not in (AssetStatus.in_stock.value, AssetStatus.in_use.value):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"资产 {card.asset_code} 当前状态 {card.status},不可借用",
        )
    due = body.due_at
    if due.tzinfo is None:
        due = due.replace(tzinfo=UTC)
    if due <= datetime.now(UTC):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "归还时间须晚于当前时间")
    active = db.query(AssetBorrowOrder).filter_by(asset_id=card.id).filter(
        AssetBorrowOrder.status.in_(
            [BorrowStatusDoc.BORROWING, BorrowStatusDoc.OVERDUE])).first()
    if active is not None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"资产 {card.asset_code} 已有进行中的借用单 {active.doc_no}",
        )
    doc_no = circ_svc.next_doc_no(db, "借用单")
    order = AssetBorrowOrder(
        doc_no=doc_no, asset_id=card.id,
        borrower_id=user.id, borrower_name=_display(user),
        reason=body.reason, due_at=due,
        status=BorrowStatusDoc.BORROWING,
    )
    db.add(order)
    db.flush()
    _transition(db, user, card, AssetStatus.lent.value, "借用单", doc_no)
    card.borrow_status = BorrowStatus.lent.value
    card.last_used_at = datetime.now(UTC)
    log_asset_action(
        db, user, "asset_borrow_create",
        target_type="borrow_order", target_id=order.id,
        detail=f"借用 {doc_no} 资产{card.asset_code} "
               f"归还时间{due.strftime('%Y-%m-%d')}",
    )
    db.commit()
    return order


@router.get("/borrows", response_model=list[BorrowOut])
def list_borrows(
    status_: str | None = Query(default=None, alias="status"),
    borrower_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    q = db.query(AssetBorrowOrder)
    if status_:
        q = q.filter_by(status=status_)
    if borrower_id is not None:
        q = q.filter_by(borrower_id=borrower_id)
    elif Role.admin.value not in user.role_names and \
            Role.asset_admin.value not in user.role_names:
        q = q.filter_by(borrower_id=user.id)
    return q.order_by(AssetBorrowOrder.id.desc()).limit(200).all()


@router.get("/borrows/overdue", response_model=list[BorrowOut])
def list_overdue_borrows(
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """借用逾期清单(#32):逾期资产集中查看。"""
    return db.query(AssetBorrowOrder).filter(
        AssetBorrowOrder.status == BorrowStatusDoc.OVERDUE
    ).order_by(AssetBorrowOrder.due_at).all()


@router.get("/borrows/{order_id}", response_model=BorrowOut)
def get_borrow(
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    order = db.get(AssetBorrowOrder, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "借用单不存在")
    return order


# ── 预约 #33 ──────────────────────────────
@router.post("/reservations", response_model=ReservationOut,
             status_code=status.HTTP_201_CREATED)
def create_reservation(
    body: ReservationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """公用资产预约(#33):按时段预约;同一资产同一时段只能一个有效
    预约,冲突返回明确错误。"""
    card = _get_card_or_404(db, body.asset_id)
    _require_booked(card)
    if card.status in (AssetStatus.repairing.value,
                       AssetStatus.pending_disposal.value):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"资产 {card.asset_code} 当前状态 {card.status},不可预约",
        )
    start, end = body.start_at, body.end_at
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    if end <= start:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "预约结束时间须晚于开始时间")
    clash = db.query(AssetReservation).filter_by(
        asset_id=card.id, status=ReservationStatus.PENDING).filter(
        AssetReservation.start_at < end,
        AssetReservation.end_at > start,
    ).first()
    if clash is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"时间冲突:资产 {card.asset_code} 在该时段已有预约单 {clash.doc_no} "
            f"({clash.start_at} 至 {clash.end_at}),请另选时段",
        )
    doc_no = circ_svc.next_doc_no(db, "预约单")
    row = AssetReservation(
        doc_no=doc_no, asset_id=card.id,
        reserver_id=user.id, reserver_name=_display(user),
        start_at=start, end_at=end, purpose=body.purpose,
        status=ReservationStatus.PENDING,
    )
    db.add(row)
    db.flush()
    log_asset_action(
        db, user, "asset_reservation_create",
        target_type="reservation", target_id=row.id,
        detail=f"预约 {doc_no} 资产{card.asset_code} "
               f"{start.strftime('%Y-%m-%d %H:%M')} 至 {end.strftime('%Y-%m-%d %H:%M')}",
    )
    db.commit()
    return row


@router.get("/reservations", response_model=list[ReservationOut])
def list_reservations(
    asset_id: int | None = None,
    status_: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    q = db.query(AssetReservation)
    if asset_id is not None:
        q = q.filter_by(asset_id=asset_id)
    if status_:
        q = q.filter_by(status=status_)
    elif Role.admin.value not in user.role_names and \
            Role.asset_admin.value not in user.role_names:
        q = q.filter_by(reserver_id=user.id)
    return q.order_by(AssetReservation.id.desc()).limit(200).all()


@router.post("/reservations/{reservation_id}/checkout", response_model=ReservationOut)
def checkout_reservation(
    reservation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """预约领用(#33):预约人到时领用,转为一笔借用单,资产状态→借出。"""
    row = db.get(AssetReservation, reservation_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "预约单不存在")
    if user.id != row.reserver_id and Role.admin.value not in user.role_names:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅预约人可领用")
    if row.status != ReservationStatus.PENDING:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"预约单当前状态 {row.status},不可领用")
    card = _get_card_or_404(db, row.asset_id)
    if card.status not in (AssetStatus.in_stock.value, AssetStatus.in_use.value):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"资产 {card.asset_code} 当前状态 {card.status},不可领用",
        )
    doc_no = circ_svc.next_doc_no(db, "借用单")
    borrow = AssetBorrowOrder(
        doc_no=doc_no, asset_id=card.id,
        borrower_id=user.id, borrower_name=_display(user),
        reason=f"预约领用 {row.doc_no}:{row.purpose}",
        due_at=row.end_at, status=BorrowStatusDoc.BORROWING,
    )
    db.add(borrow)
    db.flush()
    _transition(db, user, card, AssetStatus.lent.value, "借用单", doc_no)
    card.borrow_status = BorrowStatus.lent.value
    card.last_used_at = datetime.now(UTC)
    row.status = ReservationStatus.CHECKED_OUT
    row.borrow_order_id = borrow.id
    log_asset_action(
        db, user, "asset_reservation_checkout",
        target_type="reservation", target_id=row.id,
        detail=f"预约领用 {row.doc_no} 转借用单 {doc_no}",
    )
    db.commit()
    return row


@router.post("/reservations/{reservation_id}/cancel", response_model=ReservationOut)
def cancel_reservation(
    reservation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    row = db.get(AssetReservation, reservation_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "预约单不存在")
    if user.id != row.reserver_id and Role.admin.value not in user.role_names:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅预约人或管理员可取消")
    if row.status != ReservationStatus.PENDING:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"预约单当前状态 {row.status},不可取消")
    row.status = ReservationStatus.CANCELLED
    db.commit()
    return row


@router.post("/reservations/scan-release", response_model=dict)
def scan_release_reservations(
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """预约自动释放扫描(#33):到期未领用的预约标 已释放并记日志。
    手动触发;后续批次挂定时任务时复用同一服务函数。"""
    result = circ_svc.scan_reservation_release(db, user)
    db.commit()
    return result


# ── 归还 #34 ──────────────────────────────
@router.post("/returns", response_model=ReturnOut, status_code=status.HTTP_201_CREATED)
def create_return(
    body: ReturnCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """归还单(#34):由借用人/领用人或资产管理员发起,扫码验收时才
    改变资产状态。"""
    card = _get_card_or_404(db, body.asset_id)
    if card.status not in (AssetStatus.lent.value, AssetStatus.in_use.value):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"资产 {card.asset_code} 当前状态 {card.status},无需归还",
        )
    if body.source_doc_type not in ("借用单", "领用单"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "来源单据类型须为 借用单/领用单")
    if body.source_doc_type == "借用单" and body.source_doc_id is not None:
        borrow = db.get(AssetBorrowOrder, body.source_doc_id)
        if borrow is None or borrow.asset_id != card.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "借用单与资产不符")
        if borrow.status not in (BorrowStatusDoc.BORROWING, BorrowStatusDoc.OVERDUE):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "借用单已归还,不可重复归还")
        if user.id != borrow.borrower_id and \
                Role.asset_admin.value not in user.role_names and \
                Role.admin.value not in user.role_names:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "仅借用人或资产管理员可归还")
    doc_no = circ_svc.next_doc_no(db, "归还单")
    row = AssetReturnOrder(
        doc_no=doc_no, asset_id=card.id,
        source_doc_type=body.source_doc_type,
        source_doc_id=body.source_doc_id,
        returner_id=user.id, returner_name=_display(user),
        status=ReturnStatus.PENDING,
    )
    db.add(row)
    db.flush()
    log_asset_action(
        db, user, "asset_return_create",
        target_type="return_order", target_id=row.id,
        detail=f"归还申请 {doc_no} 资产{card.asset_code} 来源{body.source_doc_type}",
    )
    db.commit()
    return row


@router.get("/returns", response_model=list[ReturnOut])
def list_returns(
    status_: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    q = db.query(AssetReturnOrder)
    if status_:
        q = q.filter_by(status=status_)
    elif Role.admin.value not in user.role_names and \
            Role.asset_admin.value not in user.role_names:
        q = q.filter_by(returner_id=user.id)
    return q.order_by(AssetReturnOrder.id.desc()).limit(200).all()


@router.post("/returns/{return_id}/scan", response_model=ReturnOut)
def scan_return(
    return_id: int,
    body: ReturnScanIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """归还验收(扫码)(#34):完好→回在库;损坏→转维修中并生成维修占位单
    (B4 接入)。回库后 sync_status 保持原值,不自动同步。"""
    row = db.get(AssetReturnOrder, return_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "归还单不存在")
    if user.id != row.returner_id and \
            Role.asset_admin.value not in user.role_names and \
            Role.admin.value not in user.role_names:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅归还人或资产管理员可验收")
    if row.status != ReturnStatus.PENDING:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"归还单当前状态 {row.status},已验收")
    card = _get_card_or_404(db, row.asset_id)
    if body.label_code != card.label_code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "标签码与归还资产不符")
    row.result = body.result
    row.damage_note = body.damage_note
    row.scanned_at = datetime.now(UTC)
    card.last_used_at = datetime.now(UTC)
    if body.result == ReturnResult.GOOD:
        _transition(db, user, card, AssetStatus.in_stock.value, "归还单", row.doc_no)
        card.borrow_status = BorrowStatus.returned.value
        row.status = ReturnStatus.DONE
        if row.source_doc_type == "借用单" and row.source_doc_id is not None:
            borrow = db.get(AssetBorrowOrder, row.source_doc_id)
            if borrow is not None:
                borrow.status = BorrowStatusDoc.RETURNED
                borrow.returned_at = datetime.now(UTC)
    else:
        # 损坏:状态机无 借出→维修中 的直连边,须经两步转移(借出→在库→
        # 维修中),两步都走 transition 服务函数、都带归还单号、都记审计。
        _transition(db, user, card, AssetStatus.in_stock.value, "归还单", row.doc_no)
        _transition(db, user, card, AssetStatus.repairing.value, "归还单", row.doc_no)
        repair_no = circ_svc.next_doc_no(db, "维修单")
        repair = AssetRepairOrder(
            doc_no=repair_no, asset_id=card.id, source="归还验收",
            source_doc_no=row.doc_no, reporter_id=user.id,
            reporter_name=_display(user),
            description=body.damage_note or "归还验收发现损坏",
            status=RepairPlaceholderStatus.PENDING,
        )
        db.add(repair)
        db.flush()
        row.repair_order_id = repair.id
        row.status = ReturnStatus.TO_REPAIR
        if row.source_doc_type == "借用单" and row.source_doc_id is not None:
            borrow = db.get(AssetBorrowOrder, row.source_doc_id)
            if borrow is not None:
                borrow.status = BorrowStatusDoc.RETURNED
                borrow.returned_at = datetime.now(UTC)
        log_asset_action(
            db, user, "asset_repair_placeholder_create",
            target_type="repair_order", target_id=repair.id,
            detail=f"归还损坏生成维修占位单 {repair_no} 资产{card.asset_code} "
                   "(B4 接入维修流程)",
        )
    log_asset_action(
        db, user, "asset_return_scan",
        target_type="return_order", target_id=row.id,
        detail=f"归还验收 {row.doc_no} 资产{card.asset_code} 结果{body.result}",
    )
    db.commit()
    return row


# ── 团体保管 #35 ──────────────────────────────
@router.post("/group-custodies", response_model=GroupCustodyOut,
             status_code=status.HTTP_201_CREATED)
def create_group_custody(
    body: GroupCustodyCreate,
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """班级/团体保管(#35):保管单位记班级/团体,保管人记责任教师;
    复用智慧教务班级数据,不给学生开账号。"""
    card = _get_card_or_404(db, body.asset_id)
    _require_booked(card)
    if card.status not in (AssetStatus.in_stock.value, AssetStatus.in_use.value):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"资产 {card.asset_code} 当前状态 {card.status},不可办理团体保管",
        )
    teacher = db.get(User, body.teacher_id)
    if teacher is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "责任教师用户不存在")
    if body.group_ref_id is not None and db.get(ClassUnit, body.group_ref_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "班级不存在(请复用智慧教务班级数据)")
    old = db.query(AssetGroupCustody).filter_by(
        asset_id=card.id, is_active=True).first()
    if old is not None:
        old.is_active = False
    doc_no = circ_svc.next_doc_no(db, "团体保管单")
    row = AssetGroupCustody(
        doc_no=doc_no, asset_id=card.id,
        group_type=body.group_type, group_name=body.group_name,
        group_ref_id=body.group_ref_id,
        teacher_id=teacher.id, teacher_name=_display(teacher),
        note=body.note, is_active=True, created_by=user.id,
    )
    db.add(row)
    db.flush()
    card.custodian_user_id = teacher.id
    card.custodian_name = _display(teacher)
    card.use_dept = body.group_name
    card.borrow_status = BorrowStatus.issued.value
    card.last_used_at = datetime.now(UTC)
    log_asset_action(
        db, user, "asset_group_custody_create",
        target_type="group_custody", target_id=row.id,
        detail=f"团体保管 {doc_no} 资产{card.asset_code} "
               f"{body.group_type}{body.group_name} 责任教师{_display(teacher)}",
    )
    db.commit()
    return row


@router.get("/group-custodies", response_model=list[GroupCustodyOut])
def list_group_custodies(
    asset_id: int | None = None,
    is_active: bool | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    q = db.query(AssetGroupCustody)
    if asset_id is not None:
        q = q.filter_by(asset_id=asset_id)
    if is_active is not None:
        q = q.filter_by(is_active=is_active)
    return q.order_by(AssetGroupCustody.id.desc()).limit(200).all()


# ── 维修占位单(只读,B4 接入) ──────────────────────────────
@router.get("/repairs", response_model=list[RepairOut])
def list_repairs(
    asset_id: int | None = None,
    status_: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    q = db.query(AssetRepairOrder)
    if asset_id is not None:
        q = q.filter_by(asset_id=asset_id)
    if status_:
        q = q.filter_by(status=status_)
    return q.order_by(AssetRepairOrder.id.desc()).limit(200).all()


@router.get("/repairs/{repair_id}", response_model=RepairOut)
def get_repair(
    repair_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    row = db.get(AssetRepairOrder, repair_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "维修单不存在")
    return row
