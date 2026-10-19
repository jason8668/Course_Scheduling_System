"""M3-1:问题描述转换与 pre-flight 检查。

验收①:三套 fixtures 皆可转出问题描述且 pre-flight 通过
验收②:人为制造「王师 22 节但可排 20 格」→ 报告明确指出教师与数字
"""

import pytest

from app.models.basedata import ClassTrack, RoomType, TeacherRuleType, TeacherTimeRule
from app.services.solver_data import load_problem
from app.solver import preflight
from app.solver.problem import BlockSpec, Slot, max_non_overlapping, slots_overlap
from tests.fixtures import (
    Builder,
    build_elementary_small,
    build_junior_high_mid,
    build_vocational_high,
)

BUILDERS = {
    "elementary_small": (build_elementary_small, 6, 31),
    "junior_high_mid": (build_junior_high_mid, 12, 35),
    "vocational_high": (build_vocational_high, 15, 40),
}


def _codes(report) -> set[str]:
    return {i.code for i in report.issues}


# ── 验收①:三套 fixtures 转得出问题描述,pre-flight 全过 ──────────
@pytest.mark.parametrize("key", list(BUILDERS))
def test_fixtures_convert_and_pass_preflight(key, db):
    build, num_classes, slot_count = BUILDERS[key]
    fx = build(db)

    problem = load_problem(db, fx.semester_id)
    assert len(problem.classes) == num_classes
    assert len(problem.assignments) == len(fx.assignments)
    assert all(len(t.slots) == slot_count for t in problem.tables.values())
    # 节次表已解析到班级上,solver 不需再回退
    assert all(c.period_table_id in problem.tables for c in problem.classes.values())

    report = preflight.run(problem)
    assert report.ok, f"{key} pre-flight 应通过,却回报:{[i.message for i in report.errors]}"
    assert not report.warnings, [i.message for i in report.warnings]


def test_vocational_problem_keeps_group_and_blocks(db):
    fx = build_vocational_high(db)
    problem = load_problem(db, fx.semester_id)

    group = next(u for u in problem.units.values() if u.is_group)
    assert len(group.class_ids) == 6
    # 跑班群组同时段开课:班级只被占掉 3 节,而非 5 门 × 3 节
    assert problem.unit_slot_consumption(group.id) == 3

    practicum = [a for a in problem.assignments if a.subject_name == "实习工场"]
    assert len(practicum) == 15
    assert all(a.blocks == (BlockSpec(size=3, count=2),) for a in practicum)

    external = next(t for t in problem.teachers.values() if t.is_external)
    # 周一/三/五 各 8 节一般课不可排
    assert len(external.unavailable) == 24
    assert preflight.teacher_available_slots(problem, external) == 16


# ── 验收②:王师 22 节但可排 20 格 ──────────────────────────────
@pytest.fixture
def overloaded(db):
    """初中范本 35 格一般课;把王师 15 格标为不可排 → 可排 20 格,却配了 22 节。"""
    b = Builder(db, 120, 1, "junior_high")
    b.teacher("王师", base_periods=22)  # 应授 22 节,故不会另外触发超课时警告
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    b.klass("302", grade=3, track=ClassTrack.junior_high.value)
    b.assign(subject="国文", teachers=["王师"], periods=11, classes=["301"])
    b.assign(subject="数学", teachers=["王师"], periods=11, classes=["302"])

    wang = b.teachers["王师"]
    blocked = [p for p in b.regular_slots() if p.weekday in (3, 4, 5)][:15]
    for p in blocked:
        db.add(TeacherTimeRule(
            teacher_id=wang.id, weekday=p.weekday, period_no=p.period_no,
            rule_type=TeacherRuleType.unavailable.value,
        ))
    return b.build()


def test_teacher_overload_names_teacher_and_numbers(overloaded, db):
    problem = load_problem(db, overloaded.semester_id)
    report = preflight.run(problem)

    assert not report.ok
    issue = next(i for i in report.errors if i.code == "teacher_overload")
    assert "王师" in issue.message
    assert "22 节" in issue.message
    assert "20 格" in issue.message
    assert issue.detail == {"assigned": 22, "available": 20, "unavailable": 15}
    assert issue.subject_type == "teacher"
    assert issue.subject_id == overloaded.teachers["王师"].id


