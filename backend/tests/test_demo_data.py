"""示范资料(Phase 2)测试。

重点不在「有没有建出东西」,而在建出来的东西**排得出课表**——
示范资料若无解,比没有示范资料更糟:用户第一次按自动排课就看到失败。
"""

import pytest

from app.models.assignment import CourseAssignment
from app.models.basedata import ClassUnit, Teacher
from app.models.user import Role
from app.services import assignments as assign_svc
from app.services import demo_data
from tests.conftest import make_user

PW = "password123"


@pytest.fixture
def admin_client(env):
    client, db = env
    make_user(db, "adm", PW, roles=[Role.admin])
    client.post("/api/auth/login", json={"username": "adm", "password": PW})
    return client, db


# ── 规格自身的一致性 ────────────────────────────────
# 这几支不碰资料库,纯粹检查 demo_school.json 的数字有没有算错。


def test_spec_gives_every_class_the_same_weekly_periods():
    spec = demo_data.load_spec()
    per_grade = {}
    for grade in spec["classes"]["grades"]:
        per_grade[grade] = sum(
            s["periods"].get(str(grade), 0) for s in spec["subjects"]
        )
    assert set(per_grade.values()) == {34}, f"各年级节数不一致:{per_grade}"


def test_spec_capacity_covers_demand():
    """教师应授总量必须够用,否则示范资料一载入就是一片超课时。"""
    spec = demo_data.load_spec()
    n = spec["classes"]["per_grade"]
    demand = sum(
        s["periods"].get(str(g), 0) * n
        for s in spec["subjects"]
        for g in spec["classes"]["grades"]
    )
    classes = demo_data._class_names(spec)
    plans = demo_data._plan_teachers(spec, [c for _, c in classes])
    # 本规格没有外聘教师;若日后新增外聘组别,其应授在 generate() 时才依实际需求算出
    capacity = sum(p.target for p in plans if p.role != demo_data.ROLE_EXTERNAL)
    assert capacity >= demand
    assert capacity / demand < 1.15, "教师过剩,示范资料会显得不真实"


def test_spec_has_one_homeroom_teacher_per_class():
    spec = demo_data.load_spec()
    classes = demo_data._class_names(spec)
    homerooms = sum(d.get(demo_data.ROLE_HOMEROOM, 0) for d in spec["departments"])
    assert homerooms == len(classes)


# ── 产生结果 ────────────────────────────────────────


def test_generate_builds_a_complete_school(admin_client):
    client, db = admin_client
    r = client.post("/api/demo-data")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["classes"] == 18
    assert body["subjects"] == 14
    assert body["total_periods"] == 34 * 18
    assert body["assignments"] == 246
    # 每班一间普通教室 + 专科教室
    assert body["rooms"] >= 18


def test_class_names_use_grade_plus_serial(admin_client):
    """班级以「年级+序号」命名:7年级1班~9年级6班。"""
    client, db = admin_client
    client.post("/api/demo-data")
    names = sorted(cu.name for cu in db.query(ClassUnit).all())
    assert names == [
        f"{g}年级{i}班" for g in (7, 8, 9) for i in range(1, 7)
    ]


def test_school_name_is_reported(admin_client):
    """校名回报给前端,供精灵与系统管理页显示「会建出哪一所学校」。"""
    client, _ = admin_client
    status = client.get("/api/demo-data").json()
    assert status["school_name"] == "杭州市育英初级中学"
    assert client.post("/api/demo-data").json()["school_name"] == "杭州市育英初级中学"


def test_every_class_has_a_homeroom_teacher(admin_client):
    client, db = admin_client
    client.post("/api/demo-data")
    for cu in db.query(ClassUnit).all():
        assert cu.homeroom_teacher_id is not None, f"{cu.name} 没有班主任"


def test_nobody_exceeds_the_overtime_limit(admin_client):
    """示范资料自己必须守 Phase 1 的规则,否则就是拿一份违规资料当范例。"""
    client, db = admin_client
    body = client.post("/api/demo-data").json()
    loads = assign_svc.teacher_loads(db, body["semester_id"])
    over = [row for row in loads if row["over_limit"]]
    assert not over, f"有教师超过上限:{[(r['name'], r['delta']) for r in over]}"
    assert body["max_overtime_used"] <= 8


def test_shows_both_over_and_under_hours(admin_client):
    """课时统计要同时看得到红、蓝两种状态,否则等于只示范了一半。"""
    client, db = admin_client
    body = client.post("/api/demo-data").json()
    loads = assign_svc.teacher_loads(db, body["semester_id"])
    assert any(r["delta"] > 0 for r in loads), "没有任何教师超课时"
    assert any(r["delta"] < 0 for r in loads), "没有任何教师课时不足"


def test_no_teacher_is_left_without_classes(admin_client):
    client, db = admin_client
    body = client.post("/api/demo-data").json()
    idle = [
        r["name"] for r in assign_svc.teacher_loads(db, body["semester_id"])
        if r["assigned"] == 0
    ]
    assert not idle, f"有教师完全没课:{idle}"


