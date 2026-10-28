"""教师所属年级(档案多选)测试。

覆盖:API 读写与校验、代课推荐的档案优先规则、示范资料按配课回填。
"""

import pytest
from sqlalchemy import select

from app.models.assignment import (
    AssignmentTeacher,
    CourseAssignment,
    SchedulingUnitMember,
)
from app.models.basedata import ClassUnit, Teacher
from app.models.user import Role, User
from app.services import grade_scopes
from tests.conftest import make_user
from tests.dates import SEM_END, SEM_START
from tests.test_substitutions import env2  # noqa: F401  (复用已发布课表的初中 World)

PW = "password123"


@pytest.fixture
def admin_client(env):
    client, db = env
    make_user(db, "adm", PW, roles=[Role.admin])
    client.post("/api/auth/login", json={"username": "adm", "password": PW})
    return client, db


def _semester(client) -> int:
    """建一个学期(示范资料测试不用它:已有学期时载入示范资料会 409)。"""
    return client.post("/api/semesters", json={
        "academic_year": 2026, "term": 1, "template_key": "junior_high",
        "start_date": SEM_START.isoformat(), "end_date": SEM_END.isoformat(),
    }).json()["id"]


# ── API 读写与校验 ────────────────────────────────


def test_teacher_grades_crud_and_sorted(admin_client):
    client, _db = admin_client
    sid = _semester(client)
    t = client.post(f"/api/teachers?semester_id={sid}", json={
        "name": "王师", "grade_ids": [9, 7]}).json()
    assert t["grade_ids"] == [7, 9]
    t = client.patch(f"/api/teachers/{t['id']}", json={
        "name": "王师", "grade_ids": [8]}).json()
    assert t["grade_ids"] == [8]
    t = client.patch(f"/api/teachers/{t['id']}", json={
        "name": "王师", "grade_ids": []}).json()
    assert t["grade_ids"] == []
    assert client.get(f"/api/teachers/{t['id']}").json()["grade_ids"] == []


def test_teacher_grades_reject_out_of_range(admin_client):
    client, _db = admin_client
    sid = _semester(client)
    for bad in (0, 13):
        r = client.post(f"/api/teachers?semester_id={sid}", json={
            "name": "王师", "grade_ids": [bad]})
        assert r.status_code == 422, r.json()


# ── 代课推荐:档案优先,没填沿用配课推导 ─────────────


def test_profile_grade_overrides_assignment_derived(env2):
    """档案填了就以档案为准(整体替换):
    林师配课在 8 年级、档案填 7 年级 → 对 7 年级缺口算同年级;
    陈师配课在 7 年级、档案填 8 年级 → 对 7 年级缺口算跨年级。"""
    w = env2
    w.teacher("王师", ["国文"])

    def teacher_with_grades(name: str, grades: list[int]) -> None:
        tid = w.client.post(f"/api/teachers{w.q}", json={
            "name": name, "base_periods": 20,
            "subject_ids": [w.subject("国文")], "grade_ids": grades}).json()["id"]
        w.teachers[name] = tid

    teacher_with_grades("陈师", [8])
    teacher_with_grades("林师", [7])
    w.classes["801"] = w.client.post(f"/api/class-units{w.q}", json={
        "grade": 8, "name": "801", "track": "junior_high"}).json()["id"]
    w.place("王师", "国文", "701", 0)   # 王师周三第一节 701(7 年级)国文,请假后成缺口
    w.place("陈师", "国文", "702", 2)   # 配课 7 年级,但档案 8 年级
    w.place("林师", "国文", "801", 2)   # 配课 8 年级,但档案 7 年级
    w.publish()
    affected = w.leave("王师")

    rec = w.recommend(affected[0]["id"])
    chen = next(c for c in rec["candidates"] if c["teacher_name"] == "陈师")
    lin = next(c for c in rec["candidates"] if c["teacher_name"] == "林师")
    assert chen["same_grade"] is False and "跨年级教师" in chen["reasons"]
    assert lin["same_grade"] is True and "同年级教师" in lin["reasons"]


def test_unfilled_teacher_falls_back_to_assignment_derived(env2):
    """没填档案年级的老师沿用配课推导(与旧行为一致)。"""
    w = env2
    w.teacher("王师", ["国文"])
    w.teacher("陈师", ["国文"])
    w.place("王师", "国文", "701", 0)
    w.place("陈师", "国文", "702", 2)
    w.publish()
    affected = w.leave("王师")

    rec = w.recommend(affected[0]["id"])
    chen = next(c for c in rec["candidates"] if c["teacher_name"] == "陈师")
    assert chen["same_grade"] is True and "同年级教师" in chen["reasons"]


# ── 年级主任开关(教师档案里设,与账号年级页同一批数据) ─────


def _teacher_account(admin_client):
    """建一个教师角色帐号,回传 (client, db, sid, user_id)。"""
    client, db = admin_client
    sid = _semester(client)
    user = make_user(db, "t1", PW, roles=[Role.teacher])
    return client, db, sid, user.id


