"""批次 #17:帐号—年级权限与按年级自动排课。

范围以排课单位为原子;范围外已有格位钉住不动(不标锁定),范围外无格位的配课
整个排除;有年级权限的帐号不给 grades 时默认只排自己的年级,越级给 grades 403。
"""

import pytest
from fastapi import HTTPException

from tests.dates import SEM_END, SEM_START, WED

from app.api import solver as solver_api
from app.models.timetable import ScheduleEntry
from app.models.user import Role, User, UserGradeScope
from app.services import grade_scopes
from app.workers import queue as job_queue
from app.workers import solve_job
from app.workers.progress import InMemoryProgressStore
from tests.conftest import make_user

PW = "password123"


@pytest.fixture
def sched(env, monkeypatch):
    client, db = env
    s = make_user(db, "s", PW, roles=[Role.director])
    # 主账号 s 须先有年级才能做搭建(本批语意:未配年级的主任没有任何排课权限)
    db.add(UserGradeScope(user_id=s.id, grade=7))
    db.add(UserGradeScope(user_id=s.id, grade=8))
    db.commit()
    client.post("/api/auth/login", json={"username": "s", "password": PW})

    store = InMemoryProgressStore()
    client.app.dependency_overrides[solver_api.get_progress_store] = lambda: store

    def fake_enqueue(job_id, timetable_id, max_seconds, seed, user_id, username,
                     allow_partial=False, relax=(), scope_grades=None):
        solve_job.execute(db, store, job_id, timetable_id, max_seconds, seed, user_id, username,
                          allow_partial, relax, scope_grades)

    monkeypatch.setattr(job_queue, "enqueue_solve", fake_enqueue)

    sid = client.post(
        "/api/semesters", json={"academic_year": 2026, "term": 1, "template_key": "junior_high"}
    ).json()["id"]
    tt = client.post(f"/api/timetables?semester_id={sid}", json={"name": "草稿A"}).json()
    return client, db, sid, tt["id"], store


def _seed_two_grades(client, sid):
    """701(7 年级)与 801(8 年级)各一门课,每周 2 节;回传 (701配课, 801配课, 周三前两节的 period_no)。"""
    out = {}
    for grade, klass, subject, teacher in (
        (7, "701", "语文", "王师"), (8, "801", "数学", "李师"),
    ):
        c = client.post(f"/api/class-units?semester_id={sid}",
                        json={"grade": grade, "name": klass, "track": "junior_high"}).json()
        s = client.post(f"/api/subjects?semester_id={sid}", json={"name": subject}).json()
        t = client.post(f"/api/teachers?semester_id={sid}",
                        json={"name": teacher, "base_periods": 20}).json()
        a = client.post(f"/api/assignments?semester_id={sid}", json={
            "class_id": c["id"], "subject_id": s["id"], "periods_per_week": 2,
            "teachers": [{"teacher_id": t["id"]}], "block_rules": [],
        }).json()
        out[klass] = (c, a)
    slots = [p for p in client.get(
        f"/api/class-units/{out['701'][0]['id']}/period-table").json()["periods"]
        if p["weekday"] == 3 and p["type"] == "regular"]
    return out, [slots[0]["period_no"], slots[1]["period_no"]]


def _start(client, tid, **body):
    return client.post(f"/api/timetables/{tid}/auto-schedule",
                       json={"max_seconds": 20, "seed": 1, **body})


def test_allowed_grades_semantics(sched):
    _client, db, _sid, _tid, _store = sched
    admin = make_user(db, "adm", PW, roles=[Role.admin])
    director = make_user(db, "dir", PW, roles=[Role.director])
    teacher = make_user(db, "plain", PW, roles=[Role.teacher])
    scoped = make_user(db, "scoped", PW, roles=[Role.director])
    db.add(UserGradeScope(user_id=scoped.id, grade=7))
    db.commit()

    # 三角色语意:只有管理员不受限;主任按所配年级,未配年级 = 没有排课权限
    assert grade_scopes.allowed_grades(db, admin) is None
    assert grade_scopes.allowed_grades(db, director) == set()
    assert grade_scopes.allowed_grades(db, teacher) == set()
    assert grade_scopes.allowed_grades(db, scoped) == {7}
    with pytest.raises(HTTPException):
        grade_scopes.require_grades(db, scoped, {8})
    with pytest.raises(HTTPException):
        grade_scopes.require_grades(db, director, {7})
    grade_scopes.require_grades(db, scoped, {7})  # 不抛


