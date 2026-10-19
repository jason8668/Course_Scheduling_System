"""M3-5:无解冲突定位与部分排课。

三种人造无解情境,共同点是**每一项单独看都很合理**——正是市售系统只会回一句
「排不出来」的那类问题。这里要求报告精确指出是哪几件事凑在一起,并附上数字。

部分排课的结果一律再交给 `validator` 检查:除了被明确放宽的那类约束以外,
其余硬约束必须一格都没违反。「少排几节」不可以偷偷变成「排错几节」。
"""

import pytest

from app.models.basedata import ClassTrack, RoomType, TeacherRuleType, TeacherTimeRule
from app.services.solver_data import load_problem
from app.solver import conflict_explainer, preflight
from app.solver.conflict_explainer import explain
from app.solver.model_builder import (
    Relaxation,
    SolveOptions,
    SolverInputError,
    solve,
)
from app.solver.problem import SolverConfig
from app.solver.validator import validate
from tests.fixtures import Builder

# 部分排课的最佳解很快就找到,但「证明不可能只少排 1 节」很慢;
# 这里要验的是解的质量,不是最佳性证明。
FAST = SolveOptions(max_seconds=25.0, workers=4, random_seed=1)
HARD = SolverConfig.hard_only()

WEEK = [1, 2, 3, 4, 5]


def _block_days(b: Builder, teacher: str, weekdays: list[int]) -> None:
    b.unavailable_days(teacher, weekdays)


# ── 情境 A:音乐教室的供给被教师时段吃掉 ──────────────────────
def _music_room_fixture(db, year: int = 140) -> Builder:
    """6 班各 5 节音乐,共用唯一的音乐教室(30 节)。

    音乐教室一周有 35 格,两位音乐老师各教 15 节、可排时段各有 28 格——
    逐项检查全数通过。但两人都不排周五,音乐教室周五就没人能用,
    实际只有 28 格要塞 30 节课。
    """
    b = Builder(db, year, 1, "junior_high")
    b.subject("音乐", required_room_type=RoomType.special)
    b.room("音乐教室", room_type=RoomType.special, subjects=["音乐"])

    for i in (1, 2):
        b.teacher(f"音乐师{i}", base_periods=20)
        b.teacher(f"国文师{i}", base_periods=20)
        b.teacher(f"数学师{i}", base_periods=20)
    for i in (1, 2):
        _block_days(b, f"音乐师{i}", [5])

    for i in range(1, 7):
        b.klass(f"70{i}", grade=7, track=ClassTrack.junior_high.value)

    for i in range(1, 7):
        cls, half = f"70{i}", 1 if i <= 3 else 2
        b.assign(subject="音乐", teachers=[f"音乐师{half}"], periods=5, classes=[cls],
                 room="音乐教室")
        b.assign(subject="国文", teachers=[f"国文师{half}"], periods=5, classes=[cls])
        b.assign(subject="数学", teachers=[f"数学师{half}"], periods=5, classes=[cls])
    return b


def test_room_supply_eaten_by_teacher_rules_is_located(db):
    """验收①:报告指出场地与数字(需求 30 节 > 实际可用 28 节)。"""
    fx = _music_room_fixture(db).build()
    problem = load_problem(db, fx.semester_id)

    # 逐项的必要条件检查全数通过——这正是 unsat core 存在的理由
    assert preflight.run(problem).ok

    report = explain(problem, max_seconds=60.0)
    assert report.status == "infeasible"
    assert report.source == "analysis", "必要条件都通过,原因只能来自逐项试解"
    assert report.explained
    assert report.complete

    codes = {c.code for c in report.causes}
    assert codes == {"H3", "H4"}, [c.message for c in report.causes]

    room = next(c for c in report.causes if c.code == "H3")
    assert room.scope_name == "音乐教室"
    assert room.detail == {"demand": 30, "supply": 35, "usable": 28, "rooms": 1}
    assert "音乐教室" in room.message
    assert "30" in room.message and "28" in room.message

    # 两位音乐老师都是共犯,少了任何一位都排得出来
    blamed = {c.scope_name for c in report.causes if c.code == "H4"}
    assert blamed == {"音乐师1", "音乐师2"}
    assert report.mode == "each"
    assert "任何一项" in report.headline
    assert report.relaxable_codes == ("H4",)  # H3 是物理限制,不可放宽