def test_director_toggle_grants_role_and_scopes(admin_client):
    client, db, sid, uid = _teacher_account(admin_client)
    t = client.post(f"/api/teachers?semester_id={sid}", json={
        "name": "王师", "user_id": uid, "grade_ids": [7, 8],
        "is_grade_director": True}).json()
    assert t["is_grade_director"] is True
    assert Role.director.value in db.get(User, uid).role_names
    assert grade_scopes.user_grades(db, uid) == [7, 8]
    # 账号年级页看到的是同一批数据
    row = next(u for u in client.get("/api/users").json() if u["id"] == uid)
    assert row["grades"] == [7, 8] and Role.director.value in row["roles"]


def test_director_toggle_off_clears_role_and_scopes(admin_client):
    client, db, sid, uid = _teacher_account(admin_client)
    t = client.post(f"/api/teachers?semester_id={sid}", json={
        "name": "王师", "user_id": uid, "grade_ids": [7],
        "is_grade_director": True}).json()
    t = client.patch(f"/api/teachers/{t['id']}", json={
        "name": "王师", "user_id": uid, "grade_ids": [7],
        "is_grade_director": False}).json()
    assert t["is_grade_director"] is False
    assert Role.director.value not in db.get(User, uid).role_names
    assert grade_scopes.user_grades(db, uid) == []


def test_director_toggle_requires_account_and_grades(admin_client):
    client, db = admin_client
    sid = _semester(client)
    r = client.post(f"/api/teachers?semester_id={sid}", json={
        "name": "王师", "is_grade_director": True})
    assert r.status_code == 422, r.json()
    uid = make_user(db, "t1", PW, roles=[Role.teacher]).id
    r = client.post(f"/api/teachers?semester_id={sid}", json={
        "name": "王师", "user_id": uid, "grade_ids": [],
        "is_grade_director": True})
    assert r.status_code == 422, r.json()


def test_director_scope_follows_grade_change(admin_client):
    """已是主任时改所属年级,年级范围跟着改(主任管的年级 = 所属年级)。"""
    client, db, sid, uid = _teacher_account(admin_client)
    t = client.post(f"/api/teachers?semester_id={sid}", json={
        "name": "王师", "user_id": uid, "grade_ids": [7],
        "is_grade_director": True}).json()
    client.patch(f"/api/teachers/{t['id']}", json={
        "name": "王师", "user_id": uid, "grade_ids": [8],
        "is_grade_director": True})
    assert grade_scopes.user_grades(db, uid) == [8]
    assert Role.director.value in db.get(User, uid).role_names


# ── 全体升一年级 ────────────────────────────────


def _teacher_with_grades(client, sid, name, grades):
    return client.post(f"/api/teachers?semester_id={sid}", json={
        "name": name, "grade_ids": grades}).json()


def test_promote_grades_cycles(admin_client):
    """7→8、8→9、九年级→七年级循环带新生;多年级按每项单独升;没填与非 7/8/9 不动。"""
    client, _db = admin_client
    sid = _semester(client)
    _teacher_with_grades(client, sid, "甲", [7])
    _teacher_with_grades(client, sid, "乙", [8])
    _teacher_with_grades(client, sid, "丙", [9])
    _teacher_with_grades(client, sid, "丁", [7, 9])
    _teacher_with_grades(client, sid, "戊", [])
    _teacher_with_grades(client, sid, "己", [6])
    r = client.post(f"/api/teachers/promote-grades?semester_id={sid}")
    assert r.status_code == 200, r.json()
    assert r.json()["teachers_updated"] == 4
    got = {t["name"]: t["grade_ids"]
           for t in client.get(f"/api/teachers?semester_id={sid}").json()}
    assert got == {"甲": [8], "乙": [9], "丙": [7], "丁": [7, 8], "戊": [], "己": [6]}


def test_promote_grades_syncs_director_scopes(admin_client):
    """主任升年级后,年级范围跟着所属年级走(仍是主任)。"""
    client, db, sid, uid = _teacher_account(admin_client)
    t = client.post(f"/api/teachers?semester_id={sid}", json={
        "name": "王师", "user_id": uid, "grade_ids": [7],
        "is_grade_director": True}).json()
    client.post(f"/api/teachers/promote-grades?semester_id={sid}")
    assert client.get(f"/api/teachers/{t['id']}").json()["grade_ids"] == [8]
    assert grade_scopes.user_grades(db, uid) == [8]
    assert Role.director.value in db.get(User, uid).role_names


# ── 示范资料回填 ────────────────────────────────


def test_demo_teachers_have_grades_matching_assignments(admin_client):
    """所属年级按实际配课回填:只填该教师真正教的年级。"""
    client, db = admin_client
    sid = client.post("/api/demo-data").json()["semester_id"]
    for t in db.query(Teacher).filter(Teacher.semester_id == sid).all():
        via_assignments = {
            grade for (grade,) in db.execute(
                select(ClassUnit.grade)
                .join(SchedulingUnitMember,
                      SchedulingUnitMember.class_unit_id == ClassUnit.id)
                .join(CourseAssignment,
                      CourseAssignment.scheduling_unit_id
                      == SchedulingUnitMember.scheduling_unit_id)
                .join(AssignmentTeacher,
                      AssignmentTeacher.course_assignment_id == CourseAssignment.id)
                .where(CourseAssignment.semester_id == sid,
                       AssignmentTeacher.teacher_id == t.id)
            ).all()
        }
        assert via_assignments, f"{t.name} 没有配课"
        assert t.grade_ids == sorted(via_assignments), (
            f"{t.name} 所属年级 {t.grade_ids} 与实际配课 {sorted(via_assignments)} 不一致"
        )
