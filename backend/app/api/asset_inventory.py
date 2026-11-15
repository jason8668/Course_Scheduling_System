"""盘点清查 API(学校资产管理系统一期第 4 批 #48/#49/#51/#52)。

挂在 /api/asset 下。
- #48 方案与任务拆分:全校盘点/抽盘/专项盘点,按部门/房间/分类拆分
  任务分派到人;任务下发写 盘点任务 提醒并钉钉推送(复用 asset_notify)。
- #49 手机扫码盘点:同一扫码接口支持离线暂存(is_offline)、弱网续传;
  未贴标资产现场补录拍照进待核实清单;扫码校验标签码与任务范围,
  范围外明确提示、不静默计入(不建记录);扫码写 last_used_at。
- #51 五类差异自动比对:实盘与台账比对,生成正常/盘亏/盘盈/位置不符/
  保管人不符五类差异,可按任务/部门/分类查看。
- #52 差异核实与处理:盘亏查责任、盘盈走 #24 盘盈补记入库补建卡、
  位置/保管人不符直接更正并留痕;关闭须领导(director)确认,差异
  未处理完(无处理也无说明)不得关闭。盘点结果不自动同步到官方,
  报告只标注哪些差异涉及已同步资产(B5 #98/#100 手动勾选时参考)。
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.asset_foundation import (
    _get_card_or_404,
    asset_writer,
    require_asset_roles,
)
from app.core.auth import get_active_user
from app.core.db import get_db
from app.models.asset_card import AssetCard, SyncStatus
from app.models.asset_inventory import (
    AssetInventoryDifference,
    AssetInventoryPlan,
    AssetInventoryRecord,
    AssetInventoryTask,
    InventoryDiffStatus,
    InventoryDiffType,
    InventoryPlanStatus,
    InventoryTaskStatus,
)
from app.models.user import Role, User
from app.schemas.asset_repair_inventory import (
    InventoryCloseIn,
    InventoryDifferenceOut,
    InventoryPlanCreate,
    InventoryPlanDetailOut,
    InventoryPlanOut,
    InventoryRecordOut,
    InventoryReportOut,
    InventoryResolveIn,
    InventoryScanIn,
    InventoryScanOut,
    InventoryTaskCreate,
    InventoryTaskOut,
    InventoryUnlabelledIn,
)
from app.services import asset_inventory as inv_svc
from app.services.asset_audit import log_asset_action
from app.services.asset_circulation import create_reminder
from app.services import asset_notify as notify_svc

router = APIRouter(tags=["asset"])

leader_only = require_asset_roles(Role.director)


def _get_plan_or_404(db: Session, plan_id: int) -> AssetInventoryPlan:
    row = db.get(AssetInventoryPlan, plan_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "盘点方案不存在")
    return row


def _get_task_or_404(db: Session, task_id: int) -> AssetInventoryTask:
    row = db.get(AssetInventoryTask, task_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "盘点任务不存在")
    return row


def _get_diff_or_404(db: Session, diff_id: int) -> AssetInventoryDifference:
    row = db.get(AssetInventoryDifference, diff_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "差异记录不存在")
    return row


def _plan_detail(db: Session, plan: AssetInventoryPlan) -> InventoryPlanDetailOut:
    tasks = db.query(AssetInventoryTask).filter_by(plan_id=plan.id).all()
    diffs = db.query(AssetInventoryDifference).filter_by(plan_id=plan.id).all()
    counts = {t: 0 for t in (
        InventoryDiffType.NORMAL, InventoryDiffType.SHORTAGE,
        InventoryDiffType.SURPLUS, InventoryDiffType.LOCATION_MISMATCH,
        InventoryDiffType.CUSTODIAN_MISMATCH)}
    for d in diffs:
        counts[d.diff_type] = counts.get(d.diff_type, 0) + 1
    out = InventoryPlanDetailOut.model_validate(plan)
    out.tasks = [InventoryTaskOut.model_validate(t) for t in tasks]
    out.diff_counts = counts
    return out


# ── #48 盘点方案与任务拆分 ──────────────────────────────
@router.post("/inventory/plans", response_model=InventoryPlanOut,
             status_code=status.HTTP_201_CREATED)
def create_plan(
    body: InventoryPlanCreate,
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    plan = AssetInventoryPlan(
        plan_no=inv_svc.next_plan_no(db), name=body.name,
        plan_type=body.plan_type, note=body.note,
        status=InventoryPlanStatus.DRAFT, created_by=user.id,
    )
    db.add(plan)
    db.flush()
    log_asset_action(
        db, user, "asset_inventory_plan_create",
        target_type="inventory_plan", target_id=plan.id,
        detail=f"创建盘点方案 {plan.plan_no} {body.name}({body.plan_type})",
    )
    db.commit()
    db.refresh(plan)
    return plan


@router.get("/inventory/plans", response_model=list[InventoryPlanOut])
def list_plans(
    status_: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    q = db.query(AssetInventoryPlan)
    if status_:
        q = q.filter_by(status=status_)
    return q.order_by(AssetInventoryPlan.id.desc()).all()


@router.get("/inventory/plans/{plan_id}", response_model=InventoryPlanDetailOut)
def get_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    return _plan_detail(db, _get_plan_or_404(db, plan_id))


@router.post("/inventory/plans/{plan_id}/tasks", response_model=InventoryTaskOut,
             status_code=status.HTTP_201_CREATED)
def create_task(
    plan_id: int,
    body: InventoryTaskCreate,
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """任务拆分与分派(#48):任务下发后写 盘点任务 提醒并钉钉推送。"""
    plan = _get_plan_or_404(db, plan_id)
    if plan.status == InventoryPlanStatus.CLOSED:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "盘点方案已关闭,不可再拆任务")
    assignee = db.get(User, body.assignee_id)
    if assignee is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "盘点人不存在")
    task = AssetInventoryTask(
        plan_id=plan.id, assignee_id=assignee.id,
        assignee_name=body.assignee_name or assignee.display_name or assignee.username,
        scope_dept=body.scope_dept, scope_room_name=body.scope_room_name,
        scope_category_code=body.scope_category_code, due_at=body.due_at,
        status=InventoryTaskStatus.PENDING, created_by=user.id,
    )
    db.add(task)
    db.flush()
    if plan.status == InventoryPlanStatus.DRAFT:
        plan.status = InventoryPlanStatus.IN_PROGRESS
    create_reminder(
        db, kind="盘点任务", user_id=assignee.id,
        target_type="inventory_task", target_id=task.id,
        title=f"盘点任务:{plan.plan_no} {plan.name}",
        content=f"盘点方案 {plan.plan_no}({plan.plan_type})分派给你,范围:"
                f"{body.scope_dept or '全校'}"
                f"{'/' + body.scope_room_name if body.scope_room_name else ''}"
                f"{'/' + body.scope_category_code if body.scope_category_code else ''},"
                f"截止 {body.due_at.strftime('%Y-%m-%d %H:%M')}。",
        level="一般",
    )
    notify_svc.push_to_user(
        db, assignee.id, f"盘点任务:{plan.plan_no} {plan.name}",
        f"盘点任务已分派给你,截止 {body.due_at.strftime('%Y-%m-%d')},请按时完成盘点。")
    log_asset_action(
        db, user, "asset_inventory_task_create",
        target_type="inventory_task", target_id=task.id,
        detail=f"盘点任务分派 {plan.plan_no} 给{task.assignee_name} "
               f"截止{body.due_at.strftime('%Y-%m-%d')}",
    )
    db.commit()
    db.refresh(task)
    return task


