"""教师实际上课课时查询(仪表板 + 管理员查询/打印共用)。

scope: month = 本月(到今天)、week = 本周一~今天、semester = 学期(到今天)、
custom = 自选日期(须给 date_from/date_to)。未来日期不计入「已上」。
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import get_active_user, require_roles
from app.core.db import get_db
from app.models.semester import Semester
from app.models.user import Role, User
from app.schemas.teaching_hours import TeacherHoursOut, TeachingHoursOut
from app.services import teaching_hours as hours_service
from app.services.substitution_log import school_today
from app.services.teachers import current_teacher

router = APIRouter(tags=["teaching-hours"])

viewer = require_roles(Role.director)


def _get_semester(db: Session, semester_id: int) -> Semester:
    sem = db.get(Semester, semester_id)
    if sem is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到学期")
    return sem


def _resolve_range(
    sem: Semester, scope: str, date_from: date | None, date_to: date | None
) -> tuple[date, date]:
    today = school_today()
    if scope == "month":
        return today.replace(day=1), today
    if scope == "week":
        monday = today - timedelta(days=today.weekday())
        return monday, today
    if scope == "semester":
        if sem.start_date is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "学期尚未设定起讫日期")
        return sem.start_date, sem.end_date or today
    if scope == "custom":
        if date_from is None or date_to is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "自选日期须给起讫日")
        if date_to < date_from:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "讫日不可早于起日")
        return date_from, date_to
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "scope 须为 month/week/semester/custom")


def _out(
    sem: Semester, start: date, end: date, rows: list[hours_service.TeacherHours],
    eff_start: date, eff_end: date,
) -> TeachingHoursOut:
    return TeachingHoursOut(
        semester_id=sem.id,
        date_from=start.isoformat(), date_to=end.isoformat(),
        effective_from=eff_start.isoformat(), effective_to=eff_end.isoformat(),
        teachers=[
            TeacherHoursOut(
                teacher_id=r.teacher_id, teacher_name=r.teacher_name, total=r.total,
                by_grade={str(g): n for g, n in sorted(r.by_grade.items())},
                substitute_total=r.substitute_total,
            )
            for r in rows
        ],
        total_periods=sum(r.total for r in rows),
    )


@router.get("/teaching-hours", response_model=TeachingHoursOut)
def teaching_hours(
    semester_id: int = Query(...),
    scope: str = Query("semester"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    teacher_id: int | None = Query(default=None),
    grade: int | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(viewer),
):
    """管理员/主任查全校(可筛单一教师、单一年级)。"""
    sem = _get_semester(db, semester_id)
    start, end = _resolve_range(sem, scope, date_from, date_to)
    rows, eff_start, eff_end = hours_service.compute(
        db, sem, start, end, teacher_id=teacher_id, grade=grade)
    return _out(sem, start, end, rows, eff_start, eff_end)


@router.get("/teaching-hours/mine", response_model=TeachingHoursOut)
def my_teaching_hours(
    semester_id: int = Query(...),
    scope: str = Query("semester"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """教师查自己的课时。未绑定教师主档者回空表。"""
    sem = _get_semester(db, semester_id)
    start, end = _resolve_range(sem, scope, date_from, date_to)
    me = current_teacher(db, user, semester_id)
    if me is None:
        return TeachingHoursOut(
            semester_id=sem.id,
            date_from=start.isoformat(), date_to=end.isoformat(),
            effective_from=start.isoformat(), effective_to=end.isoformat(),
        )
    rows, eff_start, eff_end = hours_service.compute(
        db, sem, start, end, teacher_id=me.id)
    return _out(sem, start, end, rows, eff_start, eff_end)
