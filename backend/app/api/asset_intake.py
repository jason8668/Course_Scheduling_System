"""入库验收与入账衔接 API(学校资产管理系统一期第 2 批 #19~#28)。

挂在 /api/asset 下。六类入口同一套建卡标准、同一验收流程:先建验收单,
验收通过后才建卡;验收不通过的资产不得建卡(状态留在验收单,不进台账)。
建卡后 sync_status 强制 未同步(复用 B1 create_asset_card),is_booked
默认 False;财务回填入账凭证号后才转正式状态(#27),未回填禁止同步
(同步前校验在 B5,本批在模型层加 booked 标志与待入账清单端点)。
"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.auth import get_active_user
from app.core.db import get_db
from app.models.asset_card import AssetCard
from app.models.asset_ledger import AcceptanceStatus, AssetAcceptance, IntakeType
from app.models.user import Role, User
from app.schemas.asset import AssetCardOut
from app.schemas.asset_ledger import (
    AcceptanceConfirmIn,
    AcceptanceIn,
    AcceptanceOut,
    BookingConfirmIn,
    BookingPendingOut,
    BulkItemResult,
    BulkResultOut,
    IntakeBulkCreateIn,
    IntakeCreateCardsIn,
)
from app.services import asset_foundation as asset_svc
from app.services import asset_ledger as ledger_svc
from app.services.asset_audit import log_asset_action
from app.api.asset_foundation import (
    asset_writer,
    finance_or_admin,
    require_asset_roles,
)

router = APIRouter(tags=["asset"])

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _next_acceptance_no(db: Session) -> str:
    from datetime import UTC, datetime

    today = datetime.now(UTC).strftime("%Y%m%d")
    count = db.query(AssetAcceptance).filter(
        AssetAcceptance.acceptance_no.like(f"YS{today}%")
    ).count()
    return f"YS{today}-{count + 1:04d}"


def _get_acceptance_or_404(db: Session, acceptance_id: int) -> AssetAcceptance:
    row = db.get(AssetAcceptance, acceptance_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "验收单不存在")
    return row


def _create_one_card(db: Session, user: User, acceptance: AssetAcceptance,
                     item, batch_no: str) -> AssetCard:
    """单件建卡:取得方式由入口派生;sync_status 强制 未同步(B1 逻辑)。"""
    fields = item.model_dump()
    fields["acquire_method"] = IntakeType.ACQUIRE_METHOD[acceptance.intake_type]
    fields["acceptance_id"] = acceptance.id
    fields["batch_no"] = batch_no
    return asset_svc.create_asset_card(db, user, **fields)


# ── 验收单 #25 ──────────────────────────────
@router.post("/acceptances", response_model=AcceptanceOut,
             status_code=status.HTTP_201_CREATED)
def create_acceptance(
    body: AcceptanceIn,
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    if body.intake_type not in IntakeType.ALL:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"未知入库类型 {body.intake_type},须为 "
            f"{'/'.join(sorted(IntakeType.ALL))}",
        )
    row = AssetAcceptance(
        acceptance_no=_next_acceptance_no(db),
        intake_type=body.intake_type,
        source_doc=body.source_doc,
        acceptors=body.acceptors,
        comment=body.comment,
        created_by=user.id,
    )
    db.add(row)
    db.flush()
    log_asset_action(
        db, user, "asset_acceptance_create",
        target_type="asset_acceptance", target_id=row.id,
        detail=f"新建验收单 {row.acceptance_no} "
               f"({IntakeType.LABELS[body.intake_type]})",
    )
    db.commit()
    return row


@router.get("/acceptances", response_model=list[AcceptanceOut])
def list_acceptances(
    intake_type: str | None = None,
    status_: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    q = db.query(AssetAcceptance)
    if intake_type:
        q = q.filter_by(intake_type=intake_type)
    if status_:
        q = q.filter_by(status=status_)
    return q.order_by(AssetAcceptance.id.desc()).all()


@router.get("/acceptances/{acceptance_id}", response_model=AcceptanceOut)
def get_acceptance(
    acceptance_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    return _get_acceptance_or_404(db, acceptance_id)


@router.post("/acceptances/{acceptance_id}/confirm", response_model=AcceptanceOut)
def confirm_acceptance(
    acceptance_id: int,
    body: AcceptanceConfirmIn,
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """验收确认(#25):线上确认动作 + 确认人/时间;不通过则状态留在
    验收单,不得建卡。"""
    from datetime import UTC, datetime

    row = _get_acceptance_or_404(db, acceptance_id)
    if row.status != AcceptanceStatus.PENDING:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"验收单已{row.status},不可重复确认")
    if body.acceptors:
        row.acceptors = body.acceptors
    row.comment = body.comment or row.comment
    row.accepted_by = user.id
    row.accepted_at = datetime.now(UTC)
    row.status = (AcceptanceStatus.PASSED if body.result == "通过"
                  else AcceptanceStatus.FAILED)
    log_asset_action(
        db, user, "asset_acceptance_confirm",
        target_type="asset_acceptance", target_id=row.id,
        detail=f"验收{body.result} {row.acceptance_no} 确认人{user.username}",
    )
    db.commit()
    return row


# ── 建卡 #19~#24/#26 ──────────────────────────────
@router.post("/acceptances/{acceptance_id}/create-cards",
             response_model=BulkResultOut)
def create_cards_from_acceptance(
    acceptance_id: int,
    body: IntakeCreateCardsIn,
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """验收后建卡:仅 验收通过 的验收单可建卡;批量建卡失败逐条回告,
    不整体回滚;整批共用一个入库批次号(#26)。"""
    acceptance = _get_acceptance_or_404(db, acceptance_id)
    if acceptance.status not in (AcceptanceStatus.PASSED, AcceptanceStatus.CARDED):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"验收单状态为{acceptance.status},验收通过后才可建卡"
            "(验收不通过的资产不得建卡)",
        )
    batch_no = body.batch_no or ledger_svc.next_batch_no(db, "RK", "intake")
    succeeded: list[BulkItemResult] = []
    failed: list[BulkItemResult] = []
    total_value = 0.0
    for item in body.items:
        try:
            # 每件一个 SAVEPOINT:单件失败只回滚该件,不影响同批已建卡件。
            with db.begin_nested():
                card = _create_one_card(db, user, acceptance, item, batch_no)
            total_value += float(card.original_value or 0)
            succeeded.append(BulkItemResult(
                asset_id=card.id, asset_code=card.asset_code, ok=True))
        except ValueError as e:
            failed.append(BulkItemResult(ok=False, reason=str(e)))
        except Exception as e:  # 唯一约束撞号等:逐条回告,不整体回滚
            failed.append(BulkItemResult(ok=False, reason=f"建卡失败:{e}"))
    if succeeded:
        acceptance.status = AcceptanceStatus.CARDED
        acceptance.batch_no = batch_no
        ledger_svc.record_batch(
            db, user, batch_no, "intake", len(succeeded), total_value,
            note=f"验收单 {acceptance.acceptance_no}",
        )
        log_asset_action(
            db, user, "asset_bulk_create",
            target_type="asset_acceptance", target_id=acceptance.id,
            detail=f"验收建卡 {acceptance.acceptance_no} 批次{batch_no} "
                   f"成功{len(succeeded)}件 失败{len(failed)}件",
        )
    db.commit()
    return BulkResultOut(succeeded=succeeded, failed=failed, batch_no=batch_no)


@router.post("/acceptances/{acceptance_id}/bulk-create",
             response_model=BulkResultOut)
def bulk_create_from_acceptance(
    acceptance_id: int,
    body: IntakeBulkCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """批量建卡(#26):大批同类物资按批建卡、按件贴标,名称自动加序号后缀。"""
    from copy import deepcopy

    from app.schemas.asset_ledger import IntakeCardItem

    acceptance = _get_acceptance_or_404(db, acceptance_id)
    if acceptance.status not in (AcceptanceStatus.PASSED, AcceptanceStatus.CARDED):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"验收单状态为{acceptance.status},验收通过后才可建卡",
        )
    batch_no = body.batch_no or ledger_svc.next_batch_no(db, "RK", "intake")
    items: list[IntakeCardItem] = []
    for i in range(1, body.quantity + 1):
        data = deepcopy(body.template.model_dump())
        data["name"] = f"{body.template.name}-{i:02d}"
        data["asset_code"] = None  # 每件自动生成独立编号
        items.append(IntakeCardItem(**data))
    return create_cards_from_acceptance(
        acceptance_id,
        IntakeCreateCardsIn(items=items, batch_no=batch_no),
        db=db, user=user,
    )


# ── 待入账清单 #27 ──────────────────────────────
@router.get("/booking-pending", response_model=BookingPendingOut)
def list_booking_pending(
    month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$",
                              description="YYYY-MM,每月差异清单口径"),
    manage_dept: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """待入账清单(#27):is_booked=False 的资产;month 指定月份时只看
    该月建卡的未回填项(每月差异清单)。"""
    from datetime import UTC, datetime

    q = db.query(AssetCard).filter_by(is_booked=False, is_retired=False)
    if month:
        year, mon = int(month[:4]), int(month[5:7])
        start = datetime(year, mon, 1, tzinfo=UTC)
        end = datetime(year + (1 if mon == 12 else 0), mon % 12 + 1, 1, tzinfo=UTC)
        q = q.filter(AssetCard.created_at >= start, AssetCard.created_at < end)
    if manage_dept:
        q = q.filter_by(manage_dept=manage_dept)
    rows = q.order_by(AssetCard.id).all()
    return BookingPendingOut(
        items=[AssetCardOut.model_validate(r).model_dump(mode="json") for r in rows],
        total=len(rows),
        total_value=float(sum(float(r.original_value or 0) for r in rows)),
    )


@router.get("/booking-pending/export")
def export_booking_pending(
    month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    db: Session = Depends(get_db),
    user: User = Depends(finance_or_admin),
):
    """未回填清单可导出(#27):每月差异清单导出 Excel,记审计。"""
    pending = list_booking_pending(month=month, db=db, user=user)
    cards = db.query(AssetCard).filter(
        AssetCard.id.in_([item["id"] for item in pending.items])
    ).order_by(AssetCard.id).all() if pending.items else []
    data = ledger_svc.ledger_to_xlsx(cards, include_ext=False)
    log_asset_action(
        db, user, "asset_booking_pending_export",
        target_type="asset_booking",
        detail=f"导出待入账清单 {pending.total} 件"
               + (f" 月份{month}" if month else ""),
    )
    db.commit()
    filename = f"待入账清单{month or ''}"
    quoted = quote(filename)
    disposition = f'attachment; filename="export.xlsx"; filename*=UTF-8\'\'{quoted}.xlsx'
    return Response(content=data, media_type=_XLSX_MIME,
                    headers={"Content-Disposition": disposition})


@router.post("/assets/{asset_id}/book", response_model=AssetCardOut)
def confirm_booking(
    asset_id: int,
    body: BookingConfirmIn,
    db: Session = Depends(get_db),
    user: User = Depends(finance_or_admin),
):
    """财务回填入账凭证号(#27):回填后 is_booked=True 才转正式状态;
    凭证号为空或已回填过均拦截。"""
    from datetime import UTC, datetime

    card = db.get(AssetCard, asset_id)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "资产卡不存在")
    if card.is_retired:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "资产已核销封存,不可入账")
    if card.is_booked:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "该资产已回填入账凭证号,不可重复回填")
    card.voucher_no = body.voucher_no
    card.is_booked = True
    card.booked_at = datetime.now(UTC)
    log_asset_action(
        db, user, "asset_booking_confirm",
        target_type="asset_card", target_id=card.id,
        detail=f"财务回填入账凭证号 {card.asset_code} 凭证{body.voucher_no}",
        before={"is_booked": False}, after={"is_booked": True},
    )
    db.commit()
    return card
