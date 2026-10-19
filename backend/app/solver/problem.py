"""排课问题的纯资料描述。

**此模组(及整个 `app.solver` 套件)不得 import `app.models` / `app.api` / SQLAlchemy。**
排课引擎只认得这里的 dataclass;DB → Problem 的转换放在 `app.services.solver_data`。
如此引擎可独立测试、独立跑在 worker 容器,也不会被 ORM 的 lazy loading 拖垮效能。

时间一律以「当日分钟数」(minutes since midnight)表示,避免 solver 依赖 datetime。
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

from app.solver.week_parity import weekly_load

# (period_table_id, weekday, period_no)
SlotKey = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class Slot:
    """节次表中的一个「一般课」格位(非一般课不进 Problem)。"""

    weekday: int
    period_no: int
    name: str  # 显示名称(第一节/第五节);人话讯息一律用此栏,不用 period_no
    start_min: int | None
    end_min: int | None

    @property
    def key(self) -> tuple[int, int]:
        return (self.weekday, self.period_no)

    @property
    def has_time(self) -> bool:
        return self.start_min is not None and self.end_min is not None


@dataclass(frozen=True, slots=True)
class PeriodTableSpec:
    id: int
    name: str
    num_weekdays: int
    slots: tuple[Slot, ...]  # 仅 regular,依 (weekday, period_no) 排序

    def slot(self, weekday: int, period_no: int) -> Slot | None:
        return next(
            (s for s in self.slots if s.weekday == weekday and s.period_no == period_no), None
        )

    def slots_on(self, weekday: int) -> tuple[Slot, ...]:
        return tuple(s for s in self.slots if s.weekday == weekday)

    def longest_run(self) -> int:
        """全表最长的「连续一般课」段长度(连堂上限,H6 不跨午休)。"""
        best = 0
        for weekday in range(1, self.num_weekdays + 1):
            run = 0
            prev: int | None = None
            for s in self.slots_on(weekday):
                run = run + 1 if prev is not None and s.period_no == prev + 1 else 1
                prev = s.period_no
                best = max(best, run)
        return best


@dataclass(frozen=True, slots=True)
class TeacherSpec:
    id: int
    name: str
    base_periods: int
    admin_reduction: int
    is_external: bool
    # 时段规则。(weekday, period_no) 以其任教班级的节次表解读
    # ——多套节次表的学校语意会浮动,见 tasks.md Backlog。
    unavailable: frozenset[tuple[int, int]]  # 硬约束 H4
    avoid: frozenset[tuple[int, int]] = frozenset()   # 软约束 S1:尽量避开
    prefer: frozenset[tuple[int, int]] = frozenset()  # 软约束 S1:偏好

    @property
    def target_periods(self) -> int:
        return max(self.base_periods - self.admin_reduction, 0)

    @property
    def has_preferences(self) -> bool:
        return bool(self.avoid or self.prefer)


@dataclass(frozen=True, slots=True)
class RoomSpec:
    id: int
    name: str
    room_type: str
    capacity: int | None  # D8:仅供 pre-flight 警告,不参与求解(场地一律互斥)
    subject_ids: frozenset[int] = frozenset()  # 适用科目;空=不限


@dataclass(frozen=True, slots=True)
class ClassSpec:
    id: int
    name: str
    grade: int
    period_table_id: int  # 已解析(指定表 → 学期默认表),solver 不需再回退
    student_count: int | None
    homeroom_teacher_id: int | None = None  # 软约束 S7:导师的课优先排在自己班第一节


@dataclass(frozen=True, slots=True)
class BlockSpec:
    size: int
    count: int


@dataclass(frozen=True, slots=True)
class UnitSpec:
    id: int
    unit_type: str  # single / group / alternate
    name: str
    class_ids: tuple[int, ...]

    @property
    def is_group(self) -> bool:
        """跑班群组(多班、多门课同一节一起上)。"""
        return self.unit_type == "group"

    @property
    def is_alternate(self) -> bool:
        """单双周组(v1.3.0):同一格单周、双周轮流上不同的课。"""
        return self.unit_type == "alternate"

    @property
    def is_bundle(self) -> bool:
        """单位内的配课要排在同一个时段(跑班群组、单双周组)。"""
        return self.is_group or self.is_alternate


@dataclass(frozen=True, slots=True)
class AssignmentSpec:
    id: int
    unit_id: int
    subject_id: int
    subject_name: str
    periods_per_week: int
    teacher_ids: tuple[int, ...]
    room_id: int | None
    required_room_type: str | None
    lock_room: bool
    blocks: tuple[BlockSpec, ...]
    subject_is_major: bool = False  # 软约束 S5
    week_parity: str | None = None  # v1.3.0:None=每周;odd/even=只上单周/双周

    @property
    def block_periods(self) -> int:
        return sum(b.size * b.count for b in self.blocks)

    @property
    def weekly_load(self) -> float:
        """平均每周占用教师/场地的节数:隔周的课算一半。"""
        return weekly_load(self.periods_per_week, self.week_parity)


@dataclass(frozen=True, slots=True)
class FixedEntry:
    """课表的一个格位:某配课排在某格、用某场地。

    作为输入时 locked=True 者为 H9 硬约束,其余可作为求解起点提示;
    作为求解结果时即待写回 DB 的 schedule_entry。
    """

    assignment_id: int
    weekday: int
    period_no: int
    span: int
    room_id: int | None
    locked: bool = False


# 求解结果与既有格位同形,共用一个型别(输入来自草稿,输出写回草稿)
SolvedEntry = FixedEntry


@dataclass(frozen=True, slots=True)
class Problem:
    semester_id: int
    semester_label: str
    tables: Mapping[int, PeriodTableSpec]
    classes: Mapping[int, ClassSpec]
    teachers: Mapping[int, TeacherSpec]
    rooms: Mapping[int, RoomSpec]
    units: Mapping[int, UnitSpec]
    assignments: tuple[AssignmentSpec, ...]
    fixed_entries: tuple[FixedEntry, ...] = ()

    # ── 导览 ────────────────────────
    def classes_of(self, a: AssignmentSpec) -> tuple[ClassSpec, ...]:
        return tuple(self.classes[cid] for cid in self.units[a.unit_id].class_ids)

    def table_of(self, a: AssignmentSpec) -> PeriodTableSpec | None:
        """配课所属节次表。跑班群组成员保证同表(D7#4),故取第一个班级即可。"""
        members = self.classes_of(a)
        if not members:
            return None
        return self.tables.get(members[0].period_table_id)

    def course_key(self, a: AssignmentSpec) -> tuple[str, int]:
        """同时段一起排的最小单位。

        跑班群组的多门课同进同出(H7),对班级而言只占一格,故整个群组是一个 course;
        单双周组同理(单周、双周那两笔轮流占同一格)。
        单班则每笔配课各自是一个 course(同一班的国文与数学不可同时段)。
        """
        unit = self.units[a.unit_id]
        return ("unit", unit.id) if unit.is_bundle else ("assignment", a.id)

    def assignments_of_teacher(self, teacher_id: int) -> tuple[AssignmentSpec, ...]:
        return tuple(a for a in self.assignments if teacher_id in a.teacher_ids)

    def tables_of_teacher(self, teacher_id: int) -> tuple[PeriodTableSpec, ...]:
        seen: dict[int, PeriodTableSpec] = {}
        for a in self.assignments_of_teacher(teacher_id):
            table = self.table_of(a)
            if table is not None:
                seen[table.id] = table
        return tuple(seen.values())

    def unit_slot_consumption(self, unit_id: int) -> int:
        """该排课单位占用成员班级的节数。

        single:单位内各配课节数总和;group / alternate:单位内配课同时段开课(H7),
        班级只被占掉最长的那一笔。
        """
        periods = [a.periods_per_week for a in self.assignments if a.unit_id == unit_id]
        if not periods:
            return 0
        return max(periods) if self.units[unit_id].is_bundle else sum(periods)


# ── 约束设置(architecture.md §3.2)──────────────────────────
WEIGHT_HIGH = 8
WEIGHT_MEDIUM = 4
WEIGHT_LOW = 1

# 软约束权重上限。这不是美观限制,是**部分排课的正确性前提**:
# 一节课最多参与 S1~S8 约 8 个惩罚项,故其软约束总代价 < 8 × MAX_WEIGHT = 800,
# 必须小于「违反被放宽的硬约束」(1000),后者又必须小于「整节不排入」(10000)。
# 若权重可设到 20000,solver 会理性地「丢掉一节课」来换取分散度——那是灾难。
# 见 model_builder.Relaxation。
MAX_WEIGHT = 100

SOFT_NAMES = {
    "S1": "教师偏好时段",
    "S2": "同班同科目分散于不同日",
    "S3": "教师每日授课节数上限",
    "S4": "教师空堂集中",
    "S5": "主科优先排上午",
    "S6": "教师连续授课节数上限",
    "S7": "导师的课排在自己班第一节",
    "S8": "教师偏好达成率的公平性",
}

DEFAULT_WEIGHTS: dict[str, int] = {
    "S1": WEIGHT_MEDIUM,
    "S2": WEIGHT_HIGH,
    "S3": WEIGHT_HIGH,
    "S4": WEIGHT_LOW,
    "S5": WEIGHT_MEDIUM,
    "S6": WEIGHT_MEDIUM,
    "S7": WEIGHT_LOW,
    "S8": WEIGHT_LOW,
}

MORNING_END_MIN = 12 * 60  # 「上午」= 起始时间早于中午(S5)


@dataclass(frozen=True, slots=True)
class SolverConfig:
    """权重与可调参数。权重 0 = 关闭该项软约束(硬约束不可关)。"""

    daily_subject_cap: int = 2       # H10 同班同科目每日单节上限
    teacher_daily_max: int = 6       # S3
    teacher_consecutive_max: int = 3  # S6
    weights: Mapping[str, int] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))

    def weight(self, code: str) -> int:
        return self.weights.get(code, DEFAULT_WEIGHTS.get(code, 0))

    def enabled(self, code: str) -> bool:
        return self.weight(code) > 0

    @classmethod
    def hard_only(cls) -> "SolverConfig":
        """只求可行解(全部软约束关闭)。用于效能基准与纯硬约束测试。"""
        return cls(weights=dict.fromkeys(DEFAULT_WEIGHTS, 0))

    def without_soft(self) -> "SolverConfig":
        """保留可调参数(如每日科目上限),但关闭所有软约束。

        冲突定位要问的是「硬约束彼此是否矛盾」,目标函数只会拖慢证明无解的速度;
        CP-SAT 的 assumption 机制也不与目标函数并用。
        """
        return replace(self, weights=dict.fromkeys(DEFAULT_WEIGHTS, 0))


