"""M4-1:请假登记与受影响节次展开。

**这里验的是「周循环格 → 日历日期」这层转换。** M0–M3 的一切都建立在
`(weekday, period_no)` 上;请假是「王师 11/12 上午请假」。转换错了,M4-2 的代课推荐
(「该时段空堂、当日未请假」)整个站不住。

日期边界是重点:周末、学期起讫外、跨周、半天、连堂。
"""

import pytest

from app.models.leave import AffectedStatus, LeaveRequest, LeaveStatus
from app.models.notification import Notification, NotificationType
from app.models.user import Role
from tests.conftest import make_user

# 日期一律由执行当日推算(硬编会过期,见 tests/dates.py):
# MON/WED/FRI/SAT 同属一个未来的基准周,SUN 是该周日、NEXT_MON 是下周一。
from tests.dates import (
    AFTER_SEM,
    BEFORE_SEM,
    FRI,
    MON,
    NEXT_MON,
    SAT,
    SEM_END,
    SEM_START,
    SUN,
    WED,
)

PW = "password123"


@pytest.fixture
def school(env):
    """已发布课表的初中:王师周三 5 节国文(701~705 班各一节)、周五 1 节。

    回传 (client, db, semester_id, teacher_id)。
    """
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})

    sid = client.post("/api/semesters", json={
        "academic_year": 2026, "term": 1, "template_key": "junior_high",
        "start_date": SEM_START.isoformat(), "end_date": SEM_END.isoformat(),
    }).json()["id"]

    subject = client.post(f"/api/subjects?semester_id={sid}", json={"name": "国文"}).json()
    wang = client.post(f"/api/teachers?semester_id={sid}",
                       json={"name": "王师", "base_periods": 20}).json()
    tt = client.post(f"/api/timetables?semester_id={sid}", json={"name": "草稿A"}).json()
    classes = [
        client.post(f"/api/class-units?semester_id={sid}", json={
            "grade": 7, "name": f"70{i}", "track": "junior_high"}).json()["id"]
        for i in range(1, 6)
    ]

    # 周三的 5 个一般课节次(初中范本第一节的 period_no 是 2,不是 1)
    slots = client.get(f"/api/class-units/{classes[0]}/period-table").json()["periods"]
    wed_slots = [p["period_no"] for p in slots
                 if p["weekday"] == 3 and p["type"] == "regular"][:5]
    fri_slot = next(p["period_no"] for p in slots
                    if p["weekday"] == 5 and p["type"] == "regular")

    def assign_and_place(class_id, weekday, period_no):
        a = client.post(f"/api/assignments?semester_id={sid}", json={
            "class_id": class_id, "subject_id": subject["id"], "periods_per_week": 1,
            "teachers": [{"teacher_id": wang["id"]}], "block_rules": []}).json()
        r = client.post(f"/api/timetables/{tt['id']}/entries", json={
            "course_assignment_id": a["id"], "weekday": weekday,
            "period_no": period_no, "span": 1})
        assert r.status_code == 201, r.json()

    for cid, pno in zip(classes, wed_slots, strict=True):
        assign_and_place(cid, 3, pno)
    assign_and_place(classes[0], 5, fri_slot)  # 周五 701 班一节

    r = client.post(f"/api/timetables/{tt['id']}/publish?force=true")
    assert r.status_code == 200, r.json()
    return client, db, sid, wang["id"]


def _bind_account(client, db, teacher_id: int, username: str):
    """把登录帐号绑到教师主档。PATCH /teachers 是整笔取代,得带齐必填栏位。"""
    user = make_user(db, username, PW, roles=[Role.teacher])
    r = client.patch(f"/api/teachers/{teacher_id}", json={
        "name": "王师", "base_periods": 20, "user_id": user.id})
    assert r.status_code == 200, r.json()
    return user


def _leave(client, sid, teacher_id, **body):
    return client.post(f"/api/leaves?semester_id={sid}", json={
        "teacher_id": teacher_id, "leave_type": "sick", **body})


