"""处置与报废 API(学校资产管理系统一期第 5 批 M8 #54~#58)。

挂在 /api/asset 下。处置单本身不改资产状态:资产须先经 transition 转入
待处置;核销入口为官方批复回填后手动确认(POST /disposals/{id}/retire-confirm
或通用 retire 端点 doc_no=处置单号,未回填批复一律拦截)。

审批走 B1 通用审批流 doc_type=处置单,金额取资产原值(#56);鉴定人员角色
asset_inspector(#55);申报材料包只对已手动选择的处置单生成(#57/#99)。
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.asset_foundation import (
    _get_card_or_404,
    asset_writer,
    require_asset_roles,
)
from app.core.auth import get_active_user
from app.core.db import get_db
from app.models.asset_card import AssetCard, AssetStatus
from app.models.asset_disposal import (
    DISPOSAL_TYPES,
    AssetDisposalAppraisal,
    AssetDisposalOrder,
    AssetDisposalPackage,
    AssetDisposalRecovery,
)
from app.models.user import Role, User
from app.schemas.asset_disposal_sync import (
    AppraisalCreate,
    AppraisalOut,
    DisposalCreate,
    DisposalOut,
    OfficialReplyIn,
    PackageOut,
    RecoveryIn,
    RecoveryOut,
)
from app.services import asset_approval as approval_svc
from app.services import asset_disposal as disposal_svc
from app.services import asset_foundation as asset_svc
from app.services.asset_audit import log_asset_action

router = APIRouter(tags=["asset"])

inspector = require_asset_roles(Role.asset_inspector)
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _get_disposal_or_404(db: Session, disposal_id: int) -> AssetDisposalOrder:
    row = db.get(AssetDisposalOrder, disposal_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "处置单不存在")
    return row


def _display(user: User) -> str:
    return user.display_name or user.username


# ── #54 材料清单(按类型可配置) ──────────────────────────────
@router.get("/disposals/materials", response_model=dict)
def list_disposal_materials(
    disposal_type: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """按处置类型取应交材料清单(#54):参数 disposal.materials 可配。"""
    if disposal_type not in DISPOSAL_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"未知处置类型 {disposal_type}")
    return {
        "disposal_type": disposal_type,
        "label": DISPOSAL_TYPES[disposal_type],
        "materials_required": disposal_svc.get_disposal_materials(db, disposal_type),
    }


# ── #54 多类型处置申请 ──────────────────────────────
@router.post("/disposals", response_model=DisposalOut, status_code=status.HTTP_201_CREATED)
def create_disposal(
    body: DisposalCreate,
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """创建处置申请(#54):资产须已在 待处置(处置申请本身不直接改状态);
    七类处置按类型走不同材料,缺材料不得提交。"""
    if body.disposal_type not in DISPOSAL_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"未知处置类型 {body.disposal_type}")
    card = _get_card_or_404(db, body.asset_id)
    if card.is_retired:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "资产已核销封存,不可处置")
    if card.status != AssetStatus.pending_disposal.value:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"资产状态为{card.status},须先转入待处置才能申请处置",
        )
    required = disposal_svc.get_disposal_materials(db, body.disposal_type)
    missing = [m for m in required if m not in (body.materials or [])]
    if missing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"材料不全,缺:{'、'.join(missing)}",
        )
    existing = db.query(AssetDisposalOrder).filter_by(asset_id=card.id).filter(
        AssetDisposalOrder.status.notin_(["已关闭", "已核销", "已退回"])
    ).first()
    if existing is not None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"资产已有未办结处置单 {existing.doc_no},不可重复申请",
        )
    order = AssetDisposalOrder(
        doc_no=disposal_svc.next_disposal_no(db, AssetDisposalOrder, "CZ-"),
        asset_id=card.id, disposal_type=body.disposal_type,
        reason=body.reason or "", materials=list(body.materials or []),
        materials_required=required, status_before=card.status,
        status="待鉴定", created_by=user.id,
    )
    db.add(order)
    db.flush()
    log_asset_action(
        db, user, "asset_disposal_create",
        target_type="disposal_order", target_id=order.id,
        detail=f"创建处置申请 {order.doc_no} "
               f"{DISPOSAL_TYPES[body.disposal_type]} 资产{card.asset_code}",
    )
    db.commit()
    db.refresh(order)
    return order


