"""校历活动 API(批次 #4)。

权限:读取 = 所有已登录且完成改密者(get_active_user);
写入 = admin / director(require_roles,admin 一律放行)。
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import get_active_user, require_roles
from app.core.db import get_db
from app.models.basedata import ClassUnit
from app.models.calendar import SchoolCalendarEvent
from app.models.semester import Semester
from app.models.user import Role, User
from app.schemas.calendar import CalendarEventCreate, CalendarEventOut, CalendarEventUpdate

router = APIRouter(tags=["calendar"])

editor = require_roles(Role.director)


def _get_semester(db: Session, semester_id: int) -> Semester:
    semester = db.get(Semester, semester_id)
    if semester is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到学期")
    return semester


def _get_event(db: Session, event_id: int) -> SchoolCalendarEvent:
    event = db.get(SchoolCalendarEvent, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到校历活动")
    return event


def _validate_scope(
    db: Session, semester_id: int, scope_type: str, scope_id: int | None
) -> int | None:
    """回传规范化后的 scope_id(school 一律 None);不合法回 400。"""
    if scope_type == "school":
        return None
    if scope_type == "grade":
        if scope_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "年级范围必须提供 scope_id(年级)")
        return scope_id
    if scope_type == "class":
        if scope_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "班级范围必须提供 scope_id(班级 id)")
        cls = db.get(ClassUnit, scope_id)
        if cls is None or cls.semester_id != semester_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "scope_id 不是该学期存在的班级"
            )
        return scope_id
    raise HTTPException(status.HTTP_400_BAD_REQUEST, f"未知的范围类型:{scope_type}")


def _validate_merged(
    start_date: date, end_date: date,
    period_start: int | None, period_end: int | None,
) -> None:
    if end_date < start_date:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "结束日期不可早于开始日期"
        )
    if (period_start is None) != (period_end is None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "period_start 与 period_end 必须成对提供"
        )
    if period_start is not None and period_end is not None:
        if period_start < 1 or period_end < 1 or period_start > period_end:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "节次范围不合法"
            )


class WorkdayOut(BaseModel):
    date: date
    title: str
    has_copy: bool  # 当天已有已发布单次特殊日规则(即已复制课表)


@router.get("/calendar-events/workdays", response_model=list[WorkdayOut])
def list_workdays(
    semester_id: int = Query(...),
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
    _: User = Depends(get_active_user),
):
    """调休上班日清单(国家接口同步,note=WORKDAY_NOTE):是否已复制课表看当天
    有没有已发布单次特殊日规则。排课中心调休复制区用,提醒口径为提前 14 天。"""
    from app.models.special_day import SpecialDayRule
    from app.services.holidays import WORKDAY_NOTE

    _get_semester(db, semester_id)
    rows = db.scalars(
        select(SchoolCalendarEvent).where(
            SchoolCalendarEvent.semester_id == semester_id,
            SchoolCalendarEvent.note == WORKDAY_NOTE,
        ).order_by(SchoolCalendarEvent.start_date)
    ).all()
    copied = {
        r.single_date for r in db.scalars(
            select(SpecialDayRule).where(
                SpecialDayRule.semester_id == semester_id,
                SpecialDayRule.is_active.is_(True),
                SpecialDayRule.recurrence == "single",
            )
        ).all() if r.single_date is not None
    }
    out: list[WorkdayOut] = []
    for ev in rows:
        d = ev.start_date
        if from_date is not None and d < from_date:
            continue
        if to_date is not None and d > to_date:
            continue
        out.append(WorkdayOut(date=d, title=ev.title, has_copy=d in copied))
    return out


@router.get("/calendar-events", response_model=list[CalendarEventOut])
def list_calendar_events(
    semester_id: int = Query(...),
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
    _: User = Depends(get_active_user),
):
    semester = _get_semester(db, semester_id)
    rows = db.scalars(
        select(SchoolCalendarEvent)
        .where(SchoolCalendarEvent.semester_id == semester_id)
        .order_by(SchoolCalendarEvent.start_date, SchoolCalendarEvent.id)
    ).all()
    if from_date is None and to_date is None:
        return list(rows)

    def _included(ev: SchoolCalendarEvent) -> bool:
        normal = (
            (from_date is None or ev.end_date >= from_date)
            and (to_date is None or ev.start_date <= to_date)
        )
        if normal:
            return True
        if not ev.weekly_recurring:
            return False
        # 每周重复事件由前端展开:只要它在学期内还会重复发生,就不能因
        # 其原始 end_date 落在范围外而误删。重复的下限是 start_date,
        # 上限以学期结束日为准(未设学期结束日则视为开放)。
        if to_date is not None and ev.start_date > to_date:
            return False
        if from_date is not None and semester.end_date is not None \
                and semester.end_date < from_date:
            return False
        return True

    return [ev for ev in rows if _included(ev)]


@router.post(
    "/calendar-events", response_model=CalendarEventOut,
    status_code=status.HTTP_201_CREATED,
)
def create_calendar_event(
    body: CalendarEventCreate,
    semester_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(editor),
):
    effective_semester_id = body.semester_id if body.semester_id is not None else semester_id
    if effective_semester_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "必须提供 semester_id"
        )
    _get_semester(db, effective_semester_id)
    _validate_merged(body.start_date, body.end_date, body.period_start, body.period_end)
    scope_id = _validate_scope(db, effective_semester_id, body.scope_type, body.scope_id)
    event = SchoolCalendarEvent(
        semester_id=effective_semester_id,
        title=body.title,
        event_type=body.event_type,
        scope_type=body.scope_type,
        scope_id=scope_id,
        start_date=body.start_date,
        end_date=body.end_date,
        period_start=body.period_start,
        period_end=body.period_end,
        weekly_recurring=body.weekly_recurring,
        note=body.note,
        created_by=user.id,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.patch("/calendar-events/{event_id}", response_model=CalendarEventOut)
def update_calendar_event(
    event_id: int,
    body: CalendarEventUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(editor),
):
    event = _get_event(db, event_id)
    data = body.model_dump(exclude_unset=True)

    merged_start = data.get("start_date", event.start_date) or event.start_date
    merged_end = data.get("end_date", event.end_date) or event.end_date
    # period 栏位允许显式传 None 清除(全天),故以「是否在 data 中」区分未传与传 None
    merged_ps = data["period_start"] if "period_start" in data else event.period_start
    merged_pe = data["period_end"] if "period_end" in data else event.period_end
    _validate_merged(merged_start, merged_end, merged_ps, merged_pe)

    merged_scope_type = data.get("scope_type", event.scope_type) or event.scope_type
    merged_scope_id = data["scope_id"] if "scope_id" in data else event.scope_id
    scope_id = _validate_scope(db, event.semester_id, merged_scope_type, merged_scope_id)

    for key, value in data.items():
        setattr(event, key, value)
    event.scope_type = merged_scope_type
    event.scope_id = scope_id
    # 合并后的日期/节次以验证过的为准(显式 None 的日期不覆盖既有值)
    event.start_date = merged_start
    event.end_date = merged_end
    event.period_start = merged_ps
    event.period_end = merged_pe
    db.commit()
    db.refresh(event)
    return event


@router.delete("/calendar-events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_calendar_event(
    event_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(editor),
) -> None:
    event = _get_event(db, event_id)
    db.delete(event)
    db.commit()
