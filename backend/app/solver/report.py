"""软约束达成度报告(architecture.md §3.2 S1–S8)。

与 `validator.py` 一样**从课表本身重新推导**,不读 CP-SAT 的目标值——建模的惩罚项
写错时,solver 回报的目标值只会忠实反映错误的模型。报告要说人话:
不是「S1 得分 0.82」,而是「教师王师 周四第七节 被排课(该时段标记为尽量避开)」。

满分 = 机会数(可以被满足的次数),得分 = 实际满足数。

**`total_penalty` 不等于 `SolveResult.objective`**,两者刻意用不同尺度:
目标函数以「超出的节数」计价(S3 超 2 节就罚 2 份),让 solver 有梯度可下降;
报告以「未达成的次数」计价(S3 那天没排好就是 1 次),让教学组长知道要修几个地方。
比较两份课表的优劣时看 objective,看报告是为了知道**哪里**还不够好。
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.solver.problem import (
    MORNING_END_MIN,
    SOFT_NAMES,
    AssignmentSpec,
    ClassSpec,
    Problem,
    Slot,
    SolvedEntry,
    SolverConfig,
)

MAX_DETAILS = 20  # 每项软约束最多列出的明细笔数(其余以总数表示)


def _wd(weekday: int) -> str:
    names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return names[weekday - 1] if 1 <= weekday <= 7 else f"星期{weekday}"


@dataclass(frozen=True, slots=True)
class SoftScore:
    code: str
    name: str
    weight: int
    opportunities: int  # 满分
    violations: int
    details: tuple[str, ...] = field(default_factory=tuple)

    @property
    def satisfied(self) -> int:
        return max(self.opportunities - self.violations, 0)

    @property
    def rate(self) -> float:
        return self.satisfied / self.opportunities if self.opportunities else 1.0

    @property
    def penalty(self) -> int:
        return self.weight * self.violations


@dataclass(frozen=True, slots=True)
class SoftReport:
    items: tuple[SoftScore, ...]

    @property
    def total_penalty(self) -> int:
        return sum(i.penalty for i in self.items)

    def get(self, code: str) -> SoftScore:
        return next(i for i in self.items if i.code == code)


@dataclass(frozen=True, slots=True)
class _Busy:
    """教师在某一节次上课。position 是该教师当日可排节次序列中的位置(用来算连续/空堂)。"""

    weekday: int
    position: int
    slot: Slot


def evaluate(
    problem: Problem,
    entries: Sequence[SolvedEntry],
    config: SolverConfig | None = None,
) -> SoftReport:
    config = config or SolverConfig()
    by_id = {a.id: a for a in problem.assignments}
    busy = _teacher_busy(problem, entries, by_id)

    return SoftReport((
        _s1_preferences(problem, busy, config),
        _s2_spread(problem, entries, by_id, config),
        _s3_daily_load(problem, busy, config),
        _s4_gaps(problem, busy, config),
        _s5_major_in_morning(problem, entries, by_id, config),
        _s6_consecutive(problem, busy, config),
        _s7_homeroom_first_period(problem, entries, by_id, config),
        _s8_fairness(problem, busy, config),
    ))


def _teacher_day_slots(problem: Problem, teacher_id: int) -> dict[int, list[Slot]]:
    """该教师可能上课的节次,依星期分组并按墙钟时间排序(跨节次表也有一致的顺序)。"""
    slots: list[Slot] = []
    for table in problem.tables_of_teacher(teacher_id):
        slots.extend(table.slots)
    by_day: dict[int, list[Slot]] = {}
    for s in slots:
        by_day.setdefault(s.weekday, []).append(s)
    for day in by_day.values():
        day.sort(key=lambda s: (s.start_min if s.start_min is not None else 0, s.period_no))
    return by_day


def _teacher_busy(
    problem: Problem, entries: Sequence[SolvedEntry], by_id: dict[int, AssignmentSpec]
) -> dict[int, list[_Busy]]:
    day_slots = {tid: _teacher_day_slots(problem, tid) for tid in problem.teachers}
    positions: dict[int, dict[tuple[int, int], int]] = {}
    for tid, by_day in day_slots.items():
        positions[tid] = {
            (s.weekday, s.period_no): i for day in by_day.values() for i, s in enumerate(day)
        }

    out: dict[int, list[_Busy]] = {tid: [] for tid in problem.teachers}
    for e in entries:
        a = by_id[e.assignment_id]
        table = problem.table_of(a)
        if table is None:
            continue
        for k in range(e.span):
            slot = table.slot(e.weekday, e.period_no + k)
            if slot is None:
                continue
            for tid in a.teacher_ids:
                pos = positions.get(tid, {}).get((slot.weekday, slot.period_no))
                if pos is not None:
                    out[tid].append(_Busy(slot.weekday, pos, slot))
    return out


# ── S1 教师偏好时段 ──────────────────────────────────────────
def _s1_preferences(problem: Problem, busy: dict[int, list[_Busy]], c: SolverConfig) -> SoftScore:
    opportunities = 0
    violations = 0
    details: list[str] = []
    for t in problem.teachers.values():
        if not t.has_preferences:
            continue
        mine = busy.get(t.id, [])
        opportunities += len(mine)
        for b in mine:
            if b.slot.key in t.avoid:
                violations += 1
                if len(details) < MAX_DETAILS:
                    details.append(
                        f"教师{t.name} {_wd(b.weekday)}{b.slot.name} 被排课"
                        f"(该时段标记为尽量避开)"
                    )
    return SoftScore("S1", SOFT_NAMES["S1"], c.weight("S1"), opportunities, violations,
                     tuple(details))


# ── S2 同班同科目分散于不同日 ────────────────────────────────
def _s2_spread(
    problem: Problem, entries: Sequence[SolvedEntry], by_id: dict[int, AssignmentSpec],
    c: SolverConfig,
) -> SoftScore:
    counts: dict[tuple[int, int, int], int] = {}
    for e in entries:
        if e.span != 1:
            continue  # 连堂本来就是同一天上完
        a = by_id[e.assignment_id]
        for cls in problem.classes_of(a):
            key = (cls.id, a.subject_id, e.weekday)
            counts[key] = counts.get(key, 0) + 1

    opportunities = sum(counts.values())
    violations = 0
    details: list[str] = []
    for (class_id, subject_id, weekday), n in sorted(counts.items()):
        if n > 1:
            violations += n - 1
            if len(details) < MAX_DETAILS:
                subject = next(a.subject_name for a in problem.assignments
                               if a.subject_id == subject_id)
                details.append(
                    f"班级 {problem.classes[class_id].name} {_wd(weekday)} "
                    f"排了 {n} 节「{subject}」"
                )
    return SoftScore("S2", SOFT_NAMES["S2"], c.weight("S2"), opportunities, violations,
                     tuple(details))


# ── S3 教师每日授课节数上限 ──────────────────────────────────
def _s3_daily_load(problem: Problem, busy: dict[int, list[_Busy]], c: SolverConfig) -> SoftScore:
    opportunities = 0
    violations = 0
    details: list[str] = []
    for t in problem.teachers.values():
        by_day: dict[int, int] = {}
        for b in busy.get(t.id, []):
            by_day[b.weekday] = by_day.get(b.weekday, 0) + 1
        for weekday, load in sorted(by_day.items()):
            opportunities += 1
            if load > c.teacher_daily_max:
                violations += 1
                if len(details) < MAX_DETAILS:
                    details.append(
                        f"教师{t.name} {_wd(weekday)} 排了 {load} 节,"
                        f"超过每日上限 {c.teacher_daily_max} 节"
                    )
    return SoftScore("S3", SOFT_NAMES["S3"], c.weight("S3"), opportunities, violations,
                     tuple(details))


# ── S4 教师空堂集中 ──────────────────────────────────────────
def _s4_gaps(problem: Problem, busy: dict[int, list[_Busy]], c: SolverConfig) -> SoftScore:
    opportunities = 0
    violations = 0
    details: list[str] = []
    for t in problem.teachers.values():
        by_day: dict[int, list[int]] = {}
        for b in busy.get(t.id, []):
            by_day.setdefault(b.weekday, []).append(b.position)
        for weekday, positions in sorted(by_day.items()):
            opportunities += 1
            gaps = (max(positions) - min(positions) + 1) - len(positions)
            if gaps > 0:
                violations += 1
                if len(details) < MAX_DETAILS:
                    details.append(f"教师{t.name} {_wd(weekday)} 有 {gaps} 节零碎空堂")
    return SoftScore("S4", SOFT_NAMES["S4"], c.weight("S4"), opportunities, violations,
                     tuple(details))


# ── S5 主科优先排上午 ────────────────────────────────────────
def _s5_major_in_morning(
    problem: Problem, entries: Sequence[SolvedEntry], by_id: dict[int, AssignmentSpec],
    c: SolverConfig,
) -> SoftScore:
    opportunities = 0
    violations = 0
    details: list[str] = []
    for e in entries:
        a = by_id[e.assignment_id]
        if not a.subject_is_major:
            continue
        table = problem.table_of(a)
        if table is None:
            continue
        for k in range(e.span):
            slot = table.slot(e.weekday, e.period_no + k)
            if slot is None or slot.start_min is None:
                continue
            opportunities += 1
            if slot.start_min >= MORNING_END_MIN:
                violations += 1
                if len(details) < MAX_DETAILS:
                    names = "、".join(cls.name for cls in problem.classes_of(a))
                    details.append(
                        f"{names} 的「{a.subject_name}」排在 {_wd(e.weekday)}{slot.name}(下午)"
                    )
    return SoftScore("S5", SOFT_NAMES["S5"], c.weight("S5"), opportunities, violations,
                     tuple(details))


# ── S6 教师连续授课节数上限 ──────────────────────────────────
def _s6_consecutive(problem: Problem, busy: dict[int, list[_Busy]], c: SolverConfig) -> SoftScore:
    opportunities = 0
    violations = 0
    details: list[str] = []
    for t in problem.teachers.values():
        by_day: dict[int, list[int]] = {}
        for b in busy.get(t.id, []):
            by_day.setdefault(b.weekday, []).append(b.position)
        for weekday, positions in sorted(by_day.items()):
            opportunities += 1
            longest = _longest_run(sorted(positions))
            if longest > c.teacher_consecutive_max:
                violations += 1
                if len(details) < MAX_DETAILS:
                    details.append(
                        f"教师{t.name} {_wd(weekday)} 连续授课 {longest} 节,"
                        f"超过上限 {c.teacher_consecutive_max} 节"
                    )
    return SoftScore("S6", SOFT_NAMES["S6"], c.weight("S6"), opportunities, violations,
                     tuple(details))


def _longest_run(sorted_positions: list[int]) -> int:
    best = run = 0
    prev: int | None = None
    for p in sorted_positions:
        run = run + 1 if prev is not None and p == prev + 1 else 1
        prev = p
        best = max(best, run)
    return best


# ── S7 导师的课排在自己班第一节 ──────────────────────────────
def _homeroom_classes(problem: Problem) -> list[tuple[ClassSpec, int]]:
    """有导师、且导师确实任教该班的班级(否则这条软约束无从满足)。"""
    out: list[tuple[ClassSpec, int]] = []
    for cls in problem.classes.values():
        tid = cls.homeroom_teacher_id
        if tid is None:
            continue
        teaches = any(
            tid in a.teacher_ids and cls.id in problem.units[a.unit_id].class_ids
            for a in problem.assignments
        )
        if teaches:
            out.append((cls, tid))
    return out


def _s7_homeroom_first_period(
    problem: Problem, entries: Sequence[SolvedEntry], by_id: dict[int, AssignmentSpec],
    c: SolverConfig,
) -> SoftScore:
    opportunities = 0
    violations = 0
    details: list[str] = []
    for cls, tid in _homeroom_classes(problem):
        table = problem.tables[cls.period_table_id]
        for weekday in range(1, table.num_weekdays + 1):
            day = table.slots_on(weekday)
            if not day:
                continue
            first = day[0]
            opportunities += 1
            taken_by_homeroom = any(
                e.weekday == weekday and e.period_no == first.period_no
                and tid in by_id[e.assignment_id].teacher_ids
                and cls.id in problem.units[by_id[e.assignment_id].unit_id].class_ids
                for e in entries
            )
            if not taken_by_homeroom:
                violations += 1
                if len(details) < MAX_DETAILS:
                    details.append(
                        f"班级 {cls.name} {_wd(weekday)}{first.name} 不是导师"
                        f"{problem.teachers[tid].name}的课"
                    )
    return SoftScore("S7", SOFT_NAMES["S7"], c.weight("S7"), opportunities, violations,
                     tuple(details))


# ── S8 教师偏好达成率的公平性 ────────────────────────────────
def _s8_fairness(problem: Problem, busy: dict[int, list[_Busy]], c: SolverConfig) -> SoftScore:
    unmet: dict[int, int] = {}
    for t in problem.teachers.values():
        if not t.has_preferences:
            continue
        unmet[t.id] = sum(1 for b in busy.get(t.id, []) if b.slot.key in t.avoid)

    opportunities = len(unmet)
    violations = sum(1 for n in unmet.values() if n > 0)
    details: list[str] = []
    if unmet:
        worst_id = max(unmet, key=lambda tid: unmet[tid])
        if unmet[worst_id] > 0:
            details.append(
                f"偏好未达成最多的是教师{problem.teachers[worst_id].name}"
                f"({unmet[worst_id]} 节);共 {violations}/{opportunities} 位教师的偏好未完全达成"
            )
    return SoftScore("S8", SOFT_NAMES["S8"], c.weight("S8"), opportunities, violations,
                     tuple(details))
