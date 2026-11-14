"""今日调代课看板与调代课日志(M4-4)。

看板/日志是行政的当日排课与历史查询工具,限年级主任/教务主任。
例外:看板带 mine=true 时教师可看与自己有关的条目(见 daily_board)。
"""

from dataclasses import asdict
from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.auth import get_active_user, require_roles
from app.core.db import get_db
from app.models.semester import Semester
from app.models.user import Role, User
from app.schemas.substitution_log import DailyBoardOut, LogEntryOut, PatrolSheetsOut
from app.services import patrol_sheets, patrol_xlsx
from app.services import settings as app_settings
from app.services import substitution_log as log_service
from app.services.teachers import current_teacher

router = APIRouter(tags=["substitution-log"])

viewer = require_roles(Role.director)


def _entry_out(e: log_service.LogEntry) -> LogEntryOut:
    return LogEntryOut(**{f: getattr(e, f) for f in LogEntryOut.model_fields})


def _get_semester(db: Session, semester_id: int) -> Semester:
    sem = db.get(Semester, semester_id)
    if sem is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到学期")
    return sem


@router.get("/daily-board", response_model=DailyBoardOut)
def daily_board(
    semester_id: int = Query(...),
    on: date | None = Query(default=None, description="看板日期,默认为学校时区的今天"),
    mine: bool = Query(default=False, description="只看与我有关的调代课"),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """某一天全校的调代课异动(默认今天);无异动则 entries 为空。

    不带 mine 时只限管理员/教务主任(全校口径,默认行为不变)。
    mine=true 时教师只看与自己有关的:我是缺课的原任教师,
    或我是接手代课的教师,两个方向都算;未绑定教师主档的账号看到空看板。
    """
    names = user.role_names
    is_manager = Role.admin.value in names or Role.director.value in names
    if not is_manager and not (Role.teacher.value in names and mine):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="权限不足")
    sem = _get_semester(db, semester_id)
    day = on or log_service.school_today()
    entries = log_service.daily_board(db, semester_id, day)
    if mine:
        me = current_teacher(db, user, semester_id)
        if me is None:
            entries = []
        else:
            entries = [
                e for e in entries
                if e.absent_teacher_id == me.id or e.handler_teacher_id == me.id
            ]
    return DailyBoardOut(
        date=day,
        weekday=day.isoweekday(),
        school_name=app_settings.school_name(db),
        semester_label=sem.label,
        entries=[_entry_out(e) for e in entries],
    )


@router.get("/patrol-sheets", response_model=PatrolSheetsOut)
def get_patrol_sheets(
    semester_id: int = Query(...),
    date_from: date | None = Query(default=None, description="默认为学校时区的今天"),
    date_to: date | None = Query(default=None, description="默认同 date_from(只印一天)"),
    grade: int | None = Query(default=None, description="只印该年级,不传则印全部年级"),
    db: Session = Depends(get_db),
    _: User = Depends(viewer),
):
    """课堂巡视情况记录表的打印资料:已发布课表叠上当天的调代课,一天分上午/下午各一张。"""
    _get_semester(db, semester_id)
    start = date_from or log_service.school_today()
    try:
        sheets = patrol_sheets.build(db, semester_id, start, date_to or start, grade=grade)
    except patrol_sheets.PatrolError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return PatrolSheetsOut.model_validate(asdict(sheets))


@router.get("/patrol-sheets.xlsx")
def export_patrol_sheets(
    semester_id: int = Query(...),
    date_from: date | None = Query(default=None, description="默认为学校时区的今天"),
    date_to: date | None = Query(default=None, description="默认同 date_from(只导出一天)"),
    grade: int | None = Query(default=None, description="只导出该年级,不传则导出全部年级"),
    db: Session = Depends(get_db),
    _: User = Depends(viewer),
) -> Response:
    """课堂巡视情况记录表的 Excel 版:内容与打印页相同,给学校下载后自行增减栏位、填巡视人员。"""
    _get_semester(db, semester_id)
    start = date_from or log_service.school_today()
    end = date_to or start
    try:
        sheets = patrol_sheets.build(db, semester_id, start, end, grade=grade)
    except patrol_sheets.PatrolError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    name = f"课堂巡视情况记录表_{start:%Y-%m-%d}" + (f"_{end:%m-%d}" if end != start else "")
    # 中文档名以 RFC 5987 filename* 表达;filename 提供 ASCII 后备(与课表导出一致)
    disposition = f"attachment; filename=\"patrol.xlsx\"; filename*=UTF-8''{quote(name)}.xlsx"
    return Response(
        content=patrol_xlsx.to_xlsx(sheets),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": disposition},
    )


@router.get("/substitution-log", response_model=list[LogEntryOut])
def substitution_log(
    semester_id: int = Query(...),
    teacher_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    leave_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(viewer),
):
    """调代课历史查询:依教师(缺课或代课)、日期区间、假别筛选。"""
    _get_semester(db, semester_id)
    entries = log_service.query(
        db, semester_id,
        date_from=date_from, date_to=date_to,
        teacher_id=teacher_id, leave_type=leave_type,
    )
    return [_entry_out(e) for e in entries]