def test_teacher_over_hours_is_warning_not_error(db):
    """配课超出应授课时只是提醒(超课时费),不影响能否排出课表。"""
    b = Builder(db, 121, 1, "junior_high")
    b.teacher("李师", base_periods=20)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    b.assign(subject="国文", teachers=["李师"], periods=24, classes=["301"])
    fx = b.build()

    report = preflight.run(load_problem(db, fx.semester_id))
    assert report.ok  # 24 ≤ 35 可排格数
    warning = next(i for i in report.warnings if i.code == "teacher_over_hours")
    assert "李师" in warning.message and "24 节" in warning.message


# ── 其他必要条件 ──────────────────────────────────────────────
def test_class_overload(db):
    b = Builder(db, 122, 1, "junior_high")
    b.teacher("甲师", base_periods=40)
    b.teacher("乙师", base_periods=40)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    b.assign(subject="国文", teachers=["甲师"], periods=20, classes=["301"])
    b.assign(subject="数学", teachers=["乙师"], periods=20, classes=["301"])
    fx = b.build()

    report = preflight.run(load_problem(db, fx.semester_id))
    issue = next(i for i in report.errors if i.code == "class_overload")
    assert "301" in issue.message and "40 节" in issue.message and "35 节" in issue.message


def test_room_supply_shortage(db):
    """§3.4 的范例:音乐教室需求 > 供给。"""
    b = Builder(db, 123, 1, "junior_high")
    b.subject("音乐")
    b.room("音乐教室", room_type=RoomType.special, capacity=35)
    for i in range(1, 13):
        b.teacher(f"音乐师{i}", base_periods=40)
        b.klass(f"90{i}", grade=9, track=ClassTrack.junior_high.value)
        b.assign(subject="音乐", teachers=[f"音乐师{i}"], periods=3,
                 classes=[f"90{i}"], room="音乐教室")
    fx = b.build()

    report = preflight.run(load_problem(db, fx.semester_id))
    issue = next(i for i in report.errors if i.code == "room_supply")
    assert "音乐教室" in issue.message
    assert issue.detail == {"demand": 36, "supply": 35}


def test_room_type_supply_shortage(db):
    """只指定场地类型时,以该类型的场地总数估供给。"""
    b = Builder(db, 124, 1, "junior_high")
    b.subject("音乐", required_room_type=RoomType.special)
    b.room("音乐教室", room_type=RoomType.special, capacity=35)
    for i in range(1, 13):
        b.teacher(f"音乐师{i}", base_periods=40)
        b.klass(f"90{i}", grade=9, track=ClassTrack.junior_high.value)
        b.assign(subject="音乐", teachers=[f"音乐师{i}"], periods=3,
                 classes=[f"90{i}"], required_room_type=RoomType.special)
    fx = b.build()

    report = preflight.run(load_problem(db, fx.semester_id))
    issue = next(i for i in report.errors if i.code == "room_type_supply")
    assert "专科教室" in issue.message and "36 节" in issue.message


def test_room_capacity_is_warning_only(db):
    """D8:容量不参与求解,只在 pre-flight 提醒人数超过。"""
    b = Builder(db, 125, 1, "junior_high")
    b.teacher("师", base_periods=40)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value, student_count=40)
    b.room("小教室", room_type=RoomType.special, capacity=25)
    b.assign(subject="国文", teachers=["师"], periods=3, classes=["301"], room="小教室")
    fx = b.build()

    report = preflight.run(load_problem(db, fx.semester_id))
    assert report.ok
    warning = next(i for i in report.warnings if i.code == "room_capacity")
    assert "小教室" in warning.message and "40 人" in warning.message


def test_block_longer_than_contiguous_run(db):
    """初中范本上午 4 节、下午 3 节连续;5 连堂放不进去。"""
    b = Builder(db, 126, 1, "junior_high")
    b.teacher("师", base_periods=40)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    b.assign(subject="弹性学习", teachers=["师"], periods=5, classes=["301"], blocks=(5, 1))
    fx = b.build()

    report = preflight.run(load_problem(db, fx.semester_id))
    issue = next(i for i in report.errors if i.code == "block_infeasible")
    assert "5 连堂" in issue.message and "4 节" in issue.message


