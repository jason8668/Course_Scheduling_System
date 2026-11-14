"""阅卷与成绩录入 API(KW-30~35):阅卷分工、成绩设置、大题小分、成绩录入/导入/提交、进度看板、补考。

挂在 /api/exam 下,路由里写相对路径,与已有四个 exam 相关 router 共用同一前缀。
阅卷分工、成绩设置、补考场次只允许 admin/director;
成绩录入/导入/提交任课教师只限本人所教班级+本科目,admin/director 不限;
读接口按可见范围过滤。所有写操作记审计。
"""

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.core.auth import get_active_user, require_roles
from app.core.db import get_db
from app.models.user import Role, User
from app.schemas.exam_scores import (
    ImportResultOut,
    MakeupIn,
    MakeupListOut,
    MakeupOut,
    MakeupScoreListOut,
    MakeupScoreOut,
    MakeupScorePutIn,
    MarkingAssignmentIn,
    MarkingAssignmentListOut,
    MarkingAssignmentOut,
    ScoreItemIn,
    ScoreItemListOut,
    ScoreItemOut,
    ScoreListOut,
    ScorePutIn,
    ScorePutOut,
    ScoreSettingsOut,
    ScoreSettingsPut,
    ScoreSubmitIn,
    ScoreSubmitOut,
    ScoreProgressOut,
)
from app.services import exam_scores as svc
from app.services.exam import get_exam, require_exam_visible
from app.services.exam_audit import log_exam_action
from app.services.exam_scopes import can_manage_students

router = APIRouter(tags=["exam_scores"])

writer = require_roles(Role.admin, Role.director)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _require_can_manage(db: Session, user: User) -> None:
    if not can_manage_students(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "权限不足")


def _exam_or_404(db: Session, exam_id: int):
    return get_exam(db, exam_id)


