"""M4-4:今日调代课看板与调代课日志。

看板/日志不新增真相,只把「受影响节次 + 处置」摊平成可读纪录。测试集中在:
- 看板只列当天、且排除已销假的节次;含待处理让组长看出还有几节没排。
- 历史查询依教师(缺课或代课皆算)、日期区间、假别筛选。
- 摊平后的栏位正确(处置类型/代课教师/教室/是否已处置)。
- RBAC:纯教师不得存取行政看板。
"""


import pytest

from app.models.user import Role
from app.services import substitution_log as log_service
from tests.conftest import grant_grades, make_user
from tests.dates import SEM_END, SEM_START, WED, WED2  # 日期一律由执行当日推算,不硬编
from tests.test_substitutions import _World

PW = "password123"


@pytest.fixture
def w(env):
    """已发布课表的初中,登录教学组长。回传 _World。"""
    client, db = env
    grant_grades(db, make_user(db, "s", PW, roles=[Role.director]))
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    sid = client.post("/api/semesters", json={
        "academic_year": 2026, "term": 1, "template_key": "junior_high",
        "start_date": SEM_START.isoformat(), "end_date": SEM_END.isoformat(),
    }).json()["id"]
    return _World(client, db, sid)


def _board(w, on=WED):
    return w.client.get(f"/api/daily-board{w.q}&on={on.isoformat()}").json()


def _log(w, **params):
    qs = "".join(f"&{k}={v}" for k, v in params.items() if v is not None)
    return w.client.get(f"/api/substitution-log{w.q}{qs}").json()


# ── 验收①:看板反映当日处置;无异动则空 ──────────────────────
def test_board_empty_when_no_leave_that_day(w):
    w.teacher("王师", ["国文"])
    w.place("王师", "国文", "701", 0)
    w.publish()
    board = _board(w)
    assert board["entries"] == []
    assert board["date"] == WED.isoformat()
    assert board["weekday"] == 3
    assert board["school_name"]           # 表头校名(供打印通知单)
    assert board["semester_label"] == "2026-2027 学年 第 1 学期"


def test_board_lists_todays_changes_with_disposition(w):
    w.teacher("王师", ["国文"])
    w.teacher("陈师", ["国文"])
    w.place("王师", "国文", "701", 0)
    w.publish()
    affected_id = w.leave("王师")[0]["id"]
    w.assign(affected_id, type="substitute", handler_teacher_id=w.teachers["陈师"])

    board = _board(w)
    assert len(board["entries"]) == 1
    e = board["entries"][0]
    assert e["absent_teacher_name"] == "王师"
    assert e["disposed"] is True
    assert e["sub_type_label"] == "代课"
    assert e["handler_name"] == "陈师"
    assert e["class_names"] == "701"
    assert e["subject_name"] == "国文"
    assert e["leave_type_label"] == "病假"


def test_board_includes_pending_periods(w):
    """待处理节次也上看板,好让组长看出还有几节没排代课。"""
    w.teacher("王师", ["国文"])
    w.place("王师", "国文", "701", 0)
    w.publish()
    w.leave("王师")  # 不指派

    board = _board(w)
    assert len(board["entries"]) == 1
    e = board["entries"][0]
    assert e["disposed"] is False
    assert e["status_label"] == "待处理"
    assert e["handler_name"] is None


def test_board_ordered_by_period(w):
    w.teacher("王师", ["国文"])
    w.place("王师", "国文", "701", 2)  # 第三节
    w.place("王师", "国文", "701", 0)  # 第一节
    w.publish()
    w.leave("王师")

    board = _board(w)
    nos = [e["period_no"] for e in board["entries"]]
    assert nos == sorted(nos)


def test_board_excludes_cancelled_leave(w):
    """销假后,那天不再有异动——看板不列。"""
    w.teacher("王师", ["国文"])
    w.place("王师", "国文", "701", 0)
    w.publish()
    leave = w.client.post(f"/api/leaves{w.q}", json={
        "teacher_id": w.teachers["王师"], "leave_type": "sick",
        "start_date": WED.isoformat(), "end_date": WED.isoformat()}).json()
    assert _board(w)["entries"], "销假前应有一节"
    w.client.post(f"/api/leaves/{leave['id']}/cancel")
    assert _board(w)["entries"] == [], "销假后不该再列"