# ── D7 墙钟重叠(纯函式)────────────────────────────────────
def _slot(weekday, pno, start, end):
    return Slot(weekday=weekday, period_no=pno, name=f"第{pno}节",
                start_min=start, end_min=end)


def test_slots_overlap_same_table_uses_period_no():
    a = _slot(1, 3, 10 * 60 + 10, 11 * 60)
    b = _slot(1, 3, 9 * 60, 10 * 60)  # 时间不重叠,但同表同节次
    assert slots_overlap(a, b, same_table=True)
    assert not slots_overlap(a, _slot(1, 4, 10 * 60 + 10, 11 * 60), same_table=True)


def test_slots_overlap_cross_table_uses_wall_clock():
    # 小学 40 分/节第 4 节 10:30–11:10 vs 高中 50 分/节第 3 节 10:10–11:00
    elem = _slot(1, 4, 10 * 60 + 30, 11 * 60 + 10)
    high = _slot(1, 3, 10 * 60 + 10, 11 * 60)
    assert slots_overlap(elem, high, same_table=False)
    assert not slots_overlap(elem, _slot(1, 3, 9 * 60, 10 * 60), same_table=False)
    assert not slots_overlap(elem, _slot(2, 3, 10 * 60 + 10, 11 * 60), same_table=False)


def test_slots_overlap_cross_table_without_times_falls_back_to_period_no():
    """跨表但有一方没填时间:无从比较,保守地当成同节次号就是同时段。"""
    timed = _slot(1, 10, 16 * 60 + 20, 17 * 60 + 10)
    untimed = _slot(1, 10, None, None)
    assert slots_overlap(timed, untimed, same_table=False)
    assert not slots_overlap(
        timed, _slot(1, 9, None, None), same_table=False)


def test_max_non_overlapping_dedups_cross_table_slots():
    same_day = [
        _slot(1, 1, 480, 530),   # 08:00–08:50
        _slot(1, 2, 540, 590),   # 09:00–09:50
        _slot(1, 1, 490, 520),   # 另一套表,与第一节重叠
    ]
    assert max_non_overlapping(same_day) == 2
    # 不同星期各自计算
    assert max_non_overlapping(same_day + [_slot(2, 1, 480, 530)]) == 3


def test_cross_table_teacher_has_fewer_available_slots(db):
    """完全中学:同一位教师任教初中部(45分)与高中部(50分),可排格数少于两表之和。"""
    from app.services.templates import build_period_table_from_template, get_template

    b = Builder(db, 127, 1, "junior_high")
    template = get_template("senior_high")
    assert template is not None
    senior = build_period_table_from_template(template, name="高中部节次表")
    b.semester.period_tables.append(senior)
    db.flush()

    b.teacher("跨部师", base_periods=80)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    jh_class = b.classes["301"]
    b.klass("101", grade=1, track=ClassTrack.senior_high.value)
    b.classes["101"].period_table_id = senior.id
    db.flush()

    b.assign(subject="国文", teachers=["跨部师"], periods=3, classes=["301"])
    b.assign(subject="数学", teachers=["跨部师"], periods=3, classes=["101"])
    fx = b.build()

    problem = load_problem(db, fx.semester_id)
    assert problem.classes[jh_class.id].period_table_id != problem.classes[
        b.classes["101"].id
    ].period_table_id

    teacher = problem.teachers[b.teachers["跨部师"].id]
    tables = problem.tables_of_teacher(teacher.id)
    assert len(tables) == 2
    naive_sum = sum(len(t.slots) for t in tables)  # 35 + 40 = 75
    available = preflight.teacher_available_slots(problem, teacher)
    assert available < naive_sum, "跨节次表的节次在墙钟上重叠,不可直接相加"
    assert available >= max(len(t.slots) for t in tables)


# ── M3-5:哪些错误挡得住「部分排课」 ─────────────────────────
def _issue(code: str, detail: dict | None = None) -> preflight.Issue:
    return preflight.Issue("error", code, "x", "semester", 1, detail or {})