@router.get("/inventory/tasks", response_model=list[InventoryTaskOut])
def list_tasks(
    plan_id: int | None = None,
    assignee_id: int | None = None,
    status_: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    q = db.query(AssetInventoryTask)
    if plan_id is not None:
        q = q.filter_by(plan_id=plan_id)
    if assignee_id is not None:
        q = q.filter_by(assignee_id=assignee_id)
    if status_:
        q = q.filter_by(status=status_)
    return q.order_by(AssetInventoryTask.id.desc()).all()


@router.get("/inventory/tasks/{task_id}", response_model=InventoryTaskOut)
def get_task(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    return _get_task_or_404(db, task_id)


@router.get("/inventory/tasks/{task_id}/records",
            response_model=list[InventoryRecordOut])
def list_task_records(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    _get_task_or_404(db, task_id)
    return db.query(AssetInventoryRecord).filter_by(task_id=task_id).order_by(
        AssetInventoryRecord.id.desc()).all()


# ── #49 手机扫码盘点 ──────────────────────────────
@router.post("/inventory/tasks/{task_id}/scan", response_model=InventoryScanOut)
def scan_inventory(
    task_id: int,
    body: InventoryScanIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """扫码盘点(#49):校验标签码与任务范围;范围外明确提示、不静默计入;
    范围内写入盘点记录并更新 last_used_at。"""
    task = _get_task_or_404(db, task_id)
    if task.status == InventoryTaskStatus.DONE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "盘点任务已完成,不可再扫码")
    card = db.query(AssetCard).filter_by(label_code=body.label_code).first()
    if card is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"标签码 {body.label_code} 未找到对应资产,请走未贴标补录",
        )
    if not inv_svc.task_matches_card(task, card):
        log_asset_action(
            db, user, "asset_inventory_scan_out_of_scope",
            target_type="inventory_task", target_id=task.id,
            detail=f"范围外扫码不计入 任务{task.id} 资产{card.asset_code}",
        )
        db.commit()
        return InventoryScanOut(
            in_scope=False,
            message=f"资产 {card.asset_code} 不在本次盘点任务范围内,未计入",
            asset_id=card.id, asset_code=card.asset_code,
        )
    existing = db.query(AssetInventoryRecord).filter_by(
        task_id=task.id, asset_id=card.id).first()
    if existing is not None:
        existing.room_name = body.room_name or existing.room_name
        existing.custodian_id = body.custodian_id or existing.custodian_id
        existing.custodian_name = body.custodian_name or existing.custodian_name
        existing.photo_url = body.photo_url or existing.photo_url
        existing.is_offline = body.is_offline
        record = existing
    else:
        record = AssetInventoryRecord(
            task_id=task.id, asset_id=card.id, label_code=body.label_code,
            source="扫码", status="已记录", room_name=body.room_name,
            custodian_id=body.custodian_id, custodian_name=body.custodian_name,
            photo_url=body.photo_url, is_offline=body.is_offline,
            scanned_by=user.id,
        )
        db.add(record)
    card.last_used_at = datetime.now(UTC)
    if task.status == InventoryTaskStatus.PENDING:
        task.status = InventoryTaskStatus.IN_PROGRESS
    db.flush()
    log_asset_action(
        db, user, "asset_inventory_scan",
        target_type="inventory_task", target_id=task.id,
        detail=f"扫码盘点 任务{task.id} 资产{card.asset_code}"
               f"{'(离线续传)' if body.is_offline else ''}",
    )
    db.commit()
    return InventoryScanOut(
        in_scope=True, message=f"已盘点 {card.asset_code} {card.name}",
        record_id=record.id, asset_id=card.id, asset_code=card.asset_code,
    )


@router.post("/inventory/tasks/{task_id}/unlabelled",
             response_model=InventoryRecordOut,
             status_code=status.HTTP_201_CREATED)
def unlabelled_inventory(
    task_id: int,
    body: InventoryUnlabelledIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """未贴标资产现场补录拍照(#49):进待核实清单,比对时记为盘盈。"""
    task = _get_task_or_404(db, task_id)
    if task.status == InventoryTaskStatus.DONE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "盘点任务已完成,不可再补录")
    record = AssetInventoryRecord(
        task_id=task.id, asset_id=None, label_code=None,
        source="补录", status="待核实", name=body.name,
        description=body.description, photo_url=body.photo_url,
        room_name=body.room_name, custodian_name=body.custodian_name,
        is_offline=body.is_offline, scanned_by=user.id,
    )
    db.add(record)
    db.flush()
    if task.status == InventoryTaskStatus.PENDING:
        task.status = InventoryTaskStatus.IN_PROGRESS
    log_asset_action(
        db, user, "asset_inventory_unlabelled",
        target_type="inventory_task", target_id=task.id,
        detail=f"未贴标补录 {body.name} 待核实(比对时记盘盈)",
    )
    db.commit()
    db.refresh(record)
    return record


@router.post("/inventory/scan-due", response_model=dict)
def scan_due(
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """盘点到期扫描(#48):手动触发,未挂定时 worker;与 B3 扫描端点同一模式。"""
    result = inv_svc.scan_inventory_due(db, user)
    db.commit()
    return result


# ── #51 五类差异自动比对 ──────────────────────────────
@router.post("/inventory/tasks/{task_id}/compute-diffs", response_model=dict)
def compute_diffs(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    task = _get_task_or_404(db, task_id)
    counts = inv_svc.compute_diffs(db, task)
    log_asset_action(
        db, user, "asset_inventory_diff_compute",
        target_type="inventory_task", target_id=task.id,
        detail=f"差异比对 任务{task.id} {counts}",
    )
    db.commit()
    return {"task_id": task.id, "counts": counts}


@router.get("/inventory/plans/{plan_id}/differences",
            response_model=list[InventoryDifferenceOut])
def list_differences(
    plan_id: int,
    task_id: int | None = None,
    diff_type: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    _get_plan_or_404(db, plan_id)
    q = db.query(AssetInventoryDifference).filter_by(plan_id=plan_id)
    if task_id is not None:
        q = q.filter_by(task_id=task_id)
    if diff_type:
        q = q.filter_by(diff_type=diff_type)
    return q.order_by(AssetInventoryDifference.id).all()


@router.get("/inventory/differences/{diff_id}",
            response_model=InventoryDifferenceOut)
def get_difference(
    diff_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    return _get_diff_or_404(db, diff_id)


# ── #52 差异核实与处理 ──────────────────────────────
@router.post("/inventory/differences/{diff_id}/resolve",
             response_model=InventoryDifferenceOut)
def resolve_difference(
    diff_id: int,
    body: InventoryResolveIn,
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """差异核实与处理(#52):盘亏查责任、盘盈补建卡(走 #24 入口)、
    位置/保管人不符直接更正并留痕;note 只写说明,不改状态。"""
    diff = _get_diff_or_404(db, diff_id)
    if diff.status == InventoryDiffStatus.RESOLVED:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "差异已处理,不可重复处理")
    plan = _get_plan_or_404(db, diff.plan_id)
    if plan.status == InventoryPlanStatus.CLOSED:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "盘点方案已关闭,不可再处理差异")
    if not body.resolution:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "处理说明/责任说明不能为空")
    card = db.get(AssetCard, diff.asset_id) if diff.asset_id else None

    if body.action == "shortage":
        if diff.diff_type != InventoryDiffType.SHORTAGE:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "该差异不是盘亏,不可按盘亏查责任处理")
        diff.resolution = f"盘亏查责任:{body.resolution}"
        diff.status = InventoryDiffStatus.RESOLVED
    elif body.action == "surplus_create":
        if diff.diff_type != InventoryDiffType.SURPLUS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "该差异不是盘盈,不可补建卡")
        if not body.name or not body.category_code:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "盘盈补建卡须提供资产名称与分类代码")
        new_card, acceptance = inv_svc.create_surplus_card(
            db, user, plan_no=plan.plan_no, diff_id=diff.id,
            name=body.name, category_code=body.category_code,
            original_value=body.original_value, room_name=body.room_name,
            custodian_id=body.custodian_id, custodian_name=body.custodian_name,
        )
        diff.asset_id = new_card.id
        diff.asset_code = new_card.asset_code
        diff.asset_name = new_card.name
        diff.acceptance_id = acceptance.id
        diff.resolution = f"盘盈补建卡:{body.resolution} 新卡{new_card.asset_code}"
        diff.status = InventoryDiffStatus.RESOLVED
    elif body.action == "correct_location":
        if diff.diff_type != InventoryDiffType.LOCATION_MISMATCH:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "该差异不是位置不符,不可更正位置")
        if card is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "差异资产不存在,不可更正位置")
        record = db.query(AssetInventoryRecord).filter_by(
            task_id=diff.task_id, asset_id=card.id).first()
        new_room = body.new_room_name or (record.room_name if record else None)
        if not new_room:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "未提供实盘位置")
        before = {"room_name": card.room_name}
        card.room_name = new_room
        diff.resolution = f"位置更正:{body.resolution} {before['room_name']} → {new_room}"
        diff.status = InventoryDiffStatus.RESOLVED
        log_asset_action(
            db, user, "asset_card_update",
            target_type="asset_card", target_id=card.id,
            detail=f"盘点位置更正 {card.asset_code}",
            before=before, after={"room_name": new_room},
        )
    elif body.action == "correct_custodian":
        if diff.diff_type != InventoryDiffType.CUSTODIAN_MISMATCH:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "该差异不是保管人不符,不可更正保管人")
        if card is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "差异资产不存在,不可更正保管人")
        record = db.query(AssetInventoryRecord).filter_by(
            task_id=diff.task_id, asset_id=card.id).first()
        new_id = body.new_custodian_id or (record.custodian_id if record else None)
        new_name = body.new_custodian_name or (record.custodian_name if record else None)
        if new_id is None and not new_name:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "未提供实盘保管人")
        before = {"custodian_user_id": card.custodian_user_id,
                  "custodian_name": card.custodian_name}
        card.custodian_user_id = new_id
        card.custodian_name = new_name
        diff.resolution = f"保管人更正:{body.resolution} {before['custodian_name']} → {new_name}"
        diff.status = InventoryDiffStatus.RESOLVED
        log_asset_action(
            db, user, "asset_card_update",
            target_type="asset_card", target_id=card.id,
            detail=f"盘点保管人更正 {card.asset_code}",
            before=before,
            after={"custodian_user_id": new_id, "custodian_name": new_name},
        )
    elif body.action == "note":
        # 只写说明:状态仍为待处理,但关闭检查认"有说明"为已交代。
        diff.resolution = f"说明:{body.resolution}"
        log_asset_action(
            db, user, "asset_inventory_diff_resolve",
            target_type="inventory_difference", target_id=diff.id,
            detail=f"差异说明 {diff.diff_type} {diff.asset_code or ''}:{body.resolution}",
        )
        db.commit()
        db.refresh(diff)
        return diff
    diff.resolved_by = user.id
    diff.resolved_at = datetime.now(UTC)
    log_asset_action(
        db, user, "asset_inventory_diff_resolve",
        target_type="inventory_difference", target_id=diff.id,
        detail=f"差异处理 {diff.diff_type} {diff.asset_code or ''}:{diff.resolution}",
    )
    db.commit()
    db.refresh(diff)
    return diff