@router.get("/disposals", response_model=list[DisposalOut])
def list_disposals(
    status_: str | None = Query(default=None, alias="status"),
    disposal_type: str | None = None,
    asset_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    q = db.query(AssetDisposalOrder).order_by(AssetDisposalOrder.id.desc())
    if status_:
        q = q.filter_by(status=status_)
    if disposal_type:
        q = q.filter_by(disposal_type=disposal_type)
    if asset_id is not None:
        q = q.filter_by(asset_id=asset_id)
    return q.all()


@router.get("/disposals/{disposal_id}", response_model=DisposalOut)
def get_disposal(
    disposal_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    return _get_disposal_or_404(db, disposal_id)


# ── #55 处置前技术鉴定 ──────────────────────────────
@router.post("/disposals/{disposal_id}/appraise", response_model=AppraisalOut,
             status_code=status.HTTP_201_CREATED)
def appraise_disposal(
    disposal_id: int,
    body: AppraisalCreate,
    db: Session = Depends(get_db),
    user: User = Depends(inspector),
):
    """处置前技术鉴定(#55):处置前置,鉴定单留存。结论"可继续使用"时
    处置单关闭、资产回在库/在用(不搞一刀切按年限报废)。"""
    order = _get_disposal_or_404(db, disposal_id)
    if order.status != "待鉴定":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"处置单状态为{order.status},不可鉴定")
    if body.conclusion not in disposal_svc.APPRAISAL_CONCLUSIONS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"鉴定结论须为{'/'.join(disposal_svc.APPRAISAL_CONCLUSIONS)}")
    card = _get_card_or_404(db, order.asset_id)
    appraisal = AssetDisposalAppraisal(
        doc_no=disposal_svc.next_disposal_no(db, AssetDisposalAppraisal, "JD-"),
        disposal_id=order.id, inspector_id=user.id,
        inspector_name=_display(user), conclusion=body.conclusion,
        detail=body.detail or "",
    )
    db.add(appraisal)
    db.flush()
    if body.conclusion == "可继续使用":
        # 回状态:处置单建在资产已入待处置之后,status_before 已是待处置,
        # 故按领用情况回:已领用回在用,否则回在库(见汇报口径清单)。
        back = (AssetStatus.in_use.value
                if card.borrow_status == "已领用"
                else AssetStatus.in_stock.value)
        try:
            asset_svc.transition_asset(
                db, user, card, back, doc_type="处置单", doc_no=order.doc_no)
        except ValueError as e:
            db.rollback()
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
        order.status = "已关闭"
        log_asset_action(
            db, user, "asset_disposal_appraisal_close",
            target_type="disposal_order", target_id=order.id,
            detail=f"鉴定结论可继续使用,处置单 {order.doc_no} 关闭,"
                   f"资产{card.asset_code}回{back}",
        )
    else:
        order.status = "待审批"
        log_asset_action(
            db, user, "asset_disposal_appraise",
            target_type="disposal_order", target_id=order.id,
            detail=f"技术鉴定 {appraisal.doc_no} 结论{body.conclusion} "
                   f"处置单{order.doc_no}转待审批",
        )
    db.commit()
    db.refresh(appraisal)
    return appraisal


