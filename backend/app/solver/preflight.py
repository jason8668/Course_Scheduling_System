"""排课前置检查(architecture.md §3.4)。

在丢给 CP-SAT 之前先跑一轮廉价的**必要条件**检查,拦掉多数资料错误:
教师配课数 ≤ 可排格数、班级周节数 ≤ 可排节次、场地需求 ≤ 供给、连堂放得进连续节次。
必要条件通过不代表一定有解(那要靠 solver),但不通过就一定无解——不必浪费求解时间。

错误(error)会挡下自动排课;警告(warning)只提醒,不挡。
讯息一律用教务语言与具体数字,不是「排不出来」。
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from app.solver.problem import (
    AssignmentSpec,
    Problem,
    RoomSpec,
    Slot,
    TeacherSpec,
    UnitSpec,
    max_non_overlapping,
)
from app.solver.week_parity import fmt_periods

Level = Literal["error", "warning"]


@dataclass(frozen=True, slots=True)
class Issue:
    level: Level
    code: str
    message: str  # 人话,含具体数字
    subject_type: str  # teacher / class / room / assignment / semester
    subject_id: int
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PreflightReport:
    issues: tuple[Issue, ...]

    @property
    def errors(self) -> tuple[Issue, ...]:
        return tuple(i for i in self.issues if i.level == "error")

    @property
    def warnings(self) -> tuple[Issue, ...]:
        return tuple(i for i in self.issues if i.level == "warning")

    @property
    def ok(self) -> bool:
        return not self.errors


def teacher_available_slots(problem: Problem, teacher: TeacherSpec) -> int:
    """教师可排格数:其任教班级的节次表中,扣除不可排时段后互不重叠的节次数。

    单一节次表(绝大多数学校)= 一般课格数 − 落在一般课上的 unavailable 格数。
    跨节次表任教(完全中学)则以墙钟区间去重,见 problem.max_non_overlapping。
    """
    usable: list[Slot] = []
    for table in problem.tables_of_teacher(teacher.id):
        usable.extend(s for s in table.slots if s.key not in teacher.unavailable)
    return max_non_overlapping(usable)


def _room_supply(problem: Problem, room_id: int) -> int:
    """该场地可用的节次数:使用它的班级所属节次表的节次联集(去重叠)。"""
    tables = {}
    for a in problem.assignments:
        if a.room_id != room_id:
            continue
        table = problem.table_of(a)
        if table is not None:
            tables[table.id] = table
    if not tables:
        return 0
    slots: list[Slot] = []
    for table in tables.values():
        slots.extend(table.slots)
    return max_non_overlapping(slots)


# 这些错误连 CP-SAT 模型都建不起来(某门课根本没有可排的位置、群组结构自相矛盾),
# 「部分排课」也救不了——少排几节课不能让一个 4 连堂塞进 3 连续节次。
STRUCTURAL_CODES = frozenset({
    "assignment_without_class",
    "no_period_table",
    "group_shape_mismatch",
    "group_teacher_duplicate",
    "alternate_incomplete",
    "block_infeasible",
    "block_exceeds_periods",
    "room_no_candidate",  # 没有任何一间场地适用此科目 → _make_room_vars 直接失败
})


def blocking_errors(report: PreflightReport, *, allow_partial: bool) -> tuple[Issue, ...]:
    """哪些错误该挡在自动排课门口。

    一般模式:全部。部分排课模式:只挡结构性错误——「教师配课超量」「场地不够」
    这类总量问题,正是部分排课要处理的事(少排几节,列成未排清单)。
    """
    if not allow_partial:
        return report.errors
    return tuple(
        i
        for i in report.errors
        if i.code in STRUCTURAL_CODES
        # 该类型场地一间都没有 → 建模时就会失败,不是「少排几节」的问题
        or (i.code == "room_type_supply" and not i.detail.get("supply"))
    )


def run(problem: Problem) -> PreflightReport:
    issues: list[Issue] = []

    _check_period_tables(problem, issues)
    _check_groups(problem, issues)
    _check_teachers(problem, issues)
    _check_classes(problem, issues)
    _check_rooms(problem, issues)
    _check_blocks(problem, issues)

    order = {"error": 0, "warning": 1}
    return PreflightReport(tuple(sorted(issues, key=lambda i: (order[i.level], i.code))))


def _check_period_tables(problem: Problem, issues: list[Issue]) -> None:
    for a in problem.assignments:
        if not problem.classes_of(a):
            issues.append(Issue(
                "error", "assignment_without_class",
                f"配课「{a.subject_name}」没有任何班级,无法排课",
                "assignment", a.id,
            ))
        elif problem.table_of(a) is None:
            issues.append(Issue(
                "error", "no_period_table",
                f"配课「{a.subject_name}」的班级尚未指派节次表,无法决定可排时段",
                "assignment", a.id,
            ))


def _check_groups(problem: Problem, issues: list[Issue]) -> None:
    """跑班群组的各门课同时段开课(H7),故每周节数与连堂结构必须一致。"""
    for unit in problem.units.values():
        if unit.is_alternate:
            _check_alternate(problem, unit, issues)
            continue
        if not unit.is_group:
            continue
        members = [a for a in problem.assignments if a.unit_id == unit.id]
        shapes = {(a.periods_per_week, a.blocks) for a in members}
        if len(shapes) > 1:
            periods = sorted({a.periods_per_week for a in members})
            issues.append(Issue(
                "error", "group_shape_mismatch",
                f"跑班群组「{unit.name}」的各门课每周节数不一致({periods}),"
                f"无法同时段开课",
                "semester", problem.semester_id,
                {"unit_id": unit.id, "periods": periods},
            ))
        for teacher_id, count in duplicate_group_teachers(members).items():
            teacher = problem.teachers.get(teacher_id)
            name = teacher.name if teacher else str(teacher_id)
            issues.append(Issue(
                "error", "group_teacher_duplicate",
                f"跑班群组「{unit.name}」里,教师{name} 有 {count} 笔配课,同一节无法上 "
                f"{count} 堂课;请只留一笔(群组内的课是同一节一起上)",
                "teacher", teacher_id,
                {"unit_id": unit.id, "count": count},
            ))


def _check_alternate(problem: Problem, unit: UnitSpec, issues: list[Issue]) -> None:
    """单双周组(v1.3.0):单周、双周各一笔,节数与连堂结构相同,才能轮流占同一格。"""
    members = [a for a in problem.assignments if a.unit_id == unit.id]
    if not members:
        return  # 刚建好、还没配课的组:不挡,也没有课要排
    weeks = sorted(a.week_parity or "" for a in members)
    if weeks != ["even", "odd"]:
        missing = "双周" if "even" not in weeks else "单周" if "odd" not in weeks else ""
        detail = f"还缺{missing}的课" if missing and len(members) < 2 else "单周、双周要各一笔"
        issues.append(Issue(
            "error", "alternate_incomplete",
            f"单双周组「{unit.name}」{detail},才能排课",
            "semester", problem.semester_id,
            {"unit_id": unit.id},
        ))
        return
    if len({(a.periods_per_week, a.blocks) for a in members}) > 1:
        periods = sorted({a.periods_per_week for a in members})
        issues.append(Issue(
            "error", "group_shape_mismatch",
            f"单双周组「{unit.name}」单周与双周的节数或连堂不一致({periods}),"
            f"无法排在同一格",
            "semester", problem.semester_id,
            {"unit_id": unit.id, "periods": periods},
        ))


def duplicate_group_teachers(members: Sequence[AssignmentSpec]) -> dict[int, int]:
    """同一个跑班群组内,出现在两笔以上配课的教师 → 笔数。

    群组内的课同时段开课(H7),同一位教师有两笔就是同一节上两堂。求解器把整个群组
    当成一门课、教师合并成集合,自己看不出来(用户回报:手动放入会挡、自动排课却排得出来),
    所以要在这里与建模前挡下。
    """
    counts: dict[int, int] = {}
    for a in members:
        for tid in set(a.teacher_ids):
            counts[tid] = counts.get(tid, 0) + 1
    return {tid: n for tid, n in sorted(counts.items()) if n > 1}


def _check_teachers(problem: Problem, issues: list[Issue]) -> None:
    for teacher in problem.teachers.values():
        assigned = sum(a.weekly_load for a in problem.assignments_of_teacher(teacher.id))
        if assigned == 0:
            continue
        available = teacher_available_slots(problem, teacher)
        if assigned > available:
            blocked = len(teacher.unavailable)
            suffix = f"(已扣除 {blocked} 格不可排时段)" if blocked else ""
            issues.append(Issue(
                "error", "teacher_overload",
                f"教师{teacher.name} 配课 {fmt_periods(assigned)} 节,"
                f"但可排时段仅 {available} 格{suffix}",
                "teacher", teacher.id,
                {"assigned": assigned, "available": available, "unavailable": blocked},
            ))
        if assigned > teacher.target_periods:
            issues.append(Issue(
                "warning", "teacher_over_hours",
                f"教师{teacher.name} 配课 {fmt_periods(assigned)} 节,超出应授课时 "
                f"{teacher.target_periods} 节 {fmt_periods(assigned - teacher.target_periods)} 节",
                "teacher", teacher.id,
                {"assigned": assigned, "target": teacher.target_periods},
            ))


def _check_classes(problem: Problem, issues: list[Issue]) -> None:
    consumption: dict[int, int] = {}
    for unit in problem.units.values():
        used = problem.unit_slot_consumption(unit.id)
        for cid in unit.class_ids:
            consumption[cid] = consumption.get(cid, 0) + used

    for cid, used in consumption.items():
        cls = problem.classes[cid]
        table = problem.tables.get(cls.period_table_id)
        capacity = len(table.slots) if table else 0
        if used > capacity:
            issues.append(Issue(
                "error", "class_overload",
                f"班级 {cls.name} 每周配课 {used} 节,超过可排节次 {capacity} 节",
                "class", cid,
                {"assigned": used, "capacity": capacity},
            ))


def _check_rooms(problem: Problem, issues: list[Issue]) -> None:
    # 1) 已绑定场地:逐间比对需求与可用节次
    demand_by_room: dict[int, float] = {}
    for a in problem.assignments:
        if a.room_id is not None:
            demand_by_room[a.room_id] = demand_by_room.get(a.room_id, 0) + a.weekly_load

    for room_id, demand in demand_by_room.items():
        room = problem.rooms.get(room_id)
        if room is None:
            continue
        supply = _room_supply(problem, room_id)
        if demand > supply:
            issues.append(Issue(
                "error", "room_supply",
                f"场地 {room.name} 需求 {fmt_periods(demand)} 节,超过可用节次 {supply} 节",
                "room", room_id,
                {"demand": demand, "supply": supply},
            ))

    _check_room_types(problem, issues)

    # 3) D8:场地容量仅作警告,不参与求解(同一场地同时段仍是至多一门课)
    for a in problem.assignments:
        if a.room_id is None:
            continue
        room = problem.rooms.get(a.room_id)
        unit = problem.units[a.unit_id]
        if room is None or room.capacity is None or unit.is_group:
            continue  # 跑班群组的学生分流到多门课,人数不可直接相加
        students = sum(c.student_count or 0 for c in problem.classes_of(a))
        if students > room.capacity:
            issues.append(Issue(
                "warning", "room_capacity",
                f"「{a.subject_name}」使用 {room.name}(容量 {room.capacity} 人),"
                f"但上课人数 {students} 人",
                "assignment", a.id,
                {"students": students, "capacity": room.capacity},
            ))


def candidate_rooms(problem: Problem, a: AssignmentSpec) -> tuple[RoomSpec, ...]:
    """该配课可用的场地。**必须与 model_builder._candidate_rooms 同义**——

    pre-flight 若只看场地类型而不看「适用科目」,就会放行一个建模阶段必然失败的学期:
    唯一的专科教室绑定「美术」,而「音乐」也要求专科教室 → 检查说供给充足,
    solver 却连模型都建不起来,冲突定位也找不到该场地,最后给出一份文不对题的报告。
    """
    return tuple(
        r
        for r in problem.rooms.values()
        if r.room_type == a.required_room_type
        and (not r.subject_ids or a.subject_id in r.subject_ids)
    )


def _check_room_types(problem: Problem, issues: list[Issue]) -> None:
    """场地类型的总量检查(§3.4「音乐教室需求 35 节 > 供给 30 节」)。

    需求依「候选场地集合」分组后才与供给比对:两门课即使同样要求专科教室,
    若可用的教室集合不同,它们的需求就不该相加。
    """
    slots_per_room = max((len(t.slots) for t in problem.tables.values()), default=0)

    # 该类型一间都没有 → 建模必然失败,单独报(部分排课也挡)
    typed = [a for a in problem.assignments if a.required_room_type]
    for room_type in sorted({a.required_room_type for a in typed if a.required_room_type}):
        if not any(r.room_type == room_type for r in problem.rooms.values()):
            demand = sum(a.weekly_load for a in typed if a.required_room_type == room_type)
            issues.append(Issue(
                "error", "room_type_supply",
                f"需要「{_ROOM_TYPE_CN.get(room_type, room_type)}」的课共 {fmt_periods(demand)} 节,"
                f"但这类场地((无))合计只能提供 0 节",
                "semester", problem.semester_id,
                {"room_type": room_type, "demand": demand, "supply": 0},
            ))

    by_pool: dict[tuple[int, ...], list[AssignmentSpec]] = {}
    for a in typed:
        rooms = candidate_rooms(problem, a)
        if not rooms:
            if any(r.room_type == a.required_room_type for r in problem.rooms.values()):
                # 类型有教室,但没有一间适用这个科目
                issues.append(Issue(
                    "error", "room_no_candidate",
                    f"「{a.subject_name}」需要「"
                    f"{_ROOM_TYPE_CN.get(a.required_room_type or '', a.required_room_type)}」,"
                    f"但没有任何一间这类场地适用此科目",
                    "assignment", a.id,
                    {"room_type": a.required_room_type, "subject_id": a.subject_id},
                ))
            continue
        by_pool.setdefault(tuple(sorted(r.id for r in rooms)), []).append(a)

    for pool_ids, users in by_pool.items():
        demand = sum(a.weekly_load for a in users)
        supply = len(pool_ids) * slots_per_room
        if demand <= supply:
            continue
        names = "、".join(problem.rooms[rid].name for rid in pool_ids)
        room_type = users[0].required_room_type or ""
        issues.append(Issue(
            "error", "room_type_supply",
            f"需要「{_ROOM_TYPE_CN.get(room_type, room_type)}」的课共 {fmt_periods(demand)} 节,"
            f"但可用的场地({names})合计只能提供 {supply} 节",
            "semester", problem.semester_id,
            {"room_type": room_type, "demand": demand, "supply": supply,
             "rooms": len(pool_ids)},
        ))


def _check_blocks(problem: Problem, issues: list[Issue]) -> None:
    for a in problem.assignments:
        if not a.blocks:
            continue
        table = problem.table_of(a)
        if table is None:
            continue
        longest = table.longest_run()
        for block in a.blocks:
            if block.size > longest:
                issues.append(Issue(
                    "error", "block_infeasible",
                    f"「{a.subject_name}」要求 {block.size} 连堂,"
                    f"但节次表最长只有 {longest} 节连续的一般课(连堂不可跨午休)",
                    "assignment", a.id,
                    {"block_size": block.size, "longest_run": longest},
                ))
        if a.block_periods > a.periods_per_week:
            issues.append(Issue(
                "error", "block_exceeds_periods",
                f"「{a.subject_name}」连堂共 {a.block_periods} 节,"
                f"超过每周 {a.periods_per_week} 节",
                "assignment", a.id,
                {"block_periods": a.block_periods, "periods_per_week": a.periods_per_week},
            ))


_ROOM_TYPE_CN = {
    "normal": "普通教室",
    "special": "专科教室",
    "workshop": "实习工场",
    "outdoor": "户外场地",
}
