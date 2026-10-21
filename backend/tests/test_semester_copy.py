"""开新学期复制测试。对应 M1-5 验收标准。"""

import pytest

from app.models.user import Role
from tests.conftest import make_user

PW = "password123"


@pytest.fixture
def populated(env):
    """已登录教学组长 + 一个含完整基础资料的来源学期。回传 (client, source_id)。"""
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    sem = client.post(
        "/api/semesters", json={"academic_year": 2026, "term": 1, "template_key": "junior_high"}
    ).json()
    sid = sem["id"]
    # 科目已由范本带入;再加教师(含科目+时段规则)、场地、班级
    subs = client.get(f"/api/subjects?semester_id={sid}").json()
    t = client.post(
        f"/api/teachers?semester_id={sid}",
        json={"name": "王老师", "base_periods": 20, "subject_ids": [subs[0]["id"]]},
    ).json()
    client.put(
        f"/api/teachers/{t['id']}/time-rules",
        json=[{"weekday": 1, "period_no": 2, "rule_type": "unavailable"}],
    )
    client.post(f"/api/rooms?semester_id={sid}", json={"name": "理化教室", "room_type": "special"})
    for grade in (1, 2, 3):
        client.post(
            f"/api/class-units?semester_id={sid}",
            json={"grade": grade, "name": f"{grade}年甲", "track": "junior_high",
                  "homeroom_teacher_id": t["id"]},
        )
    return client, sid


def _copy(client, sid, **kwargs):
    body = {"academic_year": 2027, "term": 1, **kwargs}
    return client.post(f"/api/semesters/{sid}/copy", json=body)


def test_copy_all_and_counts(populated):
    client, sid = populated
    r = _copy(client, sid, grade_promotion=False)
    assert r.status_code == 201
    new = r.json()
    nid = new["id"]
    assert new["label"] == "2027 学年度第 1 学期"
    # 各实体数量一致
    assert len(client.get(f"/api/subjects?semester_id={nid}").json()) == \
        len(client.get(f"/api/subjects?semester_id={sid}").json())
    assert len(client.get(f"/api/teachers?semester_id={nid}").json()) == 1
    assert len(client.get(f"/api/rooms?semester_id={nid}").json()) == 1
    assert len(client.get(f"/api/class-units?semester_id={nid}").json()) == 3
    assert len(new["period_tables"]) == 1


def test_copy_is_independent(populated):
    """验收:改来源学期教师不影响新学期。"""
    client, sid = populated
    nid = _copy(client, sid, grade_promotion=False).json()["id"]
    src_teacher = client.get(f"/api/teachers?semester_id={sid}").json()[0]
    # 改来源教师姓名
    client.patch(f"/api/teachers/{src_teacher['id']}", json={"name": "改名了"})
    # 新学期教师不受影响
    new_teacher = client.get(f"/api/teachers?semester_id={nid}").json()[0]
    assert new_teacher["name"] == "王老师"
    assert new_teacher["id"] != src_teacher["id"]


def test_grade_promotion_and_graduation(populated):
    """验收:年级进位正确,毕业年级(初中三年级)移除。"""
    client, sid = populated
    nid = _copy(client, sid, grade_promotion=True).json()["id"]
    classes = client.get(f"/api/class-units?semester_id={nid}").json()
    grades = sorted(c["grade"] for c in classes)
    # 原 1,2,3 → 进位 2,3,(4 毕业移除)
    assert grades == [2, 3]


def test_no_promotion_keeps_grades(populated):
    client, sid = populated
    nid = _copy(client, sid, grade_promotion=False).json()["id"]
    grades = sorted(c["grade"] for c in client.get(f"/api/class-units?semester_id={nid}").json())
    assert grades == [1, 2, 3]


def test_teacher_subjects_and_rules_copied(populated):
    client, sid = populated
    nid = _copy(client, sid, grade_promotion=False).json()["id"]
    nt = client.get(f"/api/teachers?semester_id={nid}").json()[0]
    assert len(nt["subjects"]) == 1
    rules = client.get(f"/api/teachers/{nt['id']}/time-rules").json()
    assert len(rules) == 1 and rules[0]["rule_type"] == "unavailable"


def test_class_relations_remapped_to_new_semester(populated):
    """复制后班级的导师/节次表指向新学期的实体,非来源学期。"""
    client, sid = populated
    nid = _copy(client, sid, grade_promotion=False).json()["id"]
    new_teacher_ids = {t["id"] for t in client.get(f"/api/teachers?semester_id={nid}").json()}
    for c in client.get(f"/api/class-units?semester_id={nid}").json():
        assert c["homeroom_teacher_id"] in new_teacher_ids


def test_selective_copy_subjects_only(populated):
    client, sid = populated
    r = _copy(client, sid, subjects=True, teachers=False, rooms=False, classes=False,
              period_tables=False, grade_promotion=False)
    nid = r.json()["id"]
    assert len(client.get(f"/api/subjects?semester_id={nid}").json()) > 0
    assert client.get(f"/api/teachers?semester_id={nid}").json() == []
    assert client.get(f"/api/class-units?semester_id={nid}").json() == []


def test_copy_to_existing_target_409(populated):
    client, sid = populated
    assert _copy(client, sid, grade_promotion=False).status_code == 201
    assert _copy(client, sid, grade_promotion=False).status_code == 409  # 116/1 已存在


# ── M6-4:起讫日与排课偏好设置要跟著复制 ─────────────────────
def test_copy_carries_the_new_semester_dates(populated):
    """新学期的起讫日由呼叫端明确给(不能沿用来源:那是上学期的日期)。

    漏了它,请假展开、今日看板、代课的「已上过」判定全部失准,而且界面上看不出哪里不对。
    """
    client, sid = populated
    r = _copy(client, sid, grade_promotion=False,
              start_date="2027-02-01", end_date="2027-06-30")
    assert r.status_code == 201
    new = r.json()
    assert new["start_date"] == "2027-02-01"
    assert new["end_date"] == "2027-06-30"


def test_copy_rejects_reversed_dates(populated):
    client, sid = populated
    r = _copy(client, sid, grade_promotion=False,
              start_date="2027-06-30", end_date="2027-02-01")
    assert r.status_code == 422


def test_copy_carries_the_constraint_config(populated):
    """软约束权重跟著走:不带的话新学期悄悄回到默认值,上学期调好的偏好就白调了。"""
    client, sid = populated
    client.put(f"/api/solver/config?semester_id={sid}",
               json={"daily_subject_cap": 3, "weights": {"S2": 40}})
    source_cfg = client.get(f"/api/solver/config?semester_id={sid}").json()

    nid = _copy(client, sid, grade_promotion=False).json()["id"]
    new_cfg = client.get(f"/api/solver/config?semester_id={nid}").json()

    assert new_cfg["daily_subject_cap"] == 3
    assert new_cfg["weights"]["S2"] == 40
    assert new_cfg["weights"] == source_cfg["weights"]


def test_copy_can_skip_the_constraint_config(populated):
    """明确不勾选时,新学期回到默认值(而不是静默地总是如此)。"""
    client, sid = populated
    client.put(f"/api/solver/config?semester_id={sid}",
               json={"daily_subject_cap": 3, "weights": {"S2": 40}})

    nid = _copy(client, sid, grade_promotion=False, constraint_config=False).json()["id"]
    cfg = client.get(f"/api/solver/config?semester_id={nid}").json()
    assert cfg["daily_subject_cap"] == 2  # 默认值
    assert cfg["weights"]["S2"] != 40
