"""成绩发布与校对锁定 API(KW-36~40):发布设置、双人校对、成绩锁定、改分审批、发布批次、成绩异议。

挂在 /api/exam 下,路由里写相对路径,与已有五个 exam 相关 router 共用同一前缀。
写接口只允许 admin/director,另:校对决定允许指定的校对人本人;
改分申请允许成绩录入教师本人提交;异议回复与关闭允许任课教师与教务。
读接口按可见范围过滤。所有写操作记审计。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import get_active_user, require_roles
from app.core.db import get_db
from app.models.user import Role, User
from app.schemas.exam_publish import (
    ChangeRequestDecideIn,
    ChangeRequestIn,
    ChangeRequestListOut,
    ChangeRequestOut,
    LockIn,
    LockListOut,
    LockOut,
    ObjectionIn,
    ObjectionListOut,
    ObjectionOut,
    ObjectionReplyIn,
    ProofreadingDecideIn,
    ProofreadingIn,
    ProofreadingListOut,
    ProofreadingOut,
    PublishBatchIn,
    PublishBatchListOut,
    PublishBatchOut,
    PublishBatchWithdrawIn,
    PublishDueOut,
    PublishSettingsIn,
    PublishSettingsOut,
    PublishStatusOut,
)
from app.services import exam_publish as svc
from app.services.exam import get_exam, require_exam_visible
from app.services.exam_audit import log_exam_action
from app.services.exam_scopes import can_manage_students

router = APIRouter(tags=["exam_publish"])

writer = require_roles(Role.admin, Role.director)


def _exam_or_404(db: Session, exam_id: int):
    return get_exam(db, exam_id)


def _require_can_manage(db: Session, user: User) -> None:
    if not can_manage_students(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "权限不足")


# ── 发布设置 ──────────────────────────────
@router.get("/exams/{exam_id}/publish-settings", response_model=PublishSettingsOut)
def get_publish_settings(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    return PublishSettingsOut(**svc.settings_out(exam, svc.get_settings(db, exam)))


@router.put("/exams/{exam_id}/publish-settings", response_model=PublishSettingsOut)
def put_publish_settings(
    exam_id: int,
    body: PublishSettingsIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    row = svc.upsert_settings(
        db, exam, body.proofreader_role, body.approval_levels,
        body.publish_order, body.objection_open,
    )
    log_exam_action(
        db, user, "exam_publish_settings_update",
        target_type="exam", target_id=exam.id,
        detail=f"更新考试{exam.name}发布设置(校对人{row.proofreader_role},审批{row.approval_levels}层,发布顺序{row.publish_order},异议入口{'开放' if row.objection_open else '关闭'})",
    )
    db.commit()
    return PublishSettingsOut(**svc.settings_out(exam, row))


# ── 双人校对(KW-36) ──────────────────────────────
@router.get("/exams/{exam_id}/proofreading", response_model=ProofreadingListOut)
def list_proofreading(
    exam_id: int,
    subject_id: int | None = None,
    class_unit_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    items, total = svc.list_proofreading(db, user, exam, subject_id, class_unit_id)
    return ProofreadingListOut(
        items=[ProofreadingOut(**i) for i in items], total=total
    )


@router.post("/exams/{exam_id}/proofreading", response_model=ProofreadingOut, status_code=status.HTTP_201_CREATED)
def submit_proofreading(
    exam_id: int,
    body: ProofreadingIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    row = svc.submit_proofreading(
        db, user, exam, body.subject_id, body.class_unit_id, body.note,
    )
    log_exam_action(
        db, user, "exam_proofreading_submit",
        target_type="exam_proofreading", target_id=row.id,
        detail=f"考试{exam.name}提交校对(科目{row.subject_id})",
    )
    db.commit()
    return ProofreadingOut(**svc.proofreading_out(db, row))


@router.post("/exams/{exam_id}/proofreading/{pid}/decide", response_model=ProofreadingOut)
def decide_proofreading(
    exam_id: int,
    pid: int,
    body: ProofreadingDecideIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    row = svc.decide_proofreading(db, user, exam, pid, body.decision, body.note)
    log_exam_action(
        db, user, "exam_proofreading_decide",
        target_type="exam_proofreading", target_id=row.id,
        detail=f"考试{exam.name}校对{row.status}(科目{row.subject_id})",
    )
    db.commit()
    return ProofreadingOut(**svc.proofreading_out(db, row))


# ── 成绩锁定(KW-37) ──────────────────────────────
@router.get("/exams/{exam_id}/locks", response_model=LockListOut)
def list_locks(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    items, total = svc.list_locks(db, user, exam)
    return LockListOut(items=[LockOut(**i) for i in items], total=total)


@router.post("/exams/{exam_id}/locks", response_model=LockOut, status_code=status.HTTP_201_CREATED)
def create_lock(
    exam_id: int,
    body: LockIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    row = svc.create_lock(db, user, exam, body.subject_id, body.class_unit_id)
    log_exam_action(
        db, user, "exam_score_lock_create",
        target_type="exam_score_lock", target_id=row.id,
        detail=f"考试{exam.name}锁定成绩(科目{row.subject_id})",
    )
    db.commit()
    return LockOut(**svc.lock_out(db, row))


@router.delete("/exams/{exam_id}/locks/{lid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lock(
    exam_id: int,
    lid: int,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    svc.delete_lock(db, exam, lid)
    log_exam_action(
        db, user, "exam_score_lock_delete",
        target_type="exam_score_lock", target_id=lid,
        detail=f"考试{exam.name}解锁成绩",
    )
    db.commit()


# ── 改分审批(KW-38) ──────────────────────────────
@router.get("/exams/{exam_id}/score-change-requests", response_model=ChangeRequestListOut)
def list_change_requests(
    exam_id: int,
    status: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    items, total = svc.list_change_requests(db, user, exam, status)
    return ChangeRequestListOut(
        items=[ChangeRequestOut(**i) for i in items], total=total
    )


@router.post("/exams/{exam_id}/score-change-requests", response_model=ChangeRequestOut, status_code=status.HTTP_201_CREATED)
def create_change_request(
    exam_id: int,
    body: ChangeRequestIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    row = svc.create_change_request(
        db, user, exam, body.score_id, body.new_score, body.reason,
    )
    log_exam_action(
        db, user, "exam_score_change_request_create",
        target_type="exam_score_change_request", target_id=row.id,
        detail=f"考试{exam.name}提交改分申请(原分数{row.old_score},新分数{row.new_score},原因:{row.reason})",
    )
    db.commit()
    return ChangeRequestOut(**svc.change_request_out(db, row))


@router.post("/exams/{exam_id}/score-change-requests/{rid}/decide", response_model=ChangeRequestOut)
def decide_change_request(
    exam_id: int,
    rid: int,
    body: ChangeRequestDecideIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    row = svc.decide_change_request(db, user, exam, rid, body.decision, body.note)
    log_exam_action(
        db, user, "exam_score_change_decide",
        target_type="exam_score_change_request", target_id=row.id,
        detail=f"考试{exam.name}改分申请{row.status}(原分数{row.old_score},新分数{row.new_score})",
    )
    db.commit()
    return ChangeRequestOut(**svc.change_request_out(db, row))


# ── 发布批次(KW-39) ──────────────────────────────
@router.get("/exams/{exam_id}/publish-batches", response_model=PublishBatchListOut)
def list_publish_batches(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    items, total = svc.list_publish_batches(db, user, exam)
    return PublishBatchListOut(
        items=[PublishBatchOut(**i) for i in items], total=total
    )


@router.post("/exams/{exam_id}/publish-batches", response_model=PublishBatchOut, status_code=status.HTTP_201_CREATED)
def create_publish_batch(
    exam_id: int,
    body: PublishBatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    row = svc.create_publish_batch(
        db, user, exam, body.scope_type, body.scope_value,
        body.publish_at, body.note,
    )
    log_exam_action(
        db, user, "exam_publish_batch_create",
        target_type="exam_publish_batch", target_id=row.id,
        detail=f"考试{exam.name}发布成绩({row.scope_type}{row.scope_value},{row.status})",
    )
    db.commit()
    return PublishBatchOut(**svc.publish_batch_out(db, row))


@router.post("/exams/{exam_id}/publish-batches/{bid}/withdraw", response_model=PublishBatchOut)
def withdraw_publish_batch(
    exam_id: int,
    bid: int,
    body: PublishBatchWithdrawIn | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    note = body.note if body is not None else None
    row = svc.withdraw_publish_batch(db, exam, bid, note)
    log_exam_action(
        db, user, "exam_publish_batch_withdraw",
        target_type="exam_publish_batch", target_id=row.id,
        detail=f"考试{exam.name}撤回成绩发布({row.scope_type}{row.scope_value})",
    )
    db.commit()
    return PublishBatchOut(**svc.publish_batch_out(db, row))


@router.post("/exams/{exam_id}/publish-due", response_model=PublishDueOut)
def publish_due(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    count = svc.publish_due(db, exam)
    if count:
        log_exam_action(
            db, user, "exam_publish_due",
            target_type="exam", target_id=exam.id,
            detail=f"考试{exam.name}定时发布到期 {count} 个批次",
        )
    db.commit()
    return PublishDueOut(published=count)


@router.get("/exams/{exam_id}/publish-status", response_model=PublishStatusOut)
def get_publish_status(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    return PublishStatusOut(**svc.publish_status(db, exam))


# ── 成绩异议(KW-40) ──────────────────────────────
@router.get("/exams/{exam_id}/objections", response_model=ObjectionListOut)
def list_objections(
    exam_id: int,
    status: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    items, total = svc.list_objections(db, user, exam, status)
    return ObjectionListOut(
        items=[ObjectionOut(**i) for i in items], total=total
    )


@router.post("/exams/{exam_id}/objections", response_model=ObjectionOut, status_code=status.HTTP_201_CREATED)
def create_objection(
    exam_id: int,
    body: ObjectionIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    row = svc.create_objection(db, user, exam, body.score_id, body.content)
    log_exam_action(
        db, user, "exam_objection_create",
        target_type="exam_objection", target_id=row.id,
        detail=f"考试{exam.name}登记成绩异议(学生{row.student_id})",
    )
    db.commit()
    return ObjectionOut(**svc.objection_out(db, row))


@router.post("/exams/{exam_id}/objections/{oid}/reply", response_model=ObjectionOut)
def reply_objection(
    exam_id: int,
    oid: int,
    body: ObjectionReplyIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    row = svc.reply_objection(db, user, exam, oid, body.reply)
    log_exam_action(
        db, user, "exam_objection_reply",
        target_type="exam_objection", target_id=row.id,
        detail=f"考试{exam.name}回复成绩异议",
    )
    db.commit()
    return ObjectionOut(**svc.objection_out(db, row))


@router.post("/exams/{exam_id}/objections/{oid}/close", response_model=ObjectionOut)
def close_objection(
    exam_id: int,
    oid: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    row = svc.close_objection(db, user, exam, oid)
    log_exam_action(
        db, user, "exam_objection_close",
        target_type="exam_objection", target_id=row.id,
        detail=f"考试{exam.name}关闭成绩异议",
    )
    db.commit()
    return ObjectionOut(**svc.objection_out(db, row))
