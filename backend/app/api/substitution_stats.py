"""代课课时月结统计(M4-5)。

主任/主任看全校并可导出 Excel;教师只能查自己的明细(`/mine`)。
范围查询(`/range`)供统计中心本月/本学期/自定义三档用;月结与导出仍走年月。
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.auth import get_active_user, require_roles
from app.core.db import get_db
from app.models.semester import Semester
from app.models.user import Role, User
from app.schemas.substitution_stats import (
    MonthlyReportOut,
    RangeReportOut,
    StatDetailOut,
    TeacherSummaryOut,
)
from app.services import substitution_stats as stats_service
from app.services.teachers import current_teacher

router = APIRouter(tags=["substitution-stats"])

viewer = require_roles(Role.director)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _summaries_out(report) -> list[TeacherSummaryOut]:
    return [
        TeacherSummaryOut(**{f: getattr(s, f) for f in TeacherSummaryOut.model_fields})
        for s in report.summaries
    ]


def _details_out(report) -> list[StatDetailOut]:
    return [
        StatDetailOut(**{f: getattr(d, f) for f in StatDetailOut.model_fields})
        for d in report.details
    ]


def _report_out(report: stats_service.MonthlyReport) -> MonthlyReportOut:
    return MonthlyReportOut(
        year=report.year, month=report.month,
        summaries=_summaries_out(report), details=_details_out(report),
    )


def _get_semester(db: Session, semester_id: int) -> Semester:
    sem = db.get(Semester, semester_id)
    if sem is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到学期")
    return sem


def _check_month(month: int) -> None:
    if not 1 <= month <= 12:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "月份须为 1~12")


@router.get("/substitution-stats", response_model=MonthlyReportOut)
def substitution_stats(
    semester_id: int = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    teacher_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(viewer),
):
    """某月代课课时统计(全校,可筛单一教师)。"""
    _get_semester(db, semester_id)
    _check_month(month)
    report = stats_service.monthly_report(db, semester_id, year, month, teacher_id=teacher_id)
    return _report_out(report)


@router.get("/substitution-stats/mine", response_model=MonthlyReportOut)
def my_substitution_stats(
    semester_id: int = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """教师查自己的代课明细。未绑定教师主档者回空报表。"""
    _get_semester(db, semester_id)
    _check_month(month)
    me = current_teacher(db, user, semester_id)
    if me is None:
        return MonthlyReportOut(year=year, month=month)
    report = stats_service.monthly_report(db, semester_id, year, month, teacher_id=me.id)
    return _report_out(report)


@router.get("/substitution-stats/range", response_model=RangeReportOut)
def substitution_stats_range(
    semester_id: int = Query(...),
    date_from: date = Query(...),
    date_to: date = Query(...),
    teacher_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(viewer),
):
    """[date_from, date_to] 闭区间的代课课时统计(全校,可筛单一教师)。"""
    _get_semester(db, semester_id)
    if date_to < date_from:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "讫日不可早于起日")
    report = stats_service.range_report(db, semester_id, date_from, date_to, teacher_id=teacher_id)
    return RangeReportOut(
        date_from=report.date_from, date_to=report.date_to,
        summaries=_summaries_out(report), details=_details_out(report),
    )


@router.get("/substitution-stats/export")
def export_substitution_stats(
    semester_id: int = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    teacher_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(viewer),
) -> Response:
    """导出某月代课课时 Excel(汇总 + 明细两张表)。"""
    _get_semester(db, semester_id)
    _check_month(month)
    report = stats_service.monthly_report(db, semester_id, year, month, teacher_id=teacher_id)
    data = stats_service.build_workbook(report)
    filename = f"substitution_hours_{year}{month:02d}.xlsx"
    return Response(
        content=data,
        media_type=XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
