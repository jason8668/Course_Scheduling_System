"""M3-0:三套学制验证资料集的烟雾测试。

验证两件事:
1. **结构**:三套 builder 在干净资料库建出完整学期,且各自具备卡片要求的特征。
2. **自洽**:资料满足排课的必要条件——无超课时、教师配课 ≤ 可排格数、
   班级节数 ≤ 可排格数、场地需求 ≤ 供给、连堂放得进连续的一般课区段、
   跑班群组成员同节次表。

必要条件不等于充分条件:「CP-SAT 可排出全解」须待 M3-2 以独立 validator 验证。
这里拦的是资料本身的错误(pre-flight 会在 M3-1 对真实资料做同样的检查)。
"""

import pytest
from sqlalchemy import select

from app.models.assignment import CourseAssignment
from app.models.basedata import ClassTrack, RoomType
from app.models.period import Period, PeriodType
from app.services import period_tables as pt_service
from app.services.assignments import class_loads, teacher_loads
from tests.fixtures import (
    build_elementary_small,
    build_junior_high_mid,
    build_vocational_high,
    room_demand,
    teacher_available_slots,
)

BUILDERS = {
    "elementary_small": (build_elementary_small, 6, 31),
    "junior_high_mid": (build_junior_high_mid, 12, 35),
    "vocational_high": (build_vocational_high, 15, 40),
}


@pytest.fixture(params=list(BUILDERS))
def fixture_case(request, db):
    build, num_classes, regular_slots = BUILDERS[request.param]
    return build(db), num_classes, regular_slots


# ── 验收 1:三套 builder 皆建出完整学期 ────────────────────────
def test_builds_complete_semester(fixture_case, db):
    fx, num_classes, regular_slots = fixture_case

    assert fx.semester.id is not None
    assert len(fx.classes) == num_classes
    assert fx.assignments

    regular = db.scalars(
        select(Period).where(
            Period.period_table_id == fx.table.id,
            Period.type == PeriodType.regular.value,
        )
    ).all()
    assert len(regular) == regular_slots

    for c in fx.classes.values():
        assert pt_service.resolve_period_table(db, c) is not None
    for a in fx.assignments:
        assert a.teachers, "每笔配课至少一位教师"
        assert sum(1 for t in a.teachers if t.is_lead) == 1, "恰一位主教"


# ── 验收 2:资料自洽 ──────────────────────────────────────────
def test_no_teacher_over_hours(fixture_case, db):
    """无教师超课时(已配节数 ≤ 基本课时 − 行政减课)。"""
    fx, _, _ = fixture_case
    over = [row for row in teacher_loads(db, fx.semester_id) if row["delta"] > 0]
    assert not over, f"超课时教师:{[(r['name'], r['assigned'], r['target']) for r in over]}"


def test_teacher_load_within_available_slots(fixture_case, db):
    """教师配课数 ≤ 可排格数(扣除 unavailable 硬约束后)。M3-1 pre-flight 的核心检查。"""
    fx, _, _ = fixture_case
    loads = {row["teacher_id"]: row for row in teacher_loads(db, fx.semester_id)}
    for t in fx.teachers.values():
        assigned = loads[t.id]["assigned"]
        available = teacher_available_slots(db, fx, t)
        assert assigned <= available, f"{t.name} 配课 {assigned} 节 > 可排 {available} 格"


def test_no_class_over_capacity(fixture_case, db):
    """班级周节数 ≤ 该班节次表的一般课格数。"""
    fx, _, _ = fixture_case
    over = [row for row in class_loads(db, fx.semester_id) if row["over_capacity"]]
    detail = [(r["name"], r["assigned"], r["capacity"]) for r in over]
    assert not over, f"超出可排节数的班级:{detail}"


def test_room_demand_within_supply(fixture_case, db):
    """已绑定场地的配课需求 ≤ 该场地可用格数。"""
    fx, _, regular_slots = fixture_case
    by_id = {r.id: r for r in fx.rooms.values()}
    for room_id, demand in room_demand(fx).items():
        name = by_id[room_id].name
        assert demand <= regular_slots, f"{name} 需求 {demand} 节 > 供给 {regular_slots}"


def test_block_rules_fit_contiguous_regular_run(fixture_case, db):
    """连堂长度放得进某段连续的一般课节次(H6:连续且不跨午休)。"""
    fx, _, _ = fixture_case
    runs = _contiguous_regular_runs(db, fx.table.id)
    longest = max(runs.values(), default=0)
    for a in fx.assignments:
        for rule in a.block_rules:
            assert rule.block_size <= longest, (
                f"配课 {a.id} 连堂 {rule.block_size} 节 > 最长连续一般课区段 {longest} 节"
            )
            assert rule.block_size * rule.count_per_week <= a.periods_per_week


def test_group_members_share_period_table(fixture_case, db):
    """跑班群组成员班级须同节次表(architecture.md D7#4)。"""
    fx, _, _ = fixture_case
    for group in fx.groups.values():
        tables = set()
        for m in group.members:
            table = pt_service.resolve_period_table(db, m.class_unit)
            assert table is not None
            tables.add(table.id)
        assert len(tables) == 1, f"跑班群组「{group.name}」成员节次表不一致"


