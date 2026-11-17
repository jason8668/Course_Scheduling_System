"""台账 API(学校资产管理系统一期第 2 批 #8/#9/#12/#13/#14/#28)。

挂在 /api/asset 下。B1 的 GET /assets(基础筛选)保持不动,本批多维组合查询用 GET /ledger/search(同口径过滤器 + 排序白名单 + 分页),
避免 B1 的 GET /assets/{asset_id} 先注册遮挡 /assets/search(实测 422)。导出复用课表导出模式:openpyxl 同步生成。
状态转移仍只走 B1 的 transition 端点,本批不设直接改状态端点。
"""

import re
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.core.auth import get_active_user
from app.core.config import settings
from app.core.db import get_db
from app.models.asset_card import AssetCard
from app.models.asset_ledger import ATTACHMENT_TYPES, AssetAttachment
from app.models.basedata import Room
from app.models.user import Role, User
from app.schemas.asset import AssetCardOut
from app.schemas.asset_ledger import (
    AssetAttachmentIn,
    AssetAttachmentOut,
    AssetBulkUpdateIn,
    AssetIdleOut,
    AssetLabelOut,
    AssetSearchParams,
    BulkItemResult,
    BulkResultOut,
    IdleRefreshOut,
)
from app.services import asset_foundation as asset_svc
from app.services import asset_ledger as ledger_svc
from app.services.asset_audit import log_asset_action
from app.api.asset_foundation import asset_writer, require_asset_roles

router = APIRouter(tags=["asset"])
auditor_or_admin = require_asset_roles(Role.asset_auditor, Role.admin)

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _download_xlsx(data: bytes, filename: str) -> Response:
    quoted = quote(filename)
    disposition = f'attachment; filename="export.xlsx"; filename*=UTF-8\'\'{quoted}.xlsx'
    return Response(
        content=data, media_type=_XLSX_MIME,
        headers={"Content-Disposition": disposition},
    )


def _search_params(
    category_code: str | None = None,
    manage_dept: str | None = None,
    use_dept: str | None = None,
    custodian_name: str | None = None,
    custodian_user_id: int | None = None,
    room_id: int | None = None,
    room_name: str | None = None,
    status_: str | None = None,
    sync_status: str | None = None,
    acquire_method: str | None = None,
    funding_source: str | None = None,
    acquired_year: int | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
    batch_no: str | None = None,
    is_booked: bool | None = None,
    is_idle: bool | None = None,
    q: str | None = None,
    sort_by: str = "id",
    sort_dir: str = "desc",
    limit: int = 50,
    offset: int = 0,
) -> AssetSearchParams:
    return AssetSearchParams(
        category_code=category_code, manage_dept=manage_dept,
        use_dept=use_dept, custodian_name=custodian_name,
        custodian_user_id=custodian_user_id, room_id=room_id,
        room_name=room_name, status=status_, sync_status=sync_status,
        acquire_method=acquire_method, funding_source=funding_source,
        acquired_year=acquired_year, min_value=min_value,
        max_value=max_value, batch_no=batch_no, is_booked=is_booked,
        is_idle=is_idle, q=q, sort_by=sort_by, sort_dir=sort_dir,
        limit=limit, offset=offset,
    )


def _search_cards(db: Session, params: AssetSearchParams):
    """组合查询 + 排序后的全部卡片(未分页):加密字段的筛选/排序在
    服务层 Python 侧做(query_assets),调用方再按 total 切片分页。"""
    try:
        return ledger_svc.query_assets(db, params)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


