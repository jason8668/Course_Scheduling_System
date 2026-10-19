"""课表导出:班级/教师/场地 Excel/PDF/PNG、全校总表、批次 zip(M5-1)。

Excel 在 api 同步产生(openpyxl 轻量);PDF/PNG 派到 worker(WeasyPrint + 中文字型)
再取回。单一对象导出开放给所有登录者(课表本就全校可查);全校总表/批次限教学组长以上。
"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.auth import get_active_user, require_roles
from app.core.db import get_db
from app.models.user import Role, User
from app.services import timetable_export as tex
from app.workers import queue as job_queue

router = APIRouter(tags=["exports"])

manager = require_roles(Role.scheduler, Role.director)

_MIME = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
    "png": "image/png",
    "zip": "application/zip",
}


def _download(data: bytes, filename: str, ext: str) -> Response:
    # 中文档名以 RFC 5987 filename* 表达;filename 提供 ASCII 后备
    quoted = quote(filename)
    disposition = f"attachment; filename=\"export.{ext}\"; filename*=UTF-8''{quoted}.{ext}"
    return Response(
        content=data, media_type=_MIME[ext],
        headers={"Content-Disposition": disposition},
    )


@router.get("/export/timetable")
def export_timetable(
    semester_id: int = Query(...),
    view: str = Query(..., pattern="^(class|teacher|room)$"),
    target_id: int = Query(...),
    fmt: str = Query("xlsx", pattern="^(xlsx|pdf|png)$"),
    db: Session = Depends(get_db),
    _: User = Depends(get_active_user),
):
    """单一班级/教师/场地的课表,格式 xlsx/pdf/png。"""
    try:
        grid, meta = tex.build_grid(db, semester_id, view, target_id)
    except tex.ExportError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e

    filename = f"{grid.title}_{meta.semester_label}"
    if fmt == "xlsx":
        return _download(tex.grids_to_xlsx([grid], meta), filename, "xlsx")

    html = tex.grid_to_html(grid, meta)
    try:
        data = job_queue.render_export(html, fmt)
    except job_queue.RenderError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
    return _download(data, filename, fmt)


@router.get("/export/school.xlsx")
def export_school(
    semester_id: int = Query(...),
    # 教师版是后来补的(用户回报 #22);默认 class 让旧的呼叫方式照常运作
    view: str = Query("class", pattern="^(class|teacher)$"),
    db: Session = Depends(get_db),
    _: User = Depends(manager),
):
    """全校总表:一个 Excel,每班(或每位教师)一个分页。"""
    try:
        data = tex.school_workbook(db, semester_id, view)
    except tex.ExportError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    name = "全校教师课表总表" if view == "teacher" else "全校课表总表"
    return _download(data, f"{name}_{semester_id}", "xlsx")


@router.get("/export/batch.zip")
def export_batch(
    semester_id: int = Query(...),
    view: str = Query("class", pattern="^(class|teacher)$"),
    db: Session = Depends(get_db),
    _: User = Depends(manager),
):
    """批次导出:全部班级(或全部教师)各一个 Excel,打包成 zip。"""
    try:
        data = tex.batch_zip(db, semester_id, view)
    except tex.ExportError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    name = "全校教师课表" if view == "teacher" else "全校班级课表"
    return _download(data, f"{name}_{semester_id}", "zip")
