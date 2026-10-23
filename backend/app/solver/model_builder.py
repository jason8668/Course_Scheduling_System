"""CP-SAT 硬约束建模(architecture.md §3.2 H1–H10)。

**建模概念**

- 排课的最小单位是 *course*:单班配课各自一个;跑班群组整组一个(H7 同进同出)。
- 每个 course 依 `periods_per_week` 与 `block_rule` 拆成若干 **lesson**(节长 1 或连堂长度)。
- 每个 lesson 选一个 **起始节次候选**;候选只涵盖「连续且皆为一般课」的区段(H5+H6),
  且已剔除任一授课教师不可排的时段(H4 以缩小定义域的方式处理,比加约束便宜)。
- `x[course, lesson, candidate]` 恰选一个 → 周节数守恒(H8)自动成立。
- `occ[course, cell]` 为该 course 是否占用该格,连结到 x;等式(而非 ≤)同时保证
  同一 course 的两个 lesson 不会压在同一格。

H1/H2/H3 皆为「同一资源同时段至多一个」;跨节次表时「同时段」以墙钟重叠判定(D7)。
场地一律互斥,容量不参与求解(D8)。
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from ortools.sat.python import cp_model

from app.solver.preflight import duplicate_group_teachers
from app.solver.problem import (
    MAX_WEIGHT,
    MORNING_END_MIN,
    AssignmentSpec,
    PeriodTableSpec,
    Problem,
    Slot,
    SolvedEntry,
    SolverConfig,
    UnitSpec,
    slots_overlap,
)
from app.solver.week_parity import PARITIES

logger = logging.getLogger(__name__)

Cell = tuple[int, int]  # (weekday, period_no)
# 软约束的惩罚项:线性运算式,或常数 0(该项在此问题中无适用对象)
_Penalty = cp_model.LinearExpr | int

# 可放宽为软约束的硬约束(M3-5 部分排课)。
# H1/H2/H3 不在此列:一位教师不能同时出现在两间教室、一间教室不能同时容纳两班——
# 那是物理,不是政策。放宽它们只会产生一张没有人能照著上课的课表。
RELAXABLE_CODES = ("H4", "H9", "H10")

RELAXABLE_NAMES = {
    "H4": "教师不可排时段",
    "H9": "锁定的格位",
    "H10": "同班同科目每日节数上限",
}


class SolverInputError(Exception):
    """问题描述本身不合法(通常 pre-flight 应先拦下)。"""


@dataclass(frozen=True, slots=True)
class ConstraintTag:
    """一组硬约束的身分,用来在冲突定位时整组关掉。

    scope 刻意取「教学组长改得动的东西」:某位教师的不可排时段、某间场地的互斥、
    全校的每日科目上限——而不是「第 8371 条线性约束」。
    H9/H10 是全校一个开关,scope 即为学期。
    """

    code: str  # H1 / H2 / H3 / H4 / H9 / H10
    scope_type: str  # class / teacher / room / semester
    scope_id: int


@dataclass(frozen=True, slots=True)
class Relaxation:
    """部分排课:放宽选定的硬约束,并允许少数课务未排入。

    惩罚量级刻意拉开:未排入 ≫ 违反被放宽的约束 ≫ 软约束。
    教学组长勾了「可放宽教师不可排时段」,意思就是「宁可让老师委屈一节,
    也不要让这门课排不进去」。
    """

    soft_codes: frozenset[str] = frozenset()
    allow_unplaced: bool = True
    unplaced_penalty: int = 10_000
    violation_penalty: int = 1_000

    def __post_init__(self) -> None:
        unknown = set(self.soft_codes) - set(RELAXABLE_CODES)
        if unknown:
            raise SolverInputError(
                f"这些硬约束不可放宽:{'、'.join(sorted(unknown))}"
                f"(可放宽的只有 {'、'.join(RELAXABLE_CODES)})"
            )
        # 量级必须严格递减,否则 solver 会用「丢掉一节课」去换软约束的分数。
        # 软约束端的保证来自 problem.MAX_WEIGHT(见该处说明)。
        if not self.unplaced_penalty > self.violation_penalty > MAX_WEIGHT * 8:
            raise SolverInputError(
                "部分排课的惩罚量级必须是:未排入 > 放宽的硬约束 > 软约束的最大总和"
            )

    def is_soft(self, code: str) -> bool:
        return code in self.soft_codes


@dataclass(frozen=True, slots=True)
class UnscheduledCourse:
    """部分排课下未能排入的课务。

    **以「排课单位」为一笔,不是以配课为一笔**(M6-3):跑班群组同时段开课,一个时段
    掉下来就是掉一节课;若对群组内每笔成员配课各记一次,「未排 N 节」会灌水成员数倍
    (5 个班的跑班掉 1 节会报成 5 节)。`assignment_ids` 保留群组内所有成员配课,
    供前端与后续处理定位。
    """

    assignment_ids: tuple[int, ...]
    subject_name: str
    class_names: tuple[str, ...]
    periods: int           # 未排入的节数(每个时段只算一次)
    reason: str = ""       # 完全排不下时的原因;solver 主动取舍掉的则留空

@dataclass(frozen=True, slots=True)
class SolveOptions:
    max_seconds: float = 600.0  # 默认 timeout 10 分钟(architecture.md §3.3)
    workers: int = 8
    random_seed: int = 0


@dataclass(frozen=True, slots=True)
class SolveProgress:
    """每找到一个(更好的)解时回报。"""

    solutions: int
    objective: float
    elapsed: float


@dataclass(frozen=True, slots=True)
class SolveControl:
    """求解过程的观测与中断。

    CP-SAT 是 anytime solver:`should_stop()` 回 True 时停止搜寻并保留当下最佳解,
    不是丢弃结果。`on_tick` 由背景执行绪定期呼叫,即使长时间找不到新解也会回报
    (worker 据此送出心跳,前端才不会对著一个已死的工作程序永远转圈)。
    """

    on_progress: Callable[[SolveProgress], None] | None = None
    on_tick: Callable[[float], None] | None = None
    should_stop: Callable[[], bool] | None = None
    tick_seconds: float = 2.0


@dataclass(frozen=True, slots=True)
class SolveResult:
    status: str  # optimal / feasible / infeasible / unknown
    entries: tuple[SolvedEntry, ...]
    # 软约束加权惩罚(越小越好);纯硬约束模式为 0。
    # 与 report.SoftReport.total_penalty 尺度不同,见 report.py 说明。
    objective: float
    wall_time: float
    branches: int
    conflicts: int
    # 部分排课模式下未能排入的课务;一般模式恒为空(H8 周节数守恒是硬约束)
    unscheduled: tuple[UnscheduledCourse, ...] = ()

    @property
    def solved(self) -> bool:
        return self.status in ("optimal", "feasible")

    @property
    def unplaced_periods(self) -> int:
        return sum(u.periods for u in self.unscheduled)


@dataclass(frozen=True, slots=True)
class _Candidate:
    weekday: int
    period_no: int
    cells: tuple[Cell, ...]


@dataclass(frozen=True, slots=True)
class _Course:
    key: tuple[str, int]
    unit: UnitSpec
    assignments: tuple[AssignmentSpec, ...]
    table: PeriodTableSpec
    lengths: tuple[int, ...]  # 每个 lesson 的节长
    teacher_ids: frozenset[int]

    @property
    def subject_ids(self) -> frozenset[int]:
        return frozenset(a.subject_id for a in self.assignments)

    def weeks_of_teacher(self, teacher_id: int) -> frozenset[str]:
        """这位教师在这门课占用哪几周:每周的课两周都占;单双周组只占他那一周。"""
        weeks: set[str] = set()
        for a in self.assignments:
            if teacher_id in a.teacher_ids:
                weeks |= {a.week_parity} if a.week_parity else set(PARITIES)
        return frozenset(weeks)


# ── 候选时段 ────────────────────────────────────────────────
def _runs(table: PeriodTableSpec) -> list[list[Slot]]:
    """节次表中「连续的一般课」区段。连堂只能落在同一个区段内(H6 不跨午休)。"""
    runs: list[list[Slot]] = []
    current: list[Slot] = []
    for slot in table.slots:
        if current and current[-1].weekday == slot.weekday and (
            current[-1].period_no + 1 == slot.period_no
        ):
            current.append(slot)
        else:
            if current:
                runs.append(current)
            current = [slot]
    if current:
        runs.append(current)
    return runs


def _candidates(
    table: PeriodTableSpec, length: int, forbidden: frozenset[Cell]
) -> list[_Candidate]:
    out: list[_Candidate] = []
    for run in _runs(table):
        for i in range(len(run) - length + 1):
            cells = tuple(s.key for s in run[i : i + length])
            if any(c in forbidden for c in cells):
                continue  # H4:任一授课教师不可排 → 直接不进定义域
            out.append(_Candidate(run[i].weekday, run[i].period_no, cells))
    return out


def _lengths(a: AssignmentSpec) -> tuple[int, ...]:
    out: list[int] = []
    for b in a.blocks:
        out.extend([b.size] * b.count)
    out.extend([1] * (a.periods_per_week - a.block_periods))
    return tuple(out)


def _build_courses(problem: Problem) -> list[_Course]:
    courses: list[_Course] = []
    for unit in problem.units.values():
        members = [a for a in problem.assignments if a.unit_id == unit.id]
        if not members:
            continue
        table = problem.table_of(members[0])
        if table is None:
            raise SolverInputError(f"排课单位「{unit.name}」的班级没有节次表")

        if unit.is_bundle:
            shapes = {(a.periods_per_week, a.blocks) for a in members}
            if len(shapes) > 1:
                kind = "单双周组" if unit.is_alternate else "跑班群组"
                raise SolverInputError(
                    f"{kind}「{unit.name}」的各门课节数/连堂结构不一致,无法同时段开课"
                )
            # 下面把群组的教师合并成集合,重复的人会被当成一次——H2 就看不出他同一节上两堂
            for tid, count in duplicate_group_teachers(members).items():
                teacher = problem.teachers.get(tid)
                raise SolverInputError(
                    f"跑班群组「{unit.name}」里,教师{teacher.name if teacher else tid} 有 "
                    f"{count} 笔配课,同一节无法上 {count} 堂课"
                )
            courses.append(_Course(
                key=("unit", unit.id), unit=unit, assignments=tuple(members), table=table,
                lengths=_lengths(members[0]),
                teacher_ids=frozenset(t for a in members for t in a.teacher_ids),
            ))
        else:
            for a in members:
                courses.append(_Course(
                    key=("assignment", a.id), unit=unit, assignments=(a,), table=table,
                    lengths=_lengths(a), teacher_ids=frozenset(a.teacher_ids),
                ))
    return courses


def _candidate_rooms(problem: Problem, a: AssignmentSpec) -> list[int]:
    return [
        r.id
        for r in problem.rooms.values()
        if r.room_type == a.required_room_type
        and (not r.subject_ids or a.subject_id in r.subject_ids)
    ]


class _Model:
    """三种建模模式共用一份程序码,差别只在「一条硬约束怎么挂上去」。

    - 一般:全部硬约束照常加入。
    - disabled:指定的几组硬约束**整组不加**。冲突定位靠反复重建这样的模型来
      验证「关掉这一项是不是就有解了」。刻意不用 CP-SAT 的 assumption 机制:
      assumption literal 会让 presolve 认不出「N 节课塞进 M 格」的鸽笼结构,
      同一个问题从 0.8 秒证完变成 60 秒证不完(见 conflict_explainer.py 说明)。
    - relax:选定的类别改为高权重惩罚项,并允许 lesson 不排入(部分排课)。
      放宽 H4 时不能预先把不可排时段从候选剔除,改为显式惩罚 `occ`。
    """

    def __init__(
        self,
        problem: Problem,
        config: SolverConfig,
        *,
        disabled: frozenset[ConstraintTag] = frozenset(),
        relax: Relaxation | None = None,
    ) -> None:
        if disabled and relax is not None:
            raise SolverInputError("冲突定位与部分排课不可同时启用")
        self.problem = problem
        self.config = config
        self.cap = config.daily_subject_cap
        self.disabled = disabled
        self.relax = relax
        self.m = cp_model.CpModel()
        self.courses = _build_courses(problem)

        self.cands: dict[tuple[int, int], list[_Candidate]] = {}  # (ci, li) → 候选
        self.x: dict[tuple[int, int], list[cp_model.IntVar]] = {}
        self.occ: dict[tuple[int, Cell], cp_model.IntVar] = {}
        self.y: dict[tuple[int, int], cp_model.IntVar] = {}  # (assignment_id, room_id)
        self.drop: dict[tuple[int, int], cp_model.IntVar] = {}  # (ci, li) → 未排入
        # ci → 该课完全无处可排的原因(部分排课下不 raise,列入未排清单并注明,M6-3)
        self.blocked: dict[int, str] = {}
        self.relaxed: list[_Penalty] = []  # 被放宽的硬约束转成的惩罚项
        # 教师是否在某节次上课;依星期分组并按墙钟时间排序(算连续授课与空堂用)
        self.teacher_day: dict[int, dict[int, list[tuple[Slot, cp_model.IntVar]]]] = {}
        self.has_objective = False

        self._make_lesson_vars()
        self._make_room_vars()
        self._h1_class()
        self._h2_teacher()
        self._h3_room()
        self._h4_unavailable()
        self._h10_daily_cap()
        self._h9_locked()

        self._make_teacher_busy()
        self._objective()
        self._hints()

    # ── 模式开关 ────────────────────────
    @property
    def _h4_is_soft(self) -> bool:
        """放宽 H4:不可排时段不再剔除候选,改为可被违反的惩罚项。"""
        return self.relax is not None and self.relax.is_soft("H4")

    def _is_soft(self, code: str) -> bool:
        return self.relax is not None and self.relax.is_soft(code)

    def _off(self, code: str, scope_type: str, scope_id: int) -> bool:
        return ConstraintTag(code, scope_type, scope_id) in self.disabled

    # ── 变数 ────────────────────────────
    def _forbidden(self, course: _Course) -> frozenset[Cell]:
        if self._h4_is_soft:
            return frozenset()  # 改由 _h4_unavailable 表达为惩罚
        cells: set[Cell] = set()
        for tid in course.teacher_ids:
            teacher = self.problem.teachers.get(tid)
            if teacher and not self._off("H4", "teacher", tid):
                cells |= set(teacher.unavailable)
        # 班级校历占用:该 course 所属班级被活动占用的格子同样不可排
        for cid in course.unit.class_ids:
            cls = self.problem.classes.get(cid)
            if cls is not None:
                cells |= set(cls.unavailable)
        return frozenset(cells)

    def _make_lesson_vars(self) -> None:
        allow_drop = self.relax is not None and self.relax.allow_unplaced
        for ci, course in enumerate(self.courses):
            forbidden = self._forbidden(course)
            covering: dict[Cell, list[cp_model.IntVar]] = {}
            pos_by_length: dict[int, list[tuple[int, cp_model.IntVar]]] = {}

            for li, length in enumerate(course.lengths):
                cands = _candidates(course.table, length, forbidden)
                if not cands:
                    reason = (
                        f"找不到任何可排的 {length} 连堂时段"
                        "(节次表或教师不可排时段过于严格)"
                    )
                    if not allow_drop:
                        raise SolverInputError(
                            f"「{course.assignments[0].subject_name}」{reason}"
                        )
                    # 部分排课的承诺就是「排不下的列清单、其他照排」。这门课完全被挡死
                    # (例如协同教学的两位教师不可排时段刚好盖满整周),不能因此让整锅
                    # 部分排课失败——那正是用户最需要它的时候(M6-3)。
                    self._force_drop(ci, li, reason)
                    continue
                xs = [self.m.new_bool_var(f"x{ci}_{li}_{k}") for k in range(len(cands))]
                if allow_drop:
                    # H8 放宽:排入一格,或整节不排入(计入未排清单)
                    d = self.m.new_bool_var(f"d{ci}_{li}")
                    self.m.add(sum(xs) + d == 1)
                    self.drop[(ci, li)] = d
                else:
                    self.m.add_exactly_one(xs)  # H8:每个 lesson 恰排一次
                self.cands[(ci, li)] = cands
                self.x[(ci, li)] = xs
                for xv, cand in zip(xs, cands, strict=True):
                    for cell in cand.cells:
                        covering.setdefault(cell, []).append(xv)

                pos = self.m.new_int_var(0, len(cands) - 1, f"p{ci}_{li}")
                self.m.add(pos == sum(k * xs[k] for k in range(len(cands))))
                pos_by_length.setdefault(length, []).append((li, pos))

            self._break_symmetry(ci, pos_by_length)

            for slot in course.table.slots:
                o = self.m.new_bool_var(f"o{ci}_{slot.weekday}_{slot.period_no}")
                # 等式:同一 course 的两个 lesson 不得压在同一格(sum=2 直接不可行)
                self.m.add(o == sum(covering.get(slot.key, [])))
                self.occ[(ci, slot.key)] = o

    def _force_drop(self, ci: int, li: int, reason: str) -> None:
        """这一节完全无处可排:建一个恒为 1 的 drop 变数,把它送进未排清单。

        不建 x/pos 变数(候选为空,位置变数无意义);占用式(occ)自然不含它。
        惩罚照计(每节 10000),只是变成常数项——不影响最佳化,但让目标值诚实。
        """
        d = self.m.new_bool_var(f"d{ci}_{li}")
        self.m.add(d == 1)
        self.drop[(ci, li)] = d
        self.cands[(ci, li)] = []
        self.x[(ci, li)] = []
        self.blocked[ci] = reason

    def _break_symmetry(
        self, ci: int, pos_by_length: dict[int, list[tuple[int, cp_model.IntVar]]]
    ) -> None:
        """同长度的 lesson 可互换 → 强制递增以消除对称性(候选依时间排序)。

        部分排课下位置变数对「未排入」的 lesson 无意义(恒为 0),故只在两者都排入时
        比较;并要求未排入的 lesson 一律是后面几个,否则 n 个 lesson 少排 1 节
        会有 n 种等价写法。
        """
        for items in pos_by_length.values():
            for (li_a, pa), (li_b, pb) in zip(items, items[1:], strict=False):
                drop_a, drop_b = self.drop.get((ci, li_a)), self.drop.get((ci, li_b))
                if drop_a is None or drop_b is None:
                    self.m.add(pa < pb)
                else:
                    self.m.add(drop_a <= drop_b)
                    self.m.add(pa < pb).only_enforce_if(drop_b.negated())

    def _make_room_vars(self) -> None:
        for course in self.courses:
            for a in course.assignments:
                if a.room_id is not None or not a.required_room_type:
                    continue
                rooms = _candidate_rooms(self.problem, a)
                if not rooms:
                    raise SolverInputError(
                        f"「{a.subject_name}」需要 {a.required_room_type} 类型场地,但学期内没有"
                    )
                ys = [self.m.new_bool_var(f"y{a.id}_{rid}") for rid in rooms]
                self.m.add_exactly_one(ys)  # 一门课整学期固定一间教室
                for rid, yv in zip(rooms, ys, strict=True):
                    self.y[(a.id, rid)] = yv

    # ── 硬约束 ──────────────────────────
    def _courses_of_class(self, class_id: int) -> list[int]:
        return [
            ci for ci, c in enumerate(self.courses) if class_id in c.unit.class_ids
        ]

    def _h1_class(self) -> None:
        for cls in self.problem.classes.values():
            cis = self._courses_of_class(cls.id)
            if len(cis) < 2 or self._off("H1", "class", cls.id):
                continue
            table = self.problem.tables[cls.period_table_id]
            for slot in table.slots:
                self.m.add_at_most_one(self.occ[(ci, slot.key)] for ci in cis)

    def _resource_at_most_one(
        self, entries: list[tuple[int, Slot, cp_model.IntVar]]
    ) -> None:
        """同一资源(教师/场地)在同时段至多一个占用。

        entries 为 (table_id, slot, literal)。同表同节次 → 直接互斥;
        跨表则两两比对墙钟重叠(D7)。单一节次表的学校完全走前者,零额外成本。
        """
        by_key: dict[tuple[int, int, int], list[cp_model.IntVar]] = {}
        slot_of: dict[tuple[int, int, int], tuple[int, Slot]] = {}
        for table_id, slot, lit in entries:
            key = (table_id, slot.weekday, slot.period_no)
            by_key.setdefault(key, []).append(lit)
            slot_of[key] = (table_id, slot)

        for lits in by_key.values():
            if len(lits) > 1:
                self.m.add_at_most_one(lits)

        keys = list(by_key)
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                ta, sa = slot_of[keys[i]]
                tb, sb = slot_of[keys[j]]
                if ta == tb:
                    continue
                if slots_overlap(sa, sb, same_table=False):
                    self.m.add_at_most_one(by_key[keys[i]] + by_key[keys[j]])

    def _h2_teacher(self) -> None:
        """教师同一时段至多一堂课。

        单双周组(v1.3.0)的教师只在他那一周有课:单周在 701、双周在 702 的同一节不算冲堂。
        做法是把「同一时段」分成单周、双周两条线各自互斥;每周的课两条线都占。
        没有任何单双周课的教师只建一条线,与 v1.2 完全相同。
        """
        for teacher_id in self.problem.teachers:
            if self._off("H2", "teacher", teacher_id):
                continue
            items: list[tuple[frozenset[str], tuple[int, Slot, cp_model.IntVar]]] = []
            for ci, course in enumerate(self.courses):
                if teacher_id not in course.teacher_ids:
                    continue
                weeks = course.weeks_of_teacher(teacher_id)
                for slot in course.table.slots:
                    items.append((weeks, (course.table.id, slot, self.occ[(ci, slot.key)])))
            self._resource_by_week(items)

    def _resource_by_week(
        self, items: list[tuple[frozenset[str], tuple[int, Slot, cp_model.IntVar]]]
    ) -> None:
        """依周别建互斥:全部都是每周的课(没有单双周)时只建一次,与 v1.2 相同。"""
        if not items:
            return
        if all(len(weeks) == len(PARITIES) for weeks, _ in items):
            self._resource_at_most_one([item for _, item in items])
            return
        for week in PARITIES:
            line = [item for weeks, item in items if week in weeks]
            if line:
                self._resource_at_most_one(line)

    def _h4_unavailable(self) -> None:
        """教师不可排时段。

        一般模式已在候选阶段剔除(比加约束便宜),整组关掉也只是不剔除;
        只有「放宽 H4」的部分排课才需要把它表达成可以被违反的惩罚项。
        """
        if not self._h4_is_soft or self.relax is None:
            return
        for tid, teacher in self.problem.teachers.items():
            if not teacher.unavailable:
                continue
            lits = [
                self.occ[(ci, cell)]
                for ci, course in enumerate(self.courses)
                if tid in course.teacher_ids
                for cell in teacher.unavailable
                if (ci, cell) in self.occ
            ]
            if lits:
                self.relaxed.append(self.relax.violation_penalty * sum(lits))

    def _h3_room(self) -> None:
        """场地互斥(D8:容量不参与求解)。未绑定场地者由引擎在候选教室中挑一间。"""
        rooms_of_assignment: dict[int, list[int]] = {}
        for a_id, rid in self.y:
            rooms_of_assignment.setdefault(a_id, []).append(rid)

        # 单双周组的课只在单周或双周用教室(v1.3.0),所以和教师一样分两条线互斥
        by_room: dict[int, list[tuple[frozenset[str], tuple[int, Slot, cp_model.IntVar]]]] = {}
        for ci, course in enumerate(self.courses):
            for a in course.assignments:
                weeks = frozenset({a.week_parity} if a.week_parity else PARITIES)
                for slot in course.table.slots:
                    o = self.occ[(ci, slot.key)]
                    if a.room_id is not None:
                        by_room.setdefault(a.room_id, []).append(
                            (weeks, (course.table.id, slot, o)))
                        continue
                    for rid in rooms_of_assignment.get(a.id, []):
                        yv = self.y[(a.id, rid)]
                        # z = o AND y:这一格是否真的用到这间教室
                        z = self.m.new_bool_var(f"z{a.id}_{rid}_{slot.weekday}_{slot.period_no}")
                        self.m.add(z <= o)
                        self.m.add(z <= yv)
                        self.m.add(z >= o + yv - 1)
                        by_room.setdefault(rid, []).append((weeks, (course.table.id, slot, z)))

        for rid, items in by_room.items():
            if not self._off("H3", "room", rid):
                self._resource_by_week(items)

    def _h10_daily_cap(self) -> None:
        """同班同科目每日单节数上限;连堂是一次上完的整块,不计入。"""
        if self._off("H10", "semester", self.problem.semester_id):
            return
        soft = self._is_soft("H10")
        for cls in self.problem.classes.values():
            cis = self._courses_of_class(cls.id)
            subjects = {sid for ci in cis for sid in self.courses[ci].subject_ids}
            for subject_id in subjects:
                for weekday in range(1, self.problem.tables[cls.period_table_id].num_weekdays + 1):
                    lits: list[cp_model.IntVar] = []
                    for ci in cis:
                        course = self.courses[ci]
                        if subject_id not in course.subject_ids:
                            continue
                        for li, length in enumerate(course.lengths):
                            if length != 1:
                                continue
                            for xv, cand in zip(
                                self.x[(ci, li)], self.cands[(ci, li)], strict=True
                            ):
                                if cand.weekday == weekday:
                                    lits.append(xv)
                    if len(lits) <= self.cap:
                        continue  # 一天内根本放不了那么多节,约束恒成立
                    if soft and self.relax is not None:
                        over = self.m.new_int_var(
                            0, len(lits), f"r10_{cls.id}_{subject_id}_{weekday}"
                        )
                        self.m.add(over >= sum(lits) - self.cap)
                        self.relaxed.append(self.relax.violation_penalty * over)
                    else:
                        self.m.add(sum(lits) <= self.cap)

    def _course_of_assignment(self) -> dict[int, int]:
        return {
            a.id: ci
            for ci, course in enumerate(self.courses)
            for a in course.assignments
        }

    def _hints(self) -> None:
        """把来源草稿「未锁定」的格位喂成求解提示(AddHint)。

        重排时尽量少动已排好的课——教学组长不会想看到整张表被打散。
        提示是软的:CP-SAT 会把不可行的提示直接丢掉,不影响正确性。
        锁定的格位已由 _h9_locked 硬性固定,但一并提示可让 lesson 编号对齐。
        """
        if not self.problem.fixed_entries:
            return
        course_of = self._course_of_assignment()

        # (course, 节长) → 该长度的既有格位,依时间排序;对称性约束要求 lesson 位置递增
        by_course_len: dict[tuple[int, int], set[tuple[int, int]]] = {}
        for f in self.problem.fixed_entries:
            ci = course_of.get(f.assignment_id)
            if ci is None:
                continue
            by_course_len.setdefault((ci, f.span), set()).add((f.weekday, f.period_no))

        for (ci, span), cells in by_course_len.items():
            lessons = [li for li, length in enumerate(self.courses[ci].lengths) if length == span]
            for li, cell in zip(lessons, sorted(cells), strict=False):
                cands = self.cands[(ci, li)]
                idx = next(
                    (k for k, c in enumerate(cands) if (c.weekday, c.period_no) == cell), None
                )
                if idx is not None:
                    self.m.add_hint(self.x[(ci, li)][idx], 1)

    def _h9_locked(self) -> None:
        """锁定的格位必须维持原位。

        不指定「哪一个 lesson」占住该格(同长度的 lesson 可互换,绑死会与对称性
        约束打架),只要求「该长度的 lesson 中恰有一个排在这里」。
        """
        if self._off("H9", "semester", self.problem.semester_id):
            return
        course_of = self._course_of_assignment()
        pinned: set[tuple[int, int, int, int]] = set()
        for f in self.problem.fixed_entries:
            if not f.locked or f.assignment_id not in course_of:
                continue
            ci = course_of[f.assignment_id]
            key = (ci, f.weekday, f.period_no, f.span)
            if key in pinned:
                continue  # 跑班群组:多笔兄弟格位对应同一个 course
            pinned.add(key)

            lits: list[cp_model.IntVar] = []
            for li, length in enumerate(self.courses[ci].lengths):
                if length != f.span:
                    continue
                for xv, cand in zip(self.x[(ci, li)], self.cands[(ci, li)], strict=True):
                    if (cand.weekday, cand.period_no) == (f.weekday, f.period_no):
                        lits.append(xv)
            if not lits:
                raise SolverInputError(
                    f"锁定的格位(配课 {f.assignment_id} 周{f.weekday} 第 {f.period_no} 格,"
                    f"{f.span} 节)不是合法的排课位置"
                )
            if self._is_soft("H9") and self.relax is not None:
                # 放宽:允许这一格被搬走,但代价高昂
                moved = self.m.new_bool_var(f"r9_{f.assignment_id}_{f.weekday}_{f.period_no}")
                self.m.add(sum(lits) + moved == 1)
                self.relaxed.append(self.relax.violation_penalty * moved)
                continue

            self.m.add(sum(lits) == 1)
            if f.room_id is not None and (f.assignment_id, f.room_id) in self.y:
                self.m.add(self.y[(f.assignment_id, f.room_id)] == 1)

    # ── 软约束(architecture.md §3.2 S1–S8)────────────────
    def _make_teacher_busy(self) -> None:
        """teacher_day[t][weekday] = [(节次, 该教师是否在此上课), …],依墙钟时间排序。"""
        if not self.config.weights or not any(self.config.weights.values()):
            return  # 只有软约束用得到;纯可行性模型不必建这些变数
        for tid in self.problem.teachers:
            per_cell: dict[tuple[int, int, int], tuple[Slot, list[cp_model.IntVar]]] = {}
            for ci, course in enumerate(self.courses):
                if tid not in course.teacher_ids:
                    continue
                for slot in course.table.slots:
                    key = (course.table.id, slot.weekday, slot.period_no)
                    per_cell.setdefault(key, (slot, []))[1].append(self.occ[(ci, slot.key)])

            by_day: dict[int, list[tuple[Slot, cp_model.IntVar]]] = {}
            for (_table_id, weekday, period_no), (slot, lits) in per_cell.items():
                if len(lits) == 1:
                    busy = lits[0]  # 只教一门课的那一格,占用变数本身就是「是否上课」
                else:
                    busy = self.m.new_bool_var(f"b{tid}_{weekday}_{period_no}")
                    self.m.add(busy == sum(lits))  # H2 已保证至多一个为 1
                by_day.setdefault(weekday, []).append((slot, busy))

            for day in by_day.values():
                day.sort(key=lambda p: (p[0].start_min or 0, p[0].period_no))
            self.teacher_day[tid] = by_day

    def _objective(self) -> None:
        cfg = self.config
        terms: list[_Penalty] = list(self.relaxed)
        if self.relax is not None and self.drop:
            terms.append(self.relax.unplaced_penalty * sum(self.drop.values()))

        def add(code: str, expr: _Penalty) -> None:
            weight = cfg.weight(code)
            if weight:
                terms.append(weight * expr)

        s1_avoid, s1_prefer, unmet_by_teacher = self._s1_preferences()
        add("S1", s1_avoid)
        if cfg.enabled("S1") and s1_prefer is not None:
            terms.append(-cfg.weight("S1") * s1_prefer)  # 偏好达成 = 负惩罚

        add("S2", self._s2_spread())
        add("S3", self._s3_daily_load())
        add("S4", self._s4_gaps())
        add("S5", self._s5_major_in_morning())
        add("S6", self._s6_consecutive())
        add("S7", self._s7_homeroom_first_period())
        add("S8", self._s8_fairness(unmet_by_teacher))

        if terms:
            self.m.minimize(sum(terms))
            self.has_objective = True

    def _s1_preferences(self) -> tuple[_Penalty, _Penalty | None, dict[int, list[cp_model.IntVar]]]:
        """avoid 节次扣分、prefer 节次加分;顺带回传每位教师的未达成数供 S8 使用。"""
        avoid_terms: list[cp_model.IntVar] = []
        prefer_terms: list[cp_model.IntVar] = []
        unmet: dict[int, list[cp_model.IntVar]] = {}
        for tid, by_day in self.teacher_day.items():
            teacher = self.problem.teachers[tid]
            if not teacher.has_preferences:
                continue
            for day in by_day.values():
                for slot, busy in day:
                    if slot.key in teacher.avoid:
                        avoid_terms.append(busy)
                        unmet.setdefault(tid, []).append(busy)
                    elif slot.key in teacher.prefer:
                        prefer_terms.append(busy)
        return (
            sum(avoid_terms) if avoid_terms else 0,
            sum(prefer_terms) if prefer_terms else None,
            unmet,
        )

    def _s2_spread(self) -> _Penalty:
        """同班同科目同日超过 1 节的部分计为惩罚(连堂不计,本来就是同一天上完)。"""
        extras: list[cp_model.IntVar] = []
        for cls in self.problem.classes.values():
            cis = self._courses_of_class(cls.id)
            table = self.problem.tables[cls.period_table_id]
            subjects = {sid for ci in cis for sid in self.courses[ci].subject_ids}
            for subject_id in subjects:
                for weekday in range(1, table.num_weekdays + 1):
                    lits = self._single_lesson_lits(cis, subject_id, weekday)
                    if len(lits) < 2:
                        continue
                    extra = self.m.new_int_var(
                        0, len(lits) - 1, f"s2_{cls.id}_{subject_id}_{weekday}"
                    )
                    self.m.add(extra >= sum(lits) - 1)
                    extras.append(extra)
        return sum(extras) if extras else 0

    def _single_lesson_lits(
        self, cis: list[int], subject_id: int, weekday: int
    ) -> list[cp_model.IntVar]:
        lits: list[cp_model.IntVar] = []
        for ci in cis:
            course = self.courses[ci]
            if subject_id not in course.subject_ids:
                continue
            for li, length in enumerate(course.lengths):
                if length != 1:
                    continue
                for xv, cand in zip(self.x[(ci, li)], self.cands[(ci, li)], strict=True):
                    if cand.weekday == weekday:
                        lits.append(xv)
        return lits

    def _s3_daily_load(self) -> _Penalty:
        overs: list[cp_model.IntVar] = []
        for tid, by_day in self.teacher_day.items():
            for weekday, day in by_day.items():
                over = self.m.new_int_var(0, len(day), f"s3_{tid}_{weekday}")
                self.m.add(over >= sum(b for _s, b in day) - self.config.teacher_daily_max)
                overs.append(over)
        return sum(overs) if overs else 0

    def _s4_gaps(self) -> _Penalty:
        """零碎空堂 = (最后一节 − 第一节 + 1) − 当日节数。目标函数会把 first/last 压紧。"""
        gaps: list[cp_model.IntVar] = []
        for tid, by_day in self.teacher_day.items():
            for weekday, day in by_day.items():
                n = len(day)
                if n < 3:  # 少于 3 格不可能出现中间的空堂
                    continue
                first = self.m.new_int_var(0, n - 1, f"f{tid}_{weekday}")
                last = self.m.new_int_var(0, n - 1, f"l{tid}_{weekday}")
                for i, (_slot, busy) in enumerate(day):
                    self.m.add(first <= i).only_enforce_if(busy)
                    self.m.add(last >= i).only_enforce_if(busy)
                gap = self.m.new_int_var(0, n, f"s4_{tid}_{weekday}")
                self.m.add(gap >= last - first + 1 - sum(b for _s, b in day))
                gaps.append(gap)
        return sum(gaps) if gaps else 0

    def _s5_major_in_morning(self) -> _Penalty:
        afternoon: list[cp_model.IntVar] = []
        for ci, course in enumerate(self.courses):
            if not any(a.subject_is_major for a in course.assignments):
                continue
            for slot in course.table.slots:
                if slot.start_min is not None and slot.start_min >= MORNING_END_MIN:
                    afternoon.append(self.occ[(ci, slot.key)])
        return sum(afternoon) if afternoon else 0

    def _s6_consecutive(self) -> _Penalty:
        """任何 (上限+1) 节的连续视窗中,上课节数不得超过上限;超出部分计为惩罚。"""
        window = self.config.teacher_consecutive_max + 1
        excesses: list[cp_model.IntVar] = []
        for tid, by_day in self.teacher_day.items():
            for weekday, day in by_day.items():
                for i in range(len(day) - window + 1):
                    chunk = [b for _s, b in day[i : i + window]]
                    excess = self.m.new_int_var(0, 1, f"s6_{tid}_{weekday}_{i}")
                    self.m.add(excess >= sum(chunk) - self.config.teacher_consecutive_max)
                    excesses.append(excess)
        return sum(excesses) if excesses else 0

    def _s7_homeroom_first_period(self) -> _Penalty:
        misses: list[cp_model.IntVar] = []
        for cls in self.problem.classes.values():
            tid = cls.homeroom_teacher_id
            if tid is None:
                continue
            table = self.problem.tables[cls.period_table_id]
            cis = [
                ci for ci in self._courses_of_class(cls.id)
                if tid in self.courses[ci].teacher_ids
            ]
            if not cis:
                continue  # 班主任没教这个班 → 这条软约束无从满足,不列入惩罚
            for weekday in range(1, table.num_weekdays + 1):
                day = table.slots_on(weekday)
                if not day:
                    continue
                lits = [self.occ[(ci, day[0].key)] for ci in cis]
                miss = self.m.new_bool_var(f"s7_{cls.id}_{weekday}")
                self.m.add(miss == 1 - sum(lits))
                misses.append(miss)
        return sum(misses) if misses else 0

    def _s8_fairness(self, unmet: dict[int, list[cp_model.IntVar]]) -> _Penalty:
        """最差者优先:压低「偏好未达成最多的那位教师」的未达成节数。"""
        if not unmet:
            return 0
        worst = self.m.new_int_var(0, max(len(v) for v in unmet.values()), "s8_worst")
        for lits in unmet.values():
            self.m.add(worst >= sum(lits))
        return worst

    # ── 取解 ────────────────────────────
    def extract(
        self, solver: cp_model.CpSolver
    ) -> tuple[tuple[SolvedEntry, ...], tuple[UnscheduledCourse, ...]]:
        locked = {
            (f.assignment_id, f.weekday, f.period_no, f.span)
            for f in self.problem.fixed_entries
            if f.locked
        }
        rooms_of: dict[int, int] = {}
        for (a_id, rid), yv in self.y.items():
            if solver.value(yv):
                rooms_of[a_id] = rid

        out: list[SolvedEntry] = []
        # 未排节数以「排课单位(ci)」计:跑班群组同时段开课,掉一个时段就是掉一节课,
        # 不是掉「成员班级数」节(M6-3;先前按配课逐笔记,5 班跑班会报成 5 节)
        unplaced: dict[int, int] = {}
        for ci, course in enumerate(self.courses):
            for li, length in enumerate(course.lengths):
                cands = self.cands[(ci, li)]
                xs = self.x[(ci, li)]
                chosen = next(
                    (c for c, xv in zip(cands, xs, strict=True) if solver.value(xv)), None
                )
                if chosen is None:  # 部分排课:这一节没排进去
                    unplaced[ci] = unplaced.get(ci, 0) + length
                    continue
                span = len(chosen.cells)
                for a in course.assignments:
                    room_id = a.room_id if a.room_id is not None else rooms_of.get(a.id)
                    key = (a.id, chosen.weekday, chosen.period_no, span)
                    out.append(SolvedEntry(
                        assignment_id=a.id, weekday=chosen.weekday,
                        period_no=chosen.period_no, span=span, room_id=room_id,
                        locked=key in locked,
                    ))
        out.sort(key=lambda e: (e.weekday, e.period_no, e.assignment_id))
        return tuple(out), self._unscheduled(unplaced)

    def _unscheduled(self, unplaced: dict[int, int]) -> tuple[UnscheduledCourse, ...]:
        """把「哪个排课单位少排几节」翻成人看得懂的清单(每个单位一笔)。"""
        out = []
        for ci, periods in unplaced.items():
            course = self.courses[ci]
            class_names = sorted(
                self.problem.classes[cid].name for cid in course.unit.class_ids
            )
            # 跑班群组是「多门选修同时段开」,一笔 _Course 含多门课;只印第一门会误导
            subjects = sorted({a.subject_name for a in course.assignments})
            out.append(UnscheduledCourse(
                assignment_ids=tuple(a.id for a in course.assignments),
                subject_name="、".join(subjects),
                class_names=tuple(class_names),
                periods=periods,
                reason=self.blocked.get(ci, ""),
            ))
        out.sort(key=lambda u: (-u.periods, u.subject_name, u.assignment_ids))
        return tuple(out)


_STATUS = {
    cp_model.OPTIMAL: "optimal",
    cp_model.FEASIBLE: "feasible",
    cp_model.INFEASIBLE: "infeasible",
    cp_model.MODEL_INVALID: "invalid",
    cp_model.UNKNOWN: "unknown",
}


def solve(
    problem: Problem,
    options: SolveOptions | None = None,
    *,
    config: SolverConfig | None = None,
    control: SolveControl | None = None,
    relax: Relaxation | None = None,
) -> SolveResult:
    """求解一份完整课表:硬约束必须全满足,软约束以加权目标最小化。

    CP-SAT 是 anytime solver——逾时或被要求提前结束时,仍回传当下最佳解
    (status=feasible)。config 给 `SolverConfig.hard_only()` 即退化为纯可行性问题。
    control 提供进度回报与中断(M3-4 的 worker 据此送心跳、实作「提前结束」)。

    给定 `relax` 即进入**部分排课**:放宽选定的硬约束、允许少数课务未排入,
    因此永远有解(最差是整张表空著)。未排入的课务列在 `result.unscheduled`。
    """
    options = options or SolveOptions()
    config = config or SolverConfig()
    built = _Model(problem, config, relax=relax)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = options.max_seconds
    solver.parameters.num_workers = options.workers
    solver.parameters.random_seed = options.random_seed

    callback = None
    if control and (control.on_progress or control.should_stop):
        callback = _SolutionCallback(control, built.has_objective)

    watcher = _Watcher(solver, control) if control else None
    if watcher:
        watcher.start()
    try:
        status = solver.solve(built.m, callback) if callback else solver.solve(built.m)
    finally:
        if watcher:
            watcher.stop()

    entries: tuple[SolvedEntry, ...] = ()
    unscheduled: tuple[UnscheduledCourse, ...] = ()
    objective = 0.0
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        entries, unscheduled = built.extract(solver)
        objective = solver.objective_value if built.has_objective else 0.0

    return SolveResult(
        status=_STATUS.get(status, "unknown"),
        entries=entries,
        objective=objective,
        wall_time=solver.wall_time,
        branches=solver.num_branches,
        conflicts=solver.num_conflicts,
        unscheduled=unscheduled,
    )


# ── 无解冲突定位(M3-5)──────────────────────────────────────
def check_feasibility(
    problem: Problem,
    *,
    config: SolverConfig | None = None,
    disabled: frozenset[ConstraintTag] = frozenset(),
    max_seconds: float = 10.0,
    workers: int = 8,
) -> str:
    """关掉 `disabled` 这几组硬约束后,课表排得出来吗?

    回传 feasible / infeasible / unknown。不建目标函数——冲突定位只问可行性,
    软约束只会拖慢证明无解的速度。

    建模阶段就拦下的情形(例:某门课完全找不到可排时段)本身就是「排不出来」,
    视为 infeasible 而不是错误——但**讯息一定要留下来**:不记的话,未来任何建模 bug
    都会伪装成「这份资料无解」,查都无从查起(M6-3 顺手修的 Backlog 项)。
    """
    config = (config or SolverConfig()).without_soft()
    try:
        built = _Model(problem, config, disabled=disabled)
    except SolverInputError as exc:
        logger.info("可行性探测于建模阶段判定无解:%s", exc)
        return "infeasible"

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max_seconds
    solver.parameters.num_workers = workers
    status = solver.solve(built.m)
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return "feasible"
    if status == cp_model.INFEASIBLE:
        return "infeasible"
    return "unknown"


class _SolutionCallback(cp_model.CpSolverSolutionCallback):
    def __init__(self, control: SolveControl, has_objective: bool) -> None:
        super().__init__()
        self._control = control
        self._has_objective = has_objective
        self._count = 0

    def on_solution_callback(self) -> None:
        self._count += 1
        if self._control.on_progress:
            self._control.on_progress(SolveProgress(
                solutions=self._count,
                objective=self.objective_value if self._has_objective else 0.0,
                elapsed=self.wall_time,
            ))
        if self._control.should_stop and self._control.should_stop():
            self.stop_search()  # 保留当下最佳解,不是丢弃


class _Watcher:
    """背景执行绪:定期送出心跳,并在被要求停止时中断搜寻。

    只靠 solution callback 不够——长时间找不到新解时它完全不会被呼叫,
    前端就无从分辨「还在算」与「worker 已经死了」。
    """

    def __init__(self, solver: cp_model.CpSolver, control: SolveControl) -> None:
        self._solver = solver
        self._control = control
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        if self._control.on_tick or self._control.should_stop:
            self._thread.start()

    def stop(self) -> None:
        self._done.set()
        if self._thread.is_alive():
            self._thread.join(timeout=self._control.tick_seconds + 1)

    def _run(self) -> None:
        started = time.monotonic()
        while not self._done.wait(self._control.tick_seconds):
            if self._control.on_tick:
                self._control.on_tick(time.monotonic() - started)
            if self._control.should_stop and self._control.should_stop():
                self._solver.stop_search()
                return
