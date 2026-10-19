"""M3-3:软约束权重设置(GET/PUT /api/solver/config)。"""

import pytest

from app.models.constraint import ConstraintConfig
from app.models.user import Role
from app.services.solver_data import load_config
from app.solver.model_builder import Relaxation, SolverInputError
from app.solver.problem import DEFAULT_WEIGHTS, MAX_WEIGHT
from tests.conftest import make_user

PW = "password123"


def _login(client, db, username="s", roles=(Role.scheduler,)):
    make_user(db, username, PW, roles=list(roles))
    client.post("/api/auth/login", json={"username": username, "password": PW})


def _semester(client):
    return client.post(
        "/api/semesters", json={"academic_year": 115, "term": 1, "template_key": "junior_high"}
    ).json()["id"]


def test_get_returns_defaults_for_untouched_semester(env):
    client, db = env
    _login(client, db)
    sid = _semester(client)

    body = client.get(f"/api/solver/config?semester_id={sid}").json()
    assert body["weights"] == DEFAULT_WEIGHTS
    assert body["daily_subject_cap"] == 2
    assert body["teacher_daily_max"] == 6
    assert body["teacher_consecutive_max"] == 3
    assert body["weight_names"]["S2"] == "同班同科目分散于不同日"


def test_put_persists_and_zero_weight_disables(env):
    client, db = env
    _login(client, db)
    sid = _semester(client)

    r = client.put(f"/api/solver/config?semester_id={sid}", json={
        "daily_subject_cap": 3, "teacher_daily_max": 5, "teacher_consecutive_max": 2,
        "weights": {"S2": 0, "S5": 10},
    })
    assert r.status_code == 200
    body = r.json()
    assert body["weights"]["S2"] == 0 and body["weights"]["S5"] == 10
    assert body["weights"]["S1"] == DEFAULT_WEIGHTS["S1"]  # 未指定者维持默认

    again = client.get(f"/api/solver/config?semester_id={sid}").json()
    assert again["daily_subject_cap"] == 3
    assert again["teacher_daily_max"] == 5
    assert again["weights"]["S2"] == 0

    config = load_config(db, sid)
    assert config.enabled("S2") is False
    assert config.weight("S5") == 10
    assert config.daily_subject_cap == 3


def test_put_is_idempotent(env):
    client, db = env
    _login(client, db)
    sid = _semester(client)
    payload = {"daily_subject_cap": 2, "teacher_daily_max": 6,
               "teacher_consecutive_max": 3, "weights": {"S4": 0}}
    first = client.put(f"/api/solver/config?semester_id={sid}", json=payload).json()
    second = client.put(f"/api/solver/config?semester_id={sid}", json=payload).json()
    assert first == second


def test_put_rejects_unknown_code_and_negative_weight(env):
    client, db = env
    _login(client, db)
    sid = _semester(client)

    r = client.put(f"/api/solver/config?semester_id={sid}", json={"weights": {"S9": 1}})
    assert r.status_code == 400 and "S9" in r.json()["detail"]

    r = client.put(f"/api/solver/config?semester_id={sid}", json={"weights": {"S1": -1}})
    assert r.status_code == 400


def test_config_requires_scheduler_to_write(env):
    client, db = env
    _login(client, db, username="d", roles=(Role.director,))
    # director 不能建学期,借用 admin 建好的?此处仅验权限:director 可读不可写
    assert client.get("/api/solver/config?semester_id=1").status_code in (403, 404)
    assert client.put("/api/solver/config?semester_id=1", json={"weights": {}}).status_code == 403


def test_unknown_semester_404(env):
    client, db = env
    _login(client, db)
    assert client.get("/api/solver/config?semester_id=9999").status_code == 404
    assert client.put("/api/solver/config?semester_id=9999",
                      json={"weights": {}}).status_code == 404


# ── 权重上限是部分排课的正确性前提,不是美观限制 ──────────────
def _put(client, sid, weights):
    return client.put(f"/api/solver/config?semester_id={sid}", json={
        "daily_subject_cap": 2, "teacher_daily_max": 6,
        "teacher_consecutive_max": 3, "weights": weights})


def test_weight_above_max_is_rejected(env):
    """权重若能设到 20000,solver 会理性地丢掉一节课去换分散度。"""
    client, db = env
    _login(client, db)
    sid = _semester(client)

    r = _put(client, sid, {"S2": 20000})
    assert r.status_code == 400
    assert "丢课" in r.json()["detail"]
    assert _put(client, sid, {"S2": MAX_WEIGHT}).status_code == 200


def test_stored_weight_over_max_is_clamped_on_read(env):
    """旧资料可能存过超大权重;读出来一定要夹回上限,否则 worker 仍会宁可丢课。"""
    client, db = env
    _login(client, db)
    sid = _semester(client)

    db.add(ConstraintConfig(semester_id=sid, key="S2", value=99999))
    db.commit()
    assert load_config(db, sid).weight("S2") == MAX_WEIGHT
    assert client.get(f"/api/solver/config?semester_id={sid}").json()["weights"]["S2"] == MAX_WEIGHT


def test_relaxation_penalties_must_stay_ordered():
    """未排入 > 放宽的硬约束 > 软约束的最大总和。顺序反了就会用丢课换软约束分数。"""
    with pytest.raises(SolverInputError, match="惩罚量级"):
        Relaxation(unplaced_penalty=500, violation_penalty=1000)
    with pytest.raises(SolverInputError, match="惩罚量级"):
        Relaxation(violation_penalty=10)  # 小于 MAX_WEIGHT × 8
    Relaxation()  # 默认值必须合法
