"""公共假日同步 + 传统节日:接口解析、本地节气农历、幂等同步、提醒跳假日。"""

from datetime import date, datetime, time, timedelta

from app.models.calendar import SchoolCalendarEvent
from app.models.semester import Semester
from app.services.holidays import (
    _parse_jiejiariapi,
    _parse_timor,
    sync_semester,
    sync_year,
    traditional_festivals,
)


def _semester(db, start="2026-09-01", end="2027-01-31"):
    sem = Semester(
        academic_year=2026,
        term=1,
        start_date=date.fromisoformat(start),
        end_date=date.fromisoformat(end),
    )
    db.add(sem)
    db.commit()
    return sem


def _fake_ok(year):
    return "ok", {date(year, 1, 1): "元旦", date(year, 5, 1): "劳动节"}


def test_parse_timor_and_jiejiariapi():
    timor = _parse_timor(
        {
            "code": 0,
            "holiday": {
                "2026-01-01": {"holiday": True, "name": "元旦"},
                "2026-01-04": {"holiday": False, "name": "元旦"},
            },
        }
    )
    assert timor == {date(2026, 1, 1): "元旦"}
    assert _parse_timor({"code": -1, "holiday": {}}) is None
    jie = _parse_jiejiariapi(
        {
            "2026-01-01": {"name": "元旦", "isOffDay": True},
            "2026-01-04": {"name": "元旦", "isOffDay": False},
        }
    )
    assert jie == {date(2026, 1, 1): "元旦"}


def test_traditional_festivals_2026():
    got = dict(traditional_festivals(2026))
    assert got[date(2026, 2, 17)] == "春节"
    assert got[date(2026, 3, 3)] == "元宵"
    assert got[date(2026, 6, 19)] == "端午"
    assert got[date(2026, 8, 19)] == "七夕"
    assert got[date(2026, 9, 25)] == "中秋"
    assert got[date(2026, 10, 18)] == "重阳"
    assert got[date(2026, 1, 26)] == "腊八"
    assert got[date(2026, 2, 11)] == "小年"
    assert got[date(2026, 4, 5)] == "清明"
    assert got[date(2026, 12, 22)] == "冬至"


def test_sync_year_idempotent_and_manual_preserved(db):
    sem = _semester(db)
    # 手动事件 + 旧的自动事件(同年),同步后手动保留、旧自动被替换
    db.add(
        SchoolCalendarEvent(
            semester_id=sem.id,
            title="运动会",
            event_type="activity",
            scope_type="school",
            start_date=date(2026, 10, 30),
            end_date=date(2026, 10, 30),
            note=None,
        )
    )
    db.add(
        SchoolCalendarEvent(
            semester_id=sem.id,
            title="旧假日",
            event_type="holiday",
            scope_type="school",
            start_date=date(2026, 3, 3),
            end_date=date(2026, 3, 3),
            note="系统自动同步：公共假日",
        )
    )
    db.commit()
    result = sync_year(db, sem, 2026, fetcher=_fake_ok)
    assert result["status"] == "ok" and result["public_holidays"] == 2
    rows = db.query(SchoolCalendarEvent).filter_by(semester_id=sem.id).all()
    titles = [r.title for r in rows]
    assert "运动会" in titles and "旧假日" not in titles
    assert "元旦" in titles and "劳动节" in titles
    # 春节当天已是公共假日?本 fake 里没有,故传统节日春节应出现;再跑一次不翻倍
    count_before = len(rows)
    sync_year(db, sem, 2026, fetcher=_fake_ok)
    rows2 = db.query(SchoolCalendarEvent).filter_by(semester_id=sem.id).all()
    assert len(rows2) == count_before


def test_sync_year_festival_skips_public_holiday_day(db):
    sem = _semester(db)

    def fake(year):
        return "ok", {date(year, 2, 17): "春节"}

    sync_year(db, sem, 2026, fetcher=fake)
    rows = db.query(SchoolCalendarEvent).filter_by(semester_id=sem.id).all()
    # 2026-02-17 只有放假事件,没有重复的传统节日春节事件
    feb17 = [r for r in rows if r.start_date == date(2026, 2, 17)]
    assert len(feb17) == 1 and feb17[0].event_type == "holiday"
    # 非假日的传统节日照常出现
    assert any(r.title == "元宵" and r.event_type == "other" for r in rows)


def test_sync_year_unpublished_keeps_public_adds_festivals(db):
    sem = _semester(db)
    db.add(
        SchoolCalendarEvent(
            semester_id=sem.id,
            title="已公布的假日",
            event_type="holiday",
            scope_type="school",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 1),
            note="系统自动同步：公共假日",
        )
    )
    db.commit()

    def fake_unpublished(year):
        return "unpublished", {}

    result = sync_year(db, sem, 2026, fetcher=fake_unpublished)
    assert result["status"] == "unpublished" and result["public_holidays"] is None
    rows = db.query(SchoolCalendarEvent).filter_by(semester_id=sem.id).all()
    assert any(r.title == "已公布的假日" for r in rows)
    assert any(r.title == "春节" for r in rows)


