"""成绩单与查询 API(KW-52~54/56):班级成绩单、个人成绩单、教师端查询、
成绩归档表导出。

挂在 /api/exam 下,路由里写相对路径,与已有七个 exam 相关 router 共用同一前缀。
读接口按可见范围过滤;成绩册导出只允许 admin/director。所有写操作记审计。
只有教师与教务可看成绩,不设学生/家长账号与自助查询。
"""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.auth import get_active_user, require_roles
from app.core.db import get_db
from app.models.user import Role, User
from app.schemas.exam_reports import (
    ClassReportCardOut,
    StudentReportCardOut,
    TeacherScoreListOut,
)
from app.services import exam_reports as svc
from app.services.exam import get_exam
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