def test_partial_schedule_places_95_percent_and_lists_the_rest(db):
    """验收③:同一份 fixture 改用部分排课 → 95%+ 排入 + 未排清单。"""
    fx = _music_room_fixture(db, year=141).build()
    problem = load_problem(db, fx.semester_id)
    total = sum(a.periods_per_week for a in problem.assignments)  # 6 班 × 15 节

    result = solve(problem, FAST, config=HARD, relax=Relaxation())
    assert result.solved

    placed = sum(e.span for e in result.entries)
    assert placed == total - result.unplaced_periods
    assert placed / total >= 0.95, f"只排入 {placed}/{total}"

    # 少排的正好是音乐教室塞不下的 2 节,而且说得出是哪一班
    assert result.unplaced_periods == 2
    assert {u.subject_name for u in result.unscheduled} == {"音乐"}
    assert all(len(u.class_names) == 1 for u in result.unscheduled)

    # 「少排几节」不可以变成「排错几节」:除了 H8(周节数不足)外零违反
    codes = {v.code for v in validate(problem, result.entries)}
    assert codes == {"H8"}, codes


def test_partial_schedule_can_relax_teacher_rules_instead(db):
    """勾选放宽「教师不可排时段」→ 全部排入,代价是有课落在老师的不可排时段。"""
    fx = _music_room_fixture(db, year=142).build()
    problem = load_problem(db, fx.semester_id)
    total = sum(a.periods_per_week for a in problem.assignments)

    result = solve(problem, FAST, config=HARD,
                   relax=Relaxation(soft_codes=frozenset({"H4"})))
    assert result.solved
    assert result.unscheduled == (), "放宽 H4 后应该排得下"
    assert sum(e.span for e in result.entries) == total

    violations = validate(problem, result.entries)
    assert {v.code for v in violations} == {"H4"}
    # 只违反最低限度:30 节课、28 格可用 → 至少 2 节得落在周五
    assert len(violations) == 2, [v.message for v in violations]


# ── 情境 B:协同教学的两位教师没有共同可排时段 ────────────────
def _co_teaching_fixture(db, year: int = 143) -> Builder:
    """2 节协同教学。节数刻意不超过每日上限,否则「只放宽李师」会被 H10 挡住,
    李师就不算单独的瓶颈了——这种交互作用正是逐项试解才看得出来的东西。"""
    b = Builder(db, year, 1, "junior_high")
    b.teacher("王师", base_periods=20)
    b.teacher("李师", base_periods=20)
    _block_days(b, "王师", [1, 2, 3, 4])  # 只有周五能上
    _block_days(b, "李师", [5])           # 唯独周五不能上
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    b.assign(subject="自然科学", teachers=["王师", "李师"], periods=2, classes=["301"])
    return b


def test_teacher_time_contradiction_names_both_teachers(db):
    """验收②:报告指出该教师。两人各自都有足够可排格数,交集却是空的。"""
    fx = _co_teaching_fixture(db).build()
    problem = load_problem(db, fx.semester_id)
    assert preflight.run(problem).ok  # 王师 2≤7、李师 2≤28,逐项都过

    report = explain(problem, max_seconds=60.0)
    assert report.status == "infeasible"
    assert report.source == "analysis"
    assert {c.code for c in report.causes} == {"H4"}
    assert {c.scope_name for c in report.causes} == {"王师", "李师"}
    assert report.mode == "each"

    wang = next(c for c in report.causes if c.scope_name == "王师")
    assert wang.detail == {"assigned": 2, "available": 7, "unavailable": 28}
    assert wang.relaxable


def test_co_teaching_contradiction_is_explained_not_crashed(db):
    """一般求解会在建模阶段就发现此配课无任何候选时段;冲突定位仍须给得出人话。"""
    fx = _co_teaching_fixture(db, year=144).build()
    problem = load_problem(db, fx.semester_id)

    with pytest.raises(SolverInputError, match="找不到任何可排"):
        solve(problem, SolveOptions(max_seconds=10.0), config=HARD)

    assert explain(problem, max_seconds=40.0).explained


