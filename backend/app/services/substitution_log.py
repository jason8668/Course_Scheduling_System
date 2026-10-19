"""今日调代课看板与调代课日志(M4-4)。

这一层把「特定日期的受影响节次 + 其处置」摊平成一列列可读的纪录,供两个出口共用:

1. **今日看板**:某一天全校的异动——谁请假、哪一节、由谁接手、教室在哪;
   以及当天因调课而回来补课的节次(见 `_makeup_rows`)。
2. **历史日志**:依教师/日期/假别筛选的查询。

资料真相仍在 `affected_period`(受影响节次快照)与 `substitution`(处置决定);这里只做
join + 摊平 + 中文标签,不新增任何真相。看板的「今日」以学校时区(config.tz)判定,
不是 UTC——台湾凌晨的 UTC 仍是前一天(architecture.md D6)。
"""

from dataclasses import dataclass
from datetime import date, time

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core import clock
from app.models.basedata import Room
from app.models.leave import (
    AFFECTED_STATUS_CN,
    LEAVE_TYPE_CN,
    AffectedPeriod,
    AffectedStatus,
    LeaveRequest,
    LeaveStatus,
)
from app.models.substitution import SUBSTITUTION_TYPE_CN, Substitution, SubstitutionType
from app.models.timetable import ScheduleEntry
from app.services import leaves
from app.services.availability import Availability

# 栏位名 date/start_time 会遮蔽同名型别,故以别名标注型别
_Date = date
_Time = time

# 列的种类:请假展开的节次,或调课补课那天被换来的节次
ROW_LEAVE = "leave"
ROW_SWAP_MAKEUP = "swap_makeup"

# 历史查询的保护性上限(M6-5):一整年不筛选地查会是数千笔。取最新 N 笔,
# 要看更早的请缩小日期区间;完整分页 UI 留 v1.2。
MAX_ROWS = 1000


@dataclass(frozen=True, slots=True)
class LogEntry:
    """一列调代课纪录:一个受影响节次 + 它的处置(若已处置)。"""

    affected_period_id: int
    date: _Date
    weekday: int
    period_no: int
    period_name: str
    start_time: _Time | None
    end_time: _Time | None
    class_names: str
    subject_name: str
    room_name: str
    absent_teacher_id: int
    absent_teacher_name: str
    leave_type: str
    leave_type_label: str
    status: str
    status_label: str
    disposed: bool  # 是否已有处置(代课/调课/并班/自习/不处理)
    sub_type: str | None
    sub_type_label: str | None
    handler_teacher_id: int | None
    handler_name: str | None
    counts_toward_hours: bool | None
    swap_date: _Date | None
    swap_period_name: str
    swap_class_names: str
    swap_subject_name: str
    note: str
    # leave:请假的那一节。swap_makeup:调课补课日的那一节——「原任教师」是对调的乙,
    # 「接手」是回来补课的甲,swap_* 反过来记请假那一节(两列互相指向对方)。
    row_kind: str = ROW_LEAVE


def school_today() -> date:
    """学校所在时区的今天(config.tz,默认 Asia/Taipei)。"""
    return clock.school_today()


def _subs_map(db: Session, affected_ids: list[int]) -> dict[int, Substitution]:
    """一次捞齐这些受影响节次的处置,免逐列 join。"""
    if not affected_ids:
        return {}
    rows = db.scalars(
        select(Substitution).where(Substitution.affected_period_id.in_(affected_ids))
    )
    return {s.affected_period_id: s for s in rows}


def _build(ap: AffectedPeriod, sub: Substitution | None) -> LogEntry:
    leave = ap.leave_request
    status = leaves.effective_status(ap.status, ap.date, ap.end_time)
    handler_id = sub.handler_teacher_id if sub else ap.handler_teacher_id
    handler_name = None
    if sub is not None and sub.handler is not None:
        handler_name = sub.handler.name
    elif ap.handler is not None:
        handler_name = ap.handler.name
    return LogEntry(
        affected_period_id=ap.id,
        date=ap.date,
        weekday=ap.weekday,
        period_no=ap.period_no,
        period_name=ap.period_name,
        start_time=ap.start_time,
        end_time=ap.end_time,
        class_names=ap.class_names,
        subject_name=ap.subject_name,
        room_name=ap.room_name,
        absent_teacher_id=leave.teacher_id,
        absent_teacher_name=leave.teacher.name if leave.teacher else "(已移除)",
        leave_type=leave.leave_type,
        leave_type_label=LEAVE_TYPE_CN.get(leave.leave_type, leave.leave_type),
        status=status,
        status_label=AFFECTED_STATUS_CN.get(status, status),
        disposed=sub is not None,
        sub_type=sub.type if sub else None,
        sub_type_label=SUBSTITUTION_TYPE_CN.get(sub.type) if sub else None,
        handler_teacher_id=handler_id,
        handler_name=handler_name,
        counts_toward_hours=sub.counts_toward_hours if sub else None,
        swap_date=sub.swap_date if sub else None,
        swap_period_name=sub.swap_period_name if sub else "",
        swap_class_names=sub.swap_class_names if sub else "",
        swap_subject_name=sub.swap_subject_name if sub else "",
        note=ap.note or (sub.note if sub else ""),
    )


