"""课表版本服务:完整性检查、复制草稿、发布(architecture.md D4)。

发布 = draft → published;同学期原有的 published 自动转 archived(仅一份 published)。
发布为快照:已发布/已封存的课表不可再编辑格位(见 api/timetables._require_draft)。
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import clock
from app.models.assignment import CourseAssignment
from app.models.audit import AuditLog
from app.models.leave import AffectedPeriod, AffectedStatus, LeaveRequest, LeaveStatus
from app.models.timetable import ScheduleEntry, Timetable, TimetableStatus
from app.models.user import User


def _reasons_by_assignment(timetable: Timetable) -> dict[int, str]:
    """把该课表存下的 solver 未排原因摊成 {配课 id: 原因}(M6-3)。

    「哪些配课还缺节数」一律由下方 completeness 从 DB 重算——那是唯一真相,连手动改过
    的课表都算得对。这里只补上 DB 推导不出来的那一半:**为什么排不下**。
    """
    out: dict[int, str] = {}
    for item in timetable.unscheduled or []:
        reason = item.get("reason") or ""
        if not reason:
            continue
        for aid in item.get("assignment_ids", []):
            out[aid] = reason
    return out


def completeness(db: Session, timetable: Timetable) -> dict:
    """比对每笔配课的每周节数与已排入节数,回传未排完清单(H8 周节数守恒的发布面检查)。"""
    reasons = _reasons_by_assignment(timetable)
    placed_rows = db.execute(
        select(ScheduleEntry.course_assignment_id, func.sum(ScheduleEntry.span))
        .where(ScheduleEntry.timetable_id == timetable.id)
        .group_by(ScheduleEntry.course_assignment_id)
    ).all()
    placed_by = {aid: int(n or 0) for aid, n in placed_rows}

    assignments = db.scalars(
        select(CourseAssignment)
        .where(CourseAssignment.semester_id == timetable.semester_id)
        .order_by(CourseAssignment.id)
    ).all()

    unplaced = []
    required = 0
    placed_total = 0
    for a in assignments:
        required += a.periods_per_week
        placed = placed_by.get(a.id, 0)
        placed_total += placed
        if placed < a.periods_per_week:
            unplaced.append({
                "course_assignment_id": a.id,
                "subject": a.subject.name,
                "classes": [m.class_unit.name for m in a.scheduling_unit.members],
                "teachers": [at.teacher.name for at in a.teachers],
                "required": a.periods_per_week,
                "placed": placed,
                "remaining": a.periods_per_week - placed,
                "reason": reasons.get(a.id, ""),
            })
    return {
        "required": required,
        "placed": placed_total,
        "remaining": max(required - placed_total, 0),
        "complete": not unplaced,
        "unplaced": unplaced,
    }


def stale_future_affected_count(db: Session, semester_id: int) -> int:
    """今日之后仍待处理/已指派的受影响节次数。

    这些节次的快照是依**先前**已发布课表展开的;学期中重新发布课表后,它们可能指向
    已移走的格位(代课老师被派去上一节新课表里不存在的课)。回传数量供发布后提醒组长
    重新查看。完整解(重跑 expand + diff + 通知)见 tasks.md M5-0 条件 D。
    """
    return db.scalar(
        select(func.count())
        .select_from(AffectedPeriod)
        .join(LeaveRequest, AffectedPeriod.leave_request_id == LeaveRequest.id)
        .where(
            AffectedPeriod.semester_id == semester_id,
            LeaveRequest.status == LeaveStatus.registered.value,
            AffectedPeriod.status.in_(
                [AffectedStatus.pending.value, AffectedStatus.resolved.value]
            ),
            AffectedPeriod.date >= clock.school_today(),
        )
    ) or 0


def duplicate(db: Session, source: Timetable, name: str) -> Timetable:
    """复制为新草稿(含全部格位与锁定状态);两份草稿完全独立。"""
    new = Timetable(semester_id=source.semester_id, name=name,
                    status=TimetableStatus.draft.value)
    db.add(new)
    db.flush()
    entries = db.scalars(
        select(ScheduleEntry).where(ScheduleEntry.timetable_id == source.id)
    ).all()
    for e in entries:
        db.add(ScheduleEntry(
            timetable_id=new.id, course_assignment_id=e.course_assignment_id,
            weekday=e.weekday, period_no=e.period_no, span=e.span, locked=e.locked,
            room_id=e.room_id,
        ))
    db.flush()
    return new


def publish(db: Session, timetable: Timetable, user: User, forced: bool) -> Timetable:
    """draft → published;同学期原 published 转 archived。呼叫端负责 commit。"""
    previous = db.scalars(
        select(Timetable).where(
            Timetable.semester_id == timetable.semester_id,
            Timetable.status == TimetableStatus.published.value,
            Timetable.id != timetable.id,
        )
    ).all()
    for p in previous:
        p.status = TimetableStatus.archived.value
    timetable.status = TimetableStatus.published.value

    db.add(AuditLog(
        user_id=user.id, username=user.username,
        action="publish_timetable", target_type="timetable", target_id=timetable.id,
        detail=(
            f"发布课表「{timetable.name}」"
            + (f",同时封存「{'、'.join(p.name for p in previous)}」" if previous else "")
            + ("(含未排完课务,强制发布)" if forced else "")
        )[:500],
    ))
    db.flush()
    return timetable
