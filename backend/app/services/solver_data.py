"""DB → 排课引擎问题描述的转换层。

刻意放在 `app.services` 而非 `app.solver`:loader 必须 import models 与 SQLAlchemy,
而 solver 套件的架构规则是「不碰 ORM」(见 app/solver/__init__.py)。
这里是两者唯一的交界。
"""

from datetime import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assignment import (
    AssignmentTeacher,
    BlockRule,
    CourseAssignment,
    SchedulingUnit,
    SchedulingUnitMember,
)
from app.models.basedata import ClassUnit, Room, Teacher, TeacherRuleType, TeacherTimeRule
from app.models.calendar import SchoolCalendarEvent
from app.models.constraint import ConstraintConfig
from app.models.period import Period, PeriodTable, PeriodType
from app.models.semester import Semester
from app.models.timetable import ScheduleEntry, Timetable
from app.services import period_tables as pt_service
from app.solver.problem import (
    DEFAULT_WEIGHTS,
    MAX_WEIGHT,
    AssignmentSpec,
    BlockSpec,
    ClassSpec,
    FixedEntry,
    PeriodTableSpec,
    Problem,
    RoomSpec,
    Slot,
    SolverConfig,
    TeacherSpec,
    UnitSpec,
)


def _minutes(value: time | None) -> int | None:
    return value.hour * 60 + value.minute if value is not None else None


# ── 约束设置 ───────────────────────────────────────────────
_PARAM_KEYS = ("daily_subject_cap", "teacher_daily_max", "teacher_consecutive_max")


def load_config(db: Session, semester_id: int) -> SolverConfig:
    """读取该学期的约束设置;未设置的 key 回退默认值。"""
    stored = {
        row.key: row.value
        for row in db.scalars(
            select(ConstraintConfig).where(ConstraintConfig.semester_id == semester_id)
        )
    }
    defaults = SolverConfig()
    weights = dict(DEFAULT_WEIGHTS)
    for code in DEFAULT_WEIGHTS:
        if code in stored:
            # 夹到上限:API 现在挡得住,但旧资料可能存过更大的值,而超过上限会让
            # 部分排课宁可丢掉一节课也要满足软约束(见 solver/problem.py MAX_WEIGHT)
            weights[code] = max(0, min(stored[code], MAX_WEIGHT))
    return SolverConfig(
        daily_subject_cap=stored.get("daily_subject_cap", defaults.daily_subject_cap),
        teacher_daily_max=stored.get("teacher_daily_max", defaults.teacher_daily_max),
        teacher_consecutive_max=stored.get(
            "teacher_consecutive_max", defaults.teacher_consecutive_max
        ),
        weights=weights,
    )


def save_config(db: Session, semester_id: int, config: SolverConfig) -> None:
    """整份覆写该学期的约束设置。呼叫端负责 commit。"""
    values = {k: getattr(config, k) for k in _PARAM_KEYS}
    values.update({code: config.weight(code) for code in DEFAULT_WEIGHTS})

    existing = {
        row.key: row
        for row in db.scalars(
            select(ConstraintConfig).where(ConstraintConfig.semester_id == semester_id)
        )
    }
    for key, value in values.items():
        if key in existing:
            existing[key].value = value
        else:
            db.add(ConstraintConfig(semester_id=semester_id, key=key, value=value))
    db.flush()


def _load_tables(db: Session, semester_id: int) -> dict[int, PeriodTableSpec]:
    tables = db.scalars(
        select(PeriodTable).where(PeriodTable.semester_id == semester_id)
    ).all()
    out: dict[int, PeriodTableSpec] = {}
    for t in tables:
        periods = db.scalars(
            select(Period)
            .where(
                Period.period_table_id == t.id,
                Period.type == PeriodType.regular.value,  # 只有一般课参与排课(H5)
            )
            .order_by(Period.weekday, Period.period_no)
        ).all()
        out[t.id] = PeriodTableSpec(
            id=t.id,
            name=t.name,
            num_weekdays=t.num_weekdays,
            slots=tuple(
                Slot(
                    weekday=p.weekday,
                    period_no=p.period_no,
                    name=p.name,
                    start_min=_minutes(p.start_time),
                    end_min=_minutes(p.end_time),
                )
                for p in periods
            ),
        )
    return out


