"""行政值日:轮值+覆盖、行政岗限定、换班同意后替换、提醒两次、API 权限。"""

from datetime import time, timedelta

from app.models.basedata import Teacher
from app.models.duty import DutyOverride, DutyPattern
from app.models.period import Period, PeriodTable
from app.models.semester import Semester
from app.models.timetable import Timetable, TimetableStatus
from app.models.user import Role
from app.services import duty as duty_service
from app.services import settings as app_settings
from app.services.duty_reminders import run_duty_reminders
from tests.conftest import grant_grades, make_user
from tests.dates import MON
from tests.test_class_reminders import FakeClient

PW = "password123"


def _setup(db):
    sem = Semester(
        academic_year=2026, term=1,
        start_date=MON - timedelta(days=30), end_date=MON + timedelta(days=60),
    )
    db.add(sem)
    db.flush()
    table = PeriodTable(semester_id=sem.id, name="默认", is_default=True)
    db.add(table)
    db.flush()
    db.add(Period(
        period_table_id=table.id, weekday=MON.isoweekday(), period_no=1,
        name="第1节", start_time=time(8, 0), end_time=time(8, 45), type="regular",
    ))
    # 行政岗两位 + 非行政一位
    a = Teacher(semester_id=sem.id, name="张主任", phone="13800000000", admin_title="教务主任")
    b = Teacher(semester_id=sem.id, name="李副主任", phone="13900000000", admin_title="副主任")
    c = Teacher(semester_id=sem.id, name="王老师", phone="13700000000", admin_title=None)
    db.add_all([a, b, c])
    db.flush()
    tt = Timetable(semester_id=sem.id, name="t1", status=TimetableStatus.published.value)
    db.add(tt)
    db.commit()
    return {"sem": sem, "a": a, "b": b, "c": c}


def test_eligible_only_admin_post_and_override_beats_pattern(db):
    ctx = _setup(db)
    sem = ctx["sem"]
    eligible = duty_service.eligible_teachers(db, sem.id)
    assert {t.name for t in eligible} == {"张主任", "李副主任"}
    db.add(DutyPattern(semester_id=sem.id, weekday=MON.isoweekday(), teacher_id=ctx["a"].id))
    db.commit()
    assert duty_service.duty_teacher_id(db, sem.id, MON) == ctx["a"].id
    # 临时覆盖只影响当天,下周恢复
    db.add(DutyOverride(semester_id=sem.id, date=MON, teacher_id=ctx["b"].id, reason="替班"))
    db.commit()
    assert duty_service.duty_teacher_id(db, sem.id, MON) == ctx["b"].id
    assert duty_service.duty_teacher_id(db, sem.id, MON + timedelta(days=7)) == ctx["a"].id


def test_duty_reminders_day_before_and_morning(db):
    ctx = _setup(db)
    sem = ctx["sem"]
    db.add(DutyPattern(semester_id=sem.id, weekday=MON.isoweekday(), teacher_id=ctx["a"].id))
    app_settings.save_dingtalk_app(db, "key", "sec", "123456", 15)
    db.commit()
    from datetime import datetime

    client = FakeClient({"13800000000": "zhang"})
    # 前一天 17:00 之前不发,17:05 发 day_before 一次
    r0 = run_duty_reminders(
        db, now=datetime.combine(MON - timedelta(days=1), time(16, 55)), client=client
    )
    assert r0["sent"] == 0
    r1 = run_duty_reminders(
        db, now=datetime.combine(MON - timedelta(days=1), time(17, 5)), client=client
    )
    assert r1["sent"] == 1
    # 同一晚上再跑:防重复,不再发
    r2 = run_duty_reminders(
        db, now=datetime.combine(MON - timedelta(days=1), time(17, 10)), client=client
    )
    assert r2["sent"] == 0
    # 当天早上:第一节 08:00 前 60 分钟不发,前 30 分钟窗口内发 morning 一次
    r25 = run_duty_reminders(
        db, now=datetime.combine(MON, time(7, 0)), client=client
    )
    assert r25["sent"] == 0
    r3 = run_duty_reminders(
        db, now=datetime.combine(MON, time(7, 30)), client=client
    )
    assert r3["sent"] == 1
    assert len(client.sent) == 2
    assert all(s[0] == "zhang" for s in client.sent)


def _login(client, db, roles, username):
    user = make_user(db, username, PW, roles=list(roles))
    if Role.director in roles:
        grant_grades(db, user)
    resp = client.post("/api/auth/login", json={"username": username, "password": PW})
    assert resp.status_code == 200
    return user


def test_api_admin_only_and_swap_flow(env):
    client, db = env
    ctx = _setup(db)
    sem = ctx["sem"]
    # 管理员建轮值:非行政岗 400,行政岗 ok
    _login(client, db, (Role.admin,), "admin1")
    resp = client.put(f"/api/duty-roster/pattern?semester_id={sem.id}", json={
        "weekday": MON.isoweekday(), "teacher_id": ctx["c"].id,
    })
    assert resp.status_code == 400
    resp = client.put(f"/api/duty-roster/pattern?semester_id={sem.id}", json={
        "weekday": MON.isoweekday(), "teacher_id": ctx["a"].id,
    })
    assert resp.status_code == 200
    # 值日老师本人发起换班:把 MON 的值日换给李副主任
    # 绑定教师档案:张主任的 user_id 指向发起人账号
    from tests.conftest import make_user as _make

    user_a = _make(db, "zhang", PW, roles=[Role.director])
    ctx["a"].user_id = user_a.id
    user_b = _make(db, "li", PW, roles=[Role.director])
    ctx["b"].user_id = user_b.id
    db.commit()
    client.post("/api/auth/login", json={"username": "zhang", "password": PW})
    resp = client.post(f"/api/duty-roster/swap-requests?semester_id={sem.id}", json={
        "date": str(MON), "to_teacher_id": ctx["b"].id,
    })
    assert resp.status_code == 201, resp.text
    req_id = resp.json()["id"]
    # 发起人自己不能同意
    resp = client.post(f"/api/duty-roster/swap-requests/{req_id}/approve")
    assert resp.status_code == 403
    # 对方同意后,当天值日换成李副主任,下周仍是张主任
    client.post("/api/auth/login", json={"username": "li", "password": PW})
    resp = client.post(f"/api/duty-roster/swap-requests/{req_id}/approve")
    assert resp.status_code == 200 and resp.json()["status"] == "approved"
    assert duty_service.duty_teacher_id(db, sem.id, MON) == ctx["b"].id
    assert duty_service.duty_teacher_id(db, sem.id, MON + timedelta(days=7)) == ctx["a"].id