# ── 多维组合查询 #8 ──────────────────────────────
@router.get("/ledger/search", response_model=dict)
def search_assets(
    category_code: str | None = None,
    manage_dept: str | None = None,
    use_dept: str | None = None,
    custodian_name: str | None = None,
    custodian_user_id: int | None = None,
    room_id: int | None = None,
    room_name: str | None = None,
    status_: str | None = Query(default=None, alias="status"),
    sync_status: str | None = None,
    acquire_method: str | None = None,
    funding_source: str | None = None,
    acquired_year: int | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
    batch_no: str | None = None,
    is_booked: bool | None = None,
    is_idle: bool | None = None,
    q: str | None = None,
    sort_by: str = "id",
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """多维组合查询(#8):分类/部门/保管人/房间/状态/价值区间/购置年份/
    资金来源/同步状态/入账/闲置/批次组合查询,分页 + 排序白名单。"""
    params = _search_params(
        category_code, manage_dept, use_dept, custodian_name,
        custodian_user_id, room_id, room_name, status_, sync_status,
        acquire_method, funding_source, acquired_year, min_value,
        max_value, batch_no, is_booked, is_idle, q,
        sort_by, sort_dir, limit, offset,
    )
    query = _search_cards(db, params)
    total = len(query)
    rows = query[params.offset:params.offset + params.limit]
    return {"items": [AssetCardOut.model_validate(r) for r in rows], "total": total}


# ── 台账导出 #9 ──────────────────────────────
@router.get("/ledger/export")
def export_assets(
    category_code: str | None = None,
    manage_dept: str | None = None,
    use_dept: str | None = None,
    custodian_name: str | None = None,
    custodian_user_id: int | None = None,
    room_id: int | None = None,
    room_name: str | None = None,
    status_: str | None = Query(default=None, alias="status"),
    sync_status: str | None = None,
    acquire_method: str | None = None,
    funding_source: str | None = None,
    acquired_year: int | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
    batch_no: str | None = None,
    is_booked: bool | None = None,
    is_idle: bool | None = None,
    q: str | None = None,
    sort_by: str = "id",
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    include_ext: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """台账导出(#9):查询结果一键导出 Excel;默认只含校内台账字段,
    扩展区字段须 include_ext=true 才追加;导出动作记审计。"""
    params = _search_params(
        category_code, manage_dept, use_dept, custodian_name,
        custodian_user_id, room_id, room_name, status_, sync_status,
        acquire_method, funding_source, acquired_year, min_value,
        max_value, batch_no, is_booked, is_idle, q,
        sort_by, sort_dir, 5000, 0,
    )
    query = _search_cards(db, params)
    rows = query
    data = ledger_svc.ledger_to_xlsx(rows, include_ext=include_ext)
    log_asset_action(
        db, user, "asset_ledger_export",
        target_type="asset_ledger",
        detail=f"导出台账 {len(rows)} 件 include_ext={include_ext}",
    )
    db.commit()
    return _download_xlsx(data, "资产台账")


# ── 附件归档 #12 ──────────────────────────────
@router.get("/assets/{asset_id}/attachments", response_model=list[AssetAttachmentOut])
def list_attachments(
    asset_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    if db.get(AssetCard, asset_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "资产卡不存在")
    return db.query(AssetAttachment).filter_by(
        asset_id=asset_id, is_deleted=False
    ).order_by(AssetAttachment.id).all()


@router.post("/assets/{asset_id}/attachments", response_model=AssetAttachmentOut,
             status_code=status.HTTP_201_CREATED)
def upload_attachment(
    asset_id: int,
    body: AssetAttachmentIn,
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """附件归档(#12):只存索引/路径,文件本体走系统现有附件存储。"""
    card = db.get(AssetCard, asset_id)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "资产卡不存在")
    if body.file_type not in ATTACHMENT_TYPES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"附件类型须为 {'/'.join(sorted(ATTACHMENT_TYPES))}",
        )
    row = AssetAttachment(
        asset_id=asset_id, file_type=body.file_type,
        file_name=body.file_name, file_path=body.file_path,
        file_size=body.file_size, acceptance_id=body.acceptance_id,
        uploaded_by=user.id,
    )
    db.add(row)
    db.flush()
    log_asset_action(
        db, user, "asset_attachment_upload",
        target_type="asset_attachment", target_id=row.id,
        detail=f"归档附件 {body.file_type}:{body.file_name} 到 {card.asset_code}",
    )
    db.commit()
    return row


# ── 附件直传 #12 ──────────────────────────────
#: 单个附件上限 20MB。
MAX_ATTACHMENT_SIZE = 20 * 1024 * 1024
#: 允许上传的扩展名(小写,含点)。
ALLOWED_ATTACHMENT_EXTS = frozenset({
    ".jpg", ".jpeg", ".png", ".webp",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
})

_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9_.\-\u4e00-\u9fff]+")


def _safe_attachment_name(filename: str) -> str:
    """文件名安全处理:只取 basename 防路径穿越,非法字符改下划线,
    扩展名小写,主名截断到 100 字,空主名用 file 兜底。"""
    name = Path(filename or "").name
    stem, ext = Path(name).stem, Path(name).suffix.lower()
    stem = _UNSAFE_NAME_CHARS.sub("_", stem).strip("._")[:100] or "file"
    return f"{stem}{ext}"


def _unique_attachment_path(asset_dir: Path, filename: str) -> Path:
    """重名加数字后缀:photo.jpg 已存在 → photo_1.jpg、photo_2.jpg……"""
    candidate = asset_dir / filename
    if not candidate.exists():
        return candidate
    stem, ext = Path(filename).stem, Path(filename).suffix
    n = 1
    while True:
        candidate = asset_dir / f"{stem}_{n}{ext}"
        if not candidate.exists():
            return candidate
        n += 1


@router.post("/assets/{asset_id}/attachments/upload",
             response_model=list[AssetAttachmentOut],
             status_code=status.HTTP_201_CREATED)
async def upload_attachment_files(
    asset_id: int,
    files: list[UploadFile] = File(...),
    file_type: str = Form("其他"),
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """附件直传(#12):multipart 多文件上传,与 JSON 归档端点共存。

    每个文件校验扩展名与大小(≤20MB),落盘到
    {asset_attachment_dir}/{asset_id}/,数据库只存相对路径
    {asset_id}/{文件名};每件记一条 asset_attachment_upload 审计。
    不做病毒扫描:本机无杀毒引擎,不假装已做。
    """
    card = db.get(AssetCard, asset_id)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "资产卡不存在")
    if file_type not in ATTACHMENT_TYPES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"附件类型须为 {'/'.join(sorted(ATTACHMENT_TYPES))}",
        )
    if not files:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "未选择文件")
    # 先全部校验(扩展名 + 大小),任一不合格整批 400,不落盘、不建行。
    payloads: list[tuple[str, bytes]] = []
    for upload in files:
        safe_name = _safe_attachment_name(upload.filename or "")
        ext = Path(safe_name).suffix.lower()
        if ext not in ALLOWED_ATTACHMENT_EXTS:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"不支持的文件类型:{upload.filename or safe_name}"
                f"(仅支持 {', '.join(sorted(ALLOWED_ATTACHMENT_EXTS))})",
            )
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_ATTACHMENT_SIZE:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"文件过大:{upload.filename or safe_name}"
                    f"(单文件上限 {MAX_ATTACHMENT_SIZE // (1024 * 1024)}MB)",
                )
            chunks.append(chunk)
        payloads.append((safe_name, b"".join(chunks)))
    asset_dir = Path(settings.asset_attachment_dir) / str(asset_id)
    asset_dir.mkdir(parents=True, exist_ok=True)
    rows: list[AssetAttachment] = []
    for safe_name, content in payloads:
        target = _unique_attachment_path(asset_dir, safe_name)
        target.write_bytes(content)
        row = AssetAttachment(
            asset_id=asset_id, file_type=file_type,
            file_name=target.name,
            file_path=f"{asset_id}/{target.name}",
            file_size=len(content), uploaded_by=user.id,
        )
        db.add(row)
        db.flush()
        log_asset_action(
            db, user, "asset_attachment_upload",
            target_type="asset_attachment", target_id=row.id,
            detail=f"直传附件 {file_type}:{target.name} 到 {card.asset_code}",
        )
        rows.append(row)
    db.commit()
    return rows


