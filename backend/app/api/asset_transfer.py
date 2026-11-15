"""调拨与人员移交 API(学校资产管理系统一期第 3 批 #37/#39/#40)。

挂在 /api/asset 下。
- #37 调拨:调出部门发起 → 调入部门确认 → 审批(调拨单审批流,
  金额超阈值到总务) → 完成(责任与位置同步变更)。调拨不改变资产
  状态(只改保管人/部门/位置),故不调用 transition(状态无变化时
  状态机会拦截);已同步资产完成调拨后打待同步变更标记
  pending_sync_change(供 B5 #98 手动勾选再同步),不自动同步。
- #39 移交:按人员生成移交单(手动/按人员查询触发;未接人事系统,
  不假装已联动),扫码逐件确认接收人;完成前原保管人责任不解除
  (逐件确认才逐件转移保管人)。
- #40 预警:未办结超阈值(默认 7 天)扫描预警,见 asset_workspace。
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.asset_circulation import _display, _get_card_or_404, _require_booked
from app.api.asset_foundation import asset_writer, require_asset_roles
from app.core.auth import get_active_user
from app.core.db import get_db
from app.models.asset_card import AssetCard, AssetStatus, SyncStatus
from app.models.asset_circulation import (
    AssetHandoverItem,
    AssetHandoverOrder,
    AssetTransferOrder,
    HandoverStatus,
    TransferStatus,
)
from app.models.asset_approval import ApprovalFlow, ApprovalInstance
from app.models.user import Role, User
from app.schemas.asset_circulation import (
    HandoverGenerate,
    HandoverItemConfirmIn,
    HandoverOut,
    TransferCreate,
    TransferOut,
)
from app.services import asset_approval as approval_svc
from app.services import asset_circulation as circ_svc
from app.services import asset_notify as notify_svc
from app.services.asset_audit import log_asset_action

router = APIRouter(tags=["asset"])


def _transfer_out(db: Session, order: AssetTransferOrder) -> TransferOut:
    """调拨单状态跟随审批实例:已退回→已退回;已通过且待审批→待完成。"""
    if order.approval_instance_id is not None and order.status in (
            TransferStatus.PENDING_APPROVAL,):
        inst = db.get(ApprovalInstance, order.approval_instance_id)
        if inst is not None and inst.status == "已退回":
            order.status = TransferStatus.REJECTED
        elif inst is not None and inst.status == "已通过":
            order.status = TransferStatus.PENDING_FINISH
    return TransferOut.model_validate(order)


def _handover_out(db: Session, order: AssetHandoverOrder) -> HandoverOut:
    out = HandoverOut.model_validate(order)
    items = db.query(AssetHandoverItem).filter_by(
        handover_id=order.id).order_by(AssetHandoverItem.id).all()
    from app.schemas.asset_circulation import HandoverItemOut

    out.items = [HandoverItemOut.model_validate(i) for i in items]
    return out


# ── 调拨 #37 ──────────────────────────────
@router.post("/transfers", response_model=TransferOut,
             status_code=status.HTTP_201_CREATED)
def create_transfer(
    body: TransferCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_asset_roles(Role.asset_admin, Role.asset_dept_admin)),
):
    """部门间调拨(#37):调出部门发起,调入部门确认,资产管理员审核。
    借出/维修中/待处置/已核销资产不可调拨。
    发起人须为调出部门资产管理员或资产管理员;审批流第 2 步为资产
    管理员,发起人若为资产管理员则须由他人审批(岗位分离)。"""
    card = _get_card_or_404(db, body.asset_id)
    _require_booked(card)
    if card.status not in (AssetStatus.in_stock.value, AssetStatus.in_use.value):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"资产 {card.asset_code} 当前状态 {card.status},不可调拨",
        )
    to_custodian_name = None
    if body.to_custodian_id is not None:
        to_user = db.get(User, body.to_custodian_id)
        if to_user is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "调入保管人不存在")
        to_custodian_name = _display(to_user)
    doc_no = circ_svc.next_doc_no(db, "调拨单")
    order = AssetTransferOrder(
        doc_no=doc_no, asset_id=card.id,
        from_dept=card.manage_dept, to_dept=body.to_dept,
        to_custodian_id=body.to_custodian_id,
        to_custodian_name=to_custodian_name,
        to_room_name=body.to_room_name,
        reason=body.reason,
        amount=float(card.original_value) if card.original_value is not None else None,
        status=TransferStatus.PENDING_IN,
        created_by=user.id,
    )
    db.add(order)
    db.flush()
    flow = None
    if body.flow_id is not None:
        flow = db.get(ApprovalFlow, body.flow_id)
        if flow is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "审批流不存在")
    try:
        inst = approval_svc.create_instance(
            db, user, doc_type="调拨单", doc_id=order.id, doc_no=doc_no,
            amount=order.amount, flow=flow,
        )
    except approval_svc.ApprovalError as e:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    order.approval_instance_id = inst.id
    db.flush()
    log_asset_action(
        db, user, "asset_transfer_create",
        target_type="transfer_order", target_id=order.id,
        detail=f"调拨申请 {doc_no} 资产{card.asset_code} "
               f"{card.manage_dept or ''} → {body.to_dept}",
    )
    db.commit()
    return _transfer_out(db, order)


@router.get("/transfers", response_model=list[TransferOut])
def list_transfers(
    status_: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    q = db.query(AssetTransferOrder)
    if status_:
        q = q.filter_by(status=status_)
    return [_transfer_out(db, r) for r in
            q.order_by(AssetTransferOrder.id.desc()).limit(200).all()]


@router.get("/transfers/{order_id}", response_model=TransferOut)
def get_transfer(
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    order = db.get(AssetTransferOrder, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "调拨单不存在")
    return _transfer_out(db, order)


@router.post("/transfers/{order_id}/confirm-in", response_model=TransferOut)
def confirm_in_transfer(
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """调入部门确认(#37):调入部门管理员(或资产管理员)确认接收。"""
    order = db.get(AssetTransferOrder, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "调拨单不存在")
    if Role.asset_dept_admin.value not in user.role_names and \
            Role.asset_admin.value not in user.role_names and \
            Role.admin.value not in user.role_names:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "调入确认须由部门资产管理员或资产管理员操作")
    if order.status != TransferStatus.PENDING_IN:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"调拨单当前状态 {order.status},不可确认")
    order.status = TransferStatus.PENDING_APPROVAL
    order.in_confirmed_by = user.id
    order.in_confirmed_at = datetime.now(UTC)
    log_asset_action(
        db, user, "asset_transfer_confirm_in",
        target_type="transfer_order", target_id=order.id,
        detail=f"调拨调入确认 {order.doc_no} 调入部门{order.to_dept}",
    )
    db.commit()
    return _transfer_out(db, order)