def test_sync_semester_no_dates_is_noop(db):
    sem = Semester(academic_year=2026, term=1, start_date=None, end_date=None)
    db.add(sem)
    db.commit()
    assert sync_semester(db, sem, fetcher=_fake_ok) == []


def test_reminder_skips_holiday(db):
    """放假那天第 1 节不推提醒:复用 test_class_reminders 的种子结构。"""
    from app.models.assignment import (
        AssignmentTeacher,
        CourseAssignment,
        SchedulingUnit,
        SchedulingUnitMember,
    )
    from app.models.basedata import ClassUnit, Subject, Teacher
    from app.models.period import Period, PeriodTable
    from app.models.timetable import ScheduleEntry, Timetable, TimetableStatus
    from app.services import settings as app_settings
    from app.services.class_reminders import run_class_reminders
    from tests.dates import MON
    from tests.test_class_reminders import FakeClient

    sem = Semester(
        academic_year=2026,
        term=1,
        start_date=MON - timedelta(days=30),
        end_date=MON + timedelta(days=60),
    )
    db.add(sem)
    db.flush()
    table = PeriodTable(semester_id=sem.id, name="默认", is_default=True)
    db.add(table)
    db.flush()
    db.add(
        Period(
            period_table_id=table.id,
            weekday=MON.isoweekday(),
            period_no=1,
            name="第1节",
            start_time=time(8, 0),
            end_time=time(8, 45),
            type="regular",
        )
    )
    cls = ClassUnit(semester_id=sem.id, grade=7, name="七年级1班", track="初中")
    teacher = Teacher(semester_id=sem.id, name="王小明", phone="13800000000")
    subj = Subject(semester_id=sem.id, name="数学")
    db.add_all([cls, teacher, subj])
    db.flush()
    su = SchedulingUnit(semester_id=sem.id, unit_type="single", name="七年级1班")
    db.add(su)
    db.flush()
    db.add(SchedulingUnitMember(scheduling_unit_id=su.id, class_unit_id=cls.id))
    a = CourseAssignment(
        semester_id=sem.id, scheduling_unit_id=su.id, subject_id=subj.id, periods_per_week=5
    )
    db.add(a)
    db.flush()
    db.add(AssignmentTeacher(course_assignment_id=a.id, teacher_id=teacher.id))
    tt = Timetable(semester_id=sem.id, name="t1", status=TimetableStatus.published.value)
    db.add(tt)
    db.flush()
    db.add(
        ScheduleEntry(
            timetable_id=tt.id,
            course_assignment_id=a.id,
            weekday=MON.isoweekday(),
            period_no=1,
        )
    )
    # MON 当天全校放假
    db.add(
        SchoolCalendarEvent(
            semester_id=sem.id,
            title="放假",
            event_type="holiday",
            scope_type="school",
            start_date=MON,
            end_date=MON,
        )
    )
    app_settings.save_dingtalk_app(db, "key", "sec", "123456", 15)
    db.commit()
    client = FakeClient({"13800000000": "zhangsan"})
    result = run_class_reminders(db, now=datetime.combine(MON, time(7, 50)), client=client)
    assert result["sent"] == 0 and client.sent == []


def test_manual_sync_endpoint(env, monkeypatch):
    """手动同步端点:立即同步已建学期,没公布年份也不 5xx(本例 fake 全 ok)。"""
    from app.models.user import Role
    from app.services import holidays as holidays_mod
    from tests.conftest import grant_grades, make_user

    client, db = env
    user = make_user(db, "s", "password123", roles=[Role.director])
    grant_grades(db, user)
    resp = client.post("/api/auth/login", json={"username": "s", "password": "password123"})
    assert resp.status_code == 200
    resp = client.post(
        "/api/semesters",
        json={
            "academic_year": 2026,
            "term": 1,
            "start_date": "2026-09-01",
            "end_date": "2027-01-31",
        },
    )
    assert resp.status_code == 201, resp.text
    sid = resp.json()["id"]
    monkeypatch.setattr(holidays_mod, "fetch_public_holidays", _fake_ok)
    resp = client.post(f"/api/semesters/{sid}/sync-holidays")
    assert resp.status_code == 200, resp.text
    results = resp.json()["results"]
    assert {r["year"] for r in results} == {2026, 2027}
    assert all(r["status"] == "ok" for r in results)
    lst = client.get(f"/api/calendar-events?semester_id={sid}").json()
    assert any(e["title"] == "元宵" and e["event_type"] == "other" for e in lst)
    assert any(e["title"] == "元旦" and e["event_type"] == "holiday" for e in lst)
