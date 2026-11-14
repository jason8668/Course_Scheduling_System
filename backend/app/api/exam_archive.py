"""考试归档、历史对比与备份导出 API(KW-65~67)。

挂在 /api/exam 下,路由里写相对路径,与已有九个 exam 相关 router
共用同一前缀。
归档/取消归档/归档包下载/备份导出只允许 admin/director;
历史查询与对比读接口按可见范围过滤。所有写操作记审计。
"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.auth import get_active_user, require_roles
from app.core.db import get_db
from app.models.user import Role, User
from app.schemas.exam_archive import (
    ArchiveIn,
    ArchiveItemOut,
    ArchiveListOut,
    ArchiveOut,
    CompareOut,
)
from app.services import exam_archive as svc
from app.services.exam import get_exam, require_exam_visible
from app.services.exam_audit import log_exam_action
from app.services.exam_scopes import can_manage_students

router = APIRouter(tags=["exam_archive"])

writer = require_roles(Role.admin, Role.director)

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _require_can_manage(db: Session, user: User) -> None:
    if not can_manage_students(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "权限不足")


def _exam_or_404(db: Session, exam_id: int):
    return get_exam(db, exam_id)


def _archive_or_404(db: Session, exam_id: int):
    row = svc.get_archive(db, exam_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该考试尚未归档")
    return row


# ── 归档(KW-65) ──────────────────────────────
@router.post("/exams/{exam_id}/archive", status_code=status.HTTP_201_CREATED)
def create_archive(
    exam_id: int,
    body: ArchiveIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    row = svc.create_archive(db, user, exam, body.note)
    log_exam_action(
        db, user, "exam_archive_create",
        target_type="exam_archive", target_id=row.id,
        detail=f"考试{exam.name}归档",
    )
    db.commit()
    out = svc.archive_out(row)
    return {
        "archive_id": out["archive_id"],
        "exam_id": out["exam_id"],
        "archived_by": out["archived_by"],
        "archived_at": out["archived_at"],
        "manifest": out["manifest"],
    }


@router.get("/exams/{exam_id}/archive", response_model=ArchiveOut)
def get_archive(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    row = _archive_or_404(db, exam_id)
    return ArchiveOut(**svc.archive_out(row))


@router.get("/exams/{exam_id}/archive/download")
def download_archive(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    row = _archive_or_404(db, exam_id)
    data = svc.build_archive_zip(db, user, exam)
    log_exam_action(
        db, user, "exam_archive_download",
        target_type="exam_archive", target_id=row.id,
        detail=f"考试{exam.name}下载归档包",
    )
    db.commit()
    filename = quote(f"{exam.name}考试档案")
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition":
                f"attachment; filename=\"archive.zip\"; "
                f"filename*=UTF-8''{filename}.zip"
        },
    )


@router.delete("/exams/{exam_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
def delete_archive(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
) -> None:
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    row = _archive_or_404(db, exam_id)
    archive_id = row.id
    svc.delete_archive(db, user, exam, row)
    log_exam_action(
        db, user, "exam_archive_delete",
        target_type="exam_archive", target_id=archive_id,
        detail=f"考试{exam.name}取消归档,状态回到已发布成绩",
    )
    db.commit()


# ── 历史查询与对比(KW-66) ──────────────────────────────
@router.get("/archives", response_model=ArchiveListOut)
def list_archives(
    semester_id: int | None = None,
    q: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    items, total = svc.list_archives(db, user, semester_id, q, status)
    return ArchiveListOut(
        items=[ArchiveItemOut(**i) for i in items], total=total
    )


@router.get("/archives/compare", response_model=CompareOut)
def compare_archives(
    exam_a: int,
    exam_b: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    a = _exam_or_404(db, exam_a)
    b = _exam_or_404(db, exam_b)
    return CompareOut(**svc.compare_exams(db, user, a, b))


# ── 备份导出(KW-67) ──────────────────────────────
@router.get("/backup/export")
def export_backup(
    semester_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    data = svc.build_backup_workbook(db, semester_id)
    log_exam_action(
        db, user, "exam_backup_export",
        target_type="semester", target_id=semester_id,
        detail="全量导出考务与成绩数据备份",
    )
    db.commit()
    filename = quote("考务与成绩数据备份")
    return Response(
        content=data, media_type=_XLSX_MIME,
        headers={
            "Content-Disposition":
                f"attachment; filename=\"backup.xlsx\"; "
                f"filename*=UTF-8''{filename}.xlsx"
        },
    )