# ── 成绩设置 ──────────────────────────────
@router.get("/exams/{exam_id}/score-settings", response_model=ScoreSettingsOut)
def get_score_settings(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    row = svc.get_settings(db, exam)
    data = svc.settings_out(exam, row)
    return ScoreSettingsOut(**data)


@router.put("/exams/{exam_id}/score-settings", response_model=ScoreSettingsOut)
def put_score_settings(
    exam_id: int,
    body: ScoreSettingsPut,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    row = svc.upsert_settings(
        db, exam, body.entry_mode, body.makeup_mode,
        body.cheating_score_mode, body.absent_counts, body.score_deadline,
    )
    log_exam_action(
        db, user, "exam_score_settings_update",
        target_type="exam", target_id=exam.id,
        detail=f"更新考试{exam.name}成绩设置(录入模式{row.entry_mode},补考口径{row.makeup_mode})",
    )
    db.commit()
    return ScoreSettingsOut(**svc.settings_out(exam, row))


# ── 阅卷分工(KW-30) ──────────────────────────────
@router.get("/exams/{exam_id}/marking-assignments", response_model=MarkingAssignmentListOut)
def list_marking_assignments(
    exam_id: int,
    subject_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    items, total = svc.list_marking_assignments(db, exam, subject_id)
    return MarkingAssignmentListOut(
        items=[MarkingAssignmentOut(**i) for i in items], total=total
    )


@router.post("/exams/{exam_id}/marking-assignments", response_model=MarkingAssignmentOut, status_code=status.HTTP_201_CREATED)
def create_marking_assignment(
    exam_id: int,
    body: MarkingAssignmentIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    row = svc.create_marking_assignment(
        db, exam, body.subject_id, body.teacher_id,
        body.role, body.scope_type, body.scope_value,
    )
    items, _ = svc.list_marking_assignments(db, exam, body.subject_id)
    out = next(i for i in items if i["id"] == row.id)
    log_exam_action(
        db, user, "exam_marking_assignment_create",
        target_type="exam_marking_assignment", target_id=row.id,
        detail=f"考试{exam.name}登记阅卷分工({body.role})",
    )
    db.commit()
    return MarkingAssignmentOut(**out)


@router.delete("/exams/{exam_id}/marking-assignments/{mid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_marking_assignment(
    exam_id: int,
    mid: int,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    svc.delete_marking_assignment(db, exam, mid)
    log_exam_action(
        db, user, "exam_marking_assignment_delete",
        target_type="exam_marking_assignment", target_id=mid,
        detail=f"考试{exam.name}删除阅卷分工",
    )
    db.commit()


# ── 大题小分(KW-31) ──────────────────────────────
@router.get("/exams/{exam_id}/score-items", response_model=ScoreItemListOut)
def list_score_items(
    exam_id: int,
    subject_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    rows, total = svc.list_score_items(db, exam, subject_id)
    return ScoreItemListOut(
        items=[ScoreItemOut.model_validate(r) for r in rows], total=total
    )


@router.post("/exams/{exam_id}/score-items", response_model=ScoreItemOut, status_code=status.HTTP_201_CREATED)
def create_score_item(
    exam_id: int,
    body: ScoreItemIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    row = svc.create_score_item(db, exam, body.subject_id, body.name, body.max_score)
    log_exam_action(
        db, user, "exam_score_item_create",
        target_type="exam_score_item", target_id=row.id,
        detail=f"考试{exam.name}新增大题「{body.name}」(满分{body.max_score:g})",
    )
    db.commit()
    return ScoreItemOut.model_validate(row)


@router.delete("/exams/{exam_id}/score-items/{iid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_score_item(
    exam_id: int,
    iid: int,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    svc.delete_score_item(db, exam, iid)
    log_exam_action(
        db, user, "exam_score_item_delete",
        target_type="exam_score_item", target_id=iid,
        detail=f"考试{exam.name}删除大题",
    )
    db.commit()


# ── 成绩录入/提交(KW-31/33,静态路由须在 /scores/{id} 之前注册) ──
@router.get("/exams/{exam_id}/scores", response_model=ScoreListOut)
def list_scores(
    exam_id: int,
    subject_id: int,
    class_unit_id: int | None = None,
    status: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    items, total = svc.list_scores(
        db, user, exam, subject_id, class_unit_id, status, q
    )
    return ScoreListOut(items=items, total=total)


@router.put("/exams/{exam_id}/scores", response_model=ScorePutOut)
def put_scores(
    exam_id: int,
    body: ScorePutIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    updated = svc.upsert_scores(
        db, user, exam, body.subject_id,
        [s.model_dump() for s in body.scores],
    )
    log_exam_action(
        db, user, "exam_score_update",
        target_type="exam", target_id=exam.id,
        detail=f"考试{exam.name}录入成绩{updated}人",
    )
    db.commit()
    return ScorePutOut(updated=updated)


@router.post("/exams/{exam_id}/scores/submit", response_model=ScoreSubmitOut)
def submit_scores(
    exam_id: int,
    body: ScoreSubmitIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    count = svc.submit_scores(db, user, exam, body.subject_id, body.class_unit_id)
    log_exam_action(
        db, user, "exam_score_submit",
        target_type="exam", target_id=exam.id,
        detail=f"考试{exam.name}提交成绩{count}人",
    )
    db.commit()
    return ScoreSubmitOut(submitted=count)


@router.get("/exams/{exam_id}/scores/template")
def download_score_template(
    exam_id: int,
    subject_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    svc._require_can_enter(db, user, exam, subject_id)
    return Response(
        content=svc.build_score_template(db, exam, subject_id),
        media_type=XLSX_MIME,
        headers={"Content-Disposition": 'attachment; filename="scores_template.xlsx"'},
    )


@router.post("/exams/{exam_id}/scores/import", response_model=ImportResultOut)
async def import_scores(
    exam_id: int,
    subject_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    content = await file.read()
    try:
        result = svc.import_scores(db, user, exam, subject_id, content)
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "无法读取成绩文件,请确认为有效的 Excel 文件"
        ) from None
    if not result["errors"]:
        log_exam_action(
            db, user, "exam_score_import",
            target_type="exam", target_id=exam.id,
            detail=f"考试{exam.name}导入成绩:新增{result['created']}人,更新{result['updated']}人",
        )
        db.commit()
    return ImportResultOut(**result)


# ── 录入进度看板(KW-34) ──────────────────────────────
@router.get("/exams/{exam_id}/score-progress", response_model=ScoreProgressOut)
def get_score_progress(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    return ScoreProgressOut(**svc.score_progress(db, user, exam))


# ── 补考(KW-35) ──────────────────────────────
@router.get("/exams/{exam_id}/makeups", response_model=MakeupListOut)
def list_makeups(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    rows, total = svc.list_makeups(db, exam)
    return MakeupListOut(
        items=[MakeupOut.model_validate(r) for r in rows], total=total
    )


@router.post("/exams/{exam_id}/makeups", response_model=MakeupOut, status_code=status.HTTP_201_CREATED)
def create_makeup(
    exam_id: int,
    body: MakeupIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    row = svc.create_makeup(db, exam, body.name, body.exam_date, body.note)
    log_exam_action(
        db, user, "exam_makeup_create",
        target_type="exam_makeup", target_id=row.id,
        detail=f"考试{exam.name}新建补考场次{body.name}",
    )
    db.commit()
    return MakeupOut.model_validate(row)


@router.delete("/exams/{exam_id}/makeups/{mid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_makeup(
    exam_id: int,
    mid: int,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    svc.delete_makeup(db, exam, mid)
    log_exam_action(
        db, user, "exam_makeup_delete",
        target_type="exam_makeup", target_id=mid,
        detail=f"考试{exam.name}删除补考场次",
    )
    db.commit()


@router.get("/exams/{exam_id}/makeups/{mid}/scores", response_model=MakeupScoreListOut)
def list_makeup_scores(
    exam_id: int,
    mid: int,
    subject_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    makeup = svc._require_makeup(db, exam, mid)
    items, total = svc.list_makeup_scores(db, user, exam, makeup, subject_id)
    return MakeupScoreListOut(
        items=[MakeupScoreOut(**i) for i in items], total=total
    )


@router.put("/exams/{exam_id}/makeups/{mid}/scores", response_model=ScorePutOut)
def put_makeup_scores(
    exam_id: int,
    mid: int,
    body: MakeupScorePutIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    makeup = svc._require_makeup(db, exam, mid)
    updated = svc.upsert_makeup_scores(
        db, user, exam, makeup, body.subject_id,
        [s.model_dump() for s in body.scores],
    )
    log_exam_action(
        db, user, "exam_makeup_score_update",
        target_type="exam_makeup", target_id=makeup.id,
        detail=f"考试{exam.name}补考{makeup.name}录入成绩{updated}人",
    )
    db.commit()
    return ScorePutOut(updated=updated)
