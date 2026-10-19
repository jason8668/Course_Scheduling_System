"""M3-3:软约束与目标函数(S1–S8)。

比较性测试:断言**方向性**(开启后违反数下降),不断言绝对分数——软约束是加权
折衷,任何绝对门槛都会在权重微调时变成假警报。

达成度报告与建模一样不共用程序码(`report.evaluate` 从课表重新推导),
所以「开启 S2 后违反数下降」是由独立的观测者说的,不是由目标函数自己说的。
"""

import pytest

from app.models.basedata import ClassTrack, TeacherRuleType, TeacherTimeRule
from app.services.solver_data import load_problem
from app.solver import report
from app.solver.model_builder import SolveOptions, solve
from app.solver.problem import DEFAULT_WEIGHTS, SolvedEntry, SolverConfig
from app.solver.validator import validate
from tests.fixtures import Builder, build_junior_high_mid

OPTS = SolveOptions(max_seconds=45.0, workers=4, random_seed=5)


def _only(code: str, **params) -> SolverConfig:
    """只开启指定的一项软约束,其余关闭——比较时才不会被其他项的折衷干扰。"""
    weights = dict.fromkeys(DEFAULT_WEIGHTS, 0)
    weights[code] = DEFAULT_WEIGHTS[code]
    return SolverConfig(weights=weights, **params)


def _off() -> SolverConfig:
    return SolverConfig.hard_only()


# ── 验收①:开/关 S2(同科分散)比较 ─────────────────────────
def test_s2_spread_reduces_same_day_repeats(db):
    """同班同科目同日 ≥2 节的数量,开启 S2 后应显著下降。"""
    fx = build_junior_high_mid(db)
    problem = load_problem(db, fx.semester_id)

    off = solve(problem, OPTS, config=_off())
    on = solve(problem, OPTS, config=_only("S2"))
    assert off.solved and on.solved
    assert not validate(problem, off.entries)
    assert not validate(problem, on.entries)

    before = report.evaluate(problem, off.entries).get("S2").violations
    after = report.evaluate(problem, on.entries).get("S2").violations
    assert before > 0, "纯硬约束的解本来就该出现同日重复,否则这个比较没有意义"
    assert after < before, f"开启 S2 后同日重复应下降,实得 {before} → {after}"
    assert after <= before // 2, f"下降幅度应显著,实得 {before} → {after}"


# ── 验收②:教师 avoid 时段在有替代方案时被避开 ────────────────
@pytest.fixture
def avoidable(db):
    """王师 4 节课、35 格可排;把周五整天标为 avoid(软)——有大量替代方案。"""
    b = Builder(db, 150, 1, "junior_high")
    b.teacher("王师", base_periods=20)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    b.assign(subject="国文", teachers=["王师"], periods=4, classes=["301"])
    wang = b.teachers["王师"]
    for p in b.regular_slots():
        if p.weekday == 5:
            db.add(TeacherTimeRule(teacher_id=wang.id, weekday=p.weekday,
                                   period_no=p.period_no,
                                   rule_type=TeacherRuleType.avoid.value))
    return b.build()


def test_avoid_slots_are_dodged_when_alternatives_exist(avoidable, db):
    problem = load_problem(db, avoidable.semester_id)
    result = solve(problem, OPTS, config=_only("S1"))
    assert result.solved
    assert not validate(problem, result.entries)

    assert all(e.weekday != 5 for e in result.entries), "有替代方案时不应排在 avoid 时段"
    assert report.evaluate(problem, result.entries).get("S1").violations == 0


def test_avoid_is_soft_not_hard(db):
    """avoid 只是软约束:没有替代方案时仍会排进去,而报告要如实列出。"""
    b = Builder(db, 151, 1, "junior_high")
    b.teacher("王师", base_periods=40)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    b.assign(subject="国文", teachers=["王师"], periods=4, classes=["301"])
    wang = b.teachers["王师"]
    for p in b.regular_slots():  # 全部时段都标为尽量避开 → 只能硬排
        db.add(TeacherTimeRule(teacher_id=wang.id, weekday=p.weekday, period_no=p.period_no,
                               rule_type=TeacherRuleType.avoid.value))
    fx = b.build()

    problem = load_problem(db, fx.semester_id)
    result = solve(problem, OPTS, config=_only("S1"))
    assert result.solved, "avoid 是软约束,不得让问题变成无解"

    score = report.evaluate(problem, result.entries).get("S1")
    assert score.violations == 4


def test_prefer_slots_are_favoured(db):
    """prefer 时段在其他条件相同时应被优先选用。"""
    b = Builder(db, 152, 1, "junior_high")
    b.teacher("王师", base_periods=40)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    b.assign(subject="国文", teachers=["王师"], periods=2, classes=["301"])
    wang = b.teachers["王师"]
    for weekday in (1, 2):  # 只偏好周一/周二的第一节(period_no 2)
        db.add(TeacherTimeRule(teacher_id=wang.id, weekday=weekday, period_no=2,
                               rule_type=TeacherRuleType.prefer.value))
    fx = b.build()

    problem = load_problem(db, fx.semester_id)
    result = solve(problem, OPTS, config=_only("S1"))
    assert result.solved
    assert sorted((e.weekday, e.period_no) for e in result.entries) == [(1, 2), (2, 2)]


