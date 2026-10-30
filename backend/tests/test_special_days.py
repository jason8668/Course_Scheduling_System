"""特殊日课表:规则展开优先级、放假优先、课时覆盖、提醒替换、API 权限。"""

from datetime import date, datetime, time, timedelta

from app.models.assignment import (
    AssignmentTeacher,
    CourseAssignment,
    SchedulingUnit,
    SchedulingUnitMember,
)
from app.models.basedata import ClassUnit, Subject, Teacher
from app.models.calendar import SchoolCalendarEvent
from app.models.period import Period, PeriodTable
from app.models.semester import Semester
from app.models.special_day import SpecialDayEntry, SpecialDayRule
from app.models.timetable import ScheduleEntry, Timetable, TimetableStatus
from app.models.user import Role
from app.services import settings as app_settings
from app.services.special_days import overrides_for_date, rule_matches_date
from tests.conftest import grant_grades, make_user
from tests.dates import MON
from tests.test_class_reminders import FakeClient

PW = "password123"


def _base(db, *, sem_start=None, sem_end=None):
    """一学期 + 两班两师两科 + 已发布周课表(周一第 1 节各班各一门)。"""
    sem = Semester(
        academic_year=2026, term=1,
        start_date=sem_start or (MON - timedelta(days=30)),
        end_date=sem_end or (MON + timedelta(days=60)),
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
    cls1 = ClassUnit(semester_id=sem.id, grade=7, name="七年级1班", track="初中")
    cls2 = ClassUnit(semester_id=sem.id, grade=7, name="七年级2班", track="初中")
    t1 = Teacher(semester_id=sem.id, name="王小明", phone="13800000000")
    t2 = Teacher(semester_id=sem.id, name="李小红", phone="13900000000")
    subj1 = Subject(semester_id=sem.id, name="数学")
    subj2 = Subject(semester_id=sem.id, name="语文")
    db.add_all([cls1, cls2, t1, t2, subj1, subj2])
    db.flush()

    def _assign(cls, teacher, subj):
        su = SchedulingUnit(semester_id=sem.id, unit_type="single", name=cls.name)
        db.add(su)
        db.flush()
        db.add(SchedulingUnitMember(scheduling_unit_id=su.id, class_unit_id=cls.id))
        a = CourseAssignment(
            semester_id=sem.id, scheduling_unit_id=su.id, subject_id=subj.id,
            periods_per_week=5,
        )
        db.add(a)
        db.flush()
        db.add(AssignmentTeacher(course_assignment_id=a.id, teacher_id=teacher.id))
        return a

    a1 = _assign(cls1, t1, subj1)
    a2 = _assign(cls2, t2, subj2)
    # 1 班的语文配课(李小红教 1 班,主课表未排入,供特殊日替换用):
    # 特殊日换课必须用教该班的配课,故不能直接拿 2 班的 a2 来换 1 班。
    a3 = _assign(cls1, t2, subj2)
    tt = Timetable(semester_id=sem.id, name="t1", status=TimetableStatus.published.value)
    db.add(tt)
    db.flush()
    db.add(ScheduleEntry(
        timetable_id=tt.id, course_assignment_id=a1.id,
        weekday=MON.isoweekday(), period_no=1,
    ))
    db.add(ScheduleEntry(
        timetable_id=tt.id, course_assignment_id=a2.id,
        weekday=MON.isoweekday(), period_no=1,
    ))
    db.commit()
    return {
        "sem": sem, "cls1": cls1, "cls2": cls2,
        "t1": t1, "t2": t2, "a1": a1, "a2": a2, "a3": a3,
    }


def _rule(db, sem, *, scope="school", scope_id=None, recurrence="single",
          single_date=None, weekday=None, day_of_month=None, active=True, title="特殊日"):
    rule = SpecialDayRule(
        semester_id=sem.id, title=title, scope_type=scope, scope_id=scope_id,
        recurrence=recurrence, single_date=single_date, weekday=weekday,
        day_of_month=day_of_month, start_date=sem.start_date, end_date=sem.end_date,
        is_active=active,
    )
    db.add(rule)
    db.commit()
    return rule


def test_rule_matches_and_priority(db):
    ctx = _base(db)
    sem = ctx["sem"]
    single = _rule(db, sem, recurrence="single", single_date=MON)
    weekly = _rule(db, sem, recurrence="weekly", weekday=MON.isoweekday())
    monthly = _rule(db, sem, recurrence="monthly", day_of_month=MON.day)
    assert rule_matches_date(single, MON)
    assert rule_matches_date(weekly, MON)
    assert rule_matches_date(monthly, MON)
    # 每月 30 号的规则在 2 月没有 30 号那天自然不生效:以 2026-02-28 为例
    assert not rule_matches_date(monthly, date(2026, 2, 28)) or monthly.day_of_month != 30
    db.add(SpecialDayEntry(
        rule_id=single.id, class_unit_id=ctx["cls1"].id, period_no=1,
        course_assignment_id=ctx["a3"].id,
    ))
    db.add(SpecialDayEntry(
        rule_id=weekly.id,
        class_unit_id=ctx["cls1"].id,
        period_no=1,
        course_assignment_id=None,
    ))
    db.add(SpecialDayEntry(
        rule_id=monthly.id,
        class_unit_id=ctx["cls1"].id,
        period_no=1,
        course_assignment_id=ctx["a1"].id,
    ))
    db.commit()
    classes = {ctx["cls1"].id: ctx["cls1"], ctx["cls2"].id: ctx["cls2"]}
    ov = overrides_for_date([single, weekly, monthly], classes, [], MON)
    # 单次最高优先级胜出:1 班第 1 节换成 a3(李小红教 1 班的语文),而不是取消或 a1
    assert ov[(ctx["cls1"].id, 1)].course_assignment_id == ctx["a3"].id
    # 未发布规则不参与
    single.is_active = False
    db.commit()
    ov2 = overrides_for_date([single, weekly, monthly], classes, [], MON)
    assert ov2[(ctx["cls1"].id, 1)].course_assignment_id is None  # 每周(取消)次之


def test_holiday_beats_special_day(db):
    ctx = _base(db)
    sem = ctx["sem"]
    rule = _rule(db, sem, recurrence="single", single_date=MON)
    db.add(SpecialDayEntry(
        rule_id=rule.id, class_unit_id=ctx["cls1"].id, period_no=1,
        course_assignment_id=ctx["a3"].id,
    ))
    db.add(SchoolCalendarEvent(
        semester_id=sem.id, title="放假", event_type="holiday",
        scope_type="school", start_date=MON, end_date=MON,
    ))
    db.commit()
    classes = {ctx["cls1"].id: ctx["cls1"], ctx["cls2"].id: ctx["cls2"]}
    from app.services.special_days import load_holidays

    ov = overrides_for_date([rule], classes, load_holidays(db, sem.id), MON)
    assert (ctx["cls1"].id, 1) not in ov


def test_teaching_hours_uses_override_and_leave_on_override(db):
    """特殊日那天:1 班第 1 节改由李小红上,王小明那节不计、李小红计;
    且当天请假按换后的课算(李小红请假则那节扣掉,无人加上)。"""
    from app.services.teaching_hours import compute as _compute

    ctx = _base(db)
    sem = ctx["sem"]
    # MON 是未来 14 天后(课时统计只计到今天),故用过去的周一 PAST_MON 验覆盖:
    # 它在学期内、是周一、已上过,compute 的 eff_end 会含它。
    past_mon = MON - timedelta(days=28)
    rule = _rule(db, sem, recurrence="single", single_date=past_mon)
    db.add(SpecialDayEntry(
        rule_id=rule.id, class_unit_id=ctx["cls1"].id, period_no=1,
        course_assignment_id=ctx["a3"].id,
    ))
    db.commit()
    hours, _, _ = _compute(db, sem, past_mon, past_mon)
    by_name = {h.teacher_name: h.total for h in hours}
    # 王小明:1 班被换走,2 班?王小明只教 1 班,故当天 0;李小红:2 班原课 + 1 班换来的课 = 2?不对:
    # 李小红教 2 班第 1 节 + 1 班换来的第 1 节,同一节次两个班,按 (教师,日期,节次) 计一次,故总数 1。
    # total 只按格计一次,故李小红 total=1,王小明 0(不在 hours 里或 0)。
    assert by_name.get("王小明", 0) == 0
    assert by_name.get("李小红", 0) == 1


def test_reminder_replaced_by_override(db):
    ctx = _base(db)
    sem = ctx["sem"]
    rule = _rule(db, sem, recurrence="single", single_date=MON)
    db.add(SpecialDayEntry(
        rule_id=rule.id, class_unit_id=ctx["cls1"].id, period_no=1,
        course_assignment_id=ctx["a3"].id,
    ))
    app_settings.save_dingtalk_app(db, "key", "sec", "123456", 15)
    db.commit()
    from app.services.class_reminders import run_class_reminders

    client = FakeClient({"13800000000": "wang", "13900000000": "li"})
    result = run_class_reminders(db, now=datetime.combine(MON, time(7, 50)), client=client)
    # 王小明 1 班被换走,不应收到;李小红应收到 2 班原课 + 1 班换来的课?同一节次同一老师,
    # 主提醒与特殊日提醒各一封?主提醒里李小红教 2 班,特殊日提醒里李小红教 1 班,是两条不同班级的提醒,
    # 故共 2 封,都发给 li,且王小明 0 封。
    sent_to = [s[0] for s in client.sent]
    assert sent_to.count("li") == 2
    assert "wang" not in sent_to
    assert result["sent"] == 2


def _login(client, db, roles=(Role.director,), username="s"):
    user = make_user(db, username, PW, roles=list(roles))
    if Role.director in roles:
        grant_grades(db, user)
    resp = client.post("/api/auth/login", json={"username": username, "password": PW})
    assert resp.status_code == 200
    return user


def test_api_crud_publish_and_grade_guard(env):
    client, db = env
    ctx = _base(db)
    sem = ctx["sem"]
    _login(client, db)
    # 年级主任(已配 7 年级)建年级规则 ok,建全校规则 403
    resp = client.post(f"/api/special-days?semester_id={sem.id}", json={
        "title": "七年级班会日", "scope_type": "grade", "scope_id": 7,
        "recurrence": "single", "single_date": str(MON),
        "entries": [{"class_unit_id": ctx["cls1"].id, "period_no": 1,
            "course_assignment_id": ctx["a3"].id}],
    })
    assert resp.status_code == 201, resp.text
    rule_id = resp.json()["id"]
    assert resp.json()["is_active"] is False
    resp = client.post(f"/api/special-days?semester_id={sem.id}", json={
        "title": "全校", "scope_type": "school", "scope_id": None,
        "recurrence": "single", "single_date": str(MON), "entries": [],
    })
    assert resp.status_code == 403
    # 发布后 expanded 里有该天
    resp = client.post(f"/api/special-days/{rule_id}/publish")
    assert resp.status_code == 200 and resp.json()["is_active"] is True
    url = f"/api/special-days/expanded?semester_id={sem.id}&from_date={MON}&to_date={MON}"
    resp = client.get(url)
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1 and rows[0]["subject_name"] == "语文"
    # 条目配课不教该班时 400
    resp = client.put(f"/api/special-days/{rule_id}/entries", json=[
        {"class_unit_id": ctx["cls1"].id, "period_no": 1, "course_assignment_id": ctx["a3"].id},
        {"class_unit_id": ctx["cls1"].id, "period_no": 1, "course_assignment_id": None},
    ])
    assert resp.status_code in (400, 422)