@router.post("/transfers/{order_id}/finalize", response_model=TransferOut)
def finalize_transfer(
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """调拨完成(#37):须调入已确认且审批已通过;责任与位置同步变更。
    已同步资产只打待同步变更标记,不自动同步。"""
    order = db.get(AssetTransferOrder, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "调拨单不存在")
    _transfer_out(db, order)
    if order.in_confirmed_at is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "调入部门尚未确认,不可完成调拨")
    if order.status != TransferStatus.PENDING_FINISH:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"调拨单当前状态 {order.status},须审批通过后方可完成",
        )
    card = _get_card_or_404(db, order.asset_id)
    before = {"manage_dept": card.manage_dept, "custodian_name": card.custodian_name,
              "room_name": card.room_name}
    was_synced = card.sync_status == SyncStatus.synced.value
    card.manage_dept = order.to_dept
    card.use_dept = order.to_dept
    if order.to_custodian_id is not None:
        card.custodian_user_id = order.to_custodian_id
        card.custodian_name = order.to_custodian_name
    if order.to_room_name:
        card.room_name = order.to_room_name
    card.last_used_at = datetime.now(UTC)
    if was_synced:
        card.pending_sync_change = True
        card.pending_sync_change_reason = f"调拨 {order.doc_no}:部门/保管人变更"
    order.status = TransferStatus.DONE
    log_asset_action(
        db, user, "asset_transfer_finalize",
        target_type="transfer_order", target_id=order.id,
        detail=f"调拨完成 {order.doc_no} 资产{card.asset_code} "
               f"调入{order.to_dept}"
               + (" 已同步资产打待同步变更标记" if was_synced else ""),
        before={k: str(v) for k, v in before.items()},
        after={"manage_dept": card.manage_dept,
               "custodian_name": card.custodian_name,
               "room_name": card.room_name},
    )
    db.commit()
    return _transfer_out(db, order)


# ── 移交 #39 ──────────────────────────────
@router.post("/handovers/generate", response_model=HandoverOut,
             status_code=status.HTTP_201_CREATED)
