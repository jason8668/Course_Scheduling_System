"""基础资料(教师/科目/场地/班级)测试。对应 M1-2 验收标准。"""

import pytest

from app.models.user import Role
from tests.conftest import make_user

PW = "password123"


@pytest.fixture
def scheduler_env(env):
    """已登录教学组长 + 一个学期,回传 (client, semester_id)。"""
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    sem = client.post("/api/semesters", json={"academic_year": 115, "term": 1}).json()
    return client, sem["id"]


def test_subject_crud(scheduler_env):
    client, sid = scheduler_env
    r = client.post(
        f"/api/subjects?semester_id={sid}", json={"name": "数学", "default_block_size": 2}
    )
    assert r.status_code == 201
    subj = r.json()
    assert subj["name"] == "数学"
    # 更新
    r = client.patch(
        f"/api/subjects/{subj['id']}", json={"name": "数学(进阶)", "default_block_size": 1}
    )
    assert r.json()["name"] == "数学(进阶)"
    # 清单
    assert len(client.get(f"/api/subjects?semester_id={sid}").json()) == 1
    # 删除
    assert client.delete(f"/api/subjects/{subj['id']}").status_code == 204


def test_teacher_with_subjects(scheduler_env):
    client, sid = scheduler_env
    s1 = client.post(f"/api/subjects?semester_id={sid}", json={"name": "国文"}).json()
    s2 = client.post(f"/api/subjects?semester_id={sid}", json={"name": "英文"}).json()
    r = client.post(
        f"/api/teachers?semester_id={sid}",
        json={"name": "王老师", "base_periods": 20, "subject_ids": [s1["id"], s2["id"]]},
    )
    assert r.status_code == 201
    teacher = r.json()
    assert {s["name"] for s in teacher["subjects"]} == {"国文", "英文"}
    assert teacher["base_periods"] == 20


def test_teacher_subject_cross_semester_rejected(scheduler_env):
    client, sid = scheduler_env
    other = client.post("/api/semesters", json={"academic_year": 115, "term": 2}).json()
    foreign = client.post(f"/api/subjects?semester_id={other['id']}", json={"name": "体育"}).json()
    r = client.post(
        f"/api/teachers?semester_id={sid}",
        json={"name": "李老师", "subject_ids": [foreign["id"]]},
    )
    assert r.status_code == 400


def test_delete_teacher_referenced_as_homeroom_blocked(scheduler_env):
    """验收①:被引用(导师)的教师不可删,提示改离职。"""
    client, sid = scheduler_env
    tid = client.post(f"/api/teachers?semester_id={sid}", json={"name": "陈老师"}).json()["id"]
    client.post(
        f"/api/class-units?semester_id={sid}",
        json={
            "grade": 3, "name": "忠", "track": "elementary", "homeroom_teacher_id": tid,
        },
    )
    r = client.delete(f"/api/teachers/{tid}")
    assert r.status_code == 409
    assert "班主任" in r.json()["detail"]
    # 改为离职(is_active=false)则允许
    upd = client.patch(f"/api/teachers/{tid}", json={"name": "陈老师", "is_active": False})
    assert upd.json()["is_active"] is False


def test_delete_subject_referenced_blocked(scheduler_env):
    client, sid = scheduler_env
    subj = client.post(f"/api/subjects?semester_id={sid}", json={"name": "理化"}).json()
    client.post(
        f"/api/teachers?semester_id={sid}",
        json={"name": "吴老师", "subject_ids": [subj["id"]]},
    )
    assert client.delete(f"/api/subjects/{subj['id']}").status_code == 409


def test_teacher_time_rules(scheduler_env):
    """验收②:教师不可排/偏好时段设置。"""
    client, sid = scheduler_env
    teacher = client.post(f"/api/teachers?semester_id={sid}", json={"name": "林老师"}).json()
    rules = [
        {"weekday": 1, "period_no": 2, "rule_type": "unavailable"},
        {"weekday": 3, "period_no": 4, "rule_type": "prefer"},
    ]
    r = client.put(f"/api/teachers/{teacher['id']}/time-rules", json=rules)
    assert r.status_code == 200
    assert len(r.json()) == 2
    got = client.get(f"/api/teachers/{teacher['id']}/time-rules").json()
    assert {(x["weekday"], x["period_no"], x["rule_type"]) for x in got} == {
        (1, 2, "unavailable"),
        (3, 4, "prefer"),
    }


def test_time_rules_reject_duplicate_cell(scheduler_env):
    client, sid = scheduler_env
    teacher = client.post(f"/api/teachers?semester_id={sid}", json={"name": "黄老师"}).json()
    dup = [
        {"weekday": 1, "period_no": 1, "rule_type": "unavailable"},
        {"weekday": 1, "period_no": 1, "rule_type": "avoid"},
    ]
    assert client.put(f"/api/teachers/{teacher['id']}/time-rules", json=dup).status_code == 400


def test_class_vocational_department_and_homeroom(scheduler_env):
    """验收③:技高班级可填群科;可指定导师。"""
    client, sid = scheduler_env
    teacher = client.post(f"/api/teachers?semester_id={sid}", json={"name": "导师甲"}).json()
    r = client.post(
        f"/api/class-units?semester_id={sid}",
        json={
            "grade": 1, "name": "甲", "track": "vocational",
            "department": "机械科", "homeroom_teacher_id": teacher["id"],
        },
    )
    assert r.status_code == 201
    cu = r.json()
    assert cu["department"] == "机械科"
    assert cu["homeroom_teacher"]["name"] == "导师甲"


def test_room_crud_with_capacity(scheduler_env):
    client, sid = scheduler_env
    r = client.post(
        f"/api/rooms?semester_id={sid}",
        json={"name": "机械实习工场", "room_type": "workshop", "capacity": 30},
    )
    assert r.status_code == 201
    assert r.json()["room_type"] == "workshop"
    assert r.json()["capacity"] == 30


def test_search_teachers_by_name(scheduler_env):
    client, sid = scheduler_env
    client.post(f"/api/teachers?semester_id={sid}", json={"name": "王小明"})
    client.post(f"/api/teachers?semester_id={sid}", json={"name": "李大华"})
    found = client.get(f"/api/teachers?semester_id={sid}&q=王").json()
    assert len(found) == 1
    assert found[0]["name"] == "王小明"


def test_teacher_viewer_role_readonly(env):
    client, db = env
    make_user(db, "d", PW, roles=[Role.director])
    client.post("/api/auth/login", json={"username": "d", "password": PW})
    # director 可读(需先有学期,由 admin/scheduler 建立;此处直接测写入被拒)
    r = client.post("/api/teachers?semester_id=1", json={"name": "x"})
    assert r.status_code == 403
