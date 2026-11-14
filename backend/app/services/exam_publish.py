"""成绩发布与校对锁定服务(KW-36~40):发布设置、双人校对、成绩锁定、改分审批、发布批次、成绩异议。

权限口径(与 api/exam_scores.py 一致,写接口默认只允许 admin/director):
- 校对提交:教务,或任教该科目+班级的教师;校对决定:指定的校对人本人或教务。
- 锁定/解锁:只允许 admin/director;解锁记审计。
- 改分申请:教务,或该成绩的录入教师本人;审批:一层时教研组长或教务,
  两层时第一层只允许教研组长、第二层只允许教务(admin 在各层均可)。
- 发布批次/撤回/定时发布:只允许 admin/director。
- 异议登记:教师/教务代登;异议回复与关闭:任课教师或教务。
- 读接口按可见范围过滤:教师只看本人可见班级相关记录,全科范围的记录
  只在教师任教该科目时可见。

考试状态流转复用已有状态机(草稿→已发布→进行中→成绩处理中→已发布成绩→已归档):
本批不新增状态,成绩发布后考试状态由已有 /exams/{id}/status 接口按顺序
推进到“已发布成绩”,不自动改状态。
"""

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assignment import (
    AssignmentTeacher,
    CourseAssignment,
    SchedulingUnitMember,
)
from app.models.basedata import ClassUnit, Subject, Teacher
from app.models.exam import Exam, ExamGrade, ExamParticipant
from app.models.exam_foundation import Student
from app.models.exam_publish import (
    CHANGE_DECISIONS,
    PROOFREADER_ROLES,
    PUBLISH_SCOPE_TYPES,
    ExamObjection,
    ExamProofreading,
    ExamPublishBatch,
    ExamPublishSetting,
    ExamScoreChangeApproval,
    ExamScoreChangeRequest,
    ExamScoreLock,
)
from app.models.exam_scores import ExamScore
from app.models.exam_scopes import SubjectLeader
from app.models.user import Role, User
from app.services.exam_scopes import (
    can_manage_students,
    exam_roles,
    visible_class_ids,
)