# ── 时段重叠(architecture.md D7)────────────────────────────
def slots_overlap(a: Slot, b: Slot, *, same_table: bool) -> bool:
    """两个节次是否「同时段」。

    同一节次表退化为节次号相等(常见情形,零额外成本);
    跨表则以墙钟时间区间重叠判定——节次号相同不代表时间相同。
    任一方没填起讫时间就无从比较时间,保守地退回节次号相等:宁可多挡,
    也不能让老师被排到同一时段的两堂课(与 services.availability.Interval 一致)。
    """
    if a.weekday != b.weekday:
        return False
    if same_table:
        return a.period_no == b.period_no
    if not (a.has_time and b.has_time):
        return a.period_no == b.period_no
    assert a.start_min is not None and a.end_min is not None
    assert b.start_min is not None and b.end_min is not None
    return a.start_min < b.end_min and b.start_min < a.end_min


def max_non_overlapping(slots: Sequence[Slot]) -> int:
    """一组节次中,互不重叠的最大数量(每星期各自计算后加总)。

    这是「一位教师最多能上几节课」的正确上限:同表的节次天然不重叠,
    数量即节次数;跨表(完全中学同时任教初中部/高中部)则因墙钟时间交错,
    可上的节数少于两表节次之和。以区间排程的贪婪法(取最早结束者)求解。
    """
    total = 0
    by_weekday: dict[int, list[Slot]] = {}
    for s in slots:
        by_weekday.setdefault(s.weekday, []).append(s)

    for day_slots in by_weekday.values():
        timed = [s for s in day_slots if s.has_time]
        if len(timed) != len(day_slots):
            # 节次表缺起讫时间:无法判定重叠,退化为节次数(单表学校的正确值)
            total += len({(s.period_no) for s in day_slots})
            continue
        last_end = -1
        for s in sorted(timed, key=lambda x: (x.end_min, x.start_min)):
            assert s.start_min is not None and s.end_min is not None
            if s.start_min >= last_end:
                total += 1
                last_end = s.end_min
    return total