@router.post("/inventory/plans/{plan_id}/close", response_model=InventoryPlanOut)
def close_plan(
    plan_id: int,
    body: InventoryCloseIn,
    db: Session = Depends(get_db),
    user: User = Depends(leader_only),
):
    """盘点关闭(#52):须领导(director)确认;差异须全部处理或有说明,
    未处理完(待处理且无说明)不得关闭。"""
    plan = _get_plan_or_404(db, plan_id)
    if plan.status == InventoryPlanStatus.CLOSED:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "盘点方案已关闭")
    pending = db.query(AssetInventoryDifference).filter_by(
        plan_id=plan.id, status=InventoryDiffStatus.PENDING).all()
    untreated = [d for d in pending if not d.resolution]
    if untreated:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"仍有 {len(untreated)} 条差异未处理且无说明,不得关闭盘点",
        )
    plan.status = InventoryPlanStatus.CLOSED
    db.query(AssetInventoryTask).filter_by(plan_id=plan.id).filter(
        AssetInventoryTask.status != InventoryTaskStatus.DONE).update(
        {AssetInventoryTask.status: InventoryTaskStatus.DONE},
        synchronize_session=False)
    log_asset_action(
        db, user, "asset_inventory_close",
        target_type="inventory_plan", target_id=plan.id,
        detail=f"领导确认关闭盘点 {plan.plan_no} {body.confirm_note or ''}",
    )
    db.commit()
    db.refresh(plan)
    return plan