@router.delete("/attachments/{attachment_id}", response_model=dict)
def delete_attachment(
    attachment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """附件删除(#12):软删除留痕,审计日志另记,不可恢复删除记录本身。"""
    row = db.get(AssetAttachment, attachment_id)
    if row is None or row.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "附件不存在")
    from datetime import UTC, datetime

    row.is_deleted = True
    row.deleted_by = user.id
    row.deleted_at = datetime.now(UTC)
    log_asset_action(
        db, user, "asset_attachment_delete",
        target_type="asset_attachment", target_id=row.id,
        detail=f"删除附件 {row.file_type}:{row.file_name}(资产 id={row.asset_id})",
    )
    db.commit()
    return {"deleted": True, "id": attachment_id}


# ── 批量维护 #13 ──────────────────────────────
@router.post("/assets/bulk-update", response_model=BulkResultOut)
def bulk_update_assets(
    body: AssetBulkUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """批量维护(#13):批量改保管人/存放地点/管理部门/使用部门。
    默认逐条校验、逐条回告,失败不整体回滚;atomic=true 时整批回滚。"""
    updates = {
        k: v for k, v in {
            "custodian_user_id": body.custodian_user_id,
            "custodian_name": body.custodian_name,
            "room_id": body.room_id,
            "room_name": body.room_name,
            "manage_dept": body.manage_dept,
            "use_dept": body.use_dept,
        }.items() if v is not None
    }
    if not updates:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "未指定任何批量修改字段")
    if body.room_id is not None and db.get(Room, body.room_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "教室不存在")
    if body.custodian_user_id is not None and db.get(User, body.custodian_user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "保管人用户不存在")
    succeeded: list[BulkItemResult] = []
    failed: list[BulkItemResult] = []
    for asset_id in body.asset_ids:
        card = db.get(AssetCard, asset_id)
        if card is None:
            failed.append(BulkItemResult(asset_id=asset_id, ok=False, reason="资产不存在"))
            continue
        if card.is_retired:
            failed.append(BulkItemResult(
                asset_id=asset_id, asset_code=card.asset_code,
                ok=False, reason="资产已核销封存,不可修改"))
            continue
        before = {k: getattr(card, k) for k in updates}
        for key, value in updates.items():
            setattr(card, key, value)
        log_asset_action(
            db, user, "asset_bulk_update",
            target_type="asset_card", target_id=card.id,
            detail=f"批量维护 {card.asset_code}",
            before={k: str(v) for k, v in before.items()},
            after={k: str(v) for k, v in updates.items()},
        )
        succeeded.append(BulkItemResult(
            asset_id=asset_id, asset_code=card.asset_code, ok=True))
    if body.atomic and failed:
        db.rollback()
        return BulkResultOut(succeeded=[], failed=failed)
    db.commit()
    return BulkResultOut(succeeded=succeeded, failed=failed)


