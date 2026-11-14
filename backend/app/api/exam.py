"""考试管理 API(KW-08~14):考试创建、日程编排、参试名单、状态流转、复制、命题信息、特殊考生安排。

挂在 /api/exam 下,路由里写相对路径,与 exam_students 路由共用同一前缀。
写接口只允许 admin/director;读接口按可见范围过滤,越权 403。
所有写操作记审计。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import get_active_user, require_roles
from app.core.db import get_db
from app.models.user import Role, User
from app.schemas.exam import (
    ExamCopyIn,
    ExamCreate,
    ExamDetailOut,
    ExamListOut,
    ExamOut,
    ExamStatusIn,
    ExamSubjectsOut,
    ExamSubjectsPut,
    ExamUpdate,
    PaperInfoListOut,
    PaperInfoPut,
    ParticipantAddIn,
    ParticipantBulkAddIn,
    ParticipantGenerateOut,
    ParticipantListOut,
    ParticipantOut,
    ParticipantUpdateIn,
    ScheduleCheckOut,
    SpecialArrangementIn,
    SpecialArrangementListOut,
    SpecialArrangementOut,
    SpecialArrangementUpdateIn,
)
from app.services import exam as svc
from app.services.exam_audit import log_exam_action
from app.services.exam_scopes import can_manage_students

router = APIRouter(tags=["exam"])

writer = require_roles(Role.admin, Role.director)


def _require_can_manage(db: Session, user: User) -> None:
    if not can_manage_students(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "权限不足")


def _exam_or_404(db: Session, exam_id: int):
    return svc.get_exam(db, exam_id)


# ── 考试列表/创建/详情/修改 ──────────────────────────────
@router.get("/exams", response_model=ExamListOut)
def list_exams(
    semester_id: int | None = None,
    status: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    rows, total = svc.list_exams(db, user, semester_id, status, q)
    return ExamListOut(items=[svc.to_exam_out(db, e) for e in rows], total=total)


@router.post("/exams", response_model=ExamOut, status_code=status.HTTP_201_CREATED)
def create_exam(
    body: ExamCreate,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
) -> ExamOut:
    _require_can_manage(db, user)
    exam = svc.create_exam(
        db, user, body.semester_id, body.name, body.exam_type,
        body.grades, body.description,
    )
    log_exam_action(
        db, user, "exam_create",
        target_type="exam", target_id=exam.id,
        detail=f"新建考试{exam.name}({exam.exam_type})",
    )
    db.commit()
    return svc.to_exam_out(db, exam)


@router.get("/exams/{exam_id}", response_model=ExamDetailOut)
def get_exam(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    svc.require_exam_visible(db, user, exam)
    return svc.to_exam_detail(db, exam)


@router.patch("/exams/{exam_id}", response_model=ExamOut)
def update_exam(
    exam_id: int,
    body: ExamUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
) -> ExamOut:
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    exam = svc.update_exam(
        db, exam, body.name, body.exam_type, body.grades, body.description,
    )
    log_exam_action(
        db, user, "exam_update",
        target_type="exam", target_id=exam.id,
        detail=f"修改考试{exam.name}",
    )
    db.commit()
    return svc.to_exam_out(db, exam)


# ── 状态流转/复制 ──────────────────────────────
@router.post("/exams/{exam_id}/status", response_model=ExamOut)
def change_status(
    exam_id: int,
    body: ExamStatusIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
) -> ExamOut:
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    old = exam.status
    exam = svc.change_exam_status(db, user, exam, body.to_status, body.note)
    log_exam_action(
        db, user, "exam_status_change",
        target_type="exam", target_id=exam.id,
        detail=f"考试{exam.name}状态由{old}变更为{exam.status}",
    )
    db.commit()
    return svc.to_exam_out(db, exam)


@router.post("/exams/{exam_id}/copy", response_model=ExamOut, status_code=status.HTTP_201_CREATED)
def copy_exam(
    exam_id: int,
    body: ExamCopyIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
) -> ExamOut:
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    new_exam = svc.copy_exam(db, user, exam, body.name, body.semester_id)
    log_exam_action(
        db, user, "exam_copy",
        target_type="exam", target_id=new_exam.id,
        detail=f"复制考试{exam.name}为{new_exam.name}",
    )
    db.commit()
    return svc.to_exam_out(db, new_exam)


# ── 考试科目与日程 ──────────────────────────────
@router.get("/exams/{exam_id}/subjects", response_model=ExamSubjectsOut)
def list_subjects(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    svc.require_exam_visible(db, user, exam)
    return ExamSubjectsOut(items=svc.exam_subject_outs(db, exam.id))


@router.put("/exams/{exam_id}/subjects", response_model=ExamSubjectsOut)
def put_subjects(
    exam_id: int,
    body: ExamSubjectsPut,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    items = svc.upsert_exam_subjects(db, exam, [s.model_dump() for s in body.subjects])
    log_exam_action(
        db, user, "exam_subject_update",
        target_type="exam", target_id=exam.id,
        detail=f"更新考试{exam.name}日程{len(body.subjects)}科",
    )
    db.commit()
    return ExamSubjectsOut(items=items)


@router.post("/exams/{exam_id}/schedule-check", response_model=ScheduleCheckOut)
def schedule_check(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    svc.require_exam_visible(db, user, exam)
    return ScheduleCheckOut(conflicts=svc.check_schedule(db, exam))


# ── 参试名单 ──────────────────────────────
@router.get("/exams/{exam_id}/participants", response_model=ParticipantListOut)
def list_participants(
    exam_id: int,
    class_unit_id: int | None = None,
    class_unit_ids: list[int] | None = Query(default=None),
    status: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    rows, total = svc.list_participants(
        db, user, exam, class_unit_id, status, q, class_unit_ids
    )
    return ParticipantListOut(items=rows, total=total)


@router.post("/exams/{exam_id}/participants/generate", response_model=ParticipantGenerateOut)
def generate_participants(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    created, skipped = svc.generate_participants(db, exam)
    log_exam_action(
        db, user, "exam_participant_generate",
        target_type="exam", target_id=exam.id,
        detail=f"考试{exam.name}生成参试名单:新增{created}人,跳过{skipped}人",
    )
    db.commit()
    return ParticipantGenerateOut(created=created, skipped=skipped)


@router.post("/exams/{exam_id}/participants", response_model=ParticipantOut, status_code=status.HTTP_201_CREATED)
def add_participant(
    exam_id: int,
    body: ParticipantAddIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
) -> ParticipantOut:
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    row = svc.add_participant(db, exam, body.student_id, body.note)
    log_exam_action(
        db, user, "exam_participant_update",
        target_type="exam_participant", target_id=row.id,
        detail=f"考试{exam.name}增补参试学生",
    )
    db.commit()
    return svc.participant_out(db, row)


@router.post("/exams/{exam_id}/participants/bulk", response_model=ParticipantGenerateOut)
def add_participants_bulk(
    exam_id: int,
    body: ParticipantBulkAddIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    created, skipped = svc.add_participants(db, exam, body.student_ids, body.note)
    log_exam_action(
        db, user, "exam_participant_update",
        target_type="exam", target_id=exam.id,
        detail=f"考试{exam.name}批量增补参试学生:新增{created}人,跳过{skipped}人",
    )
    db.commit()
    return ParticipantGenerateOut(created=created, skipped=skipped)


@router.patch("/exams/{exam_id}/participants/{pid}", response_model=ParticipantOut)
def update_participant(
    exam_id: int,
    pid: int,
    body: ParticipantUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
) -> ParticipantOut:
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    row = svc.update_participant(db, exam, pid, body.status, body.note)
    log_exam_action(
        db, user, "exam_participant_update",
        target_type="exam_participant", target_id=row.id,
        detail=f"考试{exam.name}修改参试学生状态为{row.status}",
    )
    db.commit()
    return svc.participant_out(db, row)


@router.delete("/exams/{exam_id}/participants/{pid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_participant(
    exam_id: int,
    pid: int,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
) -> None:
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    svc.delete_participant(db, exam, pid)
    log_exam_action(
        db, user, "exam_participant_update",
        target_type="exam_participant", target_id=pid,
        detail=f"考试{exam.name}删除参试学生",
    )
    db.commit()


# ── 命题信息 ──────────────────────────────
@router.get("/exams/{exam_id}/paper-info", response_model=PaperInfoListOut)
def list_paper_info(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    svc.require_exam_visible(db, user, exam)
    return PaperInfoListOut(items=svc.list_paper_info(db, exam))


@router.put("/exams/{exam_id}/paper-info", response_model=PaperInfoListOut)
def put_paper_info(
    exam_id: int,
    body: PaperInfoPut,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    items = svc.upsert_paper_info(db, exam, [i.model_dump() for i in body.items])
    log_exam_action(
        db, user, "exam_paper_info_update",
        target_type="exam", target_id=exam.id,
        detail=f"更新考试{exam.name}命题信息{len(body.items)}科",
    )
    db.commit()
    return PaperInfoListOut(items=items)


# ── 特殊考生安排 ──────────────────────────────
@router.get("/exams/{exam_id}/special-arrangements", response_model=SpecialArrangementListOut)
def list_special_arrangements(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    return SpecialArrangementListOut(
        items=svc.list_special_arrangements(db, user, exam)
    )


@router.post("/exams/{exam_id}/special-arrangements", response_model=SpecialArrangementOut, status_code=status.HTTP_201_CREATED)
def create_special_arrangement(
    exam_id: int,
    body: SpecialArrangementIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
) -> SpecialArrangementOut:
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    row = svc.create_special_arrangement(
        db, exam, body.student_id, body.arrangement_type, body.detail
    )
    log_exam_action(
        db, user, "exam_special_arrangement_create",
        target_type="exam_special_arrangement", target_id=row.id,
        detail=f"考试{exam.name}登记特殊考生安排({body.arrangement_type})",
    )
    db.commit()
    return svc.arrangement_out(db, row)


@router.patch("/exams/{exam_id}/special-arrangements/{sid}", response_model=SpecialArrangementOut)
def update_special_arrangement(
    exam_id: int,
    sid: int,
    body: SpecialArrangementUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
) -> SpecialArrangementOut:
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    row = svc.update_special_arrangement(
        db, exam, sid, body.arrangement_type, body.detail, body.status
    )
    log_exam_action(
        db, user, "exam_special_arrangement_update",
        target_type="exam_special_arrangement", target_id=row.id,
        detail=f"考试{exam.name}修改特殊考生安排",
    )
    db.commit()
    return svc.arrangement_out(db, row)


@router.delete("/exams/{exam_id}/special-arrangements/{sid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_special_arrangement(
    exam_id: int,
    sid: int,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
) -> None:
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    svc.delete_special_arrangement(db, exam, sid)
    log_exam_action(
        db, user, "exam_special_arrangement_delete",
        target_type="exam_special_arrangement", target_id=sid,
        detail=f"考试{exam.name}删除特殊考生安排",
    )
    db.commit()