DEFAULT_SETTINGS = {
    "proofreader_role": "subject_leader",
    "approval_levels": 1,
    "objection_open": True,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(value: datetime | None) -> datetime | None:
    """把无时区时间按 UTC 视作有时区,避免与有时区时间比较时报错。"""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


# ── 共用小工具 ──────────────────────────────
def _is_manager(db: Session, user: User) -> bool:
    return can_manage_students(db, user)


def _is_academic(db: Session, user: User) -> bool:
    """是否教务:director 且未配年级(年级组长不算教务)。"""
    return "academic" in exam_roles(db, user)


def _is_admin(user: User) -> bool:
    return Role.admin.value in user.role_names


def _teacher_ids(db: Session, user: User) -> set[int]:
    rows = db.scalars(
        select(Teacher.id).where(Teacher.user_id == user.id)
    ).all()
    return set(rows)


def _teaching_pairs(db: Session, user: User, semester_id: int) -> set[tuple[int, int]]:
    """该账号在本考试学期内任教的 (班级 id, 科目 id) 集合。

    与 exam_scores.teaching_pairs 同一溯源口径;本模块自备一份,
    避免与 exam_scores 服务互相导入。
    """
    teacher_ids = _teacher_ids(db, user)
    if not teacher_ids:
        return set()
    rows = db.execute(
        select(SchedulingUnitMember.class_unit_id, CourseAssignment.subject_id)
        .join(
            CourseAssignment,
            CourseAssignment.scheduling_unit_id
            == SchedulingUnitMember.scheduling_unit_id,
        )
        .join(
            AssignmentTeacher,
            AssignmentTeacher.course_assignment_id == CourseAssignment.id,
        )
        .where(
            AssignmentTeacher.teacher_id.in_(teacher_ids),
            CourseAssignment.semester_id == semester_id,
        )
    ).all()
    return {(class_id, subject_id) for class_id, subject_id in rows}


def _is_subject_leader(db: Session, user: User, exam: Exam, subject_id: int) -> bool:
    """是否该科目教研组长(本考试学期内任命)。"""
    teacher_ids = _teacher_ids(db, user)
    if not teacher_ids:
        return False
    row = db.scalar(
        select(SubjectLeader).where(
            SubjectLeader.semester_id == exam.semester_id,
            SubjectLeader.subject_id == subject_id,
            SubjectLeader.teacher_id.in_(teacher_ids),
        )
    )
    return row is not None


def _display_name(db: Session, user_id: int | None) -> str:
    """用户展示名:优先绑定的教师姓名,否则用账号名。"""
    if user_id is None:
        return ""
    teacher = db.scalar(
        select(Teacher).where(Teacher.user_id == user_id).order_by(Teacher.id)
    )
    if teacher is not None:
        return teacher.name
    user = db.get(User, user_id)
    return user.username if user is not None else ""


def _subject_name_map(db: Session, subject_ids: set[int]) -> dict[int, str]:
    if not subject_ids:
        return {}
    rows = db.scalars(select(Subject).where(Subject.id.in_(subject_ids))).all()
    return {s.id: s.name for s in rows}


def _class_name_map(db: Session, class_ids: set[int]) -> dict[int, str]:
    if not class_ids:
        return {}
    rows = db.scalars(select(ClassUnit).where(ClassUnit.id.in_(class_ids))).all()
    return {c.id: c.name for c in rows}


def _participants_by_id(db: Session, exam: Exam) -> dict[int, ExamParticipant]:
    rows = db.scalars(
        select(ExamParticipant).where(ExamParticipant.exam_id == exam.id)
    ).all()
    return {r.student_id: r for r in rows}


def _class_visible_to_teacher(
    db: Session, user: User, exam: Exam, subject_id: int, class_unit_id: int | None
) -> bool:
    """教师读列表时某条记录是否可见:班级在可见集合内;全科记录须任教该科目。"""
    if class_unit_id is not None:
        class_ids = visible_class_ids(db, user)
        return class_ids is None or class_unit_id in class_ids
    pairs = _teaching_pairs(db, user, exam.semester_id)
    return any(s == subject_id for _, s in pairs)


# ── 发布设置 ──────────────────────────────
def get_settings(db: Session, exam: Exam) -> ExamPublishSetting | None:
    return db.scalar(
        select(ExamPublishSetting).where(ExamPublishSetting.exam_id == exam.id)
    )


def settings_out(exam: Exam, row: ExamPublishSetting | None) -> dict:
    if row is None:
        return {"exam_id": exam.id, **DEFAULT_SETTINGS}
    return {
        "exam_id": exam.id,
        "proofreader_role": row.proofreader_role,
        "approval_levels": row.approval_levels,
        "objection_open": row.objection_open,
    }


def upsert_settings(
    db: Session, exam: Exam, proofreader_role: str, approval_levels: int,
    objection_open: bool,
) -> ExamPublishSetting:
    if proofreader_role not in PROOFREADER_ROLES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "校对人角色只能是 subject_leader(教研组长)或 peer_teacher(同组教师)",
        )
    if approval_levels not in (1, 2):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "审批层级只能是 1 或 2"
        )
    row = get_settings(db, exam)
    if row is None:
        row = ExamPublishSetting(exam_id=exam.id)
        db.add(row)
    row.proofreader_role = proofreader_role
    row.approval_levels = approval_levels
    row.objection_open = objection_open
    db.flush()
    return row


# ── 成绩锁定(供 exam_scores 服务调用的最小检查) ──────────────────────────────
def is_score_locked(
    db: Session, exam_id: int, subject_id: int, class_unit_id: int | None
) -> bool:
    """该科目+班级成绩是否已锁定:全科锁(class_unit_id 为空)锁住全部班级。"""
    rows = db.scalars(
        select(ExamScoreLock).where(
            ExamScoreLock.exam_id == exam_id,
            ExamScoreLock.subject_id == subject_id,
        )
    ).all()
    return any(
        r.class_unit_id is None or r.class_unit_id == class_unit_id
        for r in rows
    )


def require_scores_not_locked(
    db: Session, exam_id: int, subject_id: int, class_unit_ids: set[int]
) -> None:
    """锁定检查:目标班级中任一已锁定即 403(只走改分审批)。"""
    for class_unit_id in class_unit_ids:
        if is_score_locked(db, exam_id, subject_id, class_unit_id):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "该范围成绩已锁定,不能直接修改,请走改分审批",
            )


# ── 双人校对(KW-36) ──────────────────────────────
def _resolve_proofreader(
    db: Session, exam: Exam, subject_id: int, role: str, submitted_by_id: int
) -> int:
    """按发布设置确定校对人用户 id;找不到合适人选时 409。

    subject_leader:该科目教研组长(取 id 最小的一位,须有登录账号且不是提交人);
    peer_teacher:本学期任教该科目的同组教师(取 id 最小的一位,不是提交人)。
    """
    if role == "subject_leader":
        rows = db.scalars(
            select(SubjectLeader).where(
                SubjectLeader.semester_id == exam.semester_id,
                SubjectLeader.subject_id == subject_id,
            ).order_by(SubjectLeader.id)
        ).all()
        for leader in rows:
            teacher = db.get(Teacher, leader.teacher_id)
            if (
                teacher is not None
                and teacher.user_id is not None
                and teacher.user_id != submitted_by_id
            ):
                return teacher.user_id
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "该科目尚未任命教研组长(或教研组长就是提交人),无法指定校对人",
        )
    rows = db.execute(
        select(AssignmentTeacher.teacher_id)
        .join(
            CourseAssignment,
            CourseAssignment.id == AssignmentTeacher.course_assignment_id,
        )
        .where(
            CourseAssignment.semester_id == exam.semester_id,
            CourseAssignment.subject_id == subject_id,
        )
        .order_by(AssignmentTeacher.teacher_id)
    ).all()
    seen: set[int] = set()
    for (teacher_id,) in rows:
        if teacher_id in seen:
            continue
        seen.add(teacher_id)
        teacher = db.get(Teacher, teacher_id)
        if (
            teacher is not None
            and teacher.user_id is not None
            and teacher.user_id != submitted_by_id
        ):
            return teacher.user_id
    raise HTTPException(
        status.HTTP_409_CONFLICT,
        "该科目没有可担任校对人的同组教师(须有登录账号且不是提交人)",
    )


