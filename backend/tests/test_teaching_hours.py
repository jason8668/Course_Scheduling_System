"""教师实际上课课时统计。

口径:已发布课表按日期展开、叠加请假调代课、未来日期不计入「已上」。
测试直接写 DB(不走 API):代课指派 API 拒绝过去节次,而课时统计只计到今天,
两者日期方向相反,故异动资料直接建列。
"""

from datetime import date, timedelta

import pytest

from app.models.assignment import (
    AssignmentTeacher,
    CourseAssignment,
    SchedulingUnit,
    SchedulingUnitMember,
)
from app.models.basedata import ClassUnit, Subject, Teacher
from app.models.calendar import SchoolCalendarEvent
from app.models.leave import AffectedPeriod, LeaveRequest
from app.models.semester import Semester
from app.models.substitution import Substitution
from app.models.timetable import ScheduleEntry, Timetable
from app.services import teaching_hours as hours_service
from app.services.substitution_log import school_today
from tests.conftest import grant_grades, make_user
from app.models.user import Role

PW = "password123"


def _monday_ago(today: date, weeks: int) -> date:
    monday = today - timedelta(days=today.weekday())
    return monday - timedelta(weeks=weeks)


def build_world(db):
    """三周已过去的学期:王师(701 国文,周一第 1 节 + 单周周五第 1 节)、
    陈师(801 数学,周一第 1 节)、林师(701 数学,周三第 1~2 节连堂)。
    三周底数:王师 5、陈师 3、林师 6。"""
    today = school_today()
    sem_start = _monday_ago(today, 3)
    sem = Semester(academic_year=2026, term=1, start_date=sem_start,
                   end_date=sem_start + timedelta(weeks=11))
    db.add(sem)
    db.flush()

    def teacher(name):
        t = Teacher(semester_id=sem.id, name=name)
        db.add(t)
        db.flush()
        return t

    wang, chen, lin = teacher("王师"), teacher("陈师"), teacher("林师")

    def klass(grade, name):
        c = ClassUnit(semester_id=sem.id, grade=grade, name=name, track="junior_high")
        db.add(c)
        db.flush()
        return c

    c701, c801 = klass(7, "701"), klass(8, "801")

    def subject(name):
        s = Subject(semester_id=sem.id, name=name)
        db.add(s)
        db.flush()
        return s

    guowen, shuxue = subject("国文"), subject("数学")

    def unit(classes):
        u = SchedulingUnit(semester_id=sem.id, unit_type="single", name=classes[0].name)
        db.add(u)
        db.flush()
        for c in classes:
            db.add(SchedulingUnitMember(scheduling_unit_id=u.id, class_unit_id=c.id))
        db.flush()
        return u

    def assignment(u, subj, periods, teachers, parity=None):
        a = CourseAssignment(semester_id=sem.id, scheduling_unit_id=u.id,
                             subject_id=subj.id, periods_per_week=periods,
                             week_parity=parity)
        db.add(a)
        db.flush()
        for t in teachers:
            db.add(AssignmentTeacher(course_assignment_id=a.id, teacher_id=t.id))
        db.flush()
        return a

    u701, u801 = unit([c701]), unit([c801])
    a1 = assignment(u701, guowen, 5, [wang])
    a2 = assignment(u801, shuxue, 5, [chen])
    a3 = assignment(u701, shuxue, 5, [lin])
    a4 = assignment(u701, guowen, 1, [wang], parity="odd")

    tt = Timetable(semester_id=sem.id, name="已发布", status="published")
    db.add(tt)
    db.flush()

    def entry(a, weekday, period_no, span=1):
        db.add(ScheduleEntry(timetable_id=tt.id, course_assignment_id=a.id,
                             weekday=weekday, period_no=period_no, span=span))

    entry(a1, 1, 1)
    entry(a2, 1, 1)
    entry(a3, 3, 1, span=2)
    entry(a4, 5, 1)
    db.commit()
    return {
        "sem": sem, "start": sem_start, "teachers": {"王师": wang, "陈师": chen, "林师": lin},
    }


