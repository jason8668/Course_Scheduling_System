"""课表 API:草稿 CRUD、格位放入/移动/删除、锁定、即时冲突检查。

放入/移动时以 conflict_checker 验证硬约束,违反则回 409 并附人话冲突清单。
跑班群组:放入/移动/删除/锁定皆连动同群组全部配课(H7 同时段)。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import get_active_user, require_roles
from app.core.clock import school_today
from app.core.db import get_db
from app.core.week_parity import week_number, week_parity
from app.models.assignment import CourseAssignment
from app.models.basedata import ClassUnit, Room, Teacher
from app.models.period import PeriodTable
from app.models.semester import Semester
from app.models.timetable import ScheduleEntry, Timetable, TimetableStatus
from app.models.user import Role, User
from app.schemas.timetable import (
    ActualDayOut,
    ActualSlotOut,
    CheckIssueOut,
    CheckRequest,
    CheckResponse,
    CompletenessOut,
    MoveRequest,
    NamedBrief,
    PlaceRequest,
    PublicClass,
    PublicPeriodTable,
    PublicSemester,
    PublishedTimetableOut,
    ScheduleEntryOut,
    TimetableBrief,
    TimetableCheckOut,
    TimetableCreate,
    TimetableOut,
    TimetableRename,
)
from app.services import conflict_checker as cc
from app.services import grade_scopes, timetable_check
from app.services import timetable_publish as pub
from app.services.teachers import current_teacher

router = APIRouter(tags=["timetables"])

viewer = require_roles(Role.director)
editor = require_roles(Role.director)
# 发布是整校操作:主任可发布(主任的年级范围由 grade_scopes 管,见下);
# 改名/删除仍只限管理员。
publisher = require_roles(Role.director)


def _get_timetable(db: Session, timetable_id: int) -> Timetable:
    tt = db.get(Timetable, timetable_id)
    if tt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到课表")
    return tt


def _require_draft(tt: Timetable) -> Timetable:
    """已发布/已封存的课表是快照,不得再改格位(architecture.md D4)。"""
    if tt.status != TimetableStatus.draft.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "此课表已发布或已封存,不可编辑;请复制为新草稿后修改",
        )
    return tt


def _get_assignment(db: Session, semester_id: int, assignment_id: int) -> CourseAssignment:
    a = db.get(CourseAssignment, assignment_id)
    if a is None or a.semester_id != semester_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "配课无效或不属于本课表学期")
    return a


def _serialize_entry(e: ScheduleEntry) -> ScheduleEntryOut:
    a = e.assignment
    su = a.scheduling_unit
    # 格位场地优先于配课场地(引擎逐格指派、调代课教室异动皆写在格位上)
    room = e.room if e.room is not None else a.room
    return ScheduleEntryOut(
        id=e.id, course_assignment_id=e.course_assignment_id,
        weekday=e.weekday, period_no=e.period_no, span=e.span, locked=e.locked,
        subject=a.subject.name,
        teachers=[at.teacher.name for at in a.teachers],
        classes=[m.class_unit.name for m in su.members],
        unit_type=su.unit_type, unit_name=su.name,
        room=room.name if room else None,
        teacher_ids=[at.teacher_id for at in a.teachers],
        class_ids=[m.class_unit_id for m in su.members],
        room_id=e.effective_room_id,
        week_parity=a.week_parity,
    )


def _conflict_409(conflicts: list[cc.Conflict]) -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        detail={
            "message": "与硬约束冲突,无法排入",
            "conflicts": [{"code": c.code, "message": c.message} for c in conflicts],
        },
    )


def _slot_siblings(
    db: Session, timetable_id: int, unit_id: int, weekday: int, period_no: int
) -> list[ScheduleEntry]:
    """同一排课单位在「同一格位」的全部格位。

    跑班群组:该时段开的多门课(H7 须同进同出);单班:即该格本身。
    以格位为范围而非整个排课单位,否则同班其他科目的格位会被误连动。
    """
    return list(
        db.scalars(
            select(ScheduleEntry)
            .join(CourseAssignment, ScheduleEntry.course_assignment_id == CourseAssignment.id)
            .where(
                ScheduleEntry.timetable_id == timetable_id,
                CourseAssignment.scheduling_unit_id == unit_id,
                ScheduleEntry.weekday == weekday,
                ScheduleEntry.period_no == period_no,
            )
        )
    )


def _placed_periods(db: Session, timetable_id: int, assignment_id: int) -> int:
    """该配课在此课表已排入的节数(连堂以 span 计)。"""
    total = db.scalar(
        select(func.coalesce(func.sum(ScheduleEntry.span), 0)).where(
            ScheduleEntry.timetable_id == timetable_id,
            ScheduleEntry.course_assignment_id == assignment_id,
        )
    )
    return int(total or 0)


# ── 课表草稿 ──────────────────────────
@router.get("/timetables", response_model=list[TimetableBrief])
def list_timetables(
    semester_id: int = Query(...), db: Session = Depends(get_db), _: object = Depends(viewer)
):
    tts = db.scalars(
        select(Timetable).where(Timetable.semester_id == semester_id).order_by(Timetable.id)
    ).all()
    out = []
    for tt in tts:
        n = db.scalar(
            select(func.count()).select_from(ScheduleEntry).where(
                ScheduleEntry.timetable_id == tt.id
            )
        )
        out.append(TimetableBrief(
            id=tt.id, semester_id=tt.semester_id, name=tt.name, status=tt.status,
            entry_count=n or 0,
        ))
    return out


@router.post("/timetables", response_model=TimetableOut, status_code=status.HTTP_201_CREATED)
def create_timetable(
    body: TimetableCreate,
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    _: object = Depends(editor),
):
    if db.get(Semester, semester_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到学期")
    tt = Timetable(semester_id=semester_id, name=body.name)
    db.add(tt)
    db.commit()
    db.refresh(tt)
    return TimetableOut(
        id=tt.id, semester_id=tt.semester_id, name=tt.name, status=tt.status, entries=[]
    )


@router.get("/timetables/{timetable_id}", response_model=TimetableOut)
def get_timetable(
    timetable_id: int, db: Session = Depends(get_db), _: object = Depends(viewer)
):
    tt = _get_timetable(db, timetable_id)
    rows = db.scalars(
        select(ScheduleEntry).where(ScheduleEntry.timetable_id == tt.id)
    ).all()
    entries = sorted(rows, key=lambda e: (e.weekday, e.period_no))
    return TimetableOut(
        id=tt.id, semester_id=tt.semester_id, name=tt.name, status=tt.status,
        entries=[_serialize_entry(e) for e in entries],
    )


@router.patch("/timetables/{timetable_id}", response_model=TimetableOut)
def rename_timetable(
    timetable_id: int,
    body: TimetableRename,
    db: Session = Depends(get_db),
    user: User = Depends(editor),
):
    tt = _get_timetable(db, timetable_id)
    grade_scopes.require_unrestricted(db, user)
    tt.name = body.name
    db.commit()
    return get_timetable(timetable_id, db, None)


@router.post(
    "/timetables/{timetable_id}/duplicate",
    response_model=TimetableOut,
    status_code=status.HTTP_201_CREATED,
)
def duplicate_timetable(
    timetable_id: int,
    body: TimetableRename,
    db: Session = Depends(get_db),
    _: object = Depends(editor),
):
    """复制为新草稿(含全部格位);两份草稿互不影响。"""
    src = _get_timetable(db, timetable_id)
    new = pub.duplicate(db, src, body.name)
    db.commit()
    return get_timetable(new.id, db, None)


@router.get("/timetables/{timetable_id}/completeness", response_model=CompletenessOut)
def timetable_completeness(
    timetable_id: int, db: Session = Depends(get_db), _: object = Depends(viewer)
):
    """发布前完整性检查:列出尚未排完的课务。"""
    tt = _get_timetable(db, timetable_id)
    return pub.completeness(db, tt)


@router.get("/timetables/{timetable_id}/check", response_model=TimetableCheckOut)
def timetable_check_all(
    timetable_id: int, db: Session = Depends(get_db), _: object = Depends(viewer)
):
    """检查课表:冲堂等硬约束违规 + 未排完的课务。草稿、已发布、已封存皆可检查,不改状态。"""
    tt = _get_timetable(db, timetable_id)
    report = pub.completeness(db, tt)
    issues = timetable_check.check(db, tt)
    return TimetableCheckOut(
        ok=report["complete"] and not issues,
        issues=[CheckIssueOut(code=i.code, label=i.label, message=i.message) for i in issues],
        completeness=report,
    )


@router.post("/timetables/{timetable_id}/publish", response_model=TimetableOut)
def publish_timetable(
    timetable_id: int,
    force: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(publisher),
):
    """draft → published;同学期原 published 转 archived。

    未排完、或课表有冲堂等违规时,需 force=true 才可发布(列出来让用户自己决定)。
    主任可发布(须已由管理员分配年级);未配年级的主任仍无权发布。课表一学期一张,
    点发布就是把整张发出去了,各年级主任发布前需协调好。
    """
    tt = _require_draft(_get_timetable(db, timetable_id))
    grade_scopes.require_can_publish(db, user)
    report = pub.completeness(db, tt)
    issues = timetable_check.check(db, tt)
    blocked = not report["complete"] or bool(issues)
    if blocked and not force:
        if issues and not report["complete"]:
            text = "课表有冲突,且尚有课务未排完;确认后可强制发布"
        elif issues:
            text = "课表有冲突,确认后可强制发布"
        else:
            text = "尚有课务未排完,确认后可强制发布"
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "message": text,
                "completeness": report,
                "issues": [
                    CheckIssueOut(code=i.code, label=i.label, message=i.message).model_dump()
                    for i in issues
                ],
            },
        )
    pub.publish(db, tt, user, forced=blocked)
    db.commit()
    # 条件 D:重新发布后,提醒仍有多少「今日之后」的调代课是依旧课表展开的
    out = get_timetable(timetable_id, db, None)
    out.stale_affected = pub.stale_future_affected_count(db, tt.semester_id)
    return out


@router.delete("/timetables/{timetable_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_timetable(
    timetable_id: int, db: Session = Depends(get_db), user: User = Depends(editor)
) -> None:
    tt = _get_timetable(db, timetable_id)
    grade_scopes.require_unrestricted(db, user)
    db.delete(tt)
    db.commit()


# ── 全员唯读课表查询(含 teacher 角色)────
@router.get("/published/semesters", response_model=list[PublicSemester])
def published_semesters(db: Session = Depends(get_db), _: User = Depends(get_active_user)):
    """有已发布课表的学期。"""
    rows = db.scalars(
        select(Semester)
        .join(Timetable, Timetable.semester_id == Semester.id)
        .where(Timetable.status == TimetableStatus.published.value)
        .order_by(Semester.academic_year.desc(), Semester.term.desc())
    ).unique().all()
    today = school_today()
    out = []
    for s in rows:
        if s.start_date is None:
            wn = None
            wp = None
        else:
            wn = week_number(s.start_date, today)
            wp = week_parity(s.start_date, today)
        out.append(PublicSemester(
            id=s.id, label=s.label,
            start_date=s.start_date, end_date=s.end_date,
            current_week_number=wn, current_week_parity=wp,
        ))
    return out


@router.get("/published/my-teacher", response_model=NamedBrief | None)
def published_my_teacher(
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """登录者在该学期绑定的教师主档(无绑定回 null),供教师端默认显示本人课表。"""
    t = current_teacher(db, user, semester_id)
    return NamedBrief(id=t.id, name=t.name) if t else None


@router.get("/published/timetable", response_model=PublishedTimetableOut | None)
def published_timetable(
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_active_user),
):
    """该学期的已发布课表 + 查询页所需选项与节次表(教师端只需这一支)。"""
    tt = db.scalar(
        select(Timetable).where(
            Timetable.semester_id == semester_id,
            Timetable.status == TimetableStatus.published.value,
        )
    )
    if tt is None:
        return None
    sem = db.get(Semester, semester_id)
    rows = db.scalars(select(ScheduleEntry).where(ScheduleEntry.timetable_id == tt.id)).all()
    classes = db.scalars(
        select(ClassUnit).where(ClassUnit.semester_id == semester_id)
        .order_by(ClassUnit.grade, ClassUnit.name)
    ).all()
    teachers = db.scalars(
        select(Teacher).where(Teacher.semester_id == semester_id).order_by(Teacher.name)
    ).all()
    rooms = db.scalars(
        select(Room).where(Room.semester_id == semester_id).order_by(Room.name)
    ).all()
    tables = db.scalars(
        select(PeriodTable).where(PeriodTable.semester_id == semester_id)
    ).all()
    return PublishedTimetableOut(
        id=tt.id, semester_id=semester_id, semester_label=sem.label if sem else "",
        name=tt.name, status=tt.status,
        entries=[_serialize_entry(e) for e in sorted(rows, key=lambda x: (x.weekday, x.period_no))],
        classes=[
            PublicClass(id=c.id, name=c.name, grade=c.grade, period_table_id=c.period_table_id)
            for c in classes
        ],
        teachers=[NamedBrief(id=t.id, name=t.name) for t in teachers],
        rooms=[NamedBrief(id=r.id, name=r.name) for r in rooms],
        period_tables=[
            PublicPeriodTable(
                id=p.id, name=p.name, num_weekdays=p.num_weekdays, is_default=p.is_default,
                periods=list(p.periods),
            )
            for p in tables
        ],
    )


@router.get("/published/actual", response_model=list[ActualDayOut])
def published_actual(
    semester_id: int = Query(...),
    from_date: str = Query(...),
    to_date: str = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_active_user),
):
    """实际课表:某日期区间内每天真正要上的课(已叠加特殊日、请假代课、老师调课、放假;
    调休上班日未复制课表时 workday_pending 为真)。教师端可用,不限年级。"""
    from datetime import date as _date

    from app.services import actual_timetable as _actual

    sem = db.get(Semester, semester_id)
    if sem is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到学期")
    try:
        start = _date.fromisoformat(from_date)
        end = _date.fromisoformat(to_date)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "日期格式须为 YYYY-MM-DD") from exc
    if end < start or (end - start).days > 31:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "日期区间最多 31 天")
    days = _actual.compute(db, sem, start, end)
    return [
        ActualDayOut(
            date=d.date, weekday=d.weekday, published=d.published,
            holiday_titles=d.holiday_titles, workday_title=d.workday_title,
            workday_pending=d.workday_pending,
            slots=[ActualSlotOut(**vars(s)) for s in d.slots],
        )
        for d in days
    ]


# ── 冲突检查(不写入)────────────────
@router.post("/timetables/{timetable_id}/check-conflict", response_model=CheckResponse)
def check_conflict(
    timetable_id: int,
    body: CheckRequest,
    db: Session = Depends(get_db),
    _: object = Depends(viewer),
):
    tt = _get_timetable(db, timetable_id)
    a = _get_assignment(db, tt.semester_id, body.course_assignment_id)
    ignore_ids: set[int] = set()
    if body.ignore_entry_id is not None:
        e = db.get(ScheduleEntry, body.ignore_entry_id)
        if e is not None and e.timetable_id == tt.id:
            # 移动:忽略被搬动的那一格(群组则含同格的兄弟课)
            ignore_ids = {
                s.id for s in _slot_siblings(
                    db, tt.id, e.assignment.scheduling_unit_id, e.weekday, e.period_no
                )
            }
    conflicts = cc.check_conflict(
        db, tt, a, body.weekday, body.period_no, body.span, ignore_ids, body.room_id
    )
    return CheckResponse(
        ok=not conflicts,
        conflicts=[{"code": c.code, "message": c.message} for c in conflicts],
    )


# ── 格位放入/移动/删除/锁定 ──────────
@router.post("/timetables/{timetable_id}/entries", response_model=TimetableOut,
             status_code=status.HTTP_201_CREATED)
def place_entry(
    timetable_id: int,
    body: PlaceRequest,
    db: Session = Depends(get_db),
    user: User = Depends(editor),
):
    tt = _require_draft(_get_timetable(db, timetable_id))
    a = _get_assignment(db, tt.semester_id, body.course_assignment_id)
    grade_scopes.require_grades(db, user, grade_scopes.assignment_grades(db, a.id))
    if body.room_id is not None:
        room = db.get(Room, body.room_id)
        if room is None or room.semester_id != tt.semester_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "场地无效或不属于本课表学期")
    placements = cc.placements_for(db, a, body.weekday, body.period_no, body.span, body.room_id)
    # H8 守恒(放入面):不得超过该配课的每周节数
    for pl in placements:
        placed = _placed_periods(db, tt.id, pl.assignment.id)
        if placed + pl.span > pl.assignment.periods_per_week:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"「{pl.assignment.subject.name}」已排 {placed} 节,"
                f"再排 {pl.span} 节将超过每周 {pl.assignment.periods_per_week} 节",
            )
    conflicts = cc.check_conflict(
        db, tt, a, body.weekday, body.period_no, body.span, room_id=body.room_id
    )
    if conflicts:
        raise _conflict_409(conflicts)
    for pl in placements:
        db.add(ScheduleEntry(
            timetable_id=tt.id, course_assignment_id=pl.assignment.id,
            weekday=pl.weekday, period_no=pl.period_no, span=pl.span,
            room_id=pl.room_id,
        ))
    db.commit()
    return get_timetable(timetable_id, db, None)


@router.patch("/timetables/{timetable_id}/entries/{entry_id}", response_model=TimetableOut)
def move_entry(
    timetable_id: int, entry_id: int, body: MoveRequest,
    db: Session = Depends(get_db), user: User = Depends(editor),
):
    tt = _require_draft(_get_timetable(db, timetable_id))
    e = db.get(ScheduleEntry, entry_id)
    if e is None or e.timetable_id != tt.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到格位")
    grade_scopes.require_grades(db, user, grade_scopes.assignment_grades(db, e.course_assignment_id))
    if e.locked:
        raise HTTPException(status.HTTP_409_CONFLICT, "格位已锁定,请先解锁再移动")
    a = e.assignment
    # 同格兄弟(群组同时段的多门课)一起搬;检查时忽略自己这几格
    moving = _slot_siblings(db, tt.id, a.scheduling_unit_id, e.weekday, e.period_no)
    conflicts = cc.check_conflict(
        db, tt, a, body.weekday, body.period_no, e.span,
        ignore_entry_ids={s.id for s in moving},
        room_id=e.room_id,  # 搬动时沿用格位既有的场地
    )
    if conflicts:
        raise _conflict_409(conflicts)
    for sib in moving:
        sib.weekday = body.weekday
        sib.period_no = body.period_no
    db.commit()
    return get_timetable(timetable_id, db, None)


@router.post("/timetables/{timetable_id}/entries/{entry_id}/lock", response_model=TimetableOut)
def lock_entry(
    timetable_id: int, entry_id: int, locked: bool = Query(True),
    db: Session = Depends(get_db), user: User = Depends(editor),
):
    tt = _require_draft(_get_timetable(db, timetable_id))
    e = db.get(ScheduleEntry, entry_id)
    if e is None or e.timetable_id != tt.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到格位")
    grade_scopes.require_grades(db, user, grade_scopes.assignment_grades(db, e.course_assignment_id))
    for sib in _slot_siblings(db, tt.id, e.assignment.scheduling_unit_id, e.weekday, e.period_no):
        sib.locked = locked
    db.commit()
    return get_timetable(timetable_id, db, None)


@router.delete(
    "/timetables/{timetable_id}/entries/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_entry(
    timetable_id: int,
    entry_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(editor),
) -> None:
    tt = _require_draft(_get_timetable(db, timetable_id))
    e = db.get(ScheduleEntry, entry_id)
    if e is None or e.timetable_id != tt.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到格位")
    grade_scopes.require_grades(db, user, grade_scopes.assignment_grades(db, e.course_assignment_id))
    if e.locked:
        raise HTTPException(status.HTTP_409_CONFLICT, "格位已锁定,请先解锁再移除")
    for sib in _slot_siblings(db, tt.id, e.assignment.scheduling_unit_id, e.weekday, e.period_no):
        db.delete(sib)
    db.commit()