def test_board_only_that_day(w):
    """另一天的请假不会出现在今天的看板。"""
    w.teacher("王师", ["国文"])
    w.place("王师", "国文", "701", 0)
    w.publish()
    w.client.post(f"/api/leaves{w.q}", json={
        "teacher_id": w.teachers["王师"], "leave_type": "sick",
        "start_date": WED2.isoformat(), "end_date": WED2.isoformat()})
    assert _board(w, on=WED)["entries"] == []
    assert _board(w, on=WED2)["entries"]


def test_board_defaults_to_school_today(w, monkeypatch):
    """未带 on 时以学校时区的今天为准。"""
    w.teacher("王师", ["国文"])
    w.place("王师", "国文", "701", 0)
    w.publish()
    w.leave("王师")  # WED
    monkeypatch.setattr(log_service, "school_today", lambda: WED)
    board = w.client.get(f"/api/daily-board{w.q}").json()
    assert board["date"] == WED.isoformat()
    assert board["entries"]


# ── 历史查询 ─────────────────────────────────────────────────
def test_log_filters_by_date_range(w):
    w.teacher("王师", ["国文"])
    w.place("王师", "国文", "701", 0)
    w.publish()
    w.leave("王师", when=WED)
    w.client.post(f"/api/leaves{w.q}", json={
        "teacher_id": w.teachers["王师"], "leave_type": "sick",
        "start_date": WED2.isoformat(), "end_date": WED2.isoformat()})

    only_first = _log(w, date_from=WED.isoformat(), date_to=WED.isoformat())
    dates = {e["date"] for e in only_first}
    assert dates == {WED.isoformat()}


def test_log_filters_by_leave_type(w):
    w.teacher("王师", ["国文"])
    w.teacher("李师", ["数学"])
    w.place("王师", "国文", "701", 0)
    w.place("李师", "数学", "702", 1)
    w.publish()
    w.leave("王师", when=WED)  # sick
    w.client.post(f"/api/leaves{w.q}", json={
        "teacher_id": w.teachers["李师"], "leave_type": "official",
        "start_date": WED.isoformat(), "end_date": WED.isoformat()})

    sick = _log(w, leave_type="sick")
    assert {e["absent_teacher_name"] for e in sick} == {"王师"}
    official = _log(w, leave_type="official")
    assert {e["absent_teacher_name"] for e in official} == {"李师"}


def test_log_by_teacher_matches_absent_and_handler(w):
    """查一位教师:他缺的课与他代的课都算与他相关。"""
    w.teacher("王师", ["国文"])
    w.teacher("陈师", ["国文"])
    w.place("王师", "国文", "701", 0)  # 王师第一节(被请假)
    w.publish()
    a_wang = w.leave("王师")[0]["id"]
    w.assign(a_wang, type="substitute", handler_teacher_id=w.teachers["陈师"])

    # 以陈师查询:他没请假,但代了王师的课 → 应命中
    chen = _log(w, teacher_id=w.teachers["陈师"])
    assert len(chen) == 1
    assert chen[0]["absent_teacher_name"] == "王师"
    assert chen[0]["handler_name"] == "陈师"

    # 以王师查询:他是缺课的当事人 → 应命中
    wang = _log(w, teacher_id=w.teachers["王师"])
    assert len(wang) == 1


def test_log_newest_first(w):
    w.teacher("王师", ["国文"])
    w.place("王师", "国文", "701", 0)
    w.publish()
    w.leave("王师", when=WED)
    w.client.post(f"/api/leaves{w.q}", json={
        "teacher_id": w.teachers["王师"], "leave_type": "sick",
        "start_date": WED2.isoformat(), "end_date": WED2.isoformat()})
    dates = [e["date"] for e in _log(w)]
    assert dates == sorted(dates, reverse=True)