# ── 验收①:整天假展开当天全部节次 ──────────────────────────
def test_full_day_leave_expands_every_period_that_day(school):
    client, _db, sid, tid = school
    r = _leave(client, sid, tid, start_date=WED.isoformat(), end_date=WED.isoformat())
    assert r.status_code == 201, r.json()
    body = r.json()

    assert body["affected_count"] == 5
    assert body["pending_count"] == 5
    periods = body["affected_periods"]
    assert all(p["date"] == WED.isoformat() for p in periods)
    assert all(p["weekday"] == 3 for p in periods)
    assert [p["class_names"] for p in periods] == ["701", "702", "703", "704", "705"]
    # 节次一律用节次表的名称,不用内部 period_no(period_no 2 才是「第一节」)
    assert periods[0]["period_name"] == "第一节"
    assert periods[0]["subject_name"] == "国文"


# ── 验收②:跨周末只展开上课日 ───────────────────────────────
def test_leave_across_a_weekend_skips_non_school_days(school):
    client, _db, sid, tid = school
    # 周三 ~ 下周一,中间夹周六日
    r = _leave(client, sid, tid, start_date=WED.isoformat(), end_date=NEXT_MON.isoformat())
    body = r.json()

    days = sorted({p["date"] for p in body["affected_periods"]})
    assert days == [WED.isoformat(), FRI.isoformat()]  # 周四无课、周六日不上课、周一无课
    assert body["affected_count"] == 6  # 周三 5 节 + 周五 1 节


def test_a_leave_entirely_on_the_weekend_affects_nothing(school):
    client, _db, sid, tid = school
    r = _leave(client, sid, tid, start_date=SAT.isoformat(), end_date=SUN.isoformat())
    assert r.status_code == 201
    assert r.json()["affected_count"] == 0  # 假单成立,只是没有课要处理


# ── 半天假:以墙钟时间区间判定 ───────────────────────────────
def test_morning_leave_only_expands_morning_periods(school):
    client, _db, sid, tid = school
    r = _leave(client, sid, tid, start_date=WED.isoformat(), end_date=WED.isoformat(),
               start_time="08:00", end_time="12:00")
    periods = r.json()["affected_periods"]

    assert 0 < len(periods) < 5, "上午请假不该把下午的课也列进来"
    assert all(p["end_time"] <= "12:00:00" for p in periods)


def test_afternoon_leave_only_expands_afternoon_periods(school):
    client, _db, sid, tid = school
    r = _leave(client, sid, tid, start_date=WED.isoformat(), end_date=WED.isoformat(),
               start_time="13:00", end_time="17:00")
    periods = r.json()["affected_periods"]

    assert periods, "下午应该有课"
    assert all(p["start_time"] >= "13:00:00" for p in periods)


def test_multi_day_leave_applies_times_only_to_the_boundary_days(school):
    """「周三 13:00 ~ 周五 12:00」= 周三下午 + 周四整天 + 周五上午。"""
    client, _db, sid, tid = school
    r = _leave(client, sid, tid, start_date=WED.isoformat(), end_date=FRI.isoformat(),
               start_time="13:00", end_time="12:00")
    periods = r.json()["affected_periods"]

    wed = [p for p in periods if p["date"] == WED.isoformat()]
    fri = [p for p in periods if p["date"] == FRI.isoformat()]
    assert wed and all(p["start_time"] >= "13:00:00" for p in wed)
    assert fri and all(p["end_time"] <= "12:00:00" for p in fri)


# ── 日期边界:学期起讫外一律拒绝 ─────────────────────────────
@pytest.mark.parametrize(("start", "end", "reason"), [
    (BEFORE_SEM, BEFORE_SEM, "学期开始前"),
    (AFTER_SEM, AFTER_SEM, "学期结束后"),
    (FRI, WED, "结束早于开始"),
])
def test_dates_outside_the_semester_are_rejected(school, start, end, reason):
    client, _db, sid, tid = school
    r = _leave(client, sid, tid, start_date=start.isoformat(), end_date=end.isoformat())
    assert r.status_code == 400, reason


