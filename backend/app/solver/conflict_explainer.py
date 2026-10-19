"""无解冲突定位(architecture.md §3.4)。

市售排课系统无解时只回一句「排不出来」,教学组长只能靠经验猜。本模组回答的是
「**是哪几件事凑在一起才排不出来,松开哪一个就好了**」,并附上具体数字。

两条路径,先廉价后昂贵:

1. **pre-flight**:必要条件不成立(某位教师配课 30 节但只有 21 格可排)。
   这已经是证明,而且数字现成,不必启动 solver。
2. **逐项验证**:必要条件全数通过却仍然无解——代表是几条约束**交互作用**的结果,
   单看任何一条都很合理。此时把每个「教学组长转得动的旋钮」逐一关掉重解,
   看哪一个关掉之后就排得出来。

第 2 条路径正是差异化所在。例:两位音乐老师各教 15 节、各自都有充裕的可排时段,
音乐教室一周也有 35 格——每一项单独看都宽松。但两人都不排周五,音乐教室周五就
没人能用,实际只有 28 格要塞 30 节课。这种「数字都对、凑起来就是不行」的情形,
任何逐项检查都抓不到。

**为什么不用 CP-SAT 的 assumption / unsat core?**
原本的设计(architecture.md §3.4)是每类硬约束挂 assumption literal,无解时取
unsat core。实测不可行:挂上 enforcement literal 之后,presolve 认不出「30 节课
塞进 28 格」的鸽笼结构,同一个问题从 **0.8 秒证完变成 60 秒证不完**。
改用「关掉一组约束 → 重新求解」的删除法后,每次求解都是完整 presolve 过的干净模型,
上例整套定位约 3 秒。附带的好处是每一条结论都被一次真实的求解验证过:
报告说「放宽音乐师1 的不可排时段就排得出来」,是因为真的排出来了。

本模组属于 `app.solver`,不得 import `app.models` / SQLAlchemy(见 problem.py)。
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from app.solver import preflight
from app.solver.model_builder import (
    RELAXABLE_CODES,
    RELAXABLE_NAMES,
    ConstraintTag,
    check_feasibility,
)
from app.solver.problem import (
    AssignmentSpec,
    ClassSpec,
    Problem,
    RoomSpec,
    Slot,
    SolverConfig,
    TeacherSpec,
    max_non_overlapping,
)
from app.solver.week_parity import fmt_periods

# 冲突定位的默认时间预算。求解本身可能跑十分钟,但「为什么排不出来」要尽快回答;
# 拖太久的话,教学组长会直接关掉视窗。
DEFAULT_MAX_SECONDS = 60.0
# 单次试解的上限。试解要嘛很快找到解(该项是成因),要嘛很快证明仍然无解;
# 卡住的那种对定位没有帮助,不值得等。
STEP_SECONDS = 15.0


@dataclass(frozen=True, slots=True)
class Cause:
    """一条「造成无解」的原因。message 说发生什么事,suggestion 说可以怎么办。"""

    code: str  # H3 / H4 / H9 / H10 / structural,或 pre-flight 的检查代码
    scope_type: str  # class / teacher / room / assignment / semester
    scope_id: int
    scope_name: str
    message: str
    suggestion: str
    relaxable: bool = False  # 可在「部分排课」中勾选放宽
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ConflictReport:
    status: str  # infeasible / feasible / unknown
    source: str  # preflight / analysis / none
    causes: tuple[Cause, ...] = ()
    # each:放宽任一项即可解决。joint:必须一起处理。structural:旋钮转到底仍无解。
    mode: str = ""
    wall_time: float = 0.0
    complete: bool = True  # 是否把所有可调项目都试过(时间用完时为 False)

    @property
    def explained(self) -> bool:
        return bool(self.causes)

    @property
    def headline(self) -> str:
        if not self.causes:
            return ""
        if self.source == "preflight":
            return "资料本身就排不出来,以下每一项都必须修正"
        if self.mode == "each":
            # 每一项都经过一次真实求解验证(关掉它就排出来了),即使清单可能不完整
            return f"以下 {len(self.causes)} 项各自都是瓶颈,放宽其中任何一项即可排出课表"
        if self.mode == "joint":
            return "以下项目必须一起处理,只松开其中一项仍然排不出来"
        # structural:只有「全部放宽后仍证明无解」时才敢把话说死;
        # 有任何一次试解在时限内没判定出来,就不能宣称「即使放宽所有项目仍然无解」。
        if self.complete:
            return "即使放宽所有可调整的项目仍然无解,问题出在配课总量"
        return (
            "放宽所有可调整的项目后仍未排出课表,但部分试解在时限内未能判定;"
            "最可能是配课总量的问题"
        )

    @property
    def relaxable_codes(self) -> tuple[str, ...]:
        """可放宽的约束代码,依原因出现顺序。UI 用来预先勾选「部分排课」选项。"""
        seen: list[str] = []
        for c in self.causes:
            if c.relaxable and c.code not in seen:
                seen.append(c.code)
        return tuple(seen)


class Cancelled(Exception):
    """用户在定位期间按了取消(M6-5)。

    定位最长会跑一分钟。先前这段完全不看取消旗标,用户按了「取消」只能干等,
    最后还拿到一份 failed 报告——他明明已经说不要了。
    """


def explain(
    problem: Problem,
    *,
    config: SolverConfig | None = None,
    max_seconds: float = DEFAULT_MAX_SECONDS,
    should_stop: Callable[[], bool] | None = None,
) -> ConflictReport:
    """为什么排不出来。

    `should_stop` 回 True 时掷出 `Cancelled`:定位是「反复试解」的回圈,能中断的
    只有两次试解之间(CP-SAT 单次求解上限为 STEP_SECONDS,故最慢数秒内就会回应)。
    """
    config = config or SolverConfig()

    report = preflight.run(problem)
    if not report.ok:
        return ConflictReport(
            status="infeasible",
            source="preflight",
            causes=tuple(_from_issue(problem, i) for i in report.errors),
        )

    started = time.monotonic()
    deadline = started + max_seconds
    _raise_if_cancelled(should_stop)

    base = check_feasibility(problem, config=config, max_seconds=_step(deadline))
    if base != "infeasible":
        status = "feasible" if base == "feasible" else "unknown"
        return ConflictReport(status, "none", wall_time=time.monotonic() - started)

    knobs = _knobs(problem, config)
    tags, mode, complete = _locate(problem, config, knobs, deadline, should_stop)
    causes = tuple(_describe(problem, tag, config) for tag in tags)
    if mode == "structural":
        causes = _structural_causes(problem)

    return ConflictReport(
        status="infeasible", source="analysis", causes=causes, mode=mode,
        wall_time=time.monotonic() - started, complete=complete,
    )


def _step(deadline: float) -> float:
    return max(1.0, min(STEP_SECONDS, deadline - time.monotonic()))


def _raise_if_cancelled(should_stop: Callable[[], bool] | None) -> None:
    if should_stop and should_stop():
        raise Cancelled


# ── 定位 ───────────────────────────────────────────────────
class _Prober:
    """反复试解,并记住「有没有哪一次没能得到确定的答案」。

    `check_feasibility` 回 unknown 时,我们只能保守地当作「没能证明可行」——
    但那**不等于**已证明不可行。若不追踪这件事,报告会拿一个从未被证明的结论
    (「即使放宽所有项目仍然无解」)讲得斩钉截铁。`certain` 就是这份诚实。
    """

    def __init__(
        self,
        problem: Problem,
        config: SolverConfig,
        deadline: float,
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        self._problem = problem
        self._config = config
        self._deadline = deadline
        self._should_stop = should_stop
        self.certain = True  # 每一次试解都在时限内得到确定答案

    @property
    def out_of_time(self) -> bool:
        return time.monotonic() >= self._deadline

    def feasible_without(self, disabled: set[ConstraintTag]) -> bool:
        # 每次试解前检查取消:定位是「反复试解」的回圈,只有在两次试解之间能中断
        _raise_if_cancelled(self._should_stop)
        if self.out_of_time:
            self.certain = False
            return False
        status = check_feasibility(
            problem=self._problem, config=self._config, disabled=frozenset(disabled),
            max_seconds=_step(self._deadline),
        )
        if status == "unknown":
            self.certain = False
        return status == "feasible"


def _locate(
    problem: Problem,
    config: SolverConfig,
    knobs: list[ConstraintTag],
    deadline: float,
    should_stop: Callable[[], bool] | None = None,
) -> tuple[list[ConstraintTag], str, bool]:
    """逐一关掉每个旋钮重解,看谁是瓶颈。"""
    probe = _Prober(problem, config, deadline, should_stop)

    critical: list[ConstraintTag] = []
    for tag in knobs:
        if probe.out_of_time:
            probe.certain = False
            break
        if probe.feasible_without({tag}):
            critical.append(tag)  # 只松开这一项就排得出来 → 它就是瓶颈

    if critical:
        # 每一个 critical 都被一次真实求解验证过,结论本身可信;
        # certain 只影响「清单是否完整」。
        return critical, "each", probe.certain

    # 没有单一项目能解决:要嘛需要同时松开多项,要嘛连全部松开都不够
    if not knobs or not probe.feasible_without(set(knobs)):
        return [], "structural", probe.certain
    return _joint(probe, knobs), "joint", probe.certain


def _joint(probe: _Prober, knobs: list[ConstraintTag]) -> list[ConstraintTag]:
    """需要同时松开多项时,找一组够小的组合:先累加到可行,再逐一试著拿掉。"""
    disabled: set[ConstraintTag] = set()
    for tag in knobs:
        disabled.add(tag)
        if probe.feasible_without(disabled):
            break
        if probe.out_of_time:
            probe.certain = False
            break

    for tag in list(disabled):
        if probe.out_of_time:
            probe.certain = False  # 剩下的没试过 → 这组未必是最小的
            break
        if probe.feasible_without(disabled - {tag}):
            disabled.discard(tag)  # 少了它照样可行 → 它不是必要的
    return [t for t in knobs if t in disabled]


def _knobs(problem: Problem, config: SolverConfig) -> list[ConstraintTag]:
    """教学组长转得动的旋钮,依「有多紧」由紧到松排序。

    H1(班级同时段一门课)与 H2(教师同时段一门课)不在此列:它们没有旋钮可转,
    而且真正的成因(某位教师配课超过可排格数)pre-flight 已经算得出来。
    """
    scored: list[tuple[float, ConstraintTag]] = []

    for room in problem.rooms.values():
        if not _room_users(problem, room):
            continue
        demand, _supply, usable, _pool = _room_numbers(problem, room)
        scored.append((demand / max(usable, 1), ConstraintTag("H3", "room", room.id)))

    for teacher in problem.teachers.values():
        if not teacher.unavailable or not problem.assignments_of_teacher(teacher.id):
            continue
        if _blocked_slots(problem, teacher) == 0:
            continue  # 不可排时段全落在午休之类的非上课格位,挡不住任何课
        assigned, available = _teacher_numbers(problem, teacher)
        scored.append((assigned / max(available, 1), ConstraintTag("H4", "teacher", teacher.id)))

    tightest = max(
        (_cap_ratio(problem, cls, sid, config)
         for cls in problem.classes.values()
         for sid in _subject_ids_of(problem, cls)),
        default=0.0,
    )
    if tightest > 0:
        scored.append((tightest, ConstraintTag("H10", "semester", problem.semester_id)))

    if any(f.locked for f in problem.fixed_entries):
        scored.append((1.0, ConstraintTag("H9", "semester", problem.semester_id)))

    scored.sort(key=lambda p: -p[0])
    return [tag for _score, tag in scored]


# ── pre-flight 错误 → 原因 ─────────────────────────────────
_PREFLIGHT_SUGGESTIONS = {
    "teacher_overload": "减少该教师的配课节数,或放宽其不可排时段",
    "class_overload": "减少该班配课节数,或在节次表增加一般课节次",
    "room_supply": "增设同类型场地,或把部分课移到其他场地",
    "room_type_supply": "增设该类型的场地,或减少需要此类型场地的课",
    "block_infeasible": "缩短连堂长度,或调整节次表让连续的一般课更长",
    "block_exceeds_periods": "调整连堂设置,使连堂节数不超过每周节数",
    "group_shape_mismatch": "让跑班群组内各门课的每周节数与连堂结构一致",
    "group_teacher_duplicate": "同一个跑班群组内,每位教师只留一笔配课",
    "alternate_incomplete": "单双周组补齐单周、双周各一笔配课",
    "no_period_table": "为该班级指派节次表",
    "assignment_without_class": "为该配课指定班级或跑班群组",
}


def _from_issue(problem: Problem, issue: preflight.Issue) -> Cause:
    return Cause(
        code=issue.code,
        scope_type=issue.subject_type,
        scope_id=issue.subject_id,
        scope_name=_scope_name(problem, issue.subject_type, issue.subject_id),
        message=issue.message,
        suggestion=_PREFLIGHT_SUGGESTIONS.get(issue.code, "请修正上述资料"),
        detail=dict(issue.detail),
    )


def _scope_name(problem: Problem, scope_type: str, scope_id: int) -> str:
    if scope_type == "teacher" and scope_id in problem.teachers:
        return problem.teachers[scope_id].name
    if scope_type == "class" and scope_id in problem.classes:
        return problem.classes[scope_id].name
    if scope_type == "room" and scope_id in problem.rooms:
        return problem.rooms[scope_id].name
    if scope_type == "assignment":
        a = next((a for a in problem.assignments if a.id == scope_id), None)
        if a is not None:
            return a.subject_name
    return problem.semester_label


# ── 旋钮 → 人话 ────────────────────────────────────────────
def _describe(problem: Problem, tag: ConstraintTag, config: SolverConfig) -> Cause:
    builders = {
        "H3": _room_cause,
        "H4": _unavailable_cause,
        "H9": _locked_cause,
        "H10": _daily_cap_cause,
    }
    build = builders[tag.code]
    return build(problem, tag, config)


def _room_cause(problem: Problem, tag: ConstraintTag, _config: SolverConfig) -> Cause:
    room = problem.rooms[tag.scope_id]
    demand, supply, usable, pool = _room_numbers(problem, room)

    # 需求是「用到这间教室的那些课」的总和,供给就必须是「它们可用的那些教室」的总和。
    # 两者的范围不一致(池需求 vs 单间供给)会凭空放大缺口,数字错一次信任就没了。
    if len(pool) > 1:
        names = "、".join(r.name for r in pool)
        where = f"这 {len(pool)} 间场地({names})"
    else:
        where = f"场地「{room.name}」"

    if usable < supply:
        message = (
            f"{where}需求 {fmt_periods(demand)} 节,但扣除相关教师的不可排时段后"
            f"只剩 {usable} 节可用(合计一周共 {supply} 节)"
        )
    else:
        message = f"{where}需求 {fmt_periods(demand)} 节,可用 {usable} 节,同时段每间只能容纳一班"

    return Cause(
        "H3", "room", room.id, room.name, message,
        "增设同类型场地、把部分课移到其他场地,或放宽使用该场地之教师的不可排时段",
        _relaxable("H3"),
        {"demand": demand, "supply": supply, "usable": usable, "rooms": len(pool)},
    )


def _unavailable_cause(problem: Problem, tag: ConstraintTag, _config: SolverConfig) -> Cause:
    teacher = problem.teachers[tag.scope_id]
    assigned, available = _teacher_numbers(problem, teacher)
    blocked = _blocked_slots(problem, teacher)
    return Cause(
        "H4", "teacher", teacher.id, teacher.name,
        f"教师{teacher.name} 有 {blocked} 格不可排时段,扣除后只剩 {available} 格"
        f"可安排 {fmt_periods(assigned)} 节课,挡住了排课",
        f"放宽 {teacher.name} 的不可排时段(或在部分排课中勾选放宽此项)",
        _relaxable("H4"),
        {"assigned": assigned, "available": available, "unavailable": blocked},
    )


def _locked_cause(problem: Problem, tag: ConstraintTag, _config: SolverConfig) -> Cause:
    locked = [f for f in problem.fixed_entries if f.locked]
    by_id = {a.id: a for a in problem.assignments}
    sample = "、".join(
        f"「{by_id[f.assignment_id].subject_name}」"
        f"{_cell_label(problem, by_id[f.assignment_id], f.weekday, f.period_no)}"
        for f in locked[:3]
        if f.assignment_id in by_id
    )
    tail = f"(共 {len(locked)} 格)" if len(locked) > 3 else ""
    return Cause(
        # 全校性的旋钮没有「某位教师」「某间场地」可指,scope_name 用旋钮本身的名字,
        # 学期名称对读报告的人毫无信息。
        "H9", "semester", tag.scope_id, RELAXABLE_NAMES["H9"],
        f"来源草稿中被锁定的格位与其他限制冲突:{sample}{tail}",
        "解除这些格位的锁定,或改动与它们冲突的其他课",
        _relaxable("H9"),
        {"locked": len(locked)},
    )


def _daily_cap_cause(problem: Problem, tag: ConstraintTag, config: SolverConfig) -> Cause:
    cap = config.daily_subject_cap
    over = _over_cap_pairs(problem, config)
    if over:
        cls, subject_name, singles, ceiling, days = over[0]
        extra = f",另有 {len(over) - 1} 组同样超量" if len(over) > 1 else ""
        message = (
            f"班级 {cls.name}「{subject_name}」有 {singles} 节单节课,"
            f"但每日上限 {cap} 节 × {days} 天最多只能排 {ceiling} 节{extra}"
        )
        detail = {"cap": cap, "singles": singles, "ceiling": ceiling, "over_pairs": len(over)}
    else:
        message = (
            f"「同班同科目每日至多 {cap} 节」的限制与其他条件一起造成无解"
            f"(单看任何一个班级都没有超量)"
        )
        detail = {"cap": cap, "over_pairs": 0}

    return Cause(
        "H10", "semester", tag.scope_id, RELAXABLE_NAMES["H10"], message,
        "提高「同班同科目每日节数上限」,或把部分节数改为连堂"
        "(连堂是一次上完的整块,不计入每日上限)",
        _relaxable("H10"),
        detail,
    )


def _structural_causes(problem: Problem) -> tuple[Cause, ...]:
    """所有旋钮都转到底仍然无解:问题出在配课总量与可排格数的硬碰硬。

    列出最吃紧的班级与教师——pre-flight 没报错只代表没有单一项目超量,
    但凑在一起就是塞不下。
    """
    rows: list[tuple[float, Cause]] = []
    for cls in problem.classes.values():
        used, capacity = _class_numbers(problem, cls)
        if capacity:
            rows.append((used / capacity, Cause(
                "structural", "class", cls.id, cls.name,
                f"班级 {cls.name} 每周配课 {used} 节,可排节次 {capacity} 格",
                "减少该班配课节数,或在节次表增加一般课节次",
                detail={"assigned": used, "capacity": capacity},
            )))
    for teacher in problem.teachers.values():
        assigned, available = _teacher_numbers(problem, teacher)
        if assigned and available:
            rows.append((assigned / available, Cause(
                "structural", "teacher", teacher.id, teacher.name,
                f"教师{teacher.name} 配课 {fmt_periods(assigned)} 节,可排时段 {available} 格",
                f"减少 {teacher.name} 的配课,或改由其他教师分担",
                detail={"assigned": assigned, "available": available},
            )))
    rows.sort(key=lambda r: -r[0])
    return tuple(c for _score, c in rows[:5])


def _relaxable(code: str) -> bool:
    return code in RELAXABLE_CODES


# ── 数字 ───────────────────────────────────────────────────
def _class_numbers(problem: Problem, cls: ClassSpec) -> tuple[int, int]:
    used = sum(
        problem.unit_slot_consumption(u.id)
        for u in problem.units.values()
        if cls.id in u.class_ids
    )
    table = problem.tables.get(cls.period_table_id)
    return used, len(table.slots) if table else 0


def _teacher_numbers(problem: Problem, teacher: TeacherSpec) -> tuple[float, int]:
    assigned = sum(a.weekly_load for a in problem.assignments_of_teacher(teacher.id))
    return assigned, preflight.teacher_available_slots(problem, teacher)


def _blocked_slots(problem: Problem, teacher: TeacherSpec) -> int:
    """不可排时段中,真正落在一般课节次上的格数(设在午休上的规则不挡住任何课)。"""
    cells = {s.key for table in problem.tables_of_teacher(teacher.id) for s in table.slots}
    return len(cells & teacher.unavailable)


def _room_users(problem: Problem, room: RoomSpec) -> list[AssignmentSpec]:
    bound = [a for a in problem.assignments if a.room_id == room.id]
    if bound:
        return bound
    # 未绑定场地、由引擎在候选中挑选的配课
    return [
        a for a in problem.assignments
        if a.room_id is None
        and a.required_room_type == room.room_type
        and (not room.subject_ids or a.subject_id in room.subject_ids)
    ]


def _room_pool(problem: Problem, room: RoomSpec) -> tuple[RoomSpec, ...]:
    """与 room 一起承担同一批课的场地。

    已绑定场地的课只能用那一间;未绑定、只指定类型的课则可用整个候选池,
    供给必须以整池计算。
    """
    if any(a.room_id == room.id for a in problem.assignments):
        return (room,)
    users = {a.id for a in _room_users(problem, room)}
    return tuple(
        r
        for r in problem.rooms.values()
        if r.room_type == room.room_type
        and users & {a.id for a in _room_users(problem, r)}
    )


def _room_numbers(
    problem: Problem, room: RoomSpec
) -> tuple[float, int, int, tuple[RoomSpec, ...]]:
    """(需求节数, 候选池一周合计节次数, 扣掉相关教师不可排时段后可用的节次数, 候选池)。"""
    users = _room_users(problem, room)
    demand = sum(a.weekly_load for a in users)
    pool = _room_pool(problem, room)

    all_slots: dict[tuple[int, int, int], Slot] = {}
    free_slots: dict[tuple[int, int, int], Slot] = {}
    for a in users:
        table = problem.table_of(a)
        if table is None:
            continue
        forbidden = {
            cell
            for tid in a.teacher_ids
            if tid in problem.teachers
            for cell in problem.teachers[tid].unavailable
        }
        for s in table.slots:
            all_slots[(table.id, *s.key)] = s
            if s.key not in forbidden:
                free_slots[(table.id, *s.key)] = s

    rooms = max(len(pool), 1)
    supply = max_non_overlapping(list(all_slots.values())) * rooms
    usable = max_non_overlapping(list(free_slots.values())) * rooms
    return demand, supply, usable, pool


def _subject_ids_of(problem: Problem, cls: ClassSpec) -> set[int]:
    return {
        a.subject_id
        for a in problem.assignments
        if cls.id in problem.units[a.unit_id].class_ids
    }


def _subject_singles(problem: Problem, cls: ClassSpec, subject_id: int) -> tuple[int, str]:
    """该班该科目的「单节」总数(连堂不计入每日上限)与科目名称。"""
    singles = 0
    name = str(subject_id)
    for a in problem.assignments:
        if a.subject_id != subject_id or cls.id not in problem.units[a.unit_id].class_ids:
            continue
        name = a.subject_name
        singles += a.periods_per_week - a.block_periods
    return singles, name


def _cap_ratio(problem: Problem, cls: ClassSpec, subject_id: int, config: SolverConfig) -> float:
    singles, _name = _subject_singles(problem, cls, subject_id)
    table = problem.tables.get(cls.period_table_id)
    ceiling = config.daily_subject_cap * (table.num_weekdays if table else 0)
    return singles / ceiling if ceiling else 0.0


def _over_cap_pairs(
    problem: Problem, config: SolverConfig
) -> list[tuple[ClassSpec, str, int, int, int]]:
    """(班级, 科目, 单节数, 每周上限, 天数),依超量程度排序。"""
    out = []
    for cls in problem.classes.values():
        table = problem.tables.get(cls.period_table_id)
        days = table.num_weekdays if table else 0
        ceiling = config.daily_subject_cap * days
        for sid in _subject_ids_of(problem, cls):
            singles, name = _subject_singles(problem, cls, sid)
            if ceiling and singles > ceiling:
                out.append((cls, name, singles, ceiling, days))
    out.sort(key=lambda r: r[3] - r[2])
    return out


def _cell_label(problem: Problem, a: AssignmentSpec, weekday: int, period_no: int) -> str:
    """「周二第三节」——一律用节次表里的名称,不用内部的节次编号。"""
    names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    day = names[weekday - 1] if 1 <= weekday <= 7 else f"星期{weekday}"
    table = problem.table_of(a)
    slot = table.slot(weekday, period_no) if table else None
    return f"{day}{slot.name}" if slot else f"{day}第 {period_no} 格"


__all__ = [
    "DEFAULT_MAX_SECONDS",
    "RELAXABLE_CODES",
    "RELAXABLE_NAMES",
    "Cause",
    "ConflictReport",
    "explain",
]
