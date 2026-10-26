"""Excel 导入 API:范本下载、上传导入。"""

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.core.auth import require_roles
from app.core.db import get_db
from app.models.semester import Semester
from app.models.user import Role
from app.services import importer

router = APIRouter(tags=["import"])

editor = require_roles(Role.director)

VALID_ENTITIES = {"subjects", "teachers", "classes", "assignments"}
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_FILENAMES = {
    "subjects": "subjects", "teachers": "teachers",
    "classes": "classes", "assignments": "assignments",
}


def _check_entity(entity: str) -> None:
    if entity not in VALID_ENTITIES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未知的导入类型")


@router.get("/import/templates/{entity}")
def download_template(entity: str, _: object = Depends(editor)) -> Response:
    _check_entity(entity)
    data = importer.build_template(entity)
    filename = f"{_FILENAMES[entity]}_template.xlsx"
    return Response(
        content=data,
        media_type=XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import/{entity}")
async def upload_import(
    entity: str,
    semester_id: int = Query(...),
    create_accounts: bool = Query(False),
    # 既有教师(姓名＋末四码相同)改为更新而非报错;只覆盖有填的栏位(用户回报 #18)
    update_existing: bool = Query(False),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: object = Depends(editor),
) -> dict:
    _check_entity(entity)
    if db.get(Semester, semester_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到学期")
    content = await file.read()
    try:
        result = importer.run_import(
            db, entity, semester_id, content, create_accounts, update_existing)
    except Exception:
        db.rollback()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "无法读取档案,请确认为有效的 Excel 档"
        ) from None
    return {"imported": result.imported, "updated": result.updated, "errors": result.errors}