def _leave(db, w, teacher_name, on: date, period_no: int, sub_type: str | None,
           handler_name: str | None = None, swap_date: date | None = None,
           swap_period_no: int | None = None, subject="国文", class_names="701"):
    """一节请假 + 处置(sub_type 为 None = 待处理)。"""
    t = w["teachers"][teacher_name]
    lr = LeaveRequest(semester_id=w["sem"].id, teacher_id=t.id, leave_type="sick",
                      start_date=on, end_date=on, status="registered")
    db.add(lr)
    db.flush()
    ap = AffectedPeriod(leave_request_id=lr.id, semester_id=w["sem"].id, date=on,
                        weekday=on.isoweekday(), period_no=period_no,
                        period_name=f"第{period_no}节", subject_name=subject,
                        class_names=class_names, status="resolved")
    db.add(ap)
    db.flush()
    if sub_type is not None:
        handler = w["teachers"][handler_name] if handler_name else None
        db.add(Substitution(semester_id=w["sem"].id, affected_period_id=ap.id,
                            type=sub_type,
                            handler_teacher_id=handler.id if handler else None,
                            counts_toward_hours=True, funding_source="计入课时",
                            swap_date=swap_date, swap_period_no=swap_period_no))
    db.commit()


def _totals(db, w, start, end, **kw):
    rows, _s, _e = hours_service.compute(db, w["sem"], start, end, **kw)
    return {r.teacher_name: r.total for r in rows}


def _by_grade(db, w, start, end, name):
    rows, _s, _e = hours_service.compute(db, w["sem"], start, end)
    return next(r.by_grade for r in rows if r.teacher_name == name)


@pytest.fixture
def w(db):
    return build_world(db)


def test_weekly_expansion_counts(db, w):
    """三周底数:王师 5(周一×3 + 单周周五×2)、陈师 3、林师 6。"""
    totals = _totals(db, w, w["start"], w["start"] + timedelta(days=20))
    assert totals == {"王师": 5, "陈师": 3, "林师": 6}
    assert _by_grade(db, w, w["start"], w["start"] + timedelta(days=20), "王师") == {7: 5}
    assert _by_grade(db, w, w["start"], w["start"] + timedelta(days=20), "陈师") == {8: 3}


def test_block_counts_as_periods(db, w):
    """连堂按实际节数计:林师一周 2 节,单周范围就是 2 节。"""
    assert _totals(db, w, w["start"], w["start"] + timedelta(days=6))["林师"] == 2


def test_alternate_week_only_counts_parity_weeks(db, w):
    """单周课只在单周计:第 2 周(双周)王师只有周一 1 节。"""
    week2 = _totals(db, w, w["start"] + timedelta(days=7), w["start"] + timedelta(days=13))
    assert week2["王师"] == 1


def test_substitute_moves_hours(db, w):
    """代课:缺课教师扣、代课教师加(年级跟著被代的那班走)。
    代课教师须是该节空闲的老师(林师周一没课,才能代王师周一的课)。"""
    _leave(db, w, "王师", w["start"] + timedelta(days=7), 1, "substitute", "林师")
    totals = _totals(db, w, w["start"], w["start"] + timedelta(days=20))
    assert totals == {"王师": 4, "陈师": 3, "林师": 7}
    assert _by_grade(db, w, w["start"], w["start"] + timedelta(days=20), "林师") == {7: 7}


def test_self_study_removes_hours(db, w):
    """自习:缺课教师扣掉,无人加上。"""
    _leave(db, w, "林师", w["start"] + timedelta(days=9), 1, "self_study",
           subject="数学")
    totals = _totals(db, w, w["start"], w["start"] + timedelta(days=20))
    assert totals["林师"] == 5


def test_pending_removes_hours(db, w):
    """待处理:请假教师确定不在,先扣掉。"""
    _leave(db, w, "陈师", w["start"] + timedelta(days=7), 1, None,
           subject="数学", class_names="801")
    totals = _totals(db, w, w["start"], w["start"] + timedelta(days=20))
    assert totals["陈师"] == 2