def test_zhejiang_base_periods_are_applied(admin_client):
    """语文/数学/英语/科学班主任 10 节、社会/体育/综合班主任 12 节——班主任工作量折算的差异要真的反映出来。"""
    client, db = admin_client
    client.post("/api/demo-data")
    homerooms = {
        t.name: t.base_periods
        for t in db.query(Teacher).all()
        if db.query(ClassUnit).filter(ClassUnit.homeroom_teacher_id == t.id).first()
    }
    assert set(homerooms.values()) == {10, 12}
    assert sum(1 for v in homerooms.values() if v == 10) == 14   # 语文5+数学4+英语3+科学2


def test_admin_reduction_produces_the_regulated_target(admin_client):
    """兼任主任应授 6 节、教研组长 8 节,存的是 base - reduction。"""
    client, db = admin_client
    client.post("/api/demo-data")
    targets = {
        t.admin_title: t.base_periods - t.admin_reduction
        for t in db.query(Teacher).filter(Teacher.admin_title.isnot(None)).all()
    }
    assert targets, "没有任何兼行政教师"
    for title, target in targets.items():
        expected = 6 if title.endswith("主任") else 8
        assert target == expected, f"{title} 应授 {target},应为 {expected}"


def test_subjects_follow_zhejiang_structure(admin_client):
    """浙江初中合科结构:科学、历史与社会贯通三年;信息科技只到八年级;无台湾科目。"""
    client, db = admin_client
    body = client.post("/api/demo-data").json()
    sid = body["semester_id"]
    rows = db.query(CourseAssignment).filter(CourseAssignment.semester_id == sid).all()
    by_grade: dict[int, set[str]] = {}
    for a in rows:
        for m in a.scheduling_unit.members:
            by_grade.setdefault(m.class_unit.grade, set()).add(a.subject.name)
    for g in (7, 8, 9):
        assert {"语文", "数学", "英语", "科学", "历史与社会", "道德与法治"} <= by_grade[g]
    # 信息科技在三至八年级开设,九年级不开(浙教教材〔2023〕28 号)
    assert "信息科技" in by_grade[7] and "信息科技" in by_grade[8]
    assert "信息科技" not in by_grade[9]
    # 台湾科目不得出现
    for g in (7, 8, 9):
        assert not {"国文", "本土语文", "理化", "公民"} & by_grade[g]


# ── 安全机制 ────────────────────────────────────────


def test_refuses_when_a_semester_already_exists(admin_client):
    client, _ = admin_client
    assert client.post("/api/demo-data").status_code == 201
    again = client.post("/api/demo-data")
    assert again.status_code == 409
    assert "已有学期资料" in again.json()["detail"]


def test_status_endpoint_reflects_availability(admin_client):
    client, _ = admin_client
    assert client.get("/api/demo-data").json()["available"] is True
    client.post("/api/demo-data")
    after = client.get("/api/demo-data").json()
    assert after["available"] is False and after["reason"]


def test_non_admin_cannot_load_demo_data(env):
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    assert client.post("/api/demo-data").status_code == 403


# ── 最重要的一支:示范资料排得出来吗 ──────────────────
# 示范资料若无解,比没有示范资料更糟:用户第一次按「自动排课」就看到失败,
# 而他还没有能力判断是自己弄错还是系统不行。


def test_demo_data_is_actually_solvable(admin_client):
    """以纯硬约束求解:要证明的是「有解」,软约束只影响质量不影响可行性。

    实测本机约 10 秒得到 optimal。走完整软约束是 anytime 求解,会用满时间预算
    去磨质量(60 秒 objective 从 792 降到 283),放进 CI 只是浪费几分钟。
    """
    from app.services.solver_data import load_problem
    from app.solver import preflight
    from app.solver.model_builder import SolveOptions, solve
    from app.solver.problem import SolverConfig
    from app.solver.validator import validate

    client, db = admin_client
    sid = client.post("/api/demo-data").json()["semester_id"]

    problem = load_problem(db, sid)
    errors = preflight.run(problem).errors
    assert not errors, f"pre-flight 就挡下来了:{[(i.code, i.message) for i in errors]}"

    result = solve(
        problem, SolveOptions(max_seconds=120, workers=4), config=SolverConfig.hard_only()
    )
    assert result.status in ("optimal", "feasible"), (
        f"示范资料排不出课表(status={result.status})——"
        "这代表用户第一次按自动排课就会失败"
    )
    assert not validate(problem, result.entries), "解答违反硬约束"
    # H8 周节数守恒:排入的节数必须等于配课总节数
    assert len(result.entries) == 34 * 18


def test_demo_data_marks_the_setup_wizard_complete(admin_client):
    """否则载完示范资料回首页,路由守卫会因「精灵未完成」把人弹回设置精灵——
    资料明明都建好了,却被要求再建一次。"""
    from app.models.wizard import SINGLETON_ID, WizardState

    client, db = admin_client
    body = client.post("/api/demo-data").json()
    state = db.get(WizardState, SINGLETON_ID)
    assert state is not None and state.completed is True
    assert state.semester_id == body["semester_id"]
    assert client.get("/api/wizard/state").json()["completed"] is True