# ── 验收③:报告列出人话明细 ──────────────────────────────────
def test_report_details_are_human_readable(db):
    """「教师王师 周四第七节 被排课(该时段标记为尽量避开)」。"""
    b = Builder(db, 153, 1, "junior_high")
    b.teacher("王师", base_periods=40)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    a = b.assign(subject="国文", teachers=["王师"], periods=1, classes=["301"])[0]
    db.add(TeacherTimeRule(teacher_id=b.teachers["王师"].id, weekday=4, period_no=9,
                           rule_type=TeacherRuleType.avoid.value))
    fx = b.build()

    problem = load_problem(db, fx.semester_id)
    entries = [SolvedEntry(a.id, 4, 9, 1, None)]  # 硬排在 avoid 格

    rep = report.evaluate(problem, entries)
    s1 = rep.get("S1")
    assert s1.violations == 1
    assert s1.details == ("教师王师 周四第七节 被排课(该时段标记为尽量避开)",)
    assert s1.opportunities == 1 and s1.satisfied == 0 and s1.rate == 0.0
    assert s1.penalty == DEFAULT_WEIGHTS["S1"]

    s8 = rep.get("S8")
    assert "偏好未达成最多的是教师王师(1 节)" in s8.details[0]


def test_report_covers_all_eight_soft_constraints(db):
    fx = build_junior_high_mid(db)
    problem = load_problem(db, fx.semester_id)
    result = solve(problem, OPTS, config=_off())
    rep = report.evaluate(problem, result.entries)

    assert [i.code for i in rep.items] == [f"S{n}" for n in range(1, 9)]
    assert all(0.0 <= i.rate <= 1.0 for i in rep.items)
    assert rep.total_penalty == sum(i.penalty for i in rep.items)


# ── 其余软约束的方向性 ───────────────────────────────────────
def test_s3_daily_load_cap_reduces_heavy_days(db):
    """教师每日授课上限:开启 S3 后,超过上限的教师×日组合数下降。"""
    b = Builder(db, 154, 1, "junior_high")
    b.teacher("王师", base_periods=40)
    for i in range(1, 5):
        b.klass(f"30{i}", grade=3, track=ClassTrack.junior_high.value)
        b.assign(subject="国文", teachers=["王师"], periods=5, classes=[f"30{i}"])
    fx = b.build()  # 20 节分布在 5 天 → 若不管,可能某天塞 7 节
    problem = load_problem(db, fx.semester_id)

    cfg_off = _off()
    cfg_on = _only("S3", teacher_daily_max=4)
    off = solve(problem, OPTS, config=cfg_off)
    on = solve(problem, OPTS, config=cfg_on)
    assert off.solved and on.solved

    before = report.evaluate(problem, off.entries, cfg_on).get("S3").violations
    after = report.evaluate(problem, on.entries, cfg_on).get("S3").violations
    assert after <= before
    assert after == 0, "20 节分 5 天,每日 4 节刚好排得下"


def test_s5_major_subjects_move_to_morning(db):
    """主科标记后,开启 S5 应把主科从下午移到上午。"""
    b = Builder(db, 155, 1, "junior_high")
    b.subject("国文", is_major=True)
    b.teacher("王师", base_periods=40)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    b.assign(subject="国文", teachers=["王师"], periods=4, classes=["301"])
    fx = b.build()

    problem = load_problem(db, fx.semester_id)
    assert all(a.subject_is_major for a in problem.assignments)

    result = solve(problem, OPTS, config=_only("S5"))
    assert result.solved
    score = report.evaluate(problem, result.entries).get("S5")
    assert score.violations == 0, "上午有 4 节一般课/天,主科不必排到下午"
    assert score.opportunities == 4


def test_s7_homeroom_teacher_takes_first_period(db):
    b = Builder(db, 156, 1, "junior_high")
    b.teacher("导师", base_periods=40)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value, homeroom="导师")
    b.assign(subject="国文", teachers=["导师"], periods=5, classes=["301"])
    fx = b.build()

    problem = load_problem(db, fx.semester_id)
    assert problem.classes[b.classes["301"].id].homeroom_teacher_id == b.teachers["导师"].id

    result = solve(problem, OPTS, config=_only("S7"))
    assert result.solved
    # 初中范本每日第一节的 period_no 是 2(1 是早自习,非一般课)
    assert all(e.period_no == 2 for e in result.entries)
    assert report.evaluate(problem, result.entries).get("S7").violations == 0


def test_weight_zero_disables_the_constraint(db):
    """权重 0 = 关闭;目标函数不含该项,报告仍照实计算违反数。"""
    problem = load_problem(db, build_junior_high_mid(db).semester_id)
    result = solve(problem, OPTS, config=_off())
    assert result.solved
    assert result.objective == 0.0  # 没有目标函数 → 纯可行性问题

    rep = report.evaluate(problem, result.entries, _off())
    assert all(i.weight == 0 and i.penalty == 0 for i in rep.items)
    assert rep.total_penalty == 0