def _calendar_blocks(
    db: Session, semester_id: int
) -> tuple[dict[int, dict[tuple[int, int], str]], dict[int, dict[tuple[int, int], str]]]:
    """校历每周重复活动的占用格位(批次 #4)。

    只取 weekly_recurring=True 的事件:一次性事件只影响那一周的看板显示,
    不改变整个学期的排课空间。回传 (class_cells, teacher_cells),
    皆为 id → {(weekday, period_no): 原因文字}。
    """
    class_cells: dict[int, dict[tuple[int, int], str]] = {}
    teacher_cells: dict[int, dict[tuple[int, int], str]] = {}
    events = db.scalars(
        select(SchoolCalendarEvent).where(
            SchoolCalendarEvent.semester_id == semester_id,
            SchoolCalendarEvent.weekly_recurring.is_(True),
        )
    ).all()
    if not events:
        return class_cells, teacher_cells

    all_classes = db.scalars(
        select(ClassUnit).where(ClassUnit.semester_id == semester_id)
    ).all()
    class_ids = [c.id for c in all_classes]
    all_teacher_ids = list(db.scalars(
        select(Teacher.id).where(Teacher.semester_id == semester_id)
    ))

    # 全天事件的节次集合:该学期所有节次表中该 weekday 的 regular 节次并集
    periods_by_weekday: dict[int, set[int]] = {}
    for weekday, period_no in db.execute(
        select(Period.weekday, Period.period_no)
        .join(PeriodTable, Period.period_table_id == PeriodTable.id)
        .where(
            PeriodTable.semester_id == semester_id,
            Period.type == PeriodType.regular.value,
        )
    ):
        periods_by_weekday.setdefault(weekday, set()).add(period_no)

    # 班级 → 教师映射(经排课单位成员 → 配课 → 配课教师),独立查询不依赖
    # load_problem 的中间组装顺序
    teachers_by_class: dict[int, set[int]] = {}
    for class_id, teacher_id in db.execute(
        select(SchedulingUnitMember.class_unit_id, AssignmentTeacher.teacher_id)
        .join(
            CourseAssignment,
            CourseAssignment.scheduling_unit_id == SchedulingUnitMember.scheduling_unit_id,
        )
        .join(
            AssignmentTeacher,
            AssignmentTeacher.course_assignment_id == CourseAssignment.id,
        )
        .where(CourseAssignment.semester_id == semester_id)
    ):
        teachers_by_class.setdefault(class_id, set()).add(teacher_id)

    for ev in events:
        weekday = ev.start_date.isoweekday()
        if ev.period_start is not None and ev.period_end is not None:
            cells = {
                (weekday, p) for p in range(ev.period_start, ev.period_end + 1)
            }
        else:
            cells = {(weekday, p) for p in periods_by_weekday.get(weekday, set())}
        if not cells:
            continue
        reason = f"校历活动「{ev.title}」占用"

        if ev.scope_type == "grade":
            affected = [c.id for c in all_classes if c.grade == ev.scope_id]
        elif ev.scope_type == "class":
            affected = [ev.scope_id] if ev.scope_id in class_ids else []
        else:  # school(及其余未知范围一律按全校保守处理不会发生,Literal 已挡)
            affected = list(class_ids) if ev.scope_type == "school" else []

        for cid in affected:
            slot = class_cells.setdefault(cid, {})
            for cell in cells:
                slot[cell] = reason

        if ev.scope_type == "school":
            affected_teachers = all_teacher_ids
        else:
            tset: set[int] = set()
            for cid in affected:
                tset |= teachers_by_class.get(cid, set())
            affected_teachers = list(tset)
        for tid in affected_teachers:
            slot = teacher_cells.setdefault(tid, {})
            for cell in cells:
                slot[cell] = reason

    return class_cells, teacher_cells