# ── 情境 C:同班同科目每日上限 ────────────────────────────────
def _daily_cap_fixture(db, year: int = 145) -> Builder:
    b = Builder(db, year, 1, "junior_high")
    b.teacher("陈师", base_periods=40)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    b.assign(subject="国文", teachers=["陈师"], periods=12, classes=["301"])
    return b


def test_daily_subject_cap_conflict_reports_the_arithmetic(db):
    """12 节单节课,每日上限 2 节 × 5 天 = 10 节。报告要把这个算式讲出来。"""
    fx = _daily_cap_fixture(db).build()
    problem = load_problem(db, fx.semester_id)
    assert preflight.run(problem).ok  # 12 节 ≤ 35 格,逐项检查看不出问题

    report = explain(problem, max_seconds=60.0)
    assert report.status == "infeasible"
    assert report.source == "analysis"

    cause = next(c for c in report.causes if c.code == "H10")
    assert cause.scope_name == "同班同科目每日节数上限"  # 全校旋钮,不挂学期名称
    assert "301" in cause.message
    assert cause.detail["singles"] == 12
    assert cause.detail["cap"] == 2
    assert cause.detail["ceiling"] == 10
    assert "12" in cause.message and "10" in cause.message
    assert "连堂" in cause.suggestion
    assert report.relaxable_codes == ("H10",)


def test_relaxing_daily_cap_places_everything(db):
    fx = _daily_cap_fixture(db, year=146).build()
    problem = load_problem(db, fx.semester_id)

    result = solve(problem, FAST, config=HARD,
                   relax=Relaxation(soft_codes=frozenset({"H10"})))
    assert result.solved
    assert result.unscheduled == ()
    assert sum(e.span for e in result.entries) == 12
    assert {v.code for v in validate(problem, result.entries)} == {"H10"}


def test_daily_cap_respects_config(db):
    """上限提高到 3 → 3×5 = 15 ≥ 12,不再无解。"""
    fx = _daily_cap_fixture(db, year=147).build()
    problem = load_problem(db, fx.semester_id)

    report = explain(problem, config=SolverConfig(daily_subject_cap=3), max_seconds=30.0)
    assert report.status == "feasible"
    assert not report.explained


# ── pre-flight 路径:必要条件不成立时不必启动 solver ───────────
def test_preflight_failure_short_circuits_the_solver(db):
    b = Builder(db, 148, 1, "junior_high")
    b.teacher("王师", base_periods=20)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    b.assign(subject="国文", teachers=["王师"], periods=30, classes=["301"])
    wang = b.teachers["王师"]
    for p in b.regular_slots():
        if p.weekday in (4, 5):  # 挡掉 14 格 → 可排 21 格 < 30 节
            db.add(TeacherTimeRule(teacher_id=wang.id, weekday=p.weekday,
                                   period_no=p.period_no,
                                   rule_type=TeacherRuleType.unavailable.value))
    fx = b.build()
    problem = load_problem(db, fx.semester_id)

    report = explain(problem, max_seconds=60.0)
    assert report.source == "preflight"
    assert report.wall_time == 0.0, "必要条件已是证明,不该启动 solver"
    assert "必须修正" in report.headline

    cause = next(c for c in report.causes if c.code == "teacher_overload")
    assert "王师" in cause.message
    assert cause.detail == {"assigned": 30, "available": 21, "unavailable": 14}


def test_feasible_problem_reports_no_cause(db):
    b = Builder(db, 149, 1, "junior_high")
    b.teacher("王师", base_periods=20)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    b.assign(subject="国文", teachers=["王师"], periods=4, classes=["301"])
    fx = b.build()

    report = explain(load_problem(db, fx.semester_id), max_seconds=30.0)
    assert report.status == "feasible"
    assert report.causes == ()
    assert report.relaxable_codes == ()
    assert report.headline == ""


# ── 放宽的边界 ───────────────────────────────────────────────
@pytest.mark.parametrize("code", ["H1", "H2", "H3"])
def test_physical_constraints_cannot_be_relaxed(code):
    """一位教师不能同时出现在两间教室——那是物理,不是政策。"""
    with pytest.raises(SolverInputError, match="不可放宽"):
        Relaxation(soft_codes=frozenset({code}))