def _require_scores_submitted(
    db: Session, exam: Exam, subject_id: int, class_unit_id: int | None
) -> None:
    """校对前置:该范围参试学生的成绩须已全部提交,否则 409。"""
    participants = _participants_by_id(db, exam)
    in_scope = [
        p for p in participants.values()
        if class_unit_id is None or p.class_unit_id == class_unit_id
    ]
    if not in_scope:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "该范围没有参试学生,无法提交校对"
        )
    submitted_ids = {
        r.student_id
        for r in db.scalars(
            select(ExamScore).where(
                ExamScore.exam_id == exam.id,
                ExamScore.subject_id == subject_id,
                ExamScore.submitted.is_(True),
            )
        ).all()
    }
    missing = [p for p in in_scope if p.student_id not in submitted_ids]
    if missing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"该范围还有 {len(missing)} 名学生成绩未提交,提交后才能校对",
        )


def _require_can_submit_proofreading(
    db: Session, user: User, exam: Exam, subject_id: int, class_unit_id: int | None
) -> None:
    """校对提交权限:教务不限;教师须任教该科目,指定班级时须任教该班级。"""
    if _is_manager(db, user):
        return
    if Role.teacher.value not in user.role_names:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "只有任课教师与教务可以提交校对")
    pairs = _teaching_pairs(db, user, exam.semester_id)
    if class_unit_id is not None:
        if (class_unit_id, subject_id) not in pairs:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "只能提交本人所教班级、所教科目的校对"
            )
    elif not any(s == subject_id for _, s in pairs):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "你未任教该科目,无权提交该科校对"
        )


def submit_proofreading(
    db: Session, user: User, exam: Exam, subject_id: int,
    class_unit_id: int | None, note: str | None,
) -> ExamProofreading:
    _require_can_submit_proofreading(db, user, exam, subject_id, class_unit_id)
    subject = db.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到科目")
    _require_scores_submitted(db, exam, subject_id, class_unit_id)
    existing = db.scalar(
        select(ExamProofreading).where(
            ExamProofreading.exam_id == exam.id,
            ExamProofreading.subject_id == subject_id,
            ExamProofreading.class_unit_id == class_unit_id,
            ExamProofreading.status.in_(("待校对", "通过")),
        )
    )
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "该范围校对已提交(待校对或已通过),请勿重复提交",
        )
    setting = get_settings(db, exam)
    role = setting.proofreader_role if setting else DEFAULT_SETTINGS["proofreader_role"]
    proofreader_id = _resolve_proofreader(db, exam, subject_id, role, user.id)
    row = ExamProofreading(
        exam_id=exam.id, subject_id=subject_id, class_unit_id=class_unit_id,
        submitted_by=user.id, proofreader_id=proofreader_id,
        status="待校对", note=note,
    )
    db.add(row)
    db.flush()
    return row


def decide_proofreading(
    db: Session, user: User, exam: Exam, pid: int,
    decision: str, note: str | None,
) -> ExamProofreading:
    if decision not in ("通过", "退回"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "校对决定只能是通过或退回"
        )
    row = db.get(ExamProofreading, pid)
    if row is None or row.exam_id != exam.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到校对记录")
    if row.status != "待校对":
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"该校对记录已{row.status},不能重复决定"
        )
    if row.submitted_by == user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "校对人不能是录入人本人"
        )
    if row.proofreader_id != user.id and not _is_manager(db, user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "只有指定的校对人或教务可以决定校对结果"
        )
    row.status = decision
    row.note = note if note is not None else row.note
    row.decided_at = _now()
    db.flush()
    return row


