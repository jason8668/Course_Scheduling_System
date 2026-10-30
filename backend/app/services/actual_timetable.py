"""实际课表展开:某日期区间内每天真正要上的课。

展开顺序与课时统计、提醒完全一致(口径不另起一套):
  主课表周模板 -> 特殊日覆盖(放假优先) -> 请假调代课异动 -> 老师自主调课(调课优先于请假同节)
再加两层展示用信息:
  - 放假:该班该节因校历放假不上,仍以一条 cancelled 槽位出现,前端灰显;
  - 调休上班:国家时间表里的调休日(周六日也可能是工作日)本身不排课,
    须管理员提前复制某天课表(写成单次特殊日规则)才有课;未复制前该天标
    workday_pending,前端提醒管理员去排课中心复制。

槽位以 (班级, 节次) 为单位,连堂展开成单节;跑班群组一格多班时各班各一条。
老师调课与请假对调在同节冲突时只换整格、不拆班,与 teaching_hours 的已知近似一致。
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.week_parity import runs_in_week, week_number
from app.models.assignment import CourseAssignment
from app.models.basedata import ClassUnit, Teacher
from app.models.calendar import SchoolCalendarEvent
from app.models.leave import AffectedPeriod, AffectedStatus, LeaveRequest, LeaveStatus
from app.models.semester import Semester
from app.models.substitution import Substitution, SubstitutionType
from app.models.timetable import ScheduleEntry, Timetable, TimetableStatus
from app.services import teacher_swaps as _ts
from app.services.holidays import WORKDAY_NOTE
from app.services.special_days import (
    load_active_rules,
    load_holidays,
    overrides_for_date,
)


@dataclass
class ActualSlot:
    period_no: int
    class_unit_id: int
    class_name: str
    subject: str
    teacher_ids: list[int] = field(default_factory=list)
    teacher_names: list[str] = field(default_factory=list)
    room_name: str | None = None
    # origin: base/substitute/special/teacher_swap/self_study/cancelled/holiday/pending/merge
    origin: str = "base"
    note: str = ""


@dataclass
class ActualDay:
    date: date
    weekday: int
    published: bool
    holiday_titles: list[str] = field(default_factory=list)
    workday_title: str | None = None
    workday_pending: bool = False
    slots: list[ActualSlot] = field(default_factory=list)


def _teacher_names(teachers: dict[int, str], ids: list[int]) -> list[str]:
    return [teachers.get(i, f"#{i}") for i in ids]


def _is_holiday(
    holidays: list[SchoolCalendarEvent], grade: int, class_id: int, on: date, period: int,
) -> str | None:
    for ev in holidays:
        if not (ev.start_date <= on <= ev.end_date):
            continue
        if ev.period_start is not None and not (
            ev.period_start <= period <= (ev.period_end or ev.period_start)
        ):
            continue
        if ev.scope_type == "school" or (ev.scope_type == "grade" and ev.scope_id == grade) \
                or (ev.scope_type == "class" and ev.scope_id == class_id):
            return ev.title
    return None


def _workday_title(db: Session, semester_id: int, on: date) -> str | None:
    rows = db.scalars(
        select(SchoolCalendarEvent).where(
            SchoolCalendarEvent.semester_id == semester_id,
            SchoolCalendarEvent.note == WORKDAY_NOTE,
            SchoolCalendarEvent.start_date <= on,
            SchoolCalendarEvent.end_date >= on,
        )
    ).all()
    return rows[0].title if rows else None


def compute(
    db: Session, semester: Semester, from_date: date, to_date: date,
) -> list[ActualDay]:
    tt = db.scalar(
        select(Timetable).where(
            Timetable.semester_id == semester.id,
            Timetable.status == TimetableStatus.published.value,
        ).order_by(Timetable.id.desc())
    )
    classes = {
        c.id: c for c in db.scalars(
            select(ClassUnit).where(ClassUnit.semester_id == semester.id)
        ).all()
    }
    teachers = {
        t.id: t.name for t in db.scalars(
            select(Teacher).where(Teacher.semester_id == semester.id)
        ).all()
    }
    rules = load_active_rules(db, semester.id) if tt is not None else []
    holidays = load_holidays(db, semester.id)
    # 特殊日规则名(复制来源说明用)
    rule_titles = {r.id: r.title for r in rules}

    days: list[ActualDay] = []
    d = from_date
    while d <= to_date:
        day = ActualDay(date=d, weekday=d.isoweekday(), published=tt is not None)
        if tt is None:
            days.append(day)
            d += timedelta(days=1)
            continue
        # 校历放假标题(全校范围,展示用)
        day.holiday_titles = sorted({
            ev.title for ev in holidays
            if ev.start_date <= d <= ev.end_date and ev.scope_type == "school"
        })
        wt = _workday_title(db, semester.id, d)
        if wt is not None:
            day.workday_title = wt
        wn = week_number(semester.start_date, d)
        parity = None if wn is None else ("odd" if wn % 2 == 1 else "even")
        overrides = overrides_for_date(rules, classes, holidays, d)
        # 调休待复制:调休日且当天没有任何已发布特殊日条目(即还没复制课表)
        if wt is not None and not any(
            r.single_date == d for r in rules
        ):
            day.workday_pending = True

        entries = db.scalars(
            select(ScheduleEntry).where(
                ScheduleEntry.timetable_id == tt.id,
                ScheduleEntry.weekday == d.isoweekday(),
            )
        ).all()
        slots: dict[tuple[int, int], ActualSlot] = {}
        covered: set[tuple[int, int]] = set()
        for e in entries:
            a = e.assignment
            if a is None or not runs_in_week(a.week_parity, parity):
                continue
            room = e.room if e.room is not None else a.room
            tids = [at.teacher_id for at in a.teachers]
            for m in a.scheduling_unit.members:
                if m.class_unit is None:
                    continue
                cls = m.class_unit
                for p in range(e.period_no, e.period_no + (e.span or 1)):
                    covered.add((cls.id, p))
                    hol = _is_holiday(holidays, cls.grade, cls.id, d, p)
                    if hol is not None:
                        slots[(cls.id, p)] = ActualSlot(
                            period_no=p, class_unit_id=cls.id, class_name=cls.name,
                            subject=a.subject.name if a.subject else "",
                            teacher_ids=tids, teacher_names=_teacher_names(teachers, tids),
                            room_name=room.name if room else None,
                            origin="holiday", note=f"放假:{hol}",
                        )
                        continue
                    ov = overrides.get((cls.id, p))
                    if ov is not None:
                        if ov.course_assignment_id is None:
                            slots[(cls.id, p)] = ActualSlot(
                                period_no=p, class_unit_id=cls.id, class_name=cls.name,
                                subject=a.subject.name if a.subject else "",
                                teacher_ids=tids, teacher_names=_teacher_names(teachers, tids),
                                room_name=room.name if room else None,
                                origin="cancelled",
                                note=f"特殊日取消({rule_titles.get(ov.rule_id, '')})"
                                if rule_titles.get(ov.rule_id) else "特殊日取消",
                            )
                        else:
                            oa = db.get(CourseAssignment, ov.course_assignment_id)
                            if oa is None:
                                continue
                            otids = [at.teacher_id for at in oa.teachers]
                            slots[(cls.id, p)] = ActualSlot(
                                period_no=p, class_unit_id=cls.id, class_name=cls.name,
                                subject=oa.subject.name if oa.subject else "",
                                teacher_ids=otids, teacher_names=_teacher_names(teachers, otids),
                                room_name=room.name if room else None,
                                origin="special",
                                note=f"特殊日:{rule_titles.get(ov.rule_id, '')}"
                                if rule_titles.get(ov.rule_id) else "特殊日换课",
                            )
                    else:
                        slots[(cls.id, p)] = ActualSlot(
                            period_no=p, class_unit_id=cls.id, class_name=cls.name,
                            subject=a.subject.name if a.subject else "",
                            teacher_ids=tids, teacher_names=_teacher_names(teachers, tids),
                            room_name=room.name if room else None, origin="base",
                        )
        # 特殊日新增格(主课表那天那节本来没课,如调休复制、整日重排)
        for (class_id, p), ov in overrides.items():
            if (class_id, p) in covered or ov.course_assignment_id is None:
                continue
            cls = classes.get(class_id)
            if cls is None or _is_holiday(holidays, cls.grade, cls.id, d, p) is not None:
                continue
            oa = db.get(CourseAssignment, ov.course_assignment_id)
            if oa is None:
                continue
            otids = [at.teacher_id for at in oa.teachers]
            slots[(class_id, p)] = ActualSlot(
                period_no=p, class_unit_id=class_id, class_name=cls.name,
                subject=oa.subject.name if oa.subject else "",
                teacher_ids=otids, teacher_names=_teacher_names(teachers, otids),
                origin="special",
                note=f"特殊日:{rule_titles.get(ov.rule_id, '')}"
                if rule_titles.get(ov.rule_id) else "特殊日新增",
            )

        # 请假调代课异动(只看已登记、未销假的受影响节次)
        aps = db.scalars(
            select(AffectedPeriod)
            .join(LeaveRequest, AffectedPeriod.leave_request_id == LeaveRequest.id)
            .where(
                AffectedPeriod.semester_id == semester.id,
                AffectedPeriod.date == d,
                LeaveRequest.status == LeaveStatus.registered.value,
                AffectedPeriod.status != AffectedStatus.cancelled.value,
            )
        ).all()
        subs = {
            s.affected_period_id: s for s in db.scalars(
                select(Substitution).where(
                    Substitution.affected_period_id.in_([ap.id for ap in aps])
                )
            )
        } if aps else {}
        # 受影响节次 -> 槽位键:先按 schedule_entry_id / 配课成员找班,找不到按快照班名找
        def _ap_keys(ap: AffectedPeriod) -> list[tuple[int, int]]:
            keys: list[tuple[int, int]] = []
            entry = db.get(ScheduleEntry, ap.schedule_entry_id) if ap.schedule_entry_id else None
            if entry is not None and entry.assignment is not None:
                for m in entry.assignment.scheduling_unit.members:
                    if m.class_unit is not None:
                        keys.append((m.class_unit.id, ap.period_no))
            if not keys and ap.course_assignment_id:
                a = db.get(CourseAssignment, ap.course_assignment_id)
                if a is not None:
                    for m in a.scheduling_unit.members:
                        if m.class_unit is not None:
                            keys.append((m.class_unit.id, ap.period_no))
            if not keys:
                names = {n.strip() for n in (ap.class_names or "").split("、") if n.strip()}
                for cid, cls in classes.items():
                    if cls.name in names:
                        keys.append((cid, ap.period_no))
            return keys

        makeup_subs: list[Substitution] = []
        for ap in aps:
            leave = ap.leave_request
            absent = leave.teacher_id
            absent_name = teachers.get(absent, "") if absent else ""
            sub = subs.get(ap.id)
            keys = _ap_keys(ap)
            if sub is None:
                for k in keys:
                    if k in slots:
                        slots[k].origin = "pending"
                        slots[k].note = (
                            f"请假待处理(原任{absent_name})" if absent_name else "请假待处理"
                        )
                continue
            handler = sub.handler_teacher_id
            handler_name = teachers.get(handler, "") if handler else ""
            if sub.type == SubstitutionType.substitute.value:
                for k in keys:
                    if k in slots:
                        slots[k].origin = "substitute"
                        slots[k].teacher_ids = [handler] if handler else slots[k].teacher_ids
                        slots[k].teacher_names = (
                            [handler_name] if handler_name else slots[k].teacher_names
                        )
                        slots[k].note = (
                            f"代课:{handler_name}代{absent_name}" if handler_name else "代课"
                        )
                    elif handler:
                        slots[k] = ActualSlot(
                            period_no=ap.period_no, class_unit_id=k[0],
                            class_name=classes[k[0]].name if k[0] in classes else "",
                            subject=ap.subject_name, teacher_ids=[handler],
                            teacher_names=[handler_name], origin="substitute",
                            note=f"代课:{handler_name}代{absent_name}" if handler_name else "代课",
                        )
            elif sub.type in (SubstitutionType.self_study.value,):
                for k in keys:
                    if k in slots:
                        slots[k].origin = "self_study"
                        slots[k].note = "自习"
            elif sub.type == SubstitutionType.cancel.value:
                for k in keys:
                    if k in slots:
                        slots[k].origin = "cancelled"
                        slots[k].note = "不处理(停课)"
            elif sub.type == SubstitutionType.merge.value:
                for k in keys:
                    if k in slots:
                        slots[k].origin = "merge"
                        slots[k].note = f"并班(由{handler_name}接收)" if handler_name else "并班"
            elif sub.type == SubstitutionType.swap.value:
                for k in keys:
                    if k in slots:
                        slots[k].origin = "substitute"
                        slots[k].teacher_ids = [handler] if handler else slots[k].teacher_ids
                        slots[k].teacher_names = (
                            [handler_name] if handler_name else slots[k].teacher_names
                        )
                        slots[k].note = (
                            f"调课:{handler_name}代{absent_name}" if handler_name else "调课"
                        )
                if sub.swap_date is not None:
                    makeup_subs.append(sub)
        # 请假对调的补课节:原任去上对方那节
        for sub in makeup_subs:
            if sub.swap_date != d:
                continue
            ap = db.get(AffectedPeriod, sub.affected_period_id)
            if ap is None or ap.leave_request is None:
                continue
            absent = ap.leave_request.teacher_id
            absent_name = teachers.get(absent, "") if absent else ""
            handler = sub.handler_teacher_id
            p = sub.swap_period_no or 0
            for name in (sub.swap_class_names or "").split("、"):
                name = name.strip()
                if not name:
                    continue
                for cid, cls in classes.items():
                    if cls.name != name:
                        continue
                    k = (cid, p)
                    if k in slots:
                        slots[k].origin = "base"
                        slots[k].teacher_ids = [absent] if absent else slots[k].teacher_ids
                        slots[k].teacher_names = (
                            [absent_name] if absent_name else slots[k].teacher_names
                        )
                        handler_name = teachers.get(handler, "")
                        slots[k].note = (
                            f"补课:{absent_name}补{handler_name}" if absent_name else "补课"
                        )
                    else:
                        slots[k] = ActualSlot(
                            period_no=p, class_unit_id=cid, class_name=cls.name,
                            subject=sub.swap_subject_name, teacher_ids=[absent] if absent else [],
                            teacher_names=[absent_name] if absent_name else [],
                            origin="base", note="补课",
                        )

        # 老师自主调课(生效的,最后套,同节冲突时调课优先)
        for st in _ts.swap_teachings(db, semester.id):
            if st.class_date != d:
                continue
            k = (st.class_unit_id, st.period_no)
            handler_name = teachers.get(st.handler_teacher_id, "")
            orig_name = teachers.get(st.original_teacher_id, "")
            if k in slots:
                slot = slots[k]
                # 只换原任那位,同格其他老师不动
                if st.original_teacher_id in slot.teacher_ids:
                    idx = slot.teacher_ids.index(st.original_teacher_id)
                    slot.teacher_ids[idx] = st.handler_teacher_id
                    slot.teacher_names[idx] = handler_name
                else:
                    slot.teacher_ids = [st.handler_teacher_id]
                    slot.teacher_names = [handler_name]
                slot.origin = "teacher_swap" if st.origin == "substitute" else "base"
                slot.note = (
                    f"老师调课:{handler_name}代{orig_name}"
                    if st.origin == "substitute"
                    else f"老师调课补课:{orig_name}上{handler_name}的课"
                )
            else:
                a = db.get(CourseAssignment, st.assignment_id)
                cls = classes.get(st.class_unit_id)
                if a is None or cls is None:
                    continue
                slots[k] = ActualSlot(
                    period_no=st.period_no, class_unit_id=st.class_unit_id,
                    class_name=cls.name,
                    subject=a.subject.name if a.subject else "",
                    teacher_ids=[st.handler_teacher_id], teacher_names=[handler_name],
                    origin="teacher_swap" if st.origin == "substitute" else "base",
                    note=f"老师调课:{handler_name}代{orig_name}"
                    if st.origin == "substitute" else "老师调课补课",
                )

        day.slots = [slots[k] for k in sorted(slots, key=lambda x: (x[1], x[0]))]
        days.append(day)
        d += timedelta(days=1)
    return days