@router.get("/disposals/{disposal_id}/appraisal", response_model=AppraisalOut)
def get_appraisal(
    disposal_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    order = _get_disposal_or_404(db, disposal_id)
    row = db.query(AssetDisposalAppraisal).filter_by(disposal_id=order.id).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该处置单暂无鉴定单")
    return row


# ── #56 分级处置审批 ──────────────────────────────
@router.post("/disposals/{disposal_id}/submit-approval", response_model=DisposalOut)
def submit_disposal_approval(
    disposal_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """提交分级处置审批(#56):走 B1 通用审批流 doc_type=处置单,
    金额取资产原值;阈值复用审批流节点 min_amount(参数
    approval.disposal_threshold 为建议初始值,见汇报口径清单)。
    申请与审批不得同一人由审批流 act 端岗位分离拦截。"""
    order = _get_disposal_or_404(db, disposal_id)
    if order.status != "待审批":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"处置单状态为{order.status},不可提交审批")
    card = _get_card_or_404(db, order.asset_id)
    amount = float(card.original_value or 0)
    try:
        inst = approval_svc.create_instance(
            db, user, doc_type="处置单", doc_id=order.id,
            doc_no=order.doc_no, amount=amount,
        )
    except approval_svc.ApprovalError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    order.approval_instance_id = inst.id
    db.commit()
    db.refresh(order)
    return order


# ── #57/#99 申报材料包手动选择 ──────────────────────────────
@router.post("/disposals/{disposal_id}/select-official", response_model=DisposalOut)
def select_official(
    disposal_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """手动选择生成官方申报材料包(#57/#99):未选择的处置只在校内审批、
    不向官方申报。"""
    order = _get_disposal_or_404(db, disposal_id)
    if order.status not in ("审批通过", "待官方批复", "已批复"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"处置单状态为{order.status},须校内审批通过后才能选择申报")
    order.selected_for_official = True
    order.selected_for_official_by = user.id
    order.selected_for_official_at = datetime.now(UTC)
    log_asset_action(
        db, user, "asset_disposal_select_official",
        target_type="disposal_order", target_id=order.id,
        detail=f"手动选择处置 {order.doc_no} 生成官方申报材料包",
    )
    db.commit()
    db.refresh(order)
    return order


@router.post("/disposals/{disposal_id}/package", response_model=PackageOut,
             status_code=status.HTTP_201_CREATED)
def create_package(
    disposal_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """生成官方申报材料包(#57):校内审批通过后一键整理(材料清单 +
    资产卡数据 + 鉴定单 + 审批记录);只对已手动选择的处置单生效。"""
    order = _get_disposal_or_404(db, disposal_id)
    if not order.selected_for_official:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "该处置未手动选择生成官方申报材料包,只在校内审批、不向官方申报")
    if order.status not in ("审批通过", "待官方批复", "已批复"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"处置单状态为{order.status},须校内审批通过后才能生成申报材料包")
    existing = db.query(AssetDisposalPackage).filter_by(disposal_id=order.id).first()
    if existing is not None:
        return existing
    card = _get_card_or_404(db, order.asset_id)
    appraisal = db.query(AssetDisposalAppraisal).filter_by(
        disposal_id=order.id).first()
    summary = {
        "doc_no": order.doc_no,
        "disposal_type": DISPOSAL_TYPES.get(order.disposal_type, order.disposal_type),
        "reason": order.reason,
        "materials": order.materials,
        "materials_required": order.materials_required,
        "asset": {
            "asset_code": card.asset_code, "official_code": card.official_code,
            "name": card.name, "category_code": card.category_code,
            "original_value": float(card.original_value or 0),
            "net_value": float(card.net_value or 0)
            if card.net_value is not None else None,
            "acquire_method": card.acquire_method,
            "voucher_no": card.voucher_no,
        },
        "appraisal": ({
            "doc_no": appraisal.doc_no, "conclusion": appraisal.conclusion,
            "inspector_name": appraisal.inspector_name,
            "detail": appraisal.detail,
        } if appraisal else None),
        "approval_instance_id": order.approval_instance_id,
        "note": "演示数据:材料包为校内整理稿,须学校按官方当期要求核对后提交",
    }
    package = AssetDisposalPackage(
        package_no=disposal_svc.next_package_no(db, AssetDisposalPackage),
        disposal_id=order.id, summary=summary, asset_count=1,
        total_value=float(card.original_value or 0),
        generated_by=user.id,
    )
    db.add(package)
    order.status = "待官方批复"
    db.flush()
    log_asset_action(
        db, user, "asset_disposal_package_create",
        target_type="disposal_order", target_id=order.id,
        detail=f"生成官方申报材料包 {package.package_no} 处置{order.doc_no}",
    )
    db.commit()
    db.refresh(package)
    return package


@router.get("/disposals/{disposal_id}/package", response_model=PackageOut)
def get_package(
    disposal_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    order = _get_disposal_or_404(db, disposal_id)
    row = db.query(AssetDisposalPackage).filter_by(disposal_id=order.id).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该处置单暂无申报材料包")
    return row


@router.get("/disposals/{disposal_id}/package/export")
def export_package(
    disposal_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """导出申报材料包 Excel 清单(#57):材料清单 + 资产卡数据 + 鉴定单 +
    审批记录。未生成材料包的处置不导出。"""
    from urllib.parse import quote

    from openpyxl import Workbook

    order = _get_disposal_or_404(db, disposal_id)
    package = db.query(AssetDisposalPackage).filter_by(disposal_id=order.id).first()
    if package is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该处置单暂无申报材料包")
    summary = package.summary or {}
    asset = summary.get("asset", {}) or {}
    appraisal = summary.get("appraisal") or {}
    wb = Workbook()
    ws = wb.active
    ws.title = "申报材料包"
    ws.append(["项目", "内容"])
    ws.append(["处置单号", order.doc_no])
    ws.append(["处置类型", summary.get("disposal_type", "")])
    ws.append(["材料包号", package.package_no])
    ws.append(["资产编号", asset.get("asset_code", "")])
    ws.append(["官方编号", asset.get("official_code", "") or ""])
    ws.append(["资产名称", asset.get("name", "")])
    ws.append(["分类代码", asset.get("category_code", "")])
    ws.append(["原值(元)", asset.get("original_value", "")])
    ws.append(["净值(元)", asset.get("net_value", "") or ""])
    ws.append(["取得方式", asset.get("acquire_method", "") or ""])
    ws.append(["凭证号", asset.get("voucher_no", "") or ""])
    ws.append(["鉴定单号", appraisal.get("doc_no", "")])
    ws.append(["鉴定结论", appraisal.get("conclusion", "")])
    ws.append(["鉴定人", appraisal.get("inspector_name", "")])
    ws.append(["材料清单", "、".join(summary.get("materials", []))])
    ws.append(["审批实例", str(summary.get("approval_instance_id", ""))])
    import io

    buf = io.BytesIO()
    wb.save(buf)
    filename = quote(f"申报材料包-{package.package_no}.xlsx")
    return Response(
        content=buf.getvalue(),
        media_type=_XLSX_MIME,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


# ── #57/#58 官方批复回填与核销 ──────────────────────────────
@router.post("/disposals/{disposal_id}/official-reply", response_model=DisposalOut)
def record_official_reply(
    disposal_id: int,
    body: OfficialReplyIn,
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """官方批复回填(#57/#58):批复回填后处置单置已批复,才可手动确认核销。"""
    order = _get_disposal_or_404(db, disposal_id)
    if order.status not in ("待官方批复", "审批通过"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"处置单状态为{order.status},不可回填官方批复")
    order.official_reply_no = body.reply_no
    order.official_reply_at = datetime.now(UTC)
    order.status = "已批复"
    log_asset_action(
        db, user, "asset_disposal_official_reply",
        target_type="disposal_order", target_id=order.id,
        detail=f"官方批复回填 {order.doc_no} 批复文号{body.reply_no}",
    )
    db.commit()
    db.refresh(order)
    return order


@router.post("/disposals/{disposal_id}/retire-confirm", response_model=DisposalOut)
def retire_confirm(
    disposal_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """手动确认核销(#58):官方批复回填后才可核销;未回填批复拦截。
    核销后资产编号封存(is_retired + retired_at),生成回收交接单骨架;
    账销物销同步完成,资产不再出现在在用台账(只在历史/已核销清单可查)。"""
    order = _get_disposal_or_404(db, disposal_id)
    if not order.official_reply_no:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "未回填官方批复,不得核销")
    if order.status != "已批复":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"处置单状态为{order.status},不可核销")
    card = _get_card_or_404(db, order.asset_id)
    try:
        disposal_svc.finalize_retire(db, user, order, card)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    db.commit()
    db.refresh(order)
    return order


# ── #58 回收交接 ──────────────────────────────
@router.post("/disposals/{disposal_id}/recovery", response_model=RecoveryOut)
def complete_recovery(
    disposal_id: int,
    body: RecoveryIn,
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """回收交接单补填(#58):核销后回收单位、交接影像、残值收入凭证归档。"""
    order = _get_disposal_or_404(db, disposal_id)
    if order.status != "已核销":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"处置单状态为{order.status},尚未核销")
    row = db.query(AssetDisposalRecovery).filter_by(disposal_id=order.id).first()
    if row is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "回收交接单不存在,请先核销")
    row.recovery_org = body.recovery_org
    row.residual_income = body.residual_income
    row.voucher_no = body.voucher_no
    row.photo_urls = list(body.photo_urls or [])
    row.status = "已交接"
    row.handover_at = datetime.now(UTC)
    log_asset_action(
        db, user, "asset_disposal_recovery_create",
        target_type="disposal_order", target_id=order.id,
        detail=f"回收交接 {row.recovery_no} 单位{body.recovery_org} "
               f"残值{body.residual_income or 0}元 凭证{body.voucher_no or ''}",
    )
    db.commit()
    db.refresh(row)
    return row


@router.get("/disposals/{disposal_id}/recovery", response_model=RecoveryOut)
def get_recovery(
    disposal_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    order = _get_disposal_or_404(db, disposal_id)
    row = db.query(AssetDisposalRecovery).filter_by(disposal_id=order.id).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该处置单暂无回收交接单")
    return row