def generate_handover(
    body: HandoverGenerate,
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """按人员生成移交单(#39):汇总该人名下全部未核销资产(保管人=
    该人)。触发源为手动/按人员查询触发;未接人事系统,不假装已联动。
    名下无资产时返回 400。"""
    from_user = db.get(User, body.from_user_id)
    to_user = db.get(User, body.to_user_id)
    if from_user is None or to_user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "移交方或接收方用户不存在")
    if body.from_user_id == body.to_user_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "移交方与接收方不能为同一人")
    cards = db.query(AssetCard).filter_by(
        custodian_user_id=from_user.id, is_retired=False).order_by(
        AssetCard.id).all()
    if not cards:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{_display(from_user)} 名下无未核销资产,无需生成移交单",
        )
    doc_no = circ_svc.next_doc_no(db, "移交单")
    order = AssetHandoverOrder(
        doc_no=doc_no, from_user_id=from_user.id,
        from_user_name=_display(from_user),
        to_user_id=to_user.id, to_user_name=_display(to_user),
        reason_type=body.reason_type,
        status=HandoverStatus.PENDING, created_by=user.id,
    )
    db.add(order)
    db.flush()
    for card in cards:
        db.add(AssetHandoverItem(
            handover_id=order.id, asset_id=card.id,
            asset_code=card.asset_code, status="待确认",
        ))
    db.flush()
    log_asset_action(
        db, user, "asset_handover_create",
        target_type="handover_order", target_id=order.id,
        detail=f"生成移交单 {doc_no} {_display(from_user)} → {_display(to_user)} "
               f"共 {len(cards)} 件",
    )
    # 钉钉推送(#7):通知接收人;失败只记日志不阻塞。
    notify_svc.push_to_user(
        db, to_user.id, "资产移交通知",
        f"移交单 {doc_no} 待您逐件扫码确认接收,共 {len(cards)} 件。",
    )
    db.commit()
    return _handover_out(db, order)


@router.get("/handovers", response_model=list[HandoverOut])
def list_handovers(
    status_: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    q = db.query(AssetHandoverOrder)
    if status_:
        q = q.filter_by(status=status_)
    elif Role.admin.value not in user.role_names and \
            Role.asset_admin.value not in user.role_names:
        q = q.filter(
            (AssetHandoverOrder.from_user_id == user.id) |
            (AssetHandoverOrder.to_user_id == user.id))
    return [_handover_out(db, r) for r in
            q.order_by(AssetHandoverOrder.id.desc()).limit(200).all()]


@router.get("/handovers/{order_id}", response_model=HandoverOut)
def get_handover(
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    order = db.get(AssetHandoverOrder, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "移交单不存在")
    return _handover_out(db, order)


@router.post("/handovers/{order_id}/items/{item_id}/confirm",
             response_model=HandoverOut)
def confirm_handover_item(
    order_id: int,
    item_id: int,
    body: HandoverItemConfirmIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """逐件扫码确认(#39):接收人(或资产管理员)扫标签码逐件确认;
    确认的件立即转移保管人,未确认的件责任仍在原保管人。"""
    order = db.get(AssetHandoverOrder, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "移交单不存在")
    item = db.get(AssetHandoverItem, item_id)
    if item is None or item.handover_id != order.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "移交明细不存在")
    if user.id != order.to_user_id and \
            Role.asset_admin.value not in user.role_names and \
            Role.admin.value not in user.role_names:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅接收人或资产管理员可确认")
    if item.status == "已确认":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "该件已确认,不可重复确认")
    card = _get_card_or_404(db, item.asset_id)
    if body.label_code != card.label_code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "标签码与移交资产不符")
    item.status = "已确认"
    item.confirmed_by = user.id
    item.confirmed_at = datetime.now(UTC)
    card.custodian_user_id = order.to_user_id
    card.custodian_name = order.to_user_name
    card.last_used_at = datetime.now(UTC)
    # 显式 flush:调用方会话可能 autoflush=False,须先落库再数剩余件。
    db.flush()
    remaining = db.query(AssetHandoverItem).filter_by(
        handover_id=order.id, status="待确认").count()
    if remaining == 0:
        order.status = HandoverStatus.DONE
        log_asset_action(
            db, user, "asset_handover_complete",
            target_type="handover_order", target_id=order.id,
            detail=f"移交完成 {order.doc_no} 全部件已确认",
        )
    else:
        order.status = HandoverStatus.PARTIAL
    log_asset_action(
        db, user, "asset_handover_item_confirm",
        target_type="handover_item", target_id=item.id,
        detail=f"移交逐件确认 {order.doc_no} 资产{card.asset_code} "
               f"接收人{order.to_user_name} 剩余 {remaining} 件",
    )
    db.commit()
    return _handover_out(db, order)