def test_swap_moves_both_days(db, w):
    """调课:请假日缺课教师扣、代课教师加;补课日反过来。
    代课教师须是该节空闲的老师:陈师第 3 周周一请假由周一没课的林师代,
    补课在第 3 周周三第 1 节(林师自己的课那格,改由陈师上)。"""
    _leave(db, w, "陈师", w["start"] + timedelta(days=14), 1, "swap", "林师",
           swap_date=w["start"] + timedelta(days=16), swap_period_no=1,
           subject="数学", class_names="801")
    totals = _totals(db, w, w["start"], w["start"] + timedelta(days=20))
    assert totals == {"王师": 5, "陈师": 3, "林师": 6}
    assert _by_grade(db, w, w["start"], w["start"] + timedelta(days=20), "陈师") == {8: 2, 7: 1}
    assert _by_grade(db, w, w["start"], w["start"] + timedelta(days=20), "林师") == {7: 5, 8: 1}


def test_holiday_deduction(db, w):
    """校历放假扣减:全校放假扣当天全部;年级放假只扣该年级。"""
    mon2 = w["start"] + timedelta(days=7)
    wed2 = w["start"] + timedelta(days=9)
    db.add(SchoolCalendarEvent(semester_id=w["sem"].id, title="全校放假",
                               event_type="holiday", scope_type="school", scope_id=None,
                               start_date=mon2, end_date=mon2, weekly_recurring=False))
    db.add(SchoolCalendarEvent(semester_id=w["sem"].id, title="七年级放假",
                               event_type="holiday", scope_type="grade", scope_id=7,
                               start_date=wed2, end_date=wed2, weekly_recurring=False))
    db.commit()
    totals = _totals(db, w, w["start"], w["start"] + timedelta(days=20))
    assert totals == {"王师": 4, "陈师": 2, "林师": 4}


def test_future_dates_excluded(db, w):
    """范围拉到未来:实际讫日只到今天,总数与只查到今天相同。"""
    today = school_today()
    rows_future, _s, eff_future = hours_service.compute(
        db, w["sem"], w["start"], today + timedelta(days=60))
    rows_today, _s2, eff_today = hours_service.compute(db, w["sem"], w["start"], today)
    assert eff_future == today == eff_today
    assert {r.teacher_name: r.total for r in rows_future} == \
        {r.teacher_name: r.total for r in rows_today}


def test_grade_filter(db, w):
    """按年级筛选:8 年级只有陈师;7 年级只有王师与林师。"""
    assert _totals(db, w, w["start"], w["start"] + timedelta(days=20), grade=8) == {"陈师": 3}
    assert _totals(db, w, w["start"], w["start"] + timedelta(days=20), grade=7) == \
        {"王师": 5, "林师": 6}


def test_no_published_timetable_returns_empty(db):
    """没有已发布课表:回空列,不报错。"""
    today = school_today()
    sem = Semester(academic_year=2026, term=2, start_date=today - timedelta(days=7),
                   end_date=today + timedelta(days=60))
    db.add(sem)
    db.commit()
    rows, _s, _e = hours_service.compute(db, sem, sem.start_date, today)
    assert rows == []


def test_mine_api_only_self_and_admin_sees_all(env):
    """mine 接口只回本人;管理员接口教师打会 403、组长打回全校。"""
    client, db = env
    w = build_world(db)
    sem_id = w["sem"].id
    scheduler = make_user(db, "s", PW, roles=[Role.director])
    grant_grades(db, scheduler)
    teacher_user = make_user(db, "t", PW, roles=[Role.teacher])
    w["teachers"]["王师"].user_id = teacher_user.id
    db.commit()

    def login(username):
        r = client.post("/api/auth/login", json={"username": username, "password": PW})
        assert r.status_code == 200, r.json()

    start = w["start"].isoformat()
    end = (w["start"] + timedelta(days=20)).isoformat()
    login("t")
    r = client.get(f"/api/teaching-hours/mine?semester_id={sem_id}&scope=custom"
                   f"&date_from={start}&date_to={end}")
    assert r.status_code == 200, r.json()
    assert [(t["teacher_name"], t["total"]) for t in r.json()["teachers"]] == [("王师", 5)]
    r = client.get(f"/api/teaching-hours?semester_id={sem_id}&scope=custom"
                   f"&date_from={start}&date_to={end}")
    assert r.status_code == 403
    login("s")
    r = client.get(f"/api/teaching-hours?semester_id={sem_id}&scope=custom"
                   f"&date_from={start}&date_to={end}")
    assert r.status_code == 200, r.json()
    assert {t["teacher_name"]: t["total"] for t in r.json()["teachers"]} == \
        {"王师": 5, "陈师": 3, "林师": 6}
    assert scheduler.username == "s"