def list_proofreading(
    db: Session, user: User, exam: Exam,
    subject_id: int | None, class_unit_id: int | None,
) -> tuple[list[dict], int]:
    stmt = select(ExamProofreading).where(ExamProofreading.exam_id == exam.id)
    if subject_id is not None:
        stmt = stmt.where(ExamProofreading.subject_id == subject_id)
    if class_unit_id is not None:
        stmt = stmt.where(ExamProofreading.class_unit_id == class_unit_id)
    rows = db.scalars(stmt.order_by(ExamProofreading.id)).all()
    if not _is_manager(db, user):
        rows = [
            r for r in rows
            if _class_visible_to_teacher(db, user, exam, r.subject_id, r.class_unit_id)
        ]
    subjects = _subject_name_map(db, {r.subject_id for r in rows})
    classes = _class_name_map(db, {r.class_unit_id for r in rows if r.class_unit_id})
    items = [
        {
            "id": r.id, "exam_id": r.exam_id, "subject_id": r.subject_id,
            "subject_name": subjects.get(r.subject_id, ""),
            "class_unit_id": r.class_unit_id,
            "class_name": classes.get(r.class_unit_id) if r.class_unit_id else None,
            "submitted_by": r.submitted_by,
            "submitted_by_name": _display_name(db, r.submitted_by),
            "proofreader_id": r.proofreader_id,
            "proofreader_name": _display_name(db, r.proofreader_id),
            "status": r.status, "note": r.note,
        }
        for r in rows
    ]
    return items, len(items)


def proofreading_out(db: Session, row: ExamProofreading) -> dict:
    subjects = _subject_name_map(db, {row.subject_id})
    classes = _class_name_map(db, {row.class_unit_id} if row.class_unit_id else set())
    return {
        "id": row.id, "exam_id": row.exam_id, "subject_id": row.subject_id,
        "subject_name": subjects.get(row.subject_id, ""),
        "class_unit_id": row.class_unit_id,
        "class_name": classes.get(row.class_unit_id) if row.class_unit_id else None,
        "submitted_by": row.submitted_by,
        "submitted_by_name": _display_name(db, row.submitted_by),
        "proofreader_id": row.proofreader_id,
        "proofreader_name": _display_name(db, row.proofreader_id),
        "status": row.status, "note": row.note,
    }


# ── 成绩锁定(KW-37) ──────────────────────────────
def _proofreading_passed(
    db: Session, exam: Exam, subject_id: int, class_unit_id: int | None
) -> bool:
    """该范围校对是否已通过:同班级通过,或全科(空班级)通过都算。"""
    rows = db.scalars(
        select(ExamProofreading).where(
            ExamProofreading.exam_id == exam.id,
            ExamProofreading.subject_id == subject_id,
            ExamProofreading.status == "通过",
        )
    ).all()
    return any(
        r.class_unit_id is None or r.class_unit_id == class_unit_id
        for r in rows
    )


