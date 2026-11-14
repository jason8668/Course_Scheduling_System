"""监考安排 API(KW-23~29):监考规则、教师池、自动排监考、手工调整、巡考、
监考表两视图、工作量统计与导出、考风考纪记录。

挂在 /api/exam 下,路由里写相对路径,与 exam、exam_students、
exam_arrangement 三个 router 共用同一前缀。
写接口只允许 admin/director,考风考纪登记例外,监考教师本人也可登记
本人监考场次的考生;读接口按可见范围过滤,越权 403。
所有写操作记审计。
"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.auth import get_active_user, require_roles
from app.core.db import get_db
from app.models.user import Role, User
from app.schemas.exam_invigilation import (
    DisciplineIn,
    DisciplineListOut,
    DisciplineOut,
    DisciplinePatchIn,
    InvigilateIn,
    InvigilateOut,
    InvigilationIn,
    InvigilationListOut,
    InvigilationOut,
    InvigilationPatchIn,
    InvigilationRuleIn,
    InvigilationRuleOut,
    InvigilatorPoolIn,
    InvigilatorPoolItemOut,
    InvigilatorPoolOut,
    PatrolIn,
    PatrolListOut,
    PatrolOut,
    PatrolPatchIn,
    RoomSheetListOut,
    RoomSheetOut,
    TeacherSheetOut,
    WorkloadItemOut,
    WorkloadOut,
)
from app.services import exam_invigilation as svc
from app.services import exam as exam_svc
from app.services.exam_audit import log_exam_action
from app.services.exam_scopes import can_manage_students

router = APIRouter(tags=["exam_invigilation"])

writer = require_roles(Role.admin, Role.director)

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _require_can_manage(db: Session, user: User) -> None:
    if not can_manage_students(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "权限不足")


def _exam_or_404(db: Session, exam_id: int):
    return exam_svc.get_exam(db, exam_id)


# ── 监考规则(KW-23) ──────────────────────────────
@router.get("/exams/{exam_id}/invigilation-rule", response_model=InvigilationRuleOut)
def get_rule(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    exam_svc.require_exam_visible(db, user, exam)
    row = svc.get_rule(db, exam)
    return InvigilationRuleOut(
        exam_id=exam.id,
        avoid_own_class=row.avoid_own_class,
        avoid_own_subject=row.avoid_own_subject,
        invigilators_per_room=row.invigilators_per_room,
    )


@router.put("/exams/{exam_id}/invigilation-rule", response_model=InvigilationRuleOut)
def put_rule(
    exam_id: int,
    body: InvigilationRuleIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    row = svc.upsert_rule(
        db, exam,
        body.avoid_own_class, body.avoid_own_subject,
        body.invigilators_per_room,
    )
    log_exam_action(
        db, user, "exam_invigilation_rule_update",
        target_type="exam", target_id=exam.id,
        detail=f"考试{exam.name}更新监考规则(避本班{row.avoid_own_class},"
               f"避本科{row.avoid_own_subject},每考场{row.invigilators_per_room}人)",
    )
    db.commit()
    return InvigilationRuleOut(
        exam_id=exam.id,
        avoid_own_class=row.avoid_own_class,
        avoid_own_subject=row.avoid_own_subject,
        invigilators_per_room=row.invigilators_per_room,
    )


# ── 监考教师池(KW-23) ──────────────────────────────
@router.get("/exams/{exam_id}/invigilators", response_model=InvigilatorPoolOut)
def list_invigilators(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    exam_svc.require_exam_visible(db, user, exam)
    items, total = svc.list_pool(db, exam)
    return InvigilatorPoolOut(
        items=[InvigilatorPoolItemOut(**i) for i in items], total=total
    )


@router.put("/exams/{exam_id}/invigilators", response_model=InvigilatorPoolOut)
def put_invigilators(
    exam_id: int,
    body: InvigilatorPoolIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    items, total = svc.upsert_pool(
        db, exam, [i.model_dump() for i in body.items]
    )
    log_exam_action(
        db, user, "exam_invigilator_pool_update",
        target_type="exam", target_id=exam.id,
        detail=f"考试{exam.name}设置监考教师池({total}人)",
    )
    db.commit()
    return InvigilatorPoolOut(
        items=[InvigilatorPoolItemOut(**i) for i in items], total=total
    )


# ── 自动排监考(KW-24) ──────────────────────────────
@router.post("/exams/{exam_id}/invigilate", response_model=InvigilateOut)
def invigilate(
    exam_id: int,
    body: InvigilateIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    result = svc.auto_invigilate(db, exam, body.subject_id)
    detail = f"考试{exam.name}自动排监考:安排{result['assigned']}人次"
    if result["warnings"]:
        detail += "，警告:" + "；".join(result["warnings"])
    log_exam_action(
        db, user, "exam_invigilate",
        target_type="exam", target_id=exam.id, detail=detail,
    )
    db.commit()
    return InvigilateOut(**result)


# ── 监考安排查询 / 手工调整(KW-25) ──────────────────────────────
@router.get("/exams/{exam_id}/invigilations", response_model=InvigilationListOut)
def list_invigilations(
    exam_id: int,
    subject_id: int | None = None,
    room_id: int | None = None,
    teacher_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    exam_svc.require_exam_visible(db, user, exam)
    items, total = svc.list_invigilations(
        db, user, exam, subject_id, room_id, teacher_id
    )
    return InvigilationListOut(
        items=[InvigilationOut(**i) for i in items], total=total
    )


@router.post("/exams/{exam_id}/invigilations", response_model=InvigilationOut, status_code=status.HTTP_201_CREATED)
def create_invigilation(
    exam_id: int,
    body: InvigilationIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    row = svc.create_invigilation(
        db, exam, body.subject_id, body.room_id, body.teacher_id, body.role
    )
    log_exam_action(
        db, user, "exam_invigilation_create",
        target_type="exam_invigilation", target_id=row.id,
        detail=f"考试{exam.name}手工安排监考(教师{body.teacher_id})",
    )
    db.commit()
    return InvigilationOut(**svc.invigilation_to_out(db, row))


@router.patch("/exams/{exam_id}/invigilations/{iid}", response_model=InvigilationOut)
def update_invigilation(
    exam_id: int,
    iid: int,
    body: InvigilationPatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    row = svc.update_invigilation(
        db, exam, iid, body.teacher_id, body.role
    )
    log_exam_action(
        db, user, "exam_invigilation_update",
        target_type="exam_invigilation", target_id=row.id,
        detail=f"考试{exam.name}调整监考安排(替补换人)",
    )
    db.commit()
    return InvigilationOut(**svc.invigilation_to_out(db, row))


@router.delete("/exams/{exam_id}/invigilations/{iid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_invigilation(
    exam_id: int,
    iid: int,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
) -> None:
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    svc.delete_invigilation(db, exam, iid)
    log_exam_action(
        db, user, "exam_invigilation_delete",
        target_type="exam_invigilation", target_id=iid,
        detail=f"考试{exam.name}删除监考安排",
    )
    db.commit()


# ── 巡考安排(KW-26) ──────────────────────────────
@router.get("/exams/{exam_id}/patrols", response_model=PatrolListOut)
def list_patrols(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    exam_svc.require_exam_visible(db, user, exam)
    items, total = svc.list_patrols(db, user, exam)
    return PatrolListOut(
        items=[PatrolOut(**i) for i in items], total=total
    )


@router.post("/exams/{exam_id}/patrols", response_model=PatrolOut, status_code=status.HTTP_201_CREATED)
def create_patrol(
    exam_id: int,
    body: PatrolIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    row = svc.create_patrol(
        db, exam, body.exam_date, body.teacher_id, body.scope, body.note
    )
    log_exam_action(
        db, user, "exam_patrol_create",
        target_type="exam_patrol", target_id=row.id,
        detail=f"考试{exam.name}安排巡考(教师{body.teacher_id},{body.scope})",
    )
    db.commit()
    return PatrolOut(**svc.patrol_to_out(db, row))


@router.patch("/exams/{exam_id}/patrols/{pid}", response_model=PatrolOut)
def update_patrol(
    exam_id: int,
    pid: int,
    body: PatrolPatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    row = svc.update_patrol(
        db, exam, pid,
        body.exam_date, body.teacher_id, body.scope, body.note,
    )
    log_exam_action(
        db, user, "exam_patrol_update",
        target_type="exam_patrol", target_id=row.id,
        detail=f"考试{exam.name}调整巡考安排",
    )
    db.commit()
    return PatrolOut(**svc.patrol_to_out(db, row))


@router.delete("/exams/{exam_id}/patrols/{pid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_patrol(
    exam_id: int,
    pid: int,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
) -> None:
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    svc.delete_patrol(db, exam, pid)
    log_exam_action(
        db, user, "exam_patrol_delete",
        target_type="exam_patrol", target_id=pid,
        detail=f"考试{exam.name}删除巡考安排",
    )
    db.commit()


# ── 监考表两视图(KW-27) ──────────────────────────────
@router.get("/exams/{exam_id}/invigilation-sheets")
def invigilation_sheets(
    exam_id: int,
    view: str = "teacher",
    subject_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    exam_svc.require_exam_visible(db, user, exam)
    if view not in ("teacher", "room"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "view 只能是 teacher 或 room"
        )
    if view == "teacher":
        return TeacherSheetOut(
            **svc.teacher_sheet(db, user, exam, subject_id)
        )
    return RoomSheetListOut(
        rooms=[
            RoomSheetOut(**r)
            for r in svc.room_sheet(db, user, exam, subject_id)["rooms"]
        ]
    )


# ── 工作量统计(KW-28) ──────────────────────────────
@router.get("/exams/{exam_id}/invigilation-workload", response_model=WorkloadOut)
def invigilation_workload(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    exam_svc.require_exam_visible(db, user, exam)
    items, total = svc.workload(db, user, exam)
    return WorkloadOut(
        items=[WorkloadItemOut(**i) for i in items], total=total
    )


@router.get("/exams/{exam_id}/invigilation-workload/export")
def export_workload(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    exam_svc.require_exam_visible(db, user, exam)
    data = svc.build_workload_workbook(db, user, exam)
    filename = f"{exam.name}监考工作量表"
    quoted = quote(filename)
    return Response(
        content=data, media_type=_XLSX_MIME,
        headers={
            "Content-Disposition":
                f"attachment; filename=\"export.xlsx\"; "
                f"filename*=UTF-8''{quoted}.xlsx"
        },
    )


# ── 考风考纪记录(KW-29) ──────────────────────────────
@router.get("/exams/{exam_id}/discipline", response_model=DisciplineListOut)
def list_discipline(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    exam_svc.require_exam_visible(db, user, exam)
    items, total = svc.list_discipline(db, user, exam)
    return DisciplineListOut(
        items=[DisciplineOut(**i) for i in items], total=total
    )


@router.post("/exams/{exam_id}/discipline", response_model=DisciplineOut, status_code=status.HTTP_201_CREATED)
def create_discipline(
    exam_id: int,
    body: DisciplineIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    exam_svc.require_exam_visible(db, user, exam)
    row = svc.create_discipline(
        db, user, exam,
        body.subject_id, body.student_id,
        body.type, body.description, body.handling,
    )
    log_exam_action(
        db, user, "exam_discipline_create",
        target_type="exam_discipline", target_id=row.id,
        detail=f"考试{exam.name}登记考风考纪({body.type})",
    )
    db.commit()
    return DisciplineOut(**svc._discipline_out(db, row))


@router.patch("/exams/{exam_id}/discipline/{did}", response_model=DisciplineOut)
def update_discipline(
    exam_id: int,
    did: int,
    body: DisciplinePatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    row = svc.update_discipline(
        db, exam, did,
        body.subject_id, body.student_id,
        body.type, body.description, body.handling,
    )
    log_exam_action(
        db, user, "exam_discipline_update",
        target_type="exam_discipline", target_id=row.id,
        detail=f"考试{exam.name}修改考风考纪记录",
    )
    db.commit()
    return DisciplineOut(**svc._discipline_out(db, row))


@router.delete("/exams/{exam_id}/discipline/{did}", status_code=status.HTTP_204_NO_CONTENT)
def delete_discipline(
    exam_id: int,
    did: int,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
) -> None:
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    svc.delete_discipline(db, exam, did)
    log_exam_action(
        db, user, "exam_discipline_delete",
        target_type="exam_discipline", target_id=did,
        detail=f"考试{exam.name}删除考风考纪记录",
    )
    db.commit()