def test_scoped_run_pins_other_grade_entries(sched):
    client, db, sid, tid, _store = sched
    classes, periods = _seed_two_grades(client, sid)
    a801 = classes["801"][1]
    # 801 的两节先在来源草稿排好(完整);701 完全未排
    for pn in periods:
        r = client.post(f"/api/timetables/{tid}/entries", json={
            "course_assignment_id": a801["id"], "weekday": 3, "period_no": pn, "span": 1})
        assert r.status_code == 201, r.json()

    job_id = _start(client, tid, grades=[7]).json()["job_id"]
    body = client.get(f"/api/solver/jobs/{job_id}").json()
    assert body["status"] == "finished", body
    assert body["scope_grades"] == [7]

    entries = db.query(ScheduleEntry).filter_by(timetable_id=body["result_timetable_id"]).all()
    e801 = sorted((e.weekday, e.period_no) for e in entries
                  if e.course_assignment_id == a801["id"])
    assert e801 == [(3, periods[0]), (3, periods[1])]  # 原位不动
    assert all(not e.locked for e in entries if e.course_assignment_id == a801["id"])
    a701 = classes["701"][1]
    assert sum(e.span for e in entries if e.course_assignment_id == a701["id"]) == 2


def test_write_enforcement_for_scoped_director(sched):
    """有年级权限的主任:越级写操作 403;本年级写操作放行;整批指派跳过越级节次。"""
    client, db, _sid0, _tid0, _store = sched
    sid = client.post("/api/semesters", json={
        "academic_year": 2027, "term": 1, "template_key": "junior_high",
        "start_date": SEM_START.isoformat(), "end_date": SEM_END.isoformat(),
    }).json()["id"]
    q = f"?semester_id={sid}"
    ids = {}
    for grade, klass, subject, teacher in ((7, "701", "语文", "王师"), (8, "801", "数学", "李师")):
        c = client.post(f"/api/class-units{q}",
                        json={"grade": grade, "name": klass, "track": "junior_high"}).json()
        s = client.post(f"/api/subjects{q}", json={"name": subject}).json()
        t = client.post(f"/api/teachers{q}",
                        json={"name": teacher, "base_periods": 20}).json()
        a = client.post(f"/api/assignments{q}", json={
            "class_id": c["id"], "subject_id": s["id"], "periods_per_week": 1,
            "teachers": [{"teacher_id": t["id"]}], "block_rules": [],
        }).json()
        ids[klass] = (c, s, t, a)
    slots = [p for p in client.get(
        f"/api/class-units/{ids['701'][0]['id']}/period-table").json()["periods"]
        if p["weekday"] == 3 and p["type"] == "regular"]
    tt = client.post(f"/api/timetables{q}", json={"name": "草稿B"}).json()["id"]
    for klass, pn in (("701", slots[0]["period_no"]), ("801", slots[1]["period_no"])):
        r = client.post(f"/api/timetables/{tt}/entries", json={
            "course_assignment_id": ids[klass][3]["id"], "weekday": 3,
            "period_no": pn, "span": 1})
        assert r.status_code == 201, r.json()
    # 发布是整校操作,有年级限制的主任做不了,改由管理员发布
    make_user(db, "adm", PW, roles=[Role.admin])
    client.post("/api/auth/login", json={"username": "adm", "password": PW})
    r = client.post(f"/api/timetables/{tt}/publish?force=true")
    assert r.status_code == 200, r.json()
    client.post("/api/auth/login", json={"username": "s", "password": PW})

    def _leave(teacher_id):
        r = client.post(f"/api/leaves{q}", json={
            "teacher_id": teacher_id, "leave_type": "sick",
            "start_date": WED.isoformat(), "end_date": WED.isoformat()})
        assert r.status_code == 201, r.json()
        return r.json()
    leave801 = _leave(ids["801"][2]["id"])
    leave701 = _leave(ids["701"][2]["id"])
    assert len(leave801["affected_periods"]) == 1
    assert len(leave701["affected_periods"]) == 1

    make_user(db, "s7", PW, roles=[Role.director])
    s7 = db.query(User).filter_by(username="s7").first()
    db.add(UserGradeScope(user_id=s7.id, grade=7))
    db.commit()
    client.post("/api/auth/login", json={"username": "s7", "password": PW})

    # 越级:配课、班级、格位、单节指派一律 403;发布是整校动作,已任命的主任可发布,不按年级拦
    r = client.post(f"/api/assignments{q}", json={
        "class_id": ids["801"][0]["id"], "subject_id": ids["801"][1]["id"],
        "periods_per_week": 1, "teachers": [{"teacher_id": ids["801"][2]["id"]}],
        "block_rules": []})
    assert r.status_code == 403, r.json()
    r = client.post(f"/api/class-units{q}",
                    json={"grade": 8, "name": "802", "track": "junior_high"})
    assert r.status_code == 403, r.json()
    draft2 = client.post(f"/api/timetables{q}", json={"name": "草稿C"}).json()["id"]
    r = client.post(f"/api/timetables/{draft2}/entries", json={
        "course_assignment_id": ids["801"][3]["id"], "weekday": 3,
        "period_no": slots[0]["period_no"], "span": 1})
    assert r.status_code == 403, r.json()
    r = client.post(f"/api/timetables/{draft2}/publish?force=true")
    assert r.status_code == 200, r.json()
    ap801 = leave801["affected_periods"][0]["id"]
    r = client.put(f"/api/affected-periods/{ap801}/substitution",
                   json={"type": "self_study"})
    assert r.status_code == 403, r.json()

    # 本年级放行:配课新增 + 单节指派
    r = client.post(f"/api/assignments{q}", json={
        "class_id": ids["701"][0]["id"], "subject_id": ids["701"][1]["id"],
        "periods_per_week": 1, "teachers": [{"teacher_id": ids["701"][2]["id"]}],
        "block_rules": []})
    assert r.status_code == 201, r.json()
    ap701 = leave701["affected_periods"][0]["id"]
    r = client.put(f"/api/affected-periods/{ap701}/substitution",
                   json={"type": "self_study"})
    assert r.status_code == 200, r.json()

    # 整批:越级节次被跳过并说明原因,而不是整批失败
    r = client.post(f"/api/leaves/{leave801['id']}/substitutions/batch", json={
        "handler_teacher_id": ids["701"][2]["id"], "funding_source": "计入课时",
        "counts_toward_hours": True})
    assert r.status_code == 200, r.json()
    assert r.json()["assigned"] == 0
    assert any("年级权限" in s["reason"] for s in r.json()["skipped"]), r.json()