def create_lock(
    db: Session, user: User, exam: Exam, subject_id: int, class_unit_id: int | None
) -> ExamScoreLock:
    subject = db.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到科目")
    if class_unit_id is not None and db.get(ClassUnit, class_unit_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到班级")
    if not _proofreading_passed(db, exam, subject_id, class_unit_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "该范围校对尚未通过,不能锁定"
        )
    existing = db.scalar(
        select(ExamScoreLock).where(
            ExamScoreLock.exam_id == exam.id,
            ExamScoreLock.subject_id == subject_id,
            ExamScoreLock.class_unit_id == class_unit_id,
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "该范围成绩已锁定,请勿重复锁定")
    row = ExamScoreLock(
        exam_id=exam.id, subject_id=subject_id,
        class_unit_id=class_unit_id, locked_by=user.id,
    )
    db.add(row)
    db.flush()
    return row


def delete_lock(db: Session, exam: Exam, lid: int) -> None:
    row = db.get(ExamScoreLock, lid)
    if row is None or row.exam_id != exam.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到锁定记录")
    db.delete(row)
    db.flush()


def list_locks(
    db: Session, user: User, exam: Exam,
) -> tuple[list[dict], int]:
    rows = db.scalars(
        select(ExamScoreLock)
        .where(ExamScoreLock.exam_id == exam.id)
        .order_by(ExamScoreLock.id)
    ).all()
    if not _is_manager(db, user):
        rows = [
            r for r in rows
            if _class_visible_to_teacher(db, user, exam, r.subject_id, r.class_unit_id)
        ]
    subjects = _subject_name_map(db, {r.subject_id for r in rows})
    classes = _class_name_map(db, {r.class_unit_id for r in rows if r.class_unit_id})
    items = [
        {
            "id": r.id, "exam_id": r.exam_id, "subject_id": r.subject_id,
            "subject_name": subjects.get(r.subject_id, ""),
            "class_unit_id": r.class_unit_id,
            "class_name": classes.get(r.class_unit_id) if r.class_unit_id else None,
            "locked_by": r.locked_by,
            "locked_by_name": _display_name(db, r.locked_by),
            "locked_at": r.locked_at,
        }
        for r in rows
    ]
    return items, len(items)


def lock_out(db: Session, row: ExamScoreLock) -> dict:
    subjects = _subject_name_map(db, {row.subject_id})
    classes = _class_name_map(db, {row.class_unit_id} if row.class_unit_id else set())
    return {
        "id": row.id, "exam_id": row.exam_id, "subject_id": row.subject_id,
        "subject_name": subjects.get(row.subject_id, ""),
        "class_unit_id": row.class_unit_id,
        "class_name": classes.get(row.class_unit_id) if row.class_unit_id else None,
        "locked_by": row.locked_by,
        "locked_by_name": _display_name(db, row.locked_by),
        "locked_at": row.locked_at,
    }


# ── 改分审批(KW-38) ──────────────────────────────
def _require_can_request_change(
    db: Session, user: User, exam: Exam, score: ExamScore, class_unit_id: int | None
) -> None:
    """改分申请权限:教务不限;教师须是该成绩的录入人,或任教该科目+班级。"""
    if _is_manager(db, user):
        return
    if score.submitted_by is not None and score.submitted_by == user.id:
        return
    if Role.teacher.value not in user.role_names:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "只有成绩录入教师与教务可以提交改分申请")
    pairs = _teaching_pairs(db, user, exam.semester_id)
    if class_unit_id is not None and (class_unit_id, score.subject_id) in pairs:
        return
    raise HTTPException(
        status.HTTP_403_FORBIDDEN, "只能为本人所教班级、所教科目的成绩提交改分申请"
    )


def create_change_request(
    db: Session, user: User, exam: Exam, score_id: int,
    new_score: float | None, reason: str,
) -> ExamScoreChangeRequest:
    score = db.get(ExamScore, score_id)
    if score is None or score.exam_id != exam.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到该成绩")
    participants = _participants_by_id(db, exam)
    participant = participants.get(score.student_id)
    if participant is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "该学生不在本次考试参试名单中,无法改分"
        )
    if not is_score_locked(db, exam.id, score.subject_id, participant.class_unit_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "该成绩尚未锁定,直接修改即可,无需改分审批"
        )
    _require_can_request_change(db, user, exam, score, participant.class_unit_id)
    if new_score is not None:
        if new_score < 0:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "新分数不能小于 0"
            )
        # 满分上限复用第 5 批口径(考试科目满分,未设则取科目分值设置)。
        from app.services.exam_scores import full_score_for

        full = full_score_for(db, exam, score.subject_id)
        if new_score > full:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"新分数须在 0 到满分 {full:g} 之间",
            )
    existing = db.scalar(
        select(ExamScoreChangeRequest).where(
            ExamScoreChangeRequest.score_id == score.id,
            ExamScoreChangeRequest.status == "待审批",
        )
    )
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "该成绩已有待审批的改分申请,请勿重复提交"
        )
    row = ExamScoreChangeRequest(
        exam_id=exam.id, score_id=score.id, old_score=score.score,
        new_score=new_score, reason=reason, status="待审批",
        requested_by=user.id,
    )
    db.add(row)
    db.flush()
    return row


def _change_request_out(
    db: Session, row: ExamScoreChangeRequest, approvals: list[ExamScoreChangeApproval]
) -> dict:
    score = db.get(ExamScore, row.score_id)
    student_name = ""
    subject_name = ""
    if score is not None:
        student = db.get(Student, score.student_id)
        student_name = student.name if student is not None else ""
        subjects = _subject_name_map(db, {score.subject_id})
        subject_name = subjects.get(score.subject_id, "")
    return {
        "id": row.id, "exam_id": row.exam_id, "score_id": row.score_id,
        "student_name": student_name, "subject_name": subject_name,
        "old_score": row.old_score, "new_score": row.new_score,
        "reason": row.reason, "status": row.status,
        "requested_by": row.requested_by,
        "requested_by_name": _display_name(db, row.requested_by),
        "approvals": [
            {
                "level": a.level,
                "approver_name": _display_name(db, a.approver_id),
                "decision": a.decision, "note": a.note,
            }
            for a in approvals
        ],
    }


