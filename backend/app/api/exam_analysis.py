"""成绩分析 API(KW-41~51):分析设置、科目阈值、汇总、排名、分段、临界生、
目标生、进退步、质量对比、个人趋势、等第转换、报表包。

挂在 /api/exam 下,路由里写相对路径,与已有六个 exam 相关 router 共用同一前缀。
读接口按可见范围过滤;质量对比仅管理角色;写操作只允许 admin/director,
并记审计。
"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.auth import get_active_user, require_roles
from app.core.db import get_db
from app.models.user import Role, User
from app.schemas.exam_analysis import (
    AnalysisSettingsOut,
    AnalysisSettingsPut,
    AnalysisSummaryOut,
    CriticalListOut,
    GradeBandListOut,
    GradeBandPut,
    GradeDistributionOut,
    ProgressListOut,
    QualityCompareOut,
    RankingListOut,
    SegmentListOut,
    SubjectThresholdListOut,
    SubjectThresholdPut,
    TargetStudentIn,
    TargetStudentListOut,
    TargetStudentOut,
    TargetTrackingListOut,
    TrendOut,
)
from app.services import exam_analysis as svc
from app.services.exam import get_exam, require_exam_visible
from app.services.exam_audit import log_exam_action
from app.services.exam_scopes import can_manage_students

router = APIRouter(tags=["exam_analysis"])

writer = require_roles(Role.admin, Role.director)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _require_can_manage(db: Session, user: User) -> None:
    if not can_manage_students(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "权限不足")


def _exam_or_404(db: Session, exam_id: int):
    return get_exam(db, exam_id)


# ── 分析设置 ──────────────────────────────
@router.get("/exams/{exam_id}/analysis-settings", response_model=AnalysisSettingsOut)
def get_analysis_settings(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    row = svc.get_analysis_settings(db, exam)
    return AnalysisSettingsOut(**svc.analysis_settings_out(exam, row))


@router.put("/exams/{exam_id}/analysis-settings", response_model=AnalysisSettingsOut)
def put_analysis_settings(
    exam_id: int,
    body: AnalysisSettingsPut,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    row = svc.upsert_analysis_settings(
        db, exam, body.rank_tie_rule, body.segment_size,
        body.critical_total_line, body.critical_margin,
        body.subject_critical_margin,
    )
    log_exam_action(
        db, user, "exam_analysis_settings_update",
        target_type="exam", target_id=exam.id,
        detail=f"更新考试{exam.name}成绩分析设置(并列规则{row.rank_tie_rule},分段{row.segment_size}分)",
    )
    db.commit()
    return AnalysisSettingsOut(**svc.analysis_settings_out(exam, row))


# ── 科目阈值覆盖 ──────────────────────────────
@router.get("/exams/{exam_id}/subject-thresholds", response_model=SubjectThresholdListOut)
def list_subject_thresholds(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    return SubjectThresholdListOut(items=svc.list_thresholds(db, exam))


@router.put("/exams/{exam_id}/subject-thresholds", response_model=SubjectThresholdListOut)
def put_subject_thresholds(
    exam_id: int,
    body: SubjectThresholdPut,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    items = svc.replace_thresholds(db, exam, [i.model_dump() for i in body.items])
    log_exam_action(
        db, user, "exam_subject_threshold_update",
        target_type="exam", target_id=exam.id,
        detail=f"更新考试{exam.name}科目及格优秀线覆盖{len(items)}科",
    )
    db.commit()
    return SubjectThresholdListOut(items=items)


# ── KW-41 汇总 ──────────────────────────────
@router.get("/exams/{exam_id}/analysis/summary", response_model=AnalysisSummaryOut)
def get_analysis_summary(
    exam_id: int,
    scope: str = "grade",
    grade: int | None = None,
    class_unit_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    return AnalysisSummaryOut(
        **svc.analysis_summary(db, user, exam, scope, grade, class_unit_id)
    )


# ── KW-42 排名 ──────────────────────────────
@router.get("/exams/{exam_id}/analysis/rankings", response_model=RankingListOut)
def get_analysis_rankings(
    exam_id: int,
    scope: str = "grade",
    subject_id: int | None = None,
    grade: int | None = None,
    class_unit_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    return RankingListOut(
        **svc.analysis_rankings(db, user, exam, scope, subject_id, grade, class_unit_id)
    )


# ── KW-44 分数段分布 ──────────────────────────────
@router.get("/exams/{exam_id}/analysis/segments", response_model=SegmentListOut)
def get_analysis_segments(
    exam_id: int,
    subject_id: int | None = None,
    scope: str = "grade",
    grade: int | None = None,
    class_unit_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    return SegmentListOut(
        **svc.analysis_segments(db, user, exam, subject_id, scope, grade, class_unit_id)
    )


# ── KW-45 临界生 ──────────────────────────────
@router.get("/exams/{exam_id}/analysis/critical", response_model=CriticalListOut)
def get_analysis_critical(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    return CriticalListOut(**svc.analysis_critical(db, user, exam))


# ── KW-46 目标生 ──────────────────────────────
@router.get("/exams/{exam_id}/target-students", response_model=TargetStudentListOut)
def list_target_students(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    return TargetStudentListOut(items=svc.list_target_students(db, user, exam))


@router.post("/exams/{exam_id}/target-students", response_model=TargetStudentOut, status_code=status.HTTP_201_CREATED)
def create_target_student(
    exam_id: int,
    body: TargetStudentIn,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    row = svc.create_target_student(
        db, exam, body.student_id, body.target_total, body.note,
    )
    items = svc.list_target_students(db, user, exam)
    out = next(i for i in items if i["id"] == row.id)
    log_exam_action(
        db, user, "exam_target_student_create",
        target_type="exam_target_student", target_id=row.id,
        detail=f"考试{exam.name}新增目标生{out['student_name']}",
    )
    db.commit()
    return TargetStudentOut(**out)


@router.delete("/exams/{exam_id}/target-students/{tid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_target_student(
    exam_id: int,
    tid: int,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    svc.delete_target_student(db, exam, tid)
    log_exam_action(
        db, user, "exam_target_student_delete",
        target_type="exam_target_student", target_id=tid,
        detail=f"考试{exam.name}删除目标生",
    )
    db.commit()


@router.get("/exams/{exam_id}/analysis/target-tracking", response_model=TargetTrackingListOut)
def get_target_tracking(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    return TargetTrackingListOut(**svc.target_tracking(db, user, exam))


# ── KW-47 进退步 ──────────────────────────────
@router.get("/exams/{exam_id}/analysis/progress", response_model=ProgressListOut)
def get_analysis_progress(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    return ProgressListOut(**svc.analysis_progress(db, user, exam))


# ── KW-48 质量对比 ──────────────────────────────
@router.get("/exams/{exam_id}/analysis/quality-compare", response_model=QualityCompareOut)
def get_quality_compare(
    exam_id: int,
    grade: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    svc.require_quality_compare_visible(db, user, exam, grade)
    return QualityCompareOut(**svc.quality_compare(db, user, exam, grade))


# ── KW-49 个人趋势 ──────────────────────────────
@router.get("/exams/{exam_id}/analysis/trend", response_model=TrendOut)
def get_student_trend(
    exam_id: int,
    student_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    return TrendOut(**svc.student_trend(db, user, exam, student_id))


# ── KW-50 等第 ──────────────────────────────
@router.get("/exams/{exam_id}/grade-bands", response_model=GradeBandListOut)
def list_grade_bands(
    exam_id: int,
    subject_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    return GradeBandListOut(items=svc.list_grade_bands(db, exam, subject_id))


@router.put("/exams/{exam_id}/grade-bands", response_model=GradeBandListOut)
def put_grade_bands(
    exam_id: int,
    body: GradeBandPut,
    db: Session = Depends(get_db),
    user: User = Depends(writer),
):
    _require_can_manage(db, user)
    exam = _exam_or_404(db, exam_id)
    items = svc.replace_grade_bands(db, exam, [i.model_dump() for i in body.items])
    log_exam_action(
        db, user, "exam_grade_band_update",
        target_type="exam", target_id=exam.id,
        detail=f"更新考试{exam.name}等第档{len(items)}档",
    )
    db.commit()
    return GradeBandListOut(items=items)


@router.get("/exams/{exam_id}/analysis/grade-distribution", response_model=GradeDistributionOut)
def get_grade_distribution(
    exam_id: int,
    subject_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    return GradeDistributionOut(
        **svc.grade_distribution(db, user, exam, subject_id)
    )


# ── KW-51 报表包 ──────────────────────────────
@router.get("/exams/{exam_id}/analysis/report-pack")
def get_report_pack(
    exam_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    exam = _exam_or_404(db, exam_id)
    require_exam_visible(db, user, exam)
    data = svc.build_report_pack(db, user, exam)
    log_exam_action(
        db, user, "exam_report_pack_export",
        target_type="exam", target_id=exam.id,
        detail=f"导出考试{exam.name}质量分析会报表包",
    )
    db.commit()
    filename = f"{exam.name}质量分析会报表包.xlsx"
    quoted = quote(filename)
    return Response(
        content=data,
        media_type=XLSX_MIME,
        headers={
            "Content-Disposition": (
                f'attachment; filename="report_pack.xlsx"; '
                f"filename*=UTF-8''{quoted}"
            )
        },
    )