def test_users_grade_scopes_api_admin_only(sched):
    client, db, _sid, _tid, _store = sched
    make_user(db, "adm", PW, roles=[Role.admin])
    make_user(db, "s7", PW, roles=[Role.director])
    s7 = db.query(User).filter_by(username="s7").first()

    # 主任看不到帐号一览
    r = client.get("/api/users")
    assert r.status_code == 403, r.json()

    client.post("/api/auth/login", json={"username": "adm", "password": PW})
    r = client.get("/api/users")
    assert r.status_code == 200 and any(u["username"] == "s7" for u in r.json())
    r = client.put(f"/api/users/{s7.id}/grade-scopes", json={"grades": [7, 8]})
    assert r.status_code == 200 and r.json() == [7, 8]

    client.post("/api/auth/login", json={"username": "s7", "password": PW})
    r = client.get("/api/users/me/grade-scopes")
    assert r.status_code == 200 and r.json() == [7, 8]


def test_unscoped_director_is_teacher_only(sched):
    """未被分配年级的主任:配课、自动排课一律 403;自己的年级范围回空(不是 null)。"""
    client, db, _sid, tid, _store = sched
    make_user(db, "nograde", PW, roles=[Role.director])
    make_user(db, "adm", PW, roles=[Role.admin])
    client.post("/api/auth/login", json={"username": "nograde", "password": PW})

    r = client.get("/api/users/me/grade-scopes")
    assert r.status_code == 200 and r.json() == []
    r = client.post(f"/api/timetables/{tid}/auto-schedule",
                    json={"max_seconds": 20, "seed": 1})
    assert r.status_code == 403, r.json()

    client.post("/api/auth/login", json={"username": "adm", "password": PW})
    r = client.get("/api/users/me/grade-scopes")
    assert r.status_code == 200 and r.json() is None


def test_scoped_director_defaults_to_own_grades_and_cannot_exceed(sched):
    client, db, sid, tid, _store = sched
    _classes, _periods = _seed_two_grades(client, sid)
    make_user(db, "s7", PW, roles=[Role.director])
    s7 = db.query(User).filter_by(username="s7").first()
    db.add(UserGradeScope(user_id=s7.id, grade=7))
    db.commit()
    client.post("/api/auth/login", json={"username": "s7", "password": PW})

    r = _start(client, tid, grades=[8])
    assert r.status_code == 403

    job_id = _start(client, tid).json()["job_id"]
    body = client.get(f"/api/solver/jobs/{job_id}").json()
    assert body["scope_grades"] == [7]
    assert body["status"] == "finished", body


def test_appointment_grants_director_power(env):
    """任命:管理员在账号年级页给老师配年级,配了即授予该年级的主任权限。

    老师帐号原本只能当任课老师;管理员配了 7 年级后,该帐号带上主任身份,
    能排 7 年级的课,8 年级仍 403。
    """
    client, db = env
    teacher = make_user(db, "t", PW, roles=[Role.teacher])
    make_user(db, "adm", PW, roles=[Role.admin])
    client.post("/api/auth/login", json={"username": "adm", "password": PW})

    r = client.put(f"/api/users/{teacher.id}/grade-scopes", json={"grades": [7]})
    assert r.status_code == 200 and r.json() == [7]
    # API 请求跑在另一个 session,测试自己的 db 对象会读到旧角色——经 API 查才准
    users = client.get("/api/users").json()
    t = next(u for u in users if u["username"] == "t")
    assert Role.director.value in t["roles"], t

    sid = client.post("/api/semesters", json={"academic_year": 2026, "term": 1}).json()["id"]
    client.post("/api/auth/login", json={"username": "t", "password": PW})
    for grade, name in ((7, "701"), (8, "801")):
        r = client.post(f"/api/class-units?semester_id={sid}",
                        json={"grade": grade, "name": name, "track": "junior_high"})
        assert r.status_code == (201 if grade == 7 else 403), r.json()