def list_change_requests(
    db: Session, user: User, exam: Exam, status_filter: str | None,
) -> tuple[list[dict], int]:
    stmt = select(ExamScoreChangeRequest).where(
        ExamScoreChangeRequest.exam_id == exam.id
    )
    if status_filter is not None:
        if status_filter not in ("待审批", "已通过", "已驳回"):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "改分申请状态只能是待审批、已通过或已驳回"
            )
        stmt = stmt.where(ExamScoreChangeRequest.status == status_filter)
    rows = db.scalars(stmt.order_by(ExamScoreChangeRequest.id)).all()
    if not _is_manager(db, user):
        participants = _participants_by_id(db, exam)
        class_ids = visible_class_ids(db, user)
        kept = []
        for r in rows:
            score = db.get(ExamScore, r.score_id)
            if score is None:
                continue
            p = participants.get(score.student_id)
            if p is None:
                continue
            if class_ids is not None and p.class_unit_id not in class_ids:
                continue
            kept.append(r)
        rows = kept
    approval_rows = db.scalars(
        select(ExamScoreChangeApproval).where(
            ExamScoreChangeApproval.request_id.in_([r.id for r in rows])
        ).order_by(ExamScoreChangeApproval.level)
    ).all() if rows else []
    by_request: dict[int, list[ExamScoreChangeApproval]] = {}
    for a in approval_rows:
        by_request.setdefault(a.request_id, []).append(a)
    items = [_change_request_out(db, r, by_request.get(r.id, [])) for r in rows]
    return items, len(items)


def change_request_out(db: Session, row: ExamScoreChangeRequest) -> dict:
    approvals = db.scalars(
        select(ExamScoreChangeApproval)
        .where(ExamScoreChangeApproval.request_id == row.id)
        .order_by(ExamScoreChangeApproval.level)
    ).all()
    return _change_request_out(db, row, approvals)


def decide_change_request(
    db: Session, user: User, exam: Exam, rid: int,
    decision: str, note: str | None,
) -> ExamScoreChangeRequest:
    """改分审批:一层时教研组长或教务一人通过即生效;两层时第一层教研组长、
    第二层教务依次通过,任一层驳回即终结;通过且层级走完后改 ExamScore 并留痕。"""
    if decision not in CHANGE_DECISIONS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "审批决定只能是通过或驳回"
        )
    row = db.get(ExamScoreChangeRequest, rid)
    if row is None or row.exam_id != exam.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到改分申请")
    if row.status != "待审批":
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"该改分申请已{row.status},不能重复审批"
        )
    setting = get_settings(db, exam)
    levels = setting.approval_levels if setting else DEFAULT_SETTINGS["approval_levels"]
    done = db.scalars(
        select(ExamScoreChangeApproval)
        .where(ExamScoreChangeApproval.request_id == row.id)
        .order_by(ExamScoreChangeApproval.level)
    ).all()
    current_level = len(done) + 1
    if current_level > levels:
        raise HTTPException(status.HTTP_409_CONFLICT, "该改分申请审批已完成")
    score = db.get(ExamScore, row.score_id)
    subject_id = score.subject_id if score is not None else 0
    if levels == 1:
        if not (
            _is_admin(user)
            or _is_academic(db, user)
            or _is_subject_leader(db, user, exam, subject_id)
        ):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "一层审批须由教研组长或教务决定"
            )
    else:
        if current_level == 1:
            if not (_is_admin(user) or _is_subject_leader(db, user, exam, subject_id)):
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN, "第一层审批只允许教研组长决定"
                )
        else:
            if not (_is_admin(user) or _is_academic(db, user)):
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN, "第二层审批只允许教务决定"
                )
    db.add(ExamScoreChangeApproval(
        request_id=row.id, level=current_level, approver_id=user.id,
        decision=decision, note=note,
    ))
    if decision == "驳回":
        row.status = "已驳回"
    elif current_level >= levels:
        row.status = "已通过"
        if score is not None:
            score.score = row.new_score
    db.flush()
    return row


# ── 发布批次(KW-39) ──────────────────────────────
def create_publish_batch(
    db: Session, user: User, exam: Exam, scope_type: str, scope_value: int,
    publish_at: datetime | None, note: str | None,
) -> ExamPublishBatch:
    if scope_type not in PUBLISH_SCOPE_TYPES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "发布范围只能是年级或班级"
        )
    if scope_type == "年级":
        grades = db.scalars(
            select(ExamGrade.grade).where(ExamGrade.exam_id == exam.id)
        ).all()
        if scope_value not in grades:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "该年级不在本次考试参试年级内"
            )
    else:
        cls = db.get(ClassUnit, scope_value)
        if cls is None or cls.semester_id != exam.semester_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "找不到该班级"
            )
        participants = _participants_by_id(db, exam)
        if not any(p.class_unit_id == scope_value for p in participants.values()):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "该班级没有参试学生,无法发布"
            )
    existing = db.scalar(
        select(ExamPublishBatch).where(
            ExamPublishBatch.exam_id == exam.id,
            ExamPublishBatch.scope_type == scope_type,
            ExamPublishBatch.scope_value == scope_value,
            ExamPublishBatch.status.in_(("待发布", "已发布")),
        )
    )
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "该范围已有待发布或已发布的批次,请先撤回再重新发布"
        )
    at = _as_aware(publish_at)
    batch_status = "已发布" if at is None or at <= _now() else "待发布"
    row = ExamPublishBatch(
        exam_id=exam.id, scope_type=scope_type, scope_value=scope_value,
        publish_at=at, status=batch_status, published_by=user.id, note=note,
    )
    db.add(row)
    db.flush()
    return row


