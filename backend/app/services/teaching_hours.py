"""教师实际上课课时统计(仪表板 + 管理员查询/打印共用)。

口径(用户定案):「实际上了几节课」——
- 底数:已发布课表按日期展开(连堂按实际节数计;单双周只计轮到的那一周;
  每位配课教师都计,协同教学两人各计一节;跑班群组一格只计一节)。
- 扣减:校历放假(全天或指定节次)那天/那节不上课。
- 请假调代课(只看仍有效的假单,已销假取消的不算):
  - 代课:缺课教师扣掉,代课教师加上;
  - 自习、停课(不处理):缺课教师扣掉,无人加上;
  - 并班:被并入的班扣掉,接收教师本来的那节已在底数里,不另加;
  - 调课:请假日缺课教师扣、代课教师加;补课日反过来(缺课教师加、原代课教师扣);
  - 尚未处置的待处理节次:请假教师已确定不在,先扣掉,无人加上。
- 只计到今天为止:范围超出今天的部分还没上,不能算「已上」。
  回传 effective_start/effective_end 让界面能注明「统计至今天」。

年级归属:一节课算到它所教班级的年级;跑班群组一格多班时,
该节同时算到所涉的每个年级(故各年级小计之和可能大于总计)。
按年级筛选时,只计包含该年级的节次。

注意:这里的「上课课时」与代课月结统计的「计入/不计」是两回事——
后者管代课费/代课工作量是否计酬;这里只要实际上了课就计,
不论那节代课当初选的是计入还是不计入。
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
from app.models.timetable import ScheduleEntry, Timetable
from app.services.special_days import (
    load_active_rules as _load_special_rules,
    load_holidays as _load_special_holidays,
    overrides_for_date as _special_overrides,
)
from app.services.substitution_log import school_today


@dataclass
class TeacherHours:
    teacher_id: int
    teacher_name: str
    total: int = 0
    by_grade: dict[int, int] = field(default_factory=dict)
    # 其中代课节数:替别人上的课(代课/对调中代对方那节);对调补课算自己的课,不计入
    substitute_total: int = 0


def _published_timetable(db: Session, semester_id: int) -> Timetable | None:
    return db.scalar(
        select(Timetable)
        .where(Timetable.semester_id == semester_id, Timetable.status == "published")
        .order_by(Timetable.id.desc())
    )


def _holidays(db: Session, semester_id: int) -> list[SchoolCalendarEvent]:
    """一次性放假事件(每周重复的已由求解器挡在课表外,不必再扣)。"""
    return db.scalars(
        select(SchoolCalendarEvent).where(
            SchoolCalendarEvent.semester_id == semester_id,
            SchoolCalendarEvent.event_type == "holiday",
            SchoolCalendarEvent.weekly_recurring.is_(False),
        )
    ).all()


def _is_holiday(
    holidays: list[SchoolCalendarEvent],
    grades: set[int],
    class_ids: set[int],
    on: date,
    period_no: int,
) -> bool:
    for ev in holidays:
        if not (ev.start_date <= on <= ev.end_date):
            continue
        if ev.period_start is not None and not (ev.period_start <= period_no <= (ev.period_end or ev.period_start)):
            continue
        if ev.scope_type == "school":
            return True
        if ev.scope_type == "grade" and ev.scope_id in grades:
            return True
        if ev.scope_type == "class" and ev.scope_id in class_ids:
            return True
    return False


def compute(
    db: Session,
    semester: Semester,
    start: date,
    end: date,
    *,
    teacher_id: int | None = None,
    grade: int | None = None,
) -> tuple[list[TeacherHours], date, date]:
    """回传 (教师课时列, 实际统计起日, 实际统计讫日)。"""
    today = school_today()
    eff_start = start
    eff_end = min(end, today)
    if semester.start_date is not None:
        eff_start = max(eff_start, semester.start_date)
    if semester.end_date is not None:
        eff_end = min(eff_end, semester.end_date)
    if eff_end < eff_start:
        return [], eff_start, eff_end

    tt = _published_timetable(db, semester.id)
    if tt is None:
        return [], eff_start, eff_end

    teachers = {
        t.id: t.name
        for t in db.scalars(
            select(Teacher).where(Teacher.semester_id == semester.id)
        ).all()
    }
    if teacher_id is not None:
        teachers = {k: v for k, v in teachers.items() if k == teacher_id}

    entries = db.scalars(
        select(ScheduleEntry).where(ScheduleEntry.timetable_id == tt.id)
    ).all()

    # (教师, 日期, 节次) -> 年级集合;底数先按已发布课表展开,再套特殊日覆盖。
    # 展开顺序:主课表 -> 特殊日替换(未填节次沿用主课表,放假优先) -> 请假调代课异动(在下面)。
    # 按班逐格展开:跑班群组一格多班时,各班的特殊日/放假分别判,年级集合取并集,
    # 总数仍按 (教师,日期,节次) 计一次,与旧口径一致。
    slots: dict[tuple[int, date, int], set[int]] = {}
    # 同格来源:base=自己的课,substitute=替别人代的课;被扣掉的格不计(只按现存格查)
    slot_origin: dict[tuple[int, date, int], str] = {}
    holidays = _holidays(db, semester.id)
    classes_by_id = {
        c.id: c for c in db.scalars(
            select(ClassUnit).where(ClassUnit.semester_id == semester.id)
        ).all()
    }
    special_rules = _load_special_rules(db, semester.id)
    special_holidays = _load_special_holidays(db, semester.id)
    override_assignments: dict[int, object] = {}

    def _add_slot(tids: list[int], d: date, p: int, grade: int) -> None:
        for tid in tids:
            if teacher_id is not None and tid != teacher_id:
                continue
            slots.setdefault((tid, d, p), set()).add(grade)
            slot_origin.setdefault((tid, d, p), "base")

    d = eff_start
    while d <= eff_end:
        overrides = _special_overrides(special_rules, classes_by_id, special_holidays, d)
        covered: set[tuple[int, int]] = set()
        wn = week_number(semester.start_date, d)
        parity = None if wn is None else ("odd" if wn % 2 == 1 else "even")
        for e in entries:
            if e.weekday != d.isoweekday():
                continue
            a = e.assignment
            if a is None:
                continue
            if not runs_in_week(a.week_parity, parity):
                continue
            teacher_ids = [at.teacher_id for at in a.teachers]
            for m in a.scheduling_unit.members:
                if m.class_unit is None:
                    continue
                cls = m.class_unit
                for p in range(e.period_no, e.period_no + (e.span or 1)):
                    covered.add((cls.id, p))
                    if _is_holiday(holidays, {cls.grade}, {cls.id}, d, p):
                        continue
                    ov = overrides.get((cls.id, p))
                    if ov is not None:
                        if ov.course_assignment_id is None:
                            continue
                        oa = override_assignments.get(ov.course_assignment_id)
                        if oa is None:
                            oa = db.get(CourseAssignment, ov.course_assignment_id)
                            override_assignments[ov.course_assignment_id] = oa
                        if oa is None:
                            continue
                        _add_slot([at.teacher_id for at in oa.teachers], d, p, cls.grade)
                    else:
                        _add_slot(teacher_ids, d, p, cls.grade)
        # 特殊日新增的格(主课表那天那节本来没课,如整日重排填了空节次)
        for (class_id, p), ov in overrides.items():
            if (class_id, p) in covered or ov.course_assignment_id is None:
                continue
            cls = classes_by_id.get(class_id)
            if cls is None or _is_holiday(holidays, {cls.grade}, {cls.id}, d, p):
                continue
            oa = override_assignments.get(ov.course_assignment_id)
            if oa is None:
                oa = db.get(CourseAssignment, ov.course_assignment_id)
                override_assignments[ov.course_assignment_id] = oa
            if oa is None:
                continue
            _add_slot([at.teacher_id for at in oa.teachers], d, p, cls.grade)
        d += timedelta(days=1)

    # 请假调代课异动:先找底数里对应的那格(拿年级),再扣/加
    def base_grades(tid: int, d: date, p: int) -> set[int]:
        if (tid, d, p) in slots:
            return slots[(tid, d, p)]
        # 课表改版后快照对不上底数时,退回查该教师当天该节的已发布格位
        wn_day = d.isoweekday()
        for e in entries:
            if e.weekday != wn_day or not (e.period_no <= p < e.period_no + (e.span or 1)):
                continue
            if any(at.teacher_id == tid for at in e.assignment.teachers):
                return {m.class_unit.grade for m in e.assignment.scheduling_unit.members
                        if m.class_unit is not None}
        return set()

    aps = db.scalars(
        select(AffectedPeriod)
        .join(LeaveRequest, AffectedPeriod.leave_request_id == LeaveRequest.id)
        .where(
            AffectedPeriod.semester_id == semester.id,
            AffectedPeriod.date >= eff_start,
            AffectedPeriod.date <= eff_end,
            LeaveRequest.status == LeaveStatus.registered.value,
            AffectedPeriod.status != AffectedStatus.cancelled.value,
        )
    ).all()
    subs = {
        s.affected_period_id: s
        for s in db.scalars(
            select(Substitution).where(
                Substitution.affected_period_id.in_([ap.id for ap in aps])
            )
        ).all()
    } if aps else {}

    makeup: list[Substitution] = []
    for ap in aps:
        leave = ap.leave_request
        absent = leave.teacher_id
        sub = subs.get(ap.id)
        if sub is None:
            # 待处理:请假教师确定不在,先扣掉
            slots.pop((absent, ap.date, ap.period_no), None)
            continue
        if sub.type == SubstitutionType.substitute.value:
            grades = base_grades(absent, ap.date, ap.period_no)
            slots.pop((absent, ap.date, ap.period_no), None)
            if sub.handler_teacher_id is not None and (teacher_id is None or sub.handler_teacher_id == teacher_id):
                slots[(sub.handler_teacher_id, ap.date, ap.period_no)] = grades
                slot_origin[(sub.handler_teacher_id, ap.date, ap.period_no)] = "substitute"
        elif sub.type in (SubstitutionType.self_study.value, SubstitutionType.cancel.value):
            slots.pop((absent, ap.date, ap.period_no), None)
        elif sub.type == SubstitutionType.merge.value:
            slots.pop((absent, ap.date, ap.period_no), None)
        elif sub.type == SubstitutionType.swap.value:
            grades = base_grades(absent, ap.date, ap.period_no)
            slots.pop((absent, ap.date, ap.period_no), None)
            if sub.handler_teacher_id is not None and (teacher_id is None or sub.handler_teacher_id == teacher_id):
                slots[(sub.handler_teacher_id, ap.date, ap.period_no)] = grades
                slot_origin[(sub.handler_teacher_id, ap.date, ap.period_no)] = "substitute"
            if sub.swap_date is not None:
                makeup.append(sub)

    for sub in makeup:
        if not (eff_start <= sub.swap_date <= eff_end):
            continue
        handler = sub.handler_teacher_id
        ap = db.get(AffectedPeriod, sub.affected_period_id)
        absent = ap.leave_request.teacher_id if ap else None
        if handler is None or absent is None:
            continue
        swap_period = sub.swap_period_no or 0
        grades = base_grades(handler, sub.swap_date, swap_period)
        slots.pop((handler, sub.swap_date, swap_period), None)
        if teacher_id is None or absent == teacher_id:
            slots[(absent, sub.swap_date, swap_period)] = grades
            slot_origin[(absent, sub.swap_date, swap_period)] = "base"

    # 老师自主调课(生效的):在请假异动之后套,故与请假同节冲突时调课优先。
    # 口径与请假对调同款:换课节换课教师计代课,补课节原任教师计自己的课。
    # 注意:这里是按 (教师,日期,节次) 格算,与请假对调同款;跑班群组
    # 同节多班、特殊日同节重叠时,调课只换整格,不拆班,属已知近似。
    from app.services import teacher_swaps as _ts

    for st in _ts.swap_teachings(db, semester.id):
        if not (eff_start <= st.class_date <= eff_end):
            continue
        cls = classes_by_id.get(st.class_unit_id)
        grades = {cls.grade} if cls is not None else base_grades(
            st.original_teacher_id, st.class_date, st.period_no)
        if not grades:
            grades = base_grades(st.original_teacher_id, st.class_date, st.period_no)
        slots.pop((st.original_teacher_id, st.class_date, st.period_no), None)
        if teacher_id is None or st.handler_teacher_id == teacher_id:
            slots[(st.handler_teacher_id, st.class_date, st.period_no)] = grades
            slot_origin[(st.handler_teacher_id, st.class_date, st.period_no)] = st.origin

    hours: dict[int, TeacherHours] = {}
    for (tid, _d, _p), grades in slots.items():
        if tid not in teachers:
            continue
        if grade is not None and grade not in grades:
            continue
        h = hours.setdefault(tid, TeacherHours(teacher_id=tid, teacher_name=teachers[tid]))
        h.total += 1
        if slot_origin.get((tid, _d, _p)) == "substitute":
            h.substitute_total += 1
        for g in grades:
            h.by_grade[g] = h.by_grade.get(g, 0) + 1
    out = sorted(hours.values(), key=lambda h: h.teacher_name)
    if teacher_id is not None and teacher_id in teachers and teacher_id not in hours:
        out = [TeacherHours(teacher_id=teacher_id, teacher_name=teachers[teacher_id])]
    return out, eff_start, eff_end