def test_partial_mode_only_blocks_on_structural_errors():
    """总量不足正是部分排课要处理的事;结构性错误则连模型都建不起来。"""
    report = preflight.PreflightReport((
        _issue("class_overload"), _issue("teacher_overload"), _issue("room_supply"),
        _issue("block_infeasible"), _issue("group_shape_mismatch"),
    ))
    assert len(preflight.blocking_errors(report, allow_partial=False)) == 5
    codes = {i.code for i in preflight.blocking_errors(report, allow_partial=True)}
    assert codes == {"block_infeasible", "group_shape_mismatch"}


def test_partial_mode_blocks_when_a_room_type_has_no_room_at_all():
    """供给 0 = 一间都没有 → 建模就会失败;供给不足则可以少排几节。"""
    none_at_all = preflight.PreflightReport((_issue("room_type_supply", {"supply": 0}),))
    not_enough = preflight.PreflightReport((_issue("room_type_supply", {"supply": 30}),))
    assert preflight.blocking_errors(none_at_all, allow_partial=True)
    assert not preflight.blocking_errors(not_enough, allow_partial=True)


# ── 场地供给必须与建模端的候选集合同义(不只看类型,也看适用科目)──
def _room_type_fixture(db, year: int, *, bind_subject: str | None):
    b = Builder(db, year, 1, "junior_high")
    b.subject("音乐", required_room_type=RoomType.special)
    b.subject("美术", required_room_type=RoomType.special)
    # 全校唯一一间专科教室;bind_subject 决定它适用哪一科(空=不限)
    b.room("美术教室", room_type=RoomType.special,
           subjects=[bind_subject] if bind_subject else None)
    b.teacher("音乐师", base_periods=20)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    b.assign(subject="音乐", teachers=["音乐师"], periods=2, classes=["301"],
             required_room_type=RoomType.special)
    return b.build()


def test_room_supply_respects_subject_applicability(db):
    """唯一的专科教室只适用美术,音乐课却要求专科教室 → 建模必然失败,pre-flight 要先拦下。"""
    fx = _room_type_fixture(db, 170, bind_subject="美术")
    report = preflight.run(load_problem(db, fx.semester_id))

    issue = next(i for i in report.errors if i.code == "room_no_candidate")
    assert "音乐" in issue.message
    # 这是结构性错误:少排几节课也救不了,部分排课同样要挡
    assert preflight.blocking_errors(report, allow_partial=True)


def test_room_supply_passes_when_the_room_applies_to_the_subject(db):
    fx = _room_type_fixture(db, 171, bind_subject=None)
    report = preflight.run(load_problem(db, fx.semester_id))
    assert report.ok, [i.message for i in report.errors]


def test_room_type_demand_is_grouped_by_candidate_pool(db):
    """两门课同样要专科教室,但可用的教室集合不同 → 需求不可相加。"""
    b = Builder(db, 172, 1, "junior_high")
    b.subject("音乐", required_room_type=RoomType.special)
    b.subject("美术", required_room_type=RoomType.special)
    b.room("音乐教室", room_type=RoomType.special, subjects=["音乐"])
    b.room("美术教室", room_type=RoomType.special, subjects=["美术"])
    b.teacher("音乐师", base_periods=40)
    b.teacher("美术师", base_periods=40)
    for i in range(1, 6):
        b.klass(f"30{i}", grade=3, track=ClassTrack.junior_high.value)
        b.assign(subject="音乐", teachers=["音乐师"], periods=4, classes=[f"30{i}"],
                 required_room_type=RoomType.special)
        b.assign(subject="美术", teachers=["美术师"], periods=4, classes=[f"30{i}"],
                 required_room_type=RoomType.special)
    fx = b.build()

    problem = load_problem(db, fx.semester_id)
    report = preflight.run(problem)
    # 各池需求 20 节 ≤ 单间供给 35 节;若把两池相加(40)再比对「2 间 × 35」仍会过,
    # 但把 40 节硬塞进「音乐教室」就会误报。这里确认没有误报。
    assert not [i for i in report.errors if i.code == "room_type_supply"]
