"""成绩单与查询 API(KW-52~56):班级成绩单、个人成绩单、教师端查询、
学生/家长自助查询、学生/家长账号开通与管理、成绩归档表导出。

挂在 /api/exam 下,路由里写相对路径,与已有七个 exam 相关 router 共用同一前缀。
读接口按可见范围过滤;学生/家长自助接口只允许 student/parent 角色本人;
账号开通与成绩册导出只允许 admin/director。所有写操作记审计。
"""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.auth import get_active_user, require_roles
from app.core.db import get_db
from app.models.user import Role, User
from app.schemas.exam_reports import (
    AccountListOut,
    ClassReportCardOut,
    ProvisionOut,
    ReportSettingOut,
    ReportSettingPut,
    ResetPasswordIn,
    StudentReportCardOut,
    TeacherScoreListOut,
)
from app.services import exam_reports as svc
from app.services.exam import get_exam, require_exam_visible
from app.services.exam_audit import log_exam_action
from app.services.exam_scopes import can_manage_students

router = APIRouter(tags=["exam_reports"])

writer = require_roles(Role.admin, Role.director)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _require_can_manage(db: Session, user: User) -> None:
    if not can_manage_students(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "权限不足")


def _exam_or_404(db: Session, exam_id: int):
    return get_exam(db, exam_id)


# ── 成绩单显示设置(KW-53) ──────────────────────────────
@router.get("/exams/{exam_id}/report-settings", response_model=ReportSettingOut)
def get_report_settings(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    row = svc.get_report_setting(db, exam)
    return ReportSettingOut(**svc.report_setting_out(exam, row))


@router.put("/exams/{exam_id}/report-settings", response_model=ReportSettingOut)
def put_report_settings(
    exam_id: int,
    body: ReportSettingPut,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    row = svc.upsert_report_setting(
        db, exam,
        body.parent_show_grade_rank, body.parent_show_class_rank,
    )
    log_exam_action(
        db, user, "exam_report_settings_update",
        target_type="exam", target_id=exam.id,
        detail=(
            f"更新考试{exam.name}成绩单设置"
            f"(家长版显示年级排名{row.parent_show_grade_rank},"
            f"显示班级排名{row.parent_show_class_rank})"
        ),
    )
    db.commit()
    return ReportSettingOut(**svc.report_setting_out(exam, row))


# ── KW-52 班级成绩单 ──────────────────────────────
@router.get("/exams/{exam_id}/report-cards/class", response_model=ClassReportCardOut)
def get_class_report_card(
    exam_id: int,
    class_unit_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    return ClassReportCardOut(**svc.class_report_card(db, user, exam, class_unit_id))


# ── KW-53 个人成绩单(教师/教务完整版) ──────────────────────────────
@router.get("/exams/{exam_id}/report-cards/student", response_model=StudentReportCardOut)
def get_student_report_card(
    exam_id: int,
    student_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    return StudentReportCardOut(**svc.student_report_card(db, user, exam, student_id))


# ── KW-54 教师端成绩查询 ──────────────────────────────
@router.get("/exams/{exam_id}/teacher-scores", response_model=TeacherScoreListOut)
def get_teacher_scores(
    exam_id: int,
    subject_id: int | None = None,
    class_unit_id: int | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    return TeacherScoreListOut(
        **svc.teacher_scores(db, user, exam, subject_id, class_unit_id, q)
    )


# ── KW-55 学生/家长自助查询 ──────────────────────────────
@router.get("/my-scores")
def get_my_scores(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    return svc.my_scores(db, user, exam)


@router.get("/my-report-card")
def get_my_report_card(
    exam_id: int,
    student_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    return svc.my_report_card(db, user, exam, student_id)


# ── KW-55 账号开通与管理 ──────────────────────────────
@router.post("/accounts/provision", response_model=ProvisionOut)
def provision_accounts(
    semester_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    result = svc.provision_accounts(db, semester_id)
    log_exam_action(
        db, user, "exam_account_provision",
        target_type="semester", target_id=semester_id,
        detail=(
            f"按学期开通学生/家长账号:"
            f"新建学生账号{result['students_created']}个,"
            f"新建家长账号{result['parents_created']}个"
        ),
    )
    db.commit()
    return ProvisionOut(**result)


@router.get("/accounts", response_model=AccountListOut)
def list_accounts(
    semester_id: int | None = None,
    role: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    return AccountListOut(**svc.list_accounts(db, semester_id, role, q))


@router.post("/accounts/{user_id}/reset-password")
def reset_account_password(
    user_id: int,
    body: ResetPasswordIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    target = svc.reset_account_password(db, user_id, body.new_password)
    log_exam_action(
        db, user, "exam_account_password_reset",
        target_type="user", target_id=target.id,
        detail=f"重置学生/家长账号{target.username}口令(重置后须改密)",
    )
    db.commit()
    return {"status": "ok"}


# ── KW-56 成绩归档表导出 ──────────────────────────────
@router.get("/exams/{exam_id}/grade-book/export")
def export_grade_book(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    content = svc.build_grade_book(db, exam)
    log_exam_action(
        db, user, "exam_grade_book_export",
        target_type="exam", target_id=exam.id,
        detail=f"导出考试{exam.name}完整成绩册",
    )
    db.commit()
    return Response(
        content=content,
        media_type=XLSX_MIME,
        headers={"Content-Disposition": 'attachment; filename="grade_book.xlsx"'},
    )