# ── 标签 #28 ──────────────────────────────
def _label_out(card: AssetCard) -> AssetLabelOut:
    return AssetLabelOut(
        asset_id=card.id, asset_code=card.asset_code,
        label_code=card.label_code, name=card.name,
        manage_dept=card.manage_dept,
        valid=asset_svc.verify_label_code(card.label_code),
    )


@router.get("/ledger/labels", response_model=list[AssetLabelOut])
def list_labels(
    ids: str = Query(..., description="逗号分隔的资产 id,如 1,2,3"),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """批量标签数据(#28):供标签打印页取数,打印样式在前端。"""
    out: list[AssetLabelOut] = []
    for raw in ids.split(","):
        raw = raw.strip()
        if not raw.isdigit():
            continue
        card = db.get(AssetCard, int(raw))
        if card is not None:
            out.append(_label_out(card))
    return out


@router.post("/ledger/labels/print", response_model=list[AssetLabelOut])
def print_labels(
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """批量打印标签(#28):打印动作记审计。"""
    ids = body.get("asset_ids") or []
    if not ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "未指定资产")
    out: list[AssetLabelOut] = []
    for asset_id in ids:
        card = db.get(AssetCard, asset_id)
        if card is not None:
            out.append(_label_out(card))
    log_asset_action(
        db, user, "asset_label_print",
        target_type="asset_label",
        detail=f"打印标签 {len(out)} 件:" + "、".join(o.asset_code for o in out),
    )
    db.commit()
    return out


@router.post("/assets/{asset_id}/label/reprint", response_model=AssetLabelOut)
def reprint_label(
    asset_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """补打标签(#28):单件补打,记审计。"""
    card = db.get(AssetCard, asset_id)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "资产卡不存在")
    log_asset_action(
        db, user, "asset_label_print",
        target_type="asset_label", target_id=card.id,
        detail=f"补打标签 {card.asset_code}",
    )
    db.commit()
    return _label_out(card)


@router.get("/assets/{asset_id}/label/qr")
def asset_label_qr(
    asset_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """二维码标签图(#28):标签码编成 QR(SVG),扫码即标签码,可反查资产卡。

    复核补:此前标签打印页只印标签码文本、无二维码图形,不是真正的
    二维码标签;本端点用 segno(纯 Python、无依赖)现场生成 SVG。
    """
    import io

    import segno

    card = db.get(AssetCard, asset_id)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "资产卡不存在")
    buf = io.BytesIO()
    segno.make(card.label_code).save(buf, kind="svg", scale=6, border=1)
    return Response(content=buf.getvalue(), media_type="image/svg+xml")


# ── 闲置识别 #14 ──────────────────────────────
@router.get("/idle", response_model=list[AssetIdleOut])
def list_idle_assets(
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """闲置清单(#14):仅展示刷新任务算出的标记,不手工打标记。"""
    return db.query(AssetCard).filter_by(is_idle=True).order_by(
        AssetCard.id).all()


@router.post("/idle/refresh", response_model=IdleRefreshOut)
def refresh_idle(
    body: dict | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """闲置识别刷新(#14):定时/手动刷新任务计算标记;threshold_days 可
    临时覆盖,不改参数表。"""
    threshold = (body or {}).get("threshold_days")
    idle_cards = ledger_svc.compute_idle(db, threshold_days=threshold)
    threshold_value = threshold
    if threshold_value is None:
        try:
            threshold_value = int(ledger_svc._param_value(
                db, "asset.idle.days_threshold", "180"))
        except ValueError:
            threshold_value = 180
    log_asset_action(
        db, user, "asset_idle_refresh",
        target_type="asset_idle",
        detail=f"闲置识别刷新:阈值{threshold_value}天,闲置{len(idle_cards)}件",
    )
    db.commit()
    return IdleRefreshOut(
        threshold_days=threshold_value,
        idle_count=len(idle_cards),
        idle_ids=[c.id for c in idle_cards],
    )
