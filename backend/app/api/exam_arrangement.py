"""考场编排 API(KW-15~22):考场设置、编排规则、自动编排、手动调整、座位表、导出、锁定。

挂在 /api/exam 下,路由里写相对路径,与 exam、exam_students 两个
router 共用同一前缀。
写接口只允许 admin/director;读接口按可见范围过滤,越权 403。
所有写操作记审计。
"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.auth import get_active_user, require_roles
from app.core.db import get_db
from app.models.user import Role, User
from app.schemas.exam_arrangement import (
    AdmissionTicketListOut,
    AdmissionTicketOut,
    ArrangeIn,
    ArrangeOut,
    ArrangementLockIn,
    ArrangementLockOut,
    ArrangementMoveIn,
    ArrangementSwapIn,
    AssignmentListOut,
    AssignmentOut,
    ArrangementRuleIn,
    ArrangementRuleOut,
    ExamRoomIn,
    ExamRoomBulkAddIn,
    ExamRoomBulkOut,
    ExamRoomListOut,
    ExamRoomOut,
    SeatMapOut,
)
from app.services import exam_arrangement as svc
from app.services import exam as exam_svc
from app.services.exam_audit import log_exam_action
from app.services.exam_scopes import can_manage_students

router = APIRouter(tags=["exam_arrangement"])

writer = require_roles(Role.admin, Role.director)

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _require_can_manage(db: Session, user: User) -> None:
    if not can_manage_students(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "权限不足")


def _exam_or_404(db: Session, exam_id: int):
    return exam_svc.get_exam(db, exam_id)


# ── 考场设置(KW-15) ──────────────────────────────
@router.get("/exams/{exam_id}/rooms", response_model=ExamRoomListOut)
def list_rooms(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    exam_svc.require_exam_visible(db, user, exam)
    items, total = svc.list_rooms(db, exam)
    return ExamRoomListOut(
        items=[ExamRoomOut(**i) for i in items], total=total
    )


@router.post("/exams/{exam_id}/rooms", response_model=ExamRoomOut, status_code=status.HTTP_201_CREATED)
def create_room(
    exam_id: int,
    body: ExamRoomIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    row = svc.create_room(
        db, exam, body.room_id, body.capacity, body.room_type, body.is_special
    )
    log_exam_action(
        db, user, "exam_room_create",
        target_type="exam_room", target_id=row.id,
        detail=f"考试{exam.name}设置考场(教室{body.room_id})",
    )
    db.commit()
    items, _ = svc.list_rooms(db, exam)
    item = next(i for i in items if i["id"] == row.id)
    return ExamRoomOut(**item)


@router.post("/exams/{exam_id}/rooms/bulk", response_model=ExamRoomBulkOut)
def create_rooms_bulk(
    exam_id: int,
    body: ExamRoomBulkAddIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    created, skipped = svc.create_rooms_bulk(
        db, exam, body.room_ids, body.capacity, body.room_type, body.is_special
    )
    log_exam_action(
        db, user, "exam_room_create",
        target_type="exam", target_id=exam.id,
        detail=f"考试{exam.name}批量添加考场:新增{created}间,跳过{skipped}间",
    )
    db.commit()
    return ExamRoomBulkOut(created=created, skipped=skipped)


@router.delete("/exams/{exam_id}/rooms/{rid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_room(
    exam_id: int,
    rid: int,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
) -> None:
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    svc.delete_room(db, exam, rid)
    log_exam_action(
        db, user, "exam_room_delete",
        target_type="exam_room", target_id=rid,
        detail=f"考试{exam.name}删除考场",
    )
    db.commit()


# ── 编排规则(KW-16) ──────────────────────────────
@router.get("/exams/{exam_id}/arrangement-rule", response_model=ArrangementRuleOut)
def get_rule(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    exam_svc.require_exam_visible(db, user, exam)
    row = svc.get_rule(db, exam)
    return ArrangementRuleOut(
        exam_id=exam.id, mode=row.mode,
        scatter_same_class=row.scatter_same_class,
        max_per_room=row.max_per_room,
    )


@router.put("/exams/{exam_id}/arrangement-rule", response_model=ArrangementRuleOut)
def put_rule(
    exam_id: int,
    body: ArrangementRuleIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    row = svc.upsert_rule(
        db, exam, body.mode, body.scatter_same_class, body.max_per_room
    )
    log_exam_action(
        db, user, "exam_arrangement_rule_update",
        target_type="exam", target_id=exam.id,
        detail=f"考试{exam.name}更新编排规则({row.mode},每考场{row.max_per_room}人)",
    )
    db.commit()
    return ArrangementRuleOut(
        exam_id=exam.id, mode=row.mode,
        scatter_same_class=row.scatter_same_class,
        max_per_room=row.max_per_room,
    )


# ── 自动编排(KW-17) ──────────────────────────────
@router.post("/exams/{exam_id}/arrange", response_model=ArrangeOut)
def arrange(
    exam_id: int,
    body: ArrangeIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    result, cleared = svc.arrange(db, exam, body.subject_id)
    detail = (
        f"考试{exam.name}自动编排:编排{result['assigned']}人,"
        f"使用{result['rooms_used']}间考场"
    )
    if cleared:
        detail += f",先清空原编排{cleared}条"
    if result["warnings"]:
        detail += "，警告:" + "；".join(result["warnings"])
    log_exam_action(
        db, user, "exam_arrange",
        target_type="exam", target_id=exam.id, detail=detail,
    )
    db.commit()
    return ArrangeOut(**result)


# ── 编排结果查询 / 手动调整(KW-18/19) ──────────────────────────────
@router.get("/exams/{exam_id}/arrangements", response_model=AssignmentListOut)
def list_arrangements(
    exam_id: int,
    subject_id: int | None = None,
    room_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    items, total = svc.list_assignments(db, user, exam, subject_id, room_id)
    return AssignmentListOut(
        items=[AssignmentOut(**i) for i in items], total=total
    )


@router.post("/exams/{exam_id}/arrangements/move", response_model=AssignmentOut)
def move_assignment(
    exam_id: int,
    body: ArrangementMoveIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    row = svc.move_assignment(
        db, exam, body.assignment_id, body.to_room_id, body.seat_no
    )
    log_exam_action(
        db, user, "exam_arrangement_move",
        target_type="exam_room_assignment", target_id=row.id,
        detail=f"考试{exam.name}调整考生考场至教室{body.to_room_id}",
    )
    db.commit()
    return AssignmentOut(**svc.assignment_to_out(db, row))


@router.post("/exams/{exam_id}/arrangements/swap", response_model=AssignmentListOut)
def swap_assignments(
    exam_id: int,
    body: ArrangementSwapIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    a, b = svc.swap_assignments(db, exam, body.assignment_id_a, body.assignment_id_b)
    log_exam_action(
        db, user, "exam_arrangement_swap",
        target_type="exam", target_id=exam.id,
        detail=f"考试{exam.name}互换两名考生座位",
    )
    db.commit()
    return AssignmentListOut(
        items=[
            AssignmentOut(**svc.assignment_to_out(db, a)),
            AssignmentOut(**svc.assignment_to_out(db, b)),
        ],
        total=2,
    )


@router.get("/exams/{exam_id}/seat-map", response_model=SeatMapOut)
def seat_map(
    exam_id: int,
    subject_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    return SeatMapOut(**svc.seat_map(db, user, exam, subject_id))


@router.get("/exams/{exam_id}/admission-tickets", response_model=AdmissionTicketListOut)
def admission_tickets(
    exam_id: int,
    class_unit_id: int | None = None,
    room_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """准考证数据(KW-19):按班级筛选供按班级分发打印;照片不做,无照片数据源。"""
    exam = _exam_or_404(db, exam_id)
    items, total = svc.list_admission_tickets(
        db, user, exam, class_unit_id, room_id
    )
    return AdmissionTicketListOut(
        items=[AdmissionTicketOut(**i) for i in items], total=total
    )


@router.get("/exams/{exam_id}/arrangements/export")
def export_arrangements(
    exam_id: int,
    subject_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    data = svc.build_arrangement_workbook(db, user, exam, subject_id)
    filename = svc.export_filename(db, exam, subject_id)
    quoted = quote(filename)
    return Response(
        content=data, media_type=_XLSX_MIME,
        headers={
            "Content-Disposition":
                f"attachment; filename=\"export.xlsx\"; "
                f"filename*=UTF-8''{quoted}.xlsx"
        },
    )


# ── 编排锁定(KW-22) ──────────────────────────────
@router.get("/exams/{exam_id}/arrangement-lock", response_model=ArrangementLockOut)
def get_lock(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    exam_svc.require_exam_visible(db, user, exam)
    return ArrangementLockOut(**svc.get_lock_info(db, exam))


@router.post("/exams/{exam_id}/arrangement-lock", response_model=ArrangementLockOut)
def lock(
    exam_id: int,
    body: ArrangementLockIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    svc.lock_arrangement(db, user, exam, body.note)
    log_exam_action(
        db, user, "exam_arrangement_lock",
        target_type="exam", target_id=exam.id,
        detail=f"考试{exam.name}锁定考场编排",
    )
    db.commit()
    return ArrangementLockOut(**svc.get_lock_info(db, exam))


@router.post("/exams/{exam_id}/arrangement-unlock", response_model=ArrangementLockOut)
def unlock(
    exam_id: int,
    body: ArrangementLockIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    svc.unlock_arrangement(db, exam)
    log_exam_action(
        db, user, "exam_arrangement_unlock",
        target_type="exam", target_id=exam.id,
        detail=f"考试{exam.name}解锁考场编排",
    )
    db.commit()
    return ArrangementLockOut(**svc.get_lock_info(db, exam))