# ── 各套资料集的特征(卡片描述逐项对照)────────────────────────
def test_elementary_features(db):
    fx = build_elementary_small(db)

    # 包班:导师教自己班多科
    homeroom = fx.teachers["王雅婷"]  # 三年甲班导师
    taught = [
        a for a in fx.assignments if any(t.teacher_id == homeroom.id for t in a.teachers)
    ]
    assert len(taught) >= 4
    assert {a.subject_id for a in taught} == {
        fx.subjects[n].id for n in ("国语", "数学", "自然", "社会", "综合活动")
    }

    # 科任:一位教师跨全部 6 班
    pe = fx.teachers["郑建宏"]
    pe_classes = {
        m.class_unit_id
        for a in fx.assignments
        if any(t.teacher_id == pe.id for t in a.teachers)
        for m in a.scheduling_unit.members
    }
    assert len(pe_classes) == 6

    # 周三下午不排课
    wed_pm = db.scalars(
        select(Period).where(
            Period.period_table_id == fx.table.id,
            Period.weekday == 3,
            Period.period_no.in_([7, 8, 9]),
        )
    ).all()
    assert {p.type for p in wed_pm} == {PeriodType.reserved.value}

    # 导师时间
    homeroom_slot = db.scalar(
        select(Period).where(
            Period.period_table_id == fx.table.id, Period.type == PeriodType.homeroom.value
        )
    )
    assert homeroom_slot is not None and homeroom_slot.name == "导师时间"


def test_junior_high_features(db):
    fx = build_junior_high_mid(db)

    # 兼行政减课教师
    admins = [t for t in fx.teachers.values() if t.admin_reduction > 0]
    assert {t.admin_title for t in admins} == {"教学组长", "训育组长"}
    loads = {r["teacher_id"]: r for r in teacher_loads(db, fx.semester_id)}
    for t in admins:
        assert loads[t.id]["target"] == t.base_periods - t.admin_reduction
        assert loads[t.id]["assigned"] <= loads[t.id]["target"]

    # 弹性课程
    flexible = [a for a in fx.assignments if a.subject_id == fx.subjects["校本课程"].id]
    assert len(flexible) == 12 and all(a.periods_per_week == 3 for a in flexible)

    # 每班 33 节
    for row in class_loads(db, fx.semester_id):
        assert row["assigned"] == 33

    # 导师 12 位各带一班
    homerooms = [c.homeroom_teacher_id for c in fx.classes.values()]
    assert len(set(homerooms)) == 12


def test_vocational_features(db):
    fx = build_vocational_high(db)

    assert {c.department for c in fx.classes.values()} == {"机械科", "电机科", "信息科"}
    assert all(c.track == ClassTrack.vocational.value for c in fx.classes.values())

    # 3 连堂实习 ×2,绑定实习工场
    practicum = [a for a in fx.assignments if a.subject_id == fx.subjects["实习工场"].id]
    assert len(practicum) == 15
    for a in practicum:
        assert [(r.block_size, r.count_per_week) for r in a.block_rules] == [(3, 2)]
        assert a.required_room_type == RoomType.workshop.value
        assert a.room_id is not None and a.lock_room

    # 业界师资:外聘、仅周二/周四可排
    externals = [t for t in fx.teachers.values() if t.is_external]
    assert len(externals) == 3
    for t in externals:
        blocked = {r.weekday for r in t.time_rules}
        assert blocked == {1, 3, 5}
        assert teacher_available_slots(db, fx, t) == 16  # 2 天 × 8 节

    # 协同教学:三年级实习两位教师
    co_taught = [a for a in practicum if len(a.teachers) == 2]
    assert len(co_taught) == 3
    for a in co_taught:
        lead = next(t for t in a.teachers if t.is_lead)
        assert lead.teacher.is_external

    # 跑班群组:6 班、5 门选修同时段
    group = fx.groups["二年级多元选修"]
    assert len(group.members) == 6
    electives = db.scalars(
        select(CourseAssignment).where(CourseAssignment.scheduling_unit_id == group.id)
    ).all()
    assert len(electives) == 5
    assert {a.periods_per_week for a in electives} == {3}
    assert len({a.subject_id for a in electives}) == 5, "5 门不同选修(同科目会撞 H10 每日上限)"

    # 跑班群组只占班级 3 节(而非 5×3=15 节)
    g2 = {row["name"]: row for row in class_loads(db, fx.semester_id)}
    assert g2["机械二甲"]["assigned"] == 35
    assert g2["机械一甲"]["assigned"] == 35


# ── helper ──────────────────────────────────────────────────
def _contiguous_regular_runs(db, table_id: int) -> dict[int, int]:
    """每个星期最长的连续一般课节次段长度(不跨午休/早自习/导师时间)。"""
    periods = db.scalars(
        select(Period)
        .where(Period.period_table_id == table_id)
        .order_by(Period.weekday, Period.period_no)
    ).all()
    longest: dict[int, int] = {}
    run = 0
    prev_key: tuple[int, int] | None = None
    for p in periods:
        contiguous = prev_key is not None and prev_key == (p.weekday, p.period_no - 1)
        if p.type == PeriodType.regular.value:
            run = run + 1 if contiguous else 1
            longest[p.weekday] = max(longest.get(p.weekday, 0), run)
        else:
            run = 0
        prev_key = (p.weekday, p.period_no)
    return longest