def test_end_time_before_start_time_on_the_same_day_is_rejected(school):
    client, _db, sid, tid = school
    r = _leave(client, sid, tid, start_date=WED.isoformat(), end_date=WED.isoformat(),
               start_time="13:00", end_time="09:00")
    assert r.status_code == 400


def test_semester_without_dates_cannot_accept_leaves(env):
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    sid = client.post("/api/semesters", json={
        "academic_year": 2027, "term": 1, "template_key": "junior_high"}).json()["id"]
    t = client.post(f"/api/teachers?semester_id={sid}",
                    json={"name": "王师", "base_periods": 20}).json()

    r = _leave(client, sid, t["id"], start_date=WED.isoformat(), end_date=WED.isoformat())
    assert r.status_code == 400
    assert "学期尚未设置起讫日期" in r.json()["detail"]


# ── 验收③:销假 → 级联取消 + 通知已指派的代课教师 ────────────
def test_cancelling_a_leave_notifies_the_assigned_substitute(school):
    client, db, sid, tid = school
    li = client.post(f"/api/teachers?semester_id={sid}",
                     json={"name": "李师", "base_periods": 20}).json()

    leave_id = _leave(client, sid, tid, start_date=WED.isoformat(),
                      end_date=WED.isoformat()).json()["id"]
    leave = db.get(LeaveRequest, leave_id)

    # 模拟 M4-2 已指派李师代其中 2 节、1 节已上完
    periods = sorted(leave.affected_periods, key=lambda p: p.period_no)
    for p in periods[:2]:
        p.status = AffectedStatus.resolved.value
        p.handler_teacher_id = li["id"]
    periods[4].status = AffectedStatus.completed.value
    db.commit()

    r = client.post(f"/api/leaves/{leave_id}/cancel")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == LeaveStatus.cancelled.value
    assert body["revoked_count"] == 2
    assert body["notified_teachers"] == ["李师"]

    db.expire_all()
    leave = db.get(LeaveRequest, leave_id)
    states = [p.status for p in sorted(leave.affected_periods, key=lambda p: p.period_no)]
    # 已完成的那节不动——课已经上过了,事后销假不能把历史抹掉
    assert states == ["cancelled"] * 4 + ["completed"]

    # 李师收到一封合并通知(2 节并成一封,不是两封)
    notes = db.query(Notification).filter_by(teacher_id=li["id"]).all()
    assert len(notes) == 1
    assert notes[0].type == NotificationType.substitution_cancelled.value
    assert "王师" in notes[0].title
    assert "2 节" in notes[0].body

    # 王师本人:代登通知 + 销假通知
    wang_notes = db.query(Notification).filter_by(teacher_id=tid).all()
    assert [n.type for n in wang_notes] == [
        NotificationType.leave_registered.value,
        NotificationType.leave_cancelled.value,
    ]


def test_cancelling_twice_is_rejected(school):
    client, _db, sid, tid = school
    leave_id = _leave(client, sid, tid, start_date=WED.isoformat(),
                      end_date=WED.isoformat()).json()["id"]
    assert client.post(f"/api/leaves/{leave_id}/cancel").status_code == 200
    assert client.post(f"/api/leaves/{leave_id}/cancel").status_code == 409


