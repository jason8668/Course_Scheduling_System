"""维修保养 API(学校资产管理系统一期第 4 批 #42/#43/#44)。

挂在 /api/asset 下。报修写入 B3 已建的 asset_repair_orders 占位表
(本批在该表上扩展派单/维修方/费用/结果/报修人确认字段,不另建维修表)。
流程:报修(待处理) → 管理员派单/送修(资产经 transition 入维修中,
修前状态记 pre_repair_status) → 登记维修方/费用/结果(待确认;费用
≥ approval.repair_threshold,默认 5000 元时先入待审批走通用审批流)
→ 报修人确认后关闭(费用累计进资产卡 total_repair_cost,资产按修前
状态转回在库/在用)。维修单据经履历时间轴数据源自动沉淀(#44)。
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.asset_circulation import _display, _transition
from app.api.asset_foundation import (
    _get_card_or_404,
    asset_writer,
    require_asset_roles,
)
from app.core.auth import get_active_user
from app.core.db import get_db
from app.models.asset_approval import ApprovalInstance
from app.models.asset_card import AssetCard, AssetStatus
from app.models.asset_circulation import AssetRepairOrder, RepairStatus
from app.models.user import Role, User
from app.schemas.asset_circulation import RepairOut
from app.schemas.asset_repair_inventory import (
    RepairCostSummaryOut,
    RepairCreate,
    RepairDispatchIn,
    RepairRecordIn,
    RepairScanOut,
)
from app.services import asset_approval as approval_svc
from app.services import asset_circulation as circ_svc
from app.services import asset_inventory as inv_svc
from app.services.asset_audit import log_asset_action

router = APIRouter(tags=["asset"])

#: 修好后可回的状态:修前为在库/在用按原状态回,其他一律回在库。
_RETURNABLE = {AssetStatus.in_stock.value, AssetStatus.in_use.value}


def _get_repair_or_404(db: Session, repair_id: int) -> AssetRepairOrder:
    row = db.get(AssetRepairOrder, repair_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "维修单不存在")
    return row


def _card_by_label(db: Session, label_code: str) -> AssetCard:
    card = db.query(AssetCard).filter_by(label_code=label_code).first()
    if card is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"标签码 {label_code} 未找到对应资产,请走未贴标补录",
        )
    return card


def _scan_out(card: AssetCard, order: AssetRepairOrder | None,
              created: bool) -> RepairScanOut:
    info = inv_svc.warranty_info(card)
    return RepairScanOut(
        asset_id=card.id, asset_code=card.asset_code, name=card.name,
        status=card.status, room_name=card.room_name,
        custodian_name=card.custodian_name,
        warranty_until=info["warranty_until"],
        in_warranty=info["in_warranty"], warranty_hint=info["warranty_hint"],
        repair_order_id=order.id if order else None,
        doc_no=order.doc_no if order else None, created=created,
    )


# ── #42 扫码报修 ──────────────────────────────
@router.post("/repairs/scan", response_model=RepairScanOut)
def scan_repair(
    body: RepairCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """扫码报修(#42):扫标签码自动带出设备信息、存放地点和保修状态,
    拍照描述故障一键报修;保内故障明确提示走厂商保修。

    同一资产已有未关闭工单时不重复建单,返回既有工单。
    """
    card = (_card_by_label(db, body.label_code) if body.label_code
            else _get_card_or_404(db, body.asset_id or -1))
    if card.is_retired:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "资产已核销,不可报修")
    if card.custodian_user_id != user.id and \
            Role.asset_admin.value not in user.role_names and \
            Role.admin.value not in user.role_names:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "仅保管人或资产管理员可报修")
    existing = db.query(AssetRepairOrder).filter_by(asset_id=card.id).filter(
        AssetRepairOrder.status.notin_([RepairStatus.CLOSED])).first()
    if existing is not None:
        return _scan_out(card, existing, created=False)
    doc_no = circ_svc.next_doc_no(db, "维修单")
    order = AssetRepairOrder(
        doc_no=doc_no, asset_id=card.id, source="报修",
        reporter_id=user.id, reporter_name=_display(user),
        description=body.description or "扫码报修",
        photo_url=body.photo_url, status=RepairStatus.PENDING,
    )
    db.add(order)
    db.flush()
    log_asset_action(
        db, user, "asset_repair_create",
        target_type="repair_order", target_id=order.id,
        detail=f"扫码报修 {doc_no} 资产{card.asset_code} "
               f"{'保内,提示走厂商保修' if inv_svc.warranty_info(card)['in_warranty'] else '已过保/无保修信息'}",
    )
    db.commit()
    db.refresh(order)
    return _scan_out(card, order, created=True)


@router.post("/repairs", response_model=RepairOut,
             status_code=status.HTTP_201_CREATED)
def create_repair(
    body: RepairCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """报修(与扫码报修同一入口,资产 id 直报修时用)。"""
    result = scan_repair(body, db=db, user=user)
    if not result.created:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"资产 {result.asset_code} 已有未关闭维修单 {result.doc_no}",
        )
    return _get_repair_or_404(db, result.repair_order_id or -1)


# ── #43 派单与维修处理 ──────────────────────────────
@router.post("/repairs/{repair_id}/dispatch", response_model=RepairOut)
def dispatch_repair(
    repair_id: int,
    body: RepairDispatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """管理员派单/送修(#43):登记派单对象与维修方;送修时资产经
    transition 入维修中,修前状态记 pre_repair_status。"""
    order = _get_repair_or_404(db, repair_id)
    if order.status not in (RepairStatus.PENDING, RepairStatus.DISPATCHED):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"维修单当前状态 {order.status},不可派单",
        )
    card = _get_card_or_404(db, order.asset_id)
    order.assignee_id = body.assignee_id
    order.assignee_name = body.assignee_name
    if body.vendor:
        order.vendor = body.vendor
    if body.send_to_repair:
        order.pre_repair_status = card.status
        _transition(db, user, card, AssetStatus.repairing.value,
                    doc_type="维修单", doc_no=order.doc_no)
        order.status = RepairStatus.REPAIRING
    else:
        order.status = RepairStatus.DISPATCHED
    log_asset_action(
        db, user, "asset_repair_dispatch",
        target_type="repair_order", target_id=order.id,
        detail=f"派单 {order.doc_no} 派给{order.assignee_name or ''} "
               f"维修方{order.vendor or ''} "
               f"{'已送修,资产转维修中' if body.send_to_repair else '未送修'}",
    )
    db.commit()
    db.refresh(order)
    return order


@router.post("/repairs/{repair_id}/record", response_model=RepairOut)
def record_repair(
    repair_id: int,
    body: RepairRecordIn,
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """登记维修方、费用、结果(#43):费用 ≥ 阈值(默认 5000 元)时创建
    维修单审批实例,工单先入待审批;低于阈值直接进待确认。"""
    order = _get_repair_or_404(db, repair_id)
    if order.status not in (RepairStatus.DISPATCHED, RepairStatus.REPAIRING,
                            RepairStatus.PENDING):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"维修单当前状态 {order.status},不可登记维修结果",
        )
    if not body.result:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "维修结果不能为空")
    if body.vendor:
        order.vendor = body.vendor
    order.cost = body.cost
    order.result = body.result
    threshold = inv_svc.repair_threshold(db)
    if body.cost >= threshold:
        # 申请人记报修人(费用由管理员代登记,申请人若记管理员会在
        # 资产管理员节点触发岗位分离拦截)。
        applicant = db.get(User, order.reporter_id) or user
        try:
            inst = approval_svc.create_instance(
                db, applicant, doc_type="维修单", doc_id=order.id,
                doc_no=order.doc_no, amount=body.cost)
        except approval_svc.ApprovalError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
        order.approval_instance_id = inst.id
        order.status = RepairStatus.PENDING_APPROVAL
        detail = (f"登记维修结果 {order.doc_no} 费用{body.cost}元 "
                  f"≥阈值{threshold}元,已发起审批 实例{inst.id}")
    else:
        order.status = RepairStatus.PENDING_CONFIRM
        detail = (f"登记维修结果 {order.doc_no} 费用{body.cost}元 "
                  f"<阈值{threshold}元,待报修人确认")
    log_asset_action(
        db, user, "asset_repair_record",
        target_type="repair_order", target_id=order.id, detail=detail,
        after={"cost": body.cost, "status": order.status},
    )
    db.commit()
    db.refresh(order)
    return order


@router.post("/repairs/{repair_id}/confirm", response_model=RepairOut)
def confirm_repair(
    repair_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """报修人确认后关闭工单(#43):仅报修人可确认;超阈值工单须先
    通过审批;确认时费用累计进资产卡,资产按修前状态转回在库/在用。"""
    order = _get_repair_or_404(db, repair_id)
    if order.reporter_id != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "仅报修人可确认关闭维修单")
    if order.status == RepairStatus.PENDING_APPROVAL:
        inst = db.get(ApprovalInstance, order.approval_instance_id) \
            if order.approval_instance_id else None
        if inst is None or inst.status != "已通过":
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "维修费用超阈值,须先通过审批才可确认关闭",
            )
        order.status = RepairStatus.PENDING_CONFIRM
    if order.status != RepairStatus.PENDING_CONFIRM:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"维修单当前状态 {order.status},不可确认关闭",
        )
    card = _get_card_or_404(db, order.asset_id)
    cost = float(order.cost or 0)
    card.total_repair_cost = float(card.total_repair_cost or 0) + cost
    if card.status == AssetStatus.repairing.value:
        back = order.pre_repair_status if order.pre_repair_status in _RETURNABLE \
            else AssetStatus.in_stock.value
        _transition(db, user, card, back,
                    doc_type="维修单", doc_no=order.doc_no)
    order.status = RepairStatus.CLOSED
    order.confirmed_by = user.id
    order.confirmed_at = datetime.now(UTC)
    order.closed_at = datetime.now(UTC)
    log_asset_action(
        db, user, "asset_repair_confirm",
        target_type="repair_order", target_id=order.id,
        detail=f"报修人确认关闭 {order.doc_no} 费用{cost}元已累计 "
               f"资产{card.asset_code}累计维修费{card.total_repair_cost}元",
        after={"status": RepairStatus.CLOSED, "total_repair_cost": card.total_repair_cost},
    )
    db.commit()
    db.refresh(order)
    return order


@router.get("/repairs/summary/by-asset", response_model=RepairCostSummaryOut)
def repair_cost_summary(
    asset_id: int = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """维修费用累计查询(#43):单件资产累计维修费、已关闭/未关闭工单数。"""
    card = _get_card_or_404(db, asset_id)
    orders = db.query(AssetRepairOrder).filter_by(asset_id=asset_id).all()
    closed = [o for o in orders if o.status == RepairStatus.CLOSED]
    return RepairCostSummaryOut(
        asset_id=asset_id, total_cost=float(card.total_repair_cost or 0),
        closed_count=len(closed), open_count=len(orders) - len(closed),
        threshold=inv_svc.repair_threshold(db),
    )