def load_problem(
    db: Session, semester_id: int, timetable: Timetable | None = None
) -> Problem:
    """把一个学期的排课资料读成纯 dataclass 的问题描述。

    timetable 给定时,其格位一并带入 fixed_entries:locked 者为 H9 硬约束,
    其余供求解器作为起点提示(M3-4)。
    """
    semester = db.get(Semester, semester_id)
    if semester is None:
        raise ValueError(f"找不到学期 {semester_id}")

    tables = _load_tables(db, semester_id)
    default_table = pt_service.semester_default_table(db, semester_id)
    default_table_id = default_table.id if default_table else None

    # 校历每周重复占用:先算好 dict,班级/教师 Spec 建构时直接并入
    cal_class_cells, cal_teacher_cells = _calendar_blocks(db, semester_id)

    classes: dict[int, ClassSpec] = {}
    for c in db.scalars(
        select(ClassUnit).where(ClassUnit.semester_id == semester_id).order_by(ClassUnit.id)
    ):
        # 在此一次解析节次表(指定表 → 学期默认表),solver 不需再回退
        table_id = c.period_table_id if c.period_table_id in tables else default_table_id
        if table_id is None:
            continue
        cal = cal_class_cells.get(c.id, {})
        classes[c.id] = ClassSpec(
            id=c.id, name=c.name, grade=c.grade,
            period_table_id=table_id, student_count=c.student_count,
            homeroom_teacher_id=c.homeroom_teacher_id,
            unavailable=frozenset(cal.keys()),
            unavailable_reasons=dict(cal),
        )

    # 直接查规则表而非走 Teacher.time_rules 关联:同一个 session 内若规则是稍早才写入的,
    # 关联集合可能仍是载入时的旧值,教师的不可排时段就会凭空消失(H4 静默失效)。
    rules_by_teacher: dict[int, dict[str, set[tuple[int, int]]]] = {}
    for teacher_id, weekday, period_no, rule_type in db.execute(
        select(
            TeacherTimeRule.teacher_id, TeacherTimeRule.weekday,
            TeacherTimeRule.period_no, TeacherTimeRule.rule_type,
        )
        .join(Teacher, Teacher.id == TeacherTimeRule.teacher_id)
        .where(Teacher.semester_id == semester_id)
    ):
        by_type = rules_by_teacher.setdefault(teacher_id, {})
        by_type.setdefault(rule_type, set()).add((weekday, period_no))

    teachers: dict[int, TeacherSpec] = {}
    for t in db.scalars(
        select(Teacher).where(Teacher.semester_id == semester_id).order_by(Teacher.id)
    ):
        rules = rules_by_teacher.get(t.id, {})
        cal_t = cal_teacher_cells.get(t.id, {})
        teachers[t.id] = TeacherSpec(
            id=t.id, name=t.name, base_periods=t.base_periods,
            admin_reduction=t.admin_reduction, is_external=t.is_external,
            unavailable=frozenset(
                rules.get(TeacherRuleType.unavailable.value, set()) | set(cal_t.keys())
            ),
            avoid=frozenset(rules.get(TeacherRuleType.avoid.value, set())),
            prefer=frozenset(rules.get(TeacherRuleType.prefer.value, set())),
            unavailable_reasons=dict(cal_t),
        )

    rooms = {
        r.id: RoomSpec(
            id=r.id, name=r.name, room_type=r.room_type, capacity=r.capacity,
            subject_ids=frozenset(s.id for s in r.subjects),
        )
        for r in db.scalars(
            select(Room).where(Room.semester_id == semester_id).order_by(Room.id)
        )
    }

    members: dict[int, list[int]] = {}
    for unit_id, class_id in db.execute(
        select(SchedulingUnitMember.scheduling_unit_id, SchedulingUnitMember.class_unit_id)
        .join(SchedulingUnit, SchedulingUnit.id == SchedulingUnitMember.scheduling_unit_id)
        .where(SchedulingUnit.semester_id == semester_id)
        .order_by(SchedulingUnitMember.id)
    ):
        members.setdefault(unit_id, []).append(class_id)

    units = {
        u.id: UnitSpec(
            id=u.id, unit_type=u.unit_type, name=u.name,
            class_ids=tuple(cid for cid in members.get(u.id, []) if cid in classes),
        )
        for u in db.scalars(
            select(SchedulingUnit).where(SchedulingUnit.semester_id == semester_id)
        )
    }

    teachers_by_a: dict[int, list[int]] = {}
    for a_id, t_id in db.execute(
        select(AssignmentTeacher.course_assignment_id, AssignmentTeacher.teacher_id)
        .join(CourseAssignment, CourseAssignment.id == AssignmentTeacher.course_assignment_id)
        .where(CourseAssignment.semester_id == semester_id)
        .order_by(AssignmentTeacher.id)
    ):
        teachers_by_a.setdefault(a_id, []).append(t_id)

    blocks_by_a: dict[int, list[BlockSpec]] = {}
    for a_id, size, count in db.execute(
        select(BlockRule.course_assignment_id, BlockRule.block_size, BlockRule.count_per_week)
        .join(CourseAssignment, CourseAssignment.id == BlockRule.course_assignment_id)
        .where(CourseAssignment.semester_id == semester_id)
    ):
        blocks_by_a.setdefault(a_id, []).append(BlockSpec(size=size, count=count))

    assignments = tuple(
        AssignmentSpec(
            id=a.id, unit_id=a.scheduling_unit_id,
            subject_id=a.subject_id, subject_name=a.subject.name,
            periods_per_week=a.periods_per_week,
            teacher_ids=tuple(teachers_by_a.get(a.id, [])),
            room_id=a.room_id, required_room_type=a.required_room_type,
            lock_room=a.lock_room,
            blocks=tuple(blocks_by_a.get(a.id, [])),
            subject_is_major=a.subject.is_major,
            week_parity=a.week_parity,
        )
        for a in db.scalars(
            select(CourseAssignment)
            .where(CourseAssignment.semester_id == semester_id)
            .order_by(CourseAssignment.id)
        )
    )

    fixed: tuple[FixedEntry, ...] = ()
    if timetable is not None:
        fixed = tuple(
            FixedEntry(
                assignment_id=e.course_assignment_id, weekday=e.weekday,
                period_no=e.period_no, span=e.span,
                room_id=e.room_id, locked=e.locked,
            )
            for e in db.scalars(
                select(ScheduleEntry)
                .where(ScheduleEntry.timetable_id == timetable.id)
                .order_by(ScheduleEntry.id)
            )
        )

    return Problem(
        semester_id=semester_id,
        semester_label=semester.label,
        tables=tables,
        classes=classes,
        teachers=teachers,
        rooms=rooms,
        units=units,
        assignments=assignments,
        fixed_entries=fixed,
    )