# ── 快照:课表重新发布后,已展开的节次不漂移 ──────────────────
def test_affected_periods_are_a_snapshot_not_a_join(school):
    client, db, sid, tid = school
    leave_id = _leave(client, sid, tid, start_date=WED.isoformat(),
                      end_date=WED.isoformat()).json()["id"]

    before = client.get(f"/api/leaves/{leave_id}/affected").json()
    assert before[0]["subject_name"] == "国文"

    # 课表整份删掉(等同重新发布另一份):快照仍在,溯源指标变 NULL
    assert db.get(LeaveRequest, leave_id).affected_periods[0].schedule_entry_id is not None
    published = client.get(f"/api/published/timetable?semester_id={sid}").json()
    client.patch(f"/api/timetables/{published['id']}", json={"status": "archived"})
    client.delete(f"/api/timetables/{published['id']}")

    after = client.get(f"/api/leaves/{leave_id}/affected").json()
    assert len(after) == 5
    assert after[0]["subject_name"] == "国文"
    assert after[0]["class_names"] == "701"
    assert after[0]["period_name"] == "第一节"


# ── RBAC:教师自登、只看自己 ─────────────────────────────────
def test_teacher_registers_own_leave_and_cannot_see_others(school):
    client, db, sid, tid = school
    # 王师绑定帐号 wang;另建一位陈师与其假单
    user = _bind_account(client, db, tid, "wang")
    chen = client.post(f"/api/teachers?semester_id={sid}",
                       json={"name": "陈师", "base_periods": 20}).json()
    _leave(client, sid, chen["id"], start_date=WED.isoformat(), end_date=WED.isoformat())
    assert user.id

    client.post("/api/auth/login", json={"username": "wang", "password": PW})
    r = client.post(f"/api/leaves?semester_id={sid}", json={
        "leave_type": "personal", "start_date": FRI.isoformat(), "end_date": FRI.isoformat()})
    assert r.status_code == 201
    assert r.json()["teacher_id"] == tid
    assert r.json()["affected_count"] == 1  # 王师周五只有一节

    mine = client.get(f"/api/leaves?semester_id={sid}").json()
    assert {m["teacher_name"] for m in mine} == {"王师"}  # 看不到陈师的假单


def test_teacher_cannot_register_for_someone_else(school):
    client, db, sid, tid = school
    _bind_account(client, db, tid, "wang")
    chen = client.post(f"/api/teachers?semester_id={sid}",
                       json={"name": "陈师", "base_periods": 20}).json()

    client.post("/api/auth/login", json={"username": "wang", "password": PW})
    r = client.post(f"/api/leaves?semester_id={sid}", json={
        "teacher_id": chen["id"], "leave_type": "sick",
        "start_date": WED.isoformat(), "end_date": WED.isoformat()})
    assert r.status_code == 403


def test_registrar_on_behalf_notifies_the_teacher(school):
    """组长代登 → 当事人要知道有人替他请了假;自登则不必通知自己。"""
    client, db, sid, tid = school
    _leave(client, sid, tid, start_date=MON.isoformat(), end_date=MON.isoformat())

    notes = db.query(Notification).filter_by(teacher_id=tid).all()
    assert len(notes) == 1
    assert notes[0].type == NotificationType.leave_registered.value
    assert "已为您登记" in notes[0].title


def test_unbound_account_gets_a_helpful_error(school):
    client, db, sid, _tid = school
    make_user(db, "nobody", PW, roles=[Role.teacher])
    client.post("/api/auth/login", json={"username": "nobody", "password": PW})

    r = client.post(f"/api/leaves?semester_id={sid}", json={
        "leave_type": "sick", "start_date": WED.isoformat(), "end_date": WED.isoformat()})
    assert r.status_code == 400
    assert "尚未绑定" in r.json()["detail"]


def test_leave_without_published_timetable_registers_with_no_periods(env):
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    sid = client.post("/api/semesters", json={
        "academic_year": 2028, "term": 1, "template_key": "junior_high",
        "start_date": SEM_START.isoformat(), "end_date": SEM_END.isoformat()}).json()["id"]
    t = client.post(f"/api/teachers?semester_id={sid}",
                    json={"name": "王师", "base_periods": 20}).json()

    r = _leave(client, sid, t["id"], start_date=WED.isoformat(), end_date=WED.isoformat())
    assert r.status_code == 201
    assert r.json()["affected_count"] == 0
