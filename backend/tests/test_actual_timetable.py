"""实际课表:主课表 -> 特殊日 -> 请假代课 -> 老师调课,放假与调休标记。"""

from datetime import date, timedelta

from app.models.calendar import SchoolCalendarEvent
from app.models.leave import AffectedPeriod, LeaveRequest
from app.models.special_day import SpecialDayEntry, SpecialDayRule
from app.models.teacher_swap import TeacherSwap
from app.services import actual_timetable as actual
from app.services.holidays import WORKDAY_NOTE, sync_year
from tests.dates import MON
from tests.test_special_days import _base


def _slots_by_class(day):
    return {(s.class_unit_id, s.period_no): s for s in day.slots}


def test_base_and_special_override(db):
    ctx = _base(db)
    sem, cls1, cls2 = ctx["sem"], ctx["cls1"], ctx["cls2"]
    days = actual.compute(db, sem, MON, MON)
    assert len(days) == 1 and days[0].published is True
    slots = _slots_by_class(days[0])
    assert slots[(cls1.id, 1)].origin == "base"
    assert slots[(cls1.id, 1)].subject == "数学"
    # 特殊日:1 班第 1 节换成李小红的语文
    rule = SpecialDayRule(
        semester_id=sem.id, title="调休复制", scope_type="school", scope_id=None,
        recurrence="single", single_date=MON, start_date=sem.start_date,
        end_date=sem.end_date, is_active=True,
    )
    db.add(rule)
    db.commit()
    db.add(SpecialDayEntry(
        rule_id=rule.id, class_unit_id=cls1.id, period_no=1,
        course_assignment_id=ctx["a3"].id,
    ))
    db.commit()
    days = actual.compute(db, sem, MON, MON)
    slots = _slots_by_class(days[0])
    assert slots[(cls1.id, 1)].origin == "special"
    assert slots[(cls1.id, 1)].subject == "语文"
    assert slots[(cls1.id, 1)].teacher_names == ["李小红"]
    assert slots[(cls2.id, 1)].origin == "base"


def test_holiday_and_workday_pending(db):
    ctx = _base(db)
    sem, cls1 = ctx["sem"], ctx["cls1"]
    db.add(SchoolCalendarEvent(
        semester_id=sem.id, title="国庆节", event_type="holiday",
        scope_type="school", start_date=MON, end_date=MON,
    ))
    db.commit()
    days = actual.compute(db, sem, MON, MON)
    slots = _slots_by_class(days[0])
    assert slots[(cls1.id, 1)].origin == "holiday"
    assert days[0].holiday_titles == ["国庆节"]
    # 调休日(周六)未复制:workday_pending 真,且当天周六本来没课
    sat = MON + timedelta(days=5)
    db.add(SchoolCalendarEvent(
        semester_id=sem.id, title="国庆节调休上班", event_type="other",
        scope_type="school", start_date=sat, end_date=sat, note=WORKDAY_NOTE,
    ))
    db.commit()
    days = actual.compute(db, sem, sat, sat)
    assert days[0].workday_title == "国庆节调休上班"
    assert days[0].workday_pending is True
    # 复制后(单次特殊日规则)不再 pending,且周六有了课
    rule = SpecialDayRule(
        semester_id=sem.id, title="调休复制", scope_type="school", scope_id=None,
        recurrence="single", single_date=sat, start_date=sem.start_date,
        end_date=sem.end_date, is_active=True,
    )
    db.add(rule)
    db.commit()
    db.add(SpecialDayEntry(
        rule_id=rule.id, class_unit_id=cls1.id, period_no=1,
        course_assignment_id=ctx["a1"].id,
    ))
    db.commit()
    days = actual.compute(db, sem, sat, sat)
    assert days[0].workday_pending is False
    slots = _slots_by_class(days[0])
    assert slots[(cls1.id, 1)].origin == "special"
    assert slots[(cls1.id, 1)].subject == "数学"


def test_leave_substitute_then_teacher_swap_wins(db):
    ctx = _base(db)
    sem, cls1, t1, t2 = ctx["sem"], ctx["cls1"], ctx["t1"], ctx["t2"]
    # 请假:王小明 MON 第 1 节,李小红代课(用 AffectedPeriod + Substitution 快照)
    leave = LeaveRequest(
        semester_id=sem.id, teacher_id=t1.id, leave_type="事假",
        start_date=MON, end_date=MON, status="registered",
    )
    db.add(leave)
    db.flush()
    ap = AffectedPeriod(
        semester_id=sem.id, leave_request_id=leave.id, date=MON, weekday=MON.isoweekday(),
        period_no=1, period_name="第1节", subject_name="数学",
        class_names=cls1.name, schedule_entry_id=None,
        course_assignment_id=ctx["a1"].id, status="resolved",
        handler_teacher_id=t2.id,
    )
    db.add(ap)
    db.flush()
    from app.models.substitution import Substitution

    db.add(Substitution(
        semester_id=sem.id, affected_period_id=ap.id, type="substitute",
        handler_teacher_id=t2.id,
    ))
    db.commit()
    days = actual.compute(db, sem, MON, MON)
    slots = _slots_by_class(days[0])
    assert slots[(cls1.id, 1)].origin == "substitute"
    assert slots[(cls1.id, 1)].teacher_names == ["李小红"]
    # 老师调课同节:王小明把课调给李小红已生效,调课优先,仍是李小红但来源变调课
    db.add(TeacherSwap(
        semester_id=sem.id, requester_id=t1.id, class_date=MON, period_no=1,
        class_unit_id=cls1.id, course_assignment_id=ctx["a1"].id,
        original_teacher_id=t1.id, handler_teacher_id=t2.id, status="approved",
    ))
    db.commit()
    days = actual.compute(db, sem, MON, MON)
    slots = _slots_by_class(days[0])
    assert slots[(cls1.id, 1)].origin == "teacher_swap"
    assert slots[(cls1.id, 1)].teacher_names == ["李小红"]


def test_sync_year_adds_workdays(db):
    ctx = _base(db)
    sem = ctx["sem"]

    def fake_holidays(year):
        return "ok", {date(2026, 10, 1): "国庆节"}

    def fake_workdays(year):
        return "ok", {date(2026, 10, 10): "国庆节"}

    result = sync_year(
        db, sem, 2026, fetcher=fake_holidays, workday_fetcher=fake_workdays,
    )
    assert result["public_workdays"] == 1
    rows = db.query(SchoolCalendarEvent).filter_by(note=WORKDAY_NOTE).all()
    assert len(rows) == 1 and rows[0].title == "国庆节调休上班"
    assert rows[0].start_date == date(2026, 10, 10)
    # 再跑一次不重复
    sync_year(db, sem, 2026, fetcher=fake_holidays, workday_fetcher=fake_workdays)
    assert db.query(SchoolCalendarEvent).filter_by(note=WORKDAY_NOTE).count() == 1


def test_actual_api(env):
    from tests.test_special_days import _login

    client, db = env
    ctx = _base(db)
    sem = ctx["sem"]
    _login(client, db)
    resp = client.get(
        f"/api/published/actual?semester_id={sem.id}&from_date={MON}&to_date={MON}",
    )
    assert resp.status_code == 200, resp.text
    day = resp.json()[0]
    assert day["published"] is True
    assert day["slots"][0]["origin"] == "base"
    resp = client.get(
        f"/api/calendar-events/workdays?semester_id={sem.id}",
    )
    assert resp.status_code == 200
