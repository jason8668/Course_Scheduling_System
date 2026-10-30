"""老师自主调课:对方同意即生效、事后补登、课时与提醒按换后算。"""

from datetime import time, timedelta

from app.models.assignment import CourseAssignment, SchedulingUnit, SchedulingUnitMember
from app.models.basedata import ClassUnit, Subject, Teacher
from app.models.period import Period, PeriodTable
from app.models.semester import Semester
from app.models.teacher_swap import TeacherSwap
from app.models.timetable import ScheduleEntry, Timetable, TimetableStatus
from app.models.user import Role
from app.services import teaching_hours
from app.services.class_reminders import run_class_reminders
from tests.conftest import make_user
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
    cls = ClassUnit(semester_id=sem.id, name="七1班", grade=7, track="初中")
    db.add(cls)
    db.flush()
    a = Teacher(semester_id=sem.id, name="张老师", phone="13800000000")
    b = Teacher(semester_id=sem.id, name="李老师", phone="13900000000")
    db.add_all([a, b])
    db.flush()
    subj = Subject(semester_id=sem.id, name="数学")
    db.add(subj)
    db.flush()
    unit = SchedulingUnit(semester_id=sem.id, name="七1班")
    db.add(unit)
    db.flush()
    db.add(SchedulingUnitMember(scheduling_unit_id=unit.id, class_unit_id=cls.id))
    db.flush()
    assign = CourseAssignment(
        semester_id=sem.id, scheduling_unit_id=unit.id, subject_id=subj.id,
        periods_per_week=1,
    )
    db.add(assign)
    db.flush()
    from app.models.assignment import AssignmentTeacher
    db.add(AssignmentTeacher(course_assignment_id=assign.id, teacher_id=a.id))
    tt = Timetable(semester_id=sem.id, name="t1", status=TimetableStatus.published.value)
    db.add(tt)
    db.flush()
    db.add(ScheduleEntry(
        timetable_id=tt.id, course_assignment_id=assign.id,
        weekday=MON.isoweekday(), period_no=1, span=1,
    ))
    db.commit()
    return {"sem": sem, "cls": cls, "a": a, "b": b, "assign": assign}


def _swap(db, ctx, status="approved", date=None):
    row = TeacherSwap(
        semester_id=ctx["sem"].id, requester_id=ctx["a"].id, status=status,
        class_date=date or MON, period_no=1,
        class_unit_id=ctx["cls"].id, course_assignment_id=ctx["assign"].id,
        original_teacher_id=ctx["a"].id, handler_teacher_id=ctx["b"].id,
    )
    db.add(row)
    db.commit()
    return row


def test_hours_swap_and_retroactive(db):
    # 课时统计只计到今天为止,故用过去的周一(与 special_days 的 PAST_MON 同款)
    past_mon = MON - timedelta(days=28)
    ctx = _setup(db)
    # 未同意的记录不算:张老师仍计 1 节
    _swap(db, ctx, status="pending", date=past_mon)
    hours, _, _ = teaching_hours.compute(db, ctx["sem"], past_mon, past_mon)
    by_name = {h.teacher_name: h for h in hours}
    assert by_name["张老师"].total == 1
    assert "李老师" not in by_name
    # 同意后:张老师扣掉,李老师计代课 1 节
    db.query(TeacherSwap).update({"status": "approved"})
    db.commit()
    hours, _, _ = teaching_hours.compute(db, ctx["sem"], past_mon, past_mon)
    by_name = {h.teacher_name: h for h in hours}
    assert by_name["李老师"].total == 1 and by_name["李老师"].substitute_total == 1
    assert "张老师" not in by_name
    # 事后补登:再往后一周(仍在过去、学期内)的记录同样生效
    past = past_mon + timedelta(days=7)
    _swap(db, ctx, status="approved", date=past)
    hours, _, _ = teaching_hours.compute(db, ctx["sem"], past_mon, past)
    by_name = {h.teacher_name: h for h in hours}
    assert by_name["李老师"].total == 2


def test_reminder_goes_to_handler(db):
    ctx = _setup(db)
    from app.services import settings as app_settings
    app_settings.save_dingtalk_app(db, "key", "sec", "123456", 15)
    db.commit()
    _swap(db, ctx, status="approved")
    client = FakeClient({"13800000000": "zhang", "13900000000": "li"})
    # 08:00 的课,提前 15 分钟:07:50 跑,应只推给李老师(换课),不推张老师
    from datetime import datetime
    result = run_class_reminders(
        db, now=datetime.combine(MON, time(7, 50)), client=client)
    assert result["sent"] == 1, result
    assert [s[0] for s in client.sent] == ["li"]


def test_api_approve_only_counterpart(env):
    client, db = env
    ctx = _setup(db)
    user_a = make_user(db, "zhang", PW, roles=[Role.director])
    ctx["a"].user_id = user_a.id
    user_b = make_user(db, "li", PW, roles=[Role.director])
    ctx["b"].user_id = user_b.id
    db.commit()
    sem_id = ctx["sem"].id
    # 张老师发起:把自己的课换给李老师
    client.post("/api/auth/login", json={"username": "zhang", "password": PW})
    resp = client.post(f"/api/teacher-swaps?semester_id={sem_id}", json={
        "class_date": str(MON), "period_no": 1,
        "class_unit_id": ctx["cls"].id, "course_assignment_id": ctx["assign"].id,
        "original_teacher_id": ctx["a"].id, "handler_teacher_id": ctx["b"].id,
    })
    assert resp.status_code == 201, resp.text
    swap_id = resp.json()["id"]
    # 发起人自己不能同意
    resp = client.post(f"/api/teacher-swaps/{swap_id}/approve")
    assert resp.status_code == 403
    # 对方同意即生效
    client.post("/api/auth/login", json={"username": "li", "password": PW})
    resp = client.post(f"/api/teacher-swaps/{swap_id}/approve")
    assert resp.status_code == 200 and resp.json()["status"] == "approved"
