"""校历活动(批次 #4)测试:CRUD、权限、校验、已发布学期周次、求解器占用。"""

from datetime import date

from app.core.clock import school_today
from app.core.week_parity import week_number, week_parity
from app.models.calendar import SchoolCalendarEvent
from app.models.user import Role
from app.schemas.timetable import PublicSemester
from app.services.solver_data import load_problem
from tests.conftest import as_admin, grant_grades, make_user
from tests.fixtures import build_junior_high_mid
from tests.test_timetables import MAIN_SLOTS, _assign, _class, _periods, _place, _subject, _teacher

PW = "password123"


def _login(client, db, roles=(Role.director,), username="s"):
    user = make_user(db, username, PW, roles=list(roles))
    if Role.director in roles:
        grant_grades(db, user)
    resp = client.post("/api/auth/login", json={"username": username, "password": PW})
    assert resp.status_code == 200
    return user


def _semester(client, **extra):
    payload = {
        "academic_year": 2026, "term": 1,
        "start_date": "2026-09-07", "end_date": "2027-01-15",
        **extra,
    }
    resp = client.post("/api/semesters", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _payload(sid, **over):
    base = {
        "semester_id": sid,
        "title": "运动会",
        "event_type": "activity",
        "scope_type": "school",
        "start_date": "2026-10-30",
        "end_date": "2026-10-30",
        "weekly_recurring": False,
    }
    base.update(over)
    return base


# ── CRUD ──────────────────────────────────
def test_calendar_crud(env):
    client, db = env
    user = _login(client, db)
    sid = _semester(client)

    # school 范围即使传了 scope_id 也强制置 None;created_by 记当前用户
    resp = client.post("/api/calendar-events", json=_payload(sid, scope_id=123))
    assert resp.status_code == 201, resp.text
    ev = resp.json()
    assert ev["title"] == "运动会"
    assert ev["scope_id"] is None
    assert ev["semester_id"] == sid
    assert ev["created_by"] == user.id

    # 列表能查到;范围外查不到(非重复事件)
    lst = client.get(f"/api/calendar-events?semester_id={sid}").json()
    assert [e["id"] for e in lst] == [ev["id"]]
    in_range = client.get(
        f"/api/calendar-events?semester_id={sid}&from=2026-10-01&to=2026-10-31"
    ).json()
    assert [e["id"] for e in in_range] == [ev["id"]]
    out_range = client.get(
        f"/api/calendar-events?semester_id={sid}&from=2026-11-01&to=2026-11-30"
    ).json()
    assert out_range == []

    # PATCH 改标题
    resp = client.patch(f"/api/calendar-events/{ev['id']}", json={"title": "秋季运动会"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] == "秋季运动会"

    # DELETE 后查不到
    assert client.delete(f"/api/calendar-events/{ev['id']}").status_code == 204
    assert client.get(f"/api/calendar-events?semester_id={sid}").json() == []


def test_calendar_create_accepts_semester_id_query(env):
    """semester_id 也可走查询参数(与仓库其他建立端点一致的回退方式)。"""
    client, db = env
    _login(client, db)
    sid = _semester(client)
    payload = _payload(sid)
    del payload["semester_id"]
    resp = client.post(f"/api/calendar-events?semester_id={sid}", json=payload)
    assert resp.status_code == 201, resp.text
    assert resp.json()["semester_id"] == sid


def test_calendar_recurring_event_returned_for_later_range(env):
    """每周重复事件:原始日期在范围外,学期尚未结束时仍应回传供前端展开。"""
    client, db = env
    _login(client, db)
    sid = _semester(client)
    resp = client.post(
        "/api/calendar-events",
        json=_payload(
            sid, title="周会", start_date="2026-09-07", end_date="2026-09-07",
            weekly_recurring=True,
        ),
    )
    assert resp.status_code == 201, resp.text
    later = client.get(
        f"/api/calendar-events?semester_id={sid}&from=2026-11-02&to=2026-11-08"
    ).json()
    assert [e["title"] for e in later] == ["周会"]


def test_calendar_grade_and_class_scope(env):
    client, db = env
    _login(client, db)
    sid = _semester(client)
    cls = _class(client, sid, 7, "701")

    r = client.post(
        "/api/calendar-events",
        json=_payload(sid, title="年级活动", scope_type="grade", scope_id=7),
    )
    assert r.status_code == 201, r.text
    assert r.json()["scope_id"] == 7

    r = client.post(
        "/api/calendar-events",
        json=_payload(sid, title="班级活动", scope_type="class", scope_id=cls["id"]),
    )
    assert r.status_code == 201, r.text
    assert r.json()["scope_id"] == cls["id"]


# ── 权限 ──────────────────────────────────
def test_calendar_permissions_teacher_read_only(env):
    client, db = env
    _login(client, db)
    sid = _semester(client)
    assert client.post("/api/calendar-events", json=_payload(sid)).status_code == 201

    _login(client, db, roles=(Role.teacher,), username="t")
    # _login 追加帐号后需重新登录为教师:make_user + login 已在 _login 完成,
    # 但先前的 scheduler session cookie 会被这次 login 覆盖
    resp = client.get(f"/api/calendar-events?semester_id={sid}")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert client.post("/api/calendar-events", json=_payload(sid)).status_code == 403
    ev_id = resp.json()[0]["id"]
    assert client.patch(
        f"/api/calendar-events/{ev_id}", json={"title": "x"}
    ).status_code == 403
    assert client.delete(f"/api/calendar-events/{ev_id}").status_code == 403


def test_calendar_unauthenticated(env):
    client, db = env
    # 未登录
    assert client.get("/api/calendar-events?semester_id=1").status_code == 401


def test_calendar_director_can_edit(env):
    client, db = env
    _login(client, db)
    sid = _semester(client)
    client.post("/api/auth/logout")
    _login(client, db, roles=(Role.director,), username="d")
    r = client.post("/api/calendar-events", json=_payload(sid))
    assert r.status_code == 201, r.text


# ── 校验 ──────────────────────────────────
def test_calendar_validation_end_before_start(env):
    client, db = env
    _login(client, db)
    sid = _semester(client)
    r = client.post(
        "/api/calendar-events",
        json=_payload(sid, start_date="2026-10-30", end_date="2026-10-29"),
    )
    assert r.status_code in (400, 422), r.text


def test_calendar_validation_period_must_be_pair(env):
    client, db = env
    _login(client, db)
    sid = _semester(client)
    r = client.post("/api/calendar-events", json=_payload(sid, period_start=1))
    assert r.status_code in (400, 422), r.text
    r = client.post(
        "/api/calendar-events",
        json=_payload(sid, period_start=3, period_end=2),
    )
    assert r.status_code in (400, 422), r.text
    r = client.post(
        "/api/calendar-events",
        json=_payload(sid, period_start=1, period_end=2),
    )
    assert r.status_code == 201, r.text


def test_calendar_validation_class_scope_must_exist(env):
    client, db = env
    _login(client, db)
    sid = _semester(client)
    r = client.post(
        "/api/calendar-events",
        json=_payload(sid, scope_type="class", scope_id=999999),
    )
    assert r.status_code == 400, r.text
    r = client.post(
        "/api/calendar-events",
        json=_payload(sid, scope_type="grade", scope_id=None),
    )
    assert r.status_code == 400, r.text


def test_calendar_semester_not_found(env):
    client, db = env
    _login(client, db)
    r = client.post("/api/calendar-events", json=_payload(999999))
    assert r.status_code == 404, r.text


# ── 已发布学期:周次栏位 ───────────────────
def test_week_number_and_public_semester_serialization():
    start = date(2026, 9, 7)  # 周一
    assert start.isoweekday() == 1
    assert week_number(start, date(2026, 9, 7)) == 1
    assert week_parity(start, date(2026, 9, 7)) == "odd"
    assert week_number(start, date(2026, 9, 14)) == 2
    assert week_parity(start, date(2026, 9, 14)) == "even"
    assert week_number(None, date(2026, 9, 7)) is None
    assert week_parity(None, date(2026, 9, 7)) is None

    out = PublicSemester(
        id=1, label="2026-2027 学年 第 1 学期",
        start_date=start, end_date=date(2027, 1, 15),
        current_week_number=1, current_week_parity="odd",
    ).model_dump()
    assert out["start_date"] == start
    assert out["end_date"] == date(2027, 1, 15)
    assert out["current_week_number"] == 1
    assert out["current_week_parity"] == "odd"
    # 旧栏位不变
    assert out["id"] == 1 and "学年" in out["label"]


def test_published_semesters_include_week_fields(env):
    client, db = env
    _login(client, db)
    sid = _semester(client)
    pt = client.post(
        f"/api/semesters/{sid}/period-tables", json={"name": "主表", "is_default": True}
    ).json()
    client.put(f"/api/period-tables/{pt['id']}/periods", json=_periods(MAIN_SLOTS))
    tt = client.post(f"/api/timetables?semester_id={sid}", json={"name": "草稿A"}).json()

    c = _class(client, sid, 3, "301")
    s = _subject(client, sid, "国文")
    t = _teacher(client, sid, "王师")
    a = _assign(
        client, sid, class_id=c["id"], subject_id=s["id"],
        teacher_ids=[t["id"]], periods=1,
    )
    _place(client, tt["id"], a["id"], 1, 1)
    with as_admin(client, db):
        assert client.post(f"/api/timetables/{tt['id']}/publish").status_code == 200

    sems = client.get("/api/published/semesters").json()
    assert len(sems) == 1
    sem = sems[0]
    assert sem["id"] == sid
    assert sem["start_date"] == "2026-09-07"
    assert sem["end_date"] == "2027-01-15"
    today = school_today()
    assert sem["current_week_number"] == week_number(date(2026, 9, 7), today)
    assert sem["current_week_parity"] == week_parity(date(2026, 9, 7), today)


def test_solver_calendar_blocks_class_scope(db):
    fx = build_junior_high_mid(db, academic_year=116)
    baseline = load_problem(db, fx.semester_id)
    target_id = sorted(baseline.classes)[0]
    target = baseline.classes[target_id]
    cell = baseline.tables[target.period_table_id].slots_on(1)[0].key
    # 任教该班的教师与不任教该班的教师各取一位(以配课为准)
    teaching = {
        tid
        for a in baseline.assignments
        if target_id in baseline.units[a.unit_id].class_ids
        for tid in a.teacher_ids
    }
    others = [tid for tid in baseline.teachers if tid not in teaching]
    assert teaching and others

    db.add(SchoolCalendarEvent(
        semester_id=fx.semester_id, title="班级活动", event_type="activity",
        scope_type="class", scope_id=target_id,
        start_date=date(2026, 9, 7), end_date=date(2026, 9, 7),
        period_start=cell[1], period_end=cell[1],
        weekly_recurring=True,
    ))
    db.commit()

    problem = load_problem(db, fx.semester_id)
    assert cell in problem.classes[target_id].unavailable
    assert "班级活动" in problem.classes[target_id].unavailable_reasons[cell]
    for cid, cls in problem.classes.items():
        if cid != target_id:
            assert cell not in cls.unavailable
    for tid in teaching:
        assert "班级活动" in "、".join(problem.teachers[tid].unavailable_reasons.values())
    for tid in others:
        assert "班级活动" not in "、".join(
            problem.teachers[tid].unavailable_reasons.values()
        )


# ── 求解器占用 ────────────────────────────
def test_solver_calendar_blocks_recurring_school_event(db):
    fx = build_junior_high_mid(db)
    # 2026-09-07 是周一(weekday=1),junior_high 每周一都有 regular 节次
    db.add(SchoolCalendarEvent(
        semester_id=fx.semester_id, title="运动会", event_type="activity",
        scope_type="school", scope_id=None,
        start_date=date(2026, 9, 7), end_date=date(2026, 9, 7),
        weekly_recurring=True,
    ))
    db.commit()

    problem = load_problem(db, fx.semester_id)
    assert problem.classes, "fixture 应有班级"
    for cls in problem.classes.values():
        table = problem.tables[cls.period_table_id]
        monday = table.slots_on(1)
        assert monday, "周一应有节次"
        for slot in monday:
            assert slot.key in cls.unavailable, (
                f"班级 {cls.name} 周一 {slot.key} 应被校历占用"
            )
            assert "运动会" in cls.unavailable_reasons[slot.key]

    teachers_with_block = [
        t for t in problem.teachers.values()
        if any(cell[0] == 1 for cell in t.unavailable)
    ]
    assert teachers_with_block, "至少一位教师应被全校活动占用"
    assert any(
        "运动会" in reason
        for t in teachers_with_block
        for reason in t.unavailable_reasons.values()
    )

    # 非重复事件不进 unavailable
    db.add(SchoolCalendarEvent(
        semester_id=fx.semester_id, title="临时停课", event_type="other",
        scope_type="school", scope_id=None,
        start_date=date(2026, 9, 8), end_date=date(2026, 9, 8),
        weekly_recurring=False,
    ))
    db.commit()
    problem2 = load_problem(db, fx.semester_id)
    for cls in problem2.classes.values():
        assert not any(
            "临时停课" in r for r in cls.unavailable_reasons.values()
        )
        # 周二(weekday=2)的格子不应因该一次性事件被占用
        table = problem2.tables[cls.period_table_id]
        for slot in table.slots_on(2):
            assert slot.key not in cls.unavailable
    for t in problem2.teachers.values():
        assert not any("临时停课" in r for r in t.unavailable_reasons.values())