def _makeup_rows(db: Session, semester_id: int, on: date) -> list[LogEntry]:
    """调课补课日当天被换来的节次。

    调课成立后那天有两处异动:请假日由乙代甲,补课日由甲上乙原本那节。后者在
    `affected_period` 里没有一列(乙没请假),只记在 `substitution.swap_*`——
    不另外列出,补课那天的看板与公告单就会漏掉,那一班会看到「课表上是乙、来的是甲」。
    """
    subs = db.scalars(
        select(Substitution)
        .join(AffectedPeriod, Substitution.affected_period_id == AffectedPeriod.id)
        .join(LeaveRequest, AffectedPeriod.leave_request_id == LeaveRequest.id)
        .where(
            Substitution.semester_id == semester_id,
            Substitution.type == SubstitutionType.swap.value,
            Substitution.swap_date == on,
            LeaveRequest.status == LeaveStatus.registered.value,
            AffectedPeriod.status != AffectedStatus.cancelled.value,
        )
    ).all()
    if not subs:
        return []

    av = Availability(db, semester_id)
    out: list[LogEntry] = []
    for sub in subs:
        ap = db.get(AffectedPeriod, sub.affected_period_id)
        if ap is None:
            continue
        leave = ap.leave_request
        entry = db.get(ScheduleEntry, sub.swap_entry_id) if sub.swap_entry_id else None
        period = av.entry_period(entry, sub.swap_period_no) if entry else None
        start = period.start_time if period else None
        end = period.end_time if period else None
        room_name = ""
        if entry is not None:
            room_id = entry.room_id if entry.room_id is not None else entry.assignment.room_id
            room = db.get(Room, room_id) if room_id else None
            room_name = room.name if room else ""
        status = leaves.effective_status(ap.status, on, end)
        out.append(LogEntry(
            affected_period_id=ap.id,
            date=on,
            weekday=on.isoweekday(),
            period_no=sub.swap_period_no or 0,
            period_name=sub.swap_period_name,
            start_time=start,
            end_time=end,
            class_names=sub.swap_class_names,
            subject_name=sub.swap_subject_name,
            room_name=room_name,
            absent_teacher_id=sub.handler_teacher_id or 0,
            absent_teacher_name=sub.handler.name if sub.handler else "(已移除)",
            leave_type="",
            leave_type_label="调课补课",
            status=status,
            status_label=AFFECTED_STATUS_CN.get(status, status),
            disposed=True,
            sub_type=sub.type,
            sub_type_label=SUBSTITUTION_TYPE_CN.get(sub.type),
            handler_teacher_id=leave.teacher_id,
            handler_name=leave.teacher.name if leave.teacher else "(已移除)",
            counts_toward_hours=sub.counts_toward_hours,
            swap_date=ap.date,
            swap_period_name=ap.period_name,
            swap_class_names=ap.class_names,
            swap_subject_name=ap.subject_name,
            note="",
            row_kind=ROW_SWAP_MAKEUP,
        ))
    return out


def daily_board(db: Session, semester_id: int, on: date) -> list[LogEntry]:
    """某一天全校的调代课异动,依节次、班级排序。

    只看仍有效(未销假)的假单;已因销假取消的节次不列(那天没有异动)。
    包含尚未处置(待处理)的节次,好让组长一眼看出还有几节没排代课;
    也包含当天因调课回来补课的节次。
    """
    rows = db.scalars(
        select(AffectedPeriod)
        .join(LeaveRequest, AffectedPeriod.leave_request_id == LeaveRequest.id)
        .where(
            AffectedPeriod.semester_id == semester_id,
            AffectedPeriod.date == on,
            LeaveRequest.status == LeaveStatus.registered.value,
            AffectedPeriod.status != AffectedStatus.cancelled.value,
        )
        .order_by(AffectedPeriod.period_no, AffectedPeriod.class_names)
    ).unique().all()
    subs = _subs_map(db, [r.id for r in rows])
    entries = [_build(r, subs.get(r.id)) for r in rows] + _makeup_rows(db, semester_id, on)
    return sorted(entries, key=lambda e: (e.period_no, e.class_names))


def query(
    db: Session,
    semester_id: int,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    teacher_id: int | None = None,
    leave_type: str | None = None,
    limit: int = MAX_ROWS,
) -> list[LogEntry]:
    """历史查询:依日期区间、教师、假别筛选,最新在前。

    `teacher_id` 同时比对「请假的当事人」与「接手代课的教师」——查一位教师时,
    他缺的课与他代的课都算与他相关。

    `limit` 是保护性上限(M6-5):不筛选地查一整年,会把数千笔一次拉进记忆体再序列化。
    取最新的 N 笔(呼叫端可缩小日期区间看更早的);完整分页 UI 留 v1.2。
    """
    stmt = (
        select(AffectedPeriod)
        .join(LeaveRequest, AffectedPeriod.leave_request_id == LeaveRequest.id)
        .where(AffectedPeriod.semester_id == semester_id)
    )
    if date_from is not None:
        stmt = stmt.where(AffectedPeriod.date >= date_from)
    if date_to is not None:
        stmt = stmt.where(AffectedPeriod.date <= date_to)
    if leave_type is not None:
        stmt = stmt.where(LeaveRequest.leave_type == leave_type)
    if teacher_id is not None:
        stmt = stmt.where(or_(
            LeaveRequest.teacher_id == teacher_id,
            AffectedPeriod.handler_teacher_id == teacher_id,
        ))
    rows = db.scalars(
        stmt.order_by(AffectedPeriod.date.desc(), AffectedPeriod.period_no).limit(limit)
    ).unique().all()
    subs = _subs_map(db, [r.id for r in rows])
    return [_build(r, subs.get(r.id)) for r in rows]