# ── RBAC ─────────────────────────────────────────────────────
def test_teacher_cannot_view_board(w):
    make_user(w.db, "t", PW, roles=[Role.teacher])
    w.client.post("/api/auth/logout")
    w.client.post("/api/auth/login", json={"username": "t", "password": PW})
    r = w.client.get(f"/api/daily-board{w.q}&on={WED.isoformat()}")
    assert r.status_code == 403
    r2 = w.client.get(f"/api/substitution-log{w.q}")
    assert r2.status_code == 403


def test_board_unknown_semester_404(w):
    r = w.client.get(f"/api/daily-board?semester_id=999999&on={WED.isoformat()}")
    assert r.status_code == 404


# ── mine=true:教师只看与自己有关的调代课 ───────────────────
def _bind_teacher(w, name: str, username: str) -> str:
    """把教师主档绑定到一个教师账号,返回用户名。"""
    from app.models.basedata import Teacher

    user = make_user(w.db, username, PW, roles=[Role.teacher])
    w.db.get(Teacher, w.teachers[name]).user_id = user.id
    w.db.commit()
    return username


def _login_as(w, username: str) -> None:
    r = w.client.post("/api/auth/login", json={"username": username, "password": PW})
    assert r.status_code == 200, r.json()


def _mine_board(w, on=WED):
    return w.client.get(f"/api/daily-board{w.q}&on={on.isoformat()}&mine=true").json()


def test_board_mine_filters_to_related_entries(w):
    """mine=true:教师只看与自己有关的调代课(缺课的原任教师 / 代课教师两个方向)。"""
    w.teacher("王师", ["国文"])
    w.teacher("陈师", ["国文"])
    w.teacher("李师", ["数学"])
    w.place("王师", "国文", "701", 0)
    w.place("李师", "数学", "702", 1)
    w.publish()
    affected_id = w.leave("王师")[0]["id"]
    w.assign(affected_id, type="substitute", handler_teacher_id=w.teachers["陈师"])
    w.leave("李师")  # 李师请假、无人代课:与王师、陈师都无关

    # 全校口径(默认行为不变):两条
    assert len(_board(w)["entries"]) == 2

    # 陈师登录(代课教师方向):只看到代王师那条
    _bind_teacher(w, "陈师", "chen")
    _login_as(w, "chen")
    mine = _mine_board(w)
    assert len(mine["entries"]) == 1
    assert mine["entries"][0]["absent_teacher_name"] == "王师"
    assert mine["entries"][0]["handler_name"] == "陈师"

    # 王师登录(原任教师方向):只看到自己缺课那条
    _bind_teacher(w, "王师", "wang")
    _login_as(w, "wang")
    mine = _mine_board(w)
    assert len(mine["entries"]) == 1
    assert mine["entries"][0]["absent_teacher_name"] == "王师"

    # 王师不带 mine:仍 403(教师不得看全校看板)
    r = w.client.get(f"/api/daily-board{w.q}&on={WED.isoformat()}")
    assert r.status_code == 403

    # 李师登录:只看到自己缺课那条
    _bind_teacher(w, "李师", "li")
    _login_as(w, "li")
    mine = _mine_board(w)
    assert len(mine["entries"]) == 1
    assert mine["entries"][0]["absent_teacher_name"] == "李师"


def test_board_mine_without_teacher_binding_is_empty(w):
    """mine=true 但账号未绑定教师主档:看到空看板,不报错;默认仍是全校。"""
    w.teacher("王师", ["国文"])
    w.place("王师", "国文", "701", 0)
    w.publish()
    w.leave("王师")
    make_user(w.db, "t", PW, roles=[Role.teacher])
    _login_as(w, "t")
    assert _mine_board(w)["entries"] == []

    # 主任带 mine=true 也能用(未绑定教师主档,同样空看板);默认仍是全校
    _login_as(w, "s")
    assert _mine_board(w)["entries"] == []
    assert len(_board(w)["entries"]) == 1