@router.get("/inventory/plans/{plan_id}/report", response_model=InventoryReportOut)
def plan_report(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """盘点报告(#51/#52 汇总):差异分类统计与涉及已同步资产的标注。
    盘点结果不自动同步到官方,报告只作标注(B5 #98/#100 手动勾选时参考)。"""
    plan = _get_plan_or_404(db, plan_id)
    tasks = db.query(AssetInventoryTask).filter_by(plan_id=plan.id).all()
    task_ids = [t.id for t in tasks]
    diffs = db.query(AssetInventoryDifference).filter_by(plan_id=plan.id).all()
    counts = {t: 0 for t in (
        InventoryDiffType.NORMAL, InventoryDiffType.SHORTAGE,
        InventoryDiffType.SURPLUS, InventoryDiffType.LOCATION_MISMATCH,
        InventoryDiffType.CUSTODIAN_MISMATCH)}
    for d in diffs:
        counts[d.diff_type] = counts.get(d.diff_type, 0) + 1
    expected = sum(len(inv_svc.expected_cards(db, t)) for t in tasks) \
        if task_ids else 0
    scanned = db.query(AssetInventoryRecord).filter(
        AssetInventoryRecord.task_id.in_(task_ids),
        AssetInventoryRecord.asset_id.is_not(None)).count() if task_ids else 0
    unresolved = sum(1 for d in diffs if d.status == InventoryDiffStatus.PENDING)
    synced = [d for d in diffs if d.involves_synced]
    return InventoryReportOut(
        plan_id=plan.id, plan_no=plan.plan_no, status=plan.status,
        total_expected=expected, total_scanned=scanned,
        diff_counts=counts, unresolved=unresolved,
        synced_differences=[InventoryDifferenceOut.model_validate(d) for d in synced],
        note="盘点结果不自动同步到官方;涉及已同步资产的差异须经 B5 手动勾选才同步。",
    )