def withdraw_publish_batch(
    db: Session, exam: Exam, bid: int, note: str | None,
) -> ExamPublishBatch:
    row = db.get(ExamPublishBatch, bid)
    if row is None or row.exam_id != exam.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到发布批次")
    if row.status == "已撤回":
        raise HTTPException(status.HTTP_409_CONFLICT, "该批次已撤回,不能重复撤回")
    row.status = "已撤回"
    if note is not None:
        row.note = note
    db.flush()
    return row


def publish_due(db: Session, exam: Exam) -> int:
    """把已到 publish_at 的待发布批次翻为已发布;供定时任务调用。"""
    rows = db.scalars(
        select(ExamPublishBatch).where(
            ExamPublishBatch.exam_id == exam.id,
            ExamPublishBatch.status == "待发布",
            ExamPublishBatch.publish_at.is_not(None),
        )
    ).all()
    now = _now()
    count = 0
    for row in rows:
        at = _as_aware(row.publish_at)
        if at is not None and at <= now:
            row.status = "已发布"
            count += 1
    db.flush()
    return count


def is_score_published(
    db: Session, exam_id: int, grade: int, class_unit_id: int
) -> bool:
    """判定某年级某班成绩是否已发布,供第 7~8 批调用。

    已发布批次覆盖即算已发布:年级批次按 scope_value 等于年级覆盖;
    班级批次按 scope_value 等于班级 id 覆盖。待发布与已撤回不算。
    批次已发布即视为已发布。
    """
    rows = db.scalars(
        select(ExamPublishBatch).where(
            ExamPublishBatch.exam_id == exam_id,
            ExamPublishBatch.status == "已发布",
        )
    ).all()
    return any(
        (r.scope_type == "年级" and r.scope_value == grade)
        or (r.scope_type == "班级" and r.scope_value == class_unit_id)
        for r in rows
    )


def publish_status(db: Session, exam: Exam) -> dict:
    rows = db.scalars(
        select(ExamPublishBatch)
        .where(ExamPublishBatch.exam_id == exam.id)
        .order_by(ExamPublishBatch.id)
    ).all()
    batches = [
        {
            "scope_type": r.scope_type, "scope_value": r.scope_value,
            "status": r.status, "publish_at": r.publish_at,
        }
        for r in rows
    ]
    grades = db.scalars(
        select(ExamGrade.grade).where(ExamGrade.exam_id == exam.id)
    ).all()
    published = [r for r in rows if r.status == "已发布"]
    covered: set[int] = set()
    for r in published:
        if r.scope_type == "年级":
            covered.add(r.scope_value)
        else:
            cls = db.get(ClassUnit, r.scope_value)
            if cls is not None:
                covered.add(cls.grade)
    all_published = bool(rows) and not any(
        r.status == "待发布" for r in rows
    ) and set(grades) <= covered
    return {"exam_id": exam.id, "batches": batches, "all_published": all_published}


def list_publish_batches(
    db: Session, user: User, exam: Exam,
) -> tuple[list[dict], int]:
    rows = db.scalars(
        select(ExamPublishBatch)
        .where(ExamPublishBatch.exam_id == exam.id)
        .order_by(ExamPublishBatch.id)
    ).all()
    if not _is_manager(db, user):
        grade_set = None
        from app.services.exam_scopes import visible_grade_set

        grade_set = visible_grade_set(db, user)
        class_ids = visible_class_ids(db, user)
        kept = []
        for r in rows:
            if r.scope_type == "年级":
                if grade_set is None or r.scope_value in grade_set:
                    kept.append(r)
            else:
                if class_ids is None or r.scope_value in class_ids:
                    kept.append(r)
        rows = kept
    items = [
        {
            "id": r.id, "exam_id": r.exam_id, "scope_type": r.scope_type,
            "scope_value": r.scope_value, "publish_at": r.publish_at,
            "status": r.status, "published_by": r.published_by,
            "published_by_name": _display_name(db, r.published_by),
            "note": r.note,
        }
        for r in rows
    ]
    return items, len(items)


def publish_batch_out(db: Session, row: ExamPublishBatch) -> dict:
    return {
        "id": row.id, "exam_id": row.exam_id, "scope_type": row.scope_type,
        "scope_value": row.scope_value, "publish_at": row.publish_at,
        "status": row.status, "published_by": row.published_by,
        "published_by_name": _display_name(db, row.published_by),
        "note": row.note,
    }


# ── 成绩异议(KW-40) ──────────────────────────────
def _raised_by_role(db: Session, user: User) -> str:
    if _is_admin(user):
        return "管理员"
    if _is_academic(db, user):
        return "教务"
    return "教师"