# ── 两个独立瓶颈:松开任何一个都不够 ──────────────────────────
def test_two_independent_bottlenecks_must_be_fixed_together(db):
    """音乐教室不够 + 另一班的国文超过每日上限。两者互不相干,只解决一个仍然无解。"""
    b = _music_room_fixture(db, year=150)
    b.teacher("陈师", base_periods=40)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    b.assign(subject="国文", teachers=["陈师"], periods=12, classes=["301"])
    fx = b.build()

    problem = load_problem(db, fx.semester_id)
    assert preflight.run(problem).ok

    report = explain(problem, max_seconds=90.0)
    assert report.status == "infeasible"
    assert report.mode == "joint", [c.message for c in report.causes]
    assert "必须一起处理" in report.headline

    codes = {c.code for c in report.causes}
    assert len(report.causes) >= 2
    assert "H10" in codes  # 国文那一边
    assert codes & {"H3", "H4"}  # 音乐教室那一边


# ── unknown 路径:没能判定的试解,不可以被当成「已证明不可行」 ─────
def _fake_probe(monkeypatch, unknown_when):
    """让指定的试解回 unknown,其余照常。unknown_when 收 disabled 标签集合。"""
    real = conflict_explainer.check_feasibility

    def fake(problem, *, config=None, disabled=frozenset(), max_seconds=10.0, workers=8):
        if unknown_when(disabled):
            return "unknown"
        return real(problem, config=config, disabled=disabled,
                    max_seconds=max_seconds, workers=workers)

    monkeypatch.setattr(conflict_explainer, "check_feasibility", fake)


def test_base_probe_unknown_reports_unknown_not_infeasible(db, monkeypatch):
    """连「这份资料到底有没有解」都没判定出来时,不可以摆出一份原因报告。"""
    fx = _daily_cap_fixture(db, year=151).build()
    problem = load_problem(db, fx.semester_id)
    _fake_probe(monkeypatch, lambda disabled: not disabled)  # 基准试解逾时

    report = explain(problem, max_seconds=30.0)
    assert report.status == "unknown"
    assert report.causes == ()
    assert report.headline == ""


def test_unknown_step_marks_the_report_incomplete(db, monkeypatch):
    """某个旋钮的试解逾时 → 它不该被列为原因,但报告必须承认自己不完整。"""
    fx = _music_room_fixture(db, year=152).build()
    problem = load_problem(db, fx.semester_id)
    _fake_probe(monkeypatch, lambda d: any(t.code == "H3" for t in d))

    report = explain(problem, max_seconds=60.0)
    assert report.status == "infeasible"
    assert report.mode == "each"
    assert "H3" not in {c.code for c in report.causes}  # 没证明 → 不敢说
    assert {c.code for c in report.causes} == {"H4"}    # 证明过的照样列
    assert not report.complete, "有试解没判定出来,complete 必须是 False"


def test_structural_headline_does_not_overclaim_when_unproven(db, monkeypatch):
    """所有试解都逾时 → 落到 structural,但不可以宣称「即使放宽所有项目仍然无解」。"""
    fx = _music_room_fixture(db, year=153).build()
    problem = load_problem(db, fx.semester_id)
    _fake_probe(monkeypatch, lambda d: bool(d))  # 除了基准以外全部逾时

    report = explain(problem, max_seconds=60.0)
    assert report.status == "infeasible"
    assert report.mode == "structural"
    assert not report.complete
    assert "未能判定" in report.headline
    assert "即使放宽所有可调整的项目仍然无解" not in report.headline
    assert report.causes  # structural 仍要列出最吃紧的班级/教师


def test_structural_headline_is_assertive_when_proven(db):
    """真的证明了「全部放宽仍无解」时,话就该说死。

    一个班配课 40 节 > 可排 35 格:pre-flight 会先拦下,所以这里直接验 headline 文案分支。
    """
    report = conflict_explainer.ConflictReport(
        status="infeasible", source="analysis", mode="structural",
        causes=(conflict_explainer.Cause("structural", "class", 1, "301", "x", "y"),),
        complete=True,
    )
    assert report.headline == "即使放宽所有可调整的项目仍然无解,问题出在配课总量"