def create_objection(
    db: Session, user: User, exam: Exam, score_id: int, content: str,
) -> ExamObjection:
    setting = get_settings(db, exam)
    open_flag = setting.objection_open if setting else DEFAULT_SETTINGS["objection_open"]
    if not open_flag:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "本考试未开放成绩异议入口"
        )
    score = db.get(ExamScore, score_id)
    if score is None or score.exam_id != exam.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到该成绩")
    row = ExamObjection(
        exam_id=exam.id, score_id=score.id, student_id=score.student_id,
        content=content, status="待复核",
        raised_by_role=_raised_by_role(db, user),
    )
    db.add(row)
    db.flush()
    return row


def _require_can_handle_objection(
    db: Session, user: User, exam: Exam, objection: ExamObjection,
) -> None:
    """异议回复/关闭权限:教务不限;任课教师须任教该成绩的科目+班级。"""
    if _is_manager(db, user):
        return
    score = db.get(ExamScore, objection.score_id)
    if score is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权处理该异议")
    participants = _participants_by_id(db, exam)
    participant = participants.get(score.student_id)
    if participant is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权处理该异议")
    if Role.teacher.value not in user.role_names:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "只有任课教师与教务可以处理异议")
    pairs = _teaching_pairs(db, user, exam.semester_id)
    if (participant.class_unit_id, score.subject_id) not in pairs:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "只能处理本人所教班级、所教科目的异议"
        )


def reply_objection(
    db: Session, user: User, exam: Exam, oid: int, reply: str,
) -> ExamObjection:
    row = db.get(ExamObjection, oid)
    if row is None or row.exam_id != exam.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到异议记录")
    if row.status != "待复核":
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"该异议已{row.status},不能重复回复"
        )
    _require_can_handle_objection(db, user, exam, row)
    row.reply = reply
    row.replied_by = user.id
    row.status = "已回复"
    db.flush()
    return row


def close_objection(
    db: Session, user: User, exam: Exam, oid: int,
) -> ExamObjection:
    row = db.get(ExamObjection, oid)
    if row is None or row.exam_id != exam.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到异议记录")
    if row.status != "已回复":
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"该异议当前为{row.status},只有已回复的异议可以关闭"
        )
    _require_can_handle_objection(db, user, exam, row)
    row.status = "已关闭"
    db.flush()
    return row


def list_objections(
    db: Session, user: User, exam: Exam, status_filter: str | None,
) -> tuple[list[dict], int]:
    stmt = select(ExamObjection).where(ExamObjection.exam_id == exam.id)
    if status_filter is not None:
        if status_filter not in ("待复核", "已回复", "已关闭"):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "异议状态只能是待复核、已回复或已关闭"
            )
        stmt = stmt.where(ExamObjection.status == status_filter)
    rows = db.scalars(stmt.order_by(ExamObjection.id)).all()
    if not _is_manager(db, user):
        participants = _participants_by_id(db, exam)
        class_ids = visible_class_ids(db, user)
        kept = []
        for r in rows:
            p = participants.get(r.student_id)
            if p is None:
                continue
            if class_ids is not None and p.class_unit_id not in class_ids:
                continue
            kept.append(r)
        rows = kept
    subjects: dict[int, str] = {}
    items = []
    for r in rows:
        score = db.get(ExamScore, r.score_id)
        student = db.get(Student, r.student_id)
        subject_name = ""
        if score is not None:
            if score.subject_id not in subjects:
                subjects.update(_subject_name_map(db, {score.subject_id}))
            subject_name = subjects.get(score.subject_id, "")
        items.append({
            "id": r.id, "exam_id": r.exam_id, "score_id": r.score_id,
            "student_id": r.student_id,
            "student_name": student.name if student is not None else "",
            "subject_name": subject_name, "content": r.content,
            "status": r.status, "reply": r.reply,
            "replied_by": r.replied_by,
            "replied_by_name": _display_name(db, r.replied_by),
            "raised_by_role": r.raised_by_role,
        })
    return items, len(items)


def objection_out(db: Session, row: ExamObjection) -> dict:
    score = db.get(ExamScore, row.score_id)
    student = db.get(Student, row.student_id)
    subject_name = ""
    if score is not None:
        subject_name = _subject_name_map(db, {score.subject_id}).get(
            score.subject_id, ""
        )
    return {
        "id": row.id, "exam_id": row.exam_id, "score_id": row.score_id,
        "student_id": row.student_id,
        "student_name": student.name if student is not None else "",
        "subject_name": subject_name, "content": row.content,
        "status": row.status, "reply": row.reply,
        "replied_by": row.replied_by,
        "replied_by_name": _display_name(db, row.replied_by),
        "raised_by_role": row.raised_by_role,
    }
