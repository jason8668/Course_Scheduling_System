"""个人上课提醒:服务层(已发布课表扫描、提前窗口、防重复)与企业应用设置 API。

不连真实钉钉:提醒服务注入 FakeClient;设置测试端点 monkeypatch token。
"""

from datetime import datetime, time, timedelta

import pytest

from app.models.assignment import AssignmentTeacher, CourseAssignment, SchedulingUnit, SchedulingUnitMember
from app.models.basedata import ClassUnit, Subject, Teacher
from app.models.period import Period, PeriodTable
from app.models.semester import Semester
from app.models.timetable import ClassReminderLog, ScheduleEntry, Timetable, TimetableStatus
from app.models.user import Role
from app.services import settings as app_settings
from app.services.class_reminders import run_class_reminders
from app.services.dingtalk_app import normalize_mobile
from tests.conftest import make_user
from tests.dates import MON

PW = "password123"


class FakeClient:
    """按手机号解析 userid(查不到回 None),发送只记录。"""

    def __init__(self, by_mobile: dict):
        self.by_mobile = by_mobile
        self.sent: list[tuple[str, str, str]] = []

    def get_userid(self, mobile: str):
        return self.by_mobile.get(mobile)

    def send_work_notification(self, userid: str, title: str, text: str) -> None:
        self.sent.append((userid, title, text))


def _seed(db, *, teacher_phone="13800000000", status=TimetableStatus.published.value,
          sem_start=None, sem_end=None, year=2026, term=1):
    """一学期 + 默认节次表(第 1 节 8:00,第 2 节 8:55)+ 一班一师一科已发布课表。"""
    sem = Semester(
        academic_year=year, term=term,
        start_date=sem_start or (MON - timedelta(days=30)),
        end_date=sem_end or (MON + timedelta(days=60)),
    )
    db.add(sem)
    db.flush()
    table = PeriodTable(semester_id=sem.id, name="默认", is_default=True)
    db.add(table)
    db.flush()
    for no, start in ((1, time(8, 0)), (2, time(8, 55))):
        db.add(Period(
            period_table_id=table.id, weekday=MON.isoweekday(), period_no=no,
            name=f"第{no}节", start_time=start, end_time=time(8, 45), type="regular",
        ))
    cls = ClassUnit(semester_id=sem.id, grade=7, name="七年级1班", track="初中")
    teacher = Teacher(semester_id=sem.id, name="王小明", phone=teacher_phone)
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
    tt = Timetable(semester_id=sem.id, name="t1", status=status)
    db.add(tt)
    db.flush()
    entry = ScheduleEntry(
        timetable_id=tt.id, course_assignment_id=a.id,
        weekday=MON.isoweekday(), period_no=1,
    )
    db.add(entry)
    app_settings.save_dingtalk_app(db, "key", "sec", "123456", 15)
    db.commit()
    return {"sem": sem, "teacher": teacher, "entry": entry}


def test_due_reminder_sent_cached_and_deduped(db):
    ctx = _seed(db)
    client = FakeClient({"13800000000": "zhangsan"})
    now = datetime.combine(MON, time(7, 50))  # 第 1 节 8:00,提前 10 分钟,在 15 分钟内
    result = run_class_reminders(db, now=now, client=client)
    assert result["sent"] == 1
    assert client.sent[0][0] == "zhangsan" and client.sent[0][1] == "上课提醒"
    assert "七年级1班" in client.sent[0][2] and "数学" in client.sent[0][2]
    # userid 已缓存到教师档案,提醒日志已落盘
    assert db.get(Teacher, ctx["teacher"].id).dingtalk_userid == "zhangsan"
    from sqlalchemy import select
    assert len(db.scalars(select(ClassReminderLog)).all()) == 1
    # 再跑一次:同一格同一天不再发
    result2 = run_class_reminders(db, now=now, client=client)
    assert result2["sent"] == 0 and len(client.sent) == 1


def test_not_yet_due_and_already_started(db):
    _seed(db)
    client = FakeClient({"13800000000": "zhangsan"})
    # 7:00 距 8:00 还有 60 分钟,超出 15 分钟提前量
    assert run_class_reminders(db, now=datetime.combine(MON, time(7, 0)), client=client)["sent"] == 0
    # 8:01 已开课,不补发
    assert run_class_reminders(db, now=datetime.combine(MON, time(8, 1)), client=client)["sent"] == 0
    assert client.sent == []


def test_unconfigured_is_silent(db):
    _seed(db)
    app_settings.save_dingtalk_app(db, "", "", "", 15)
    db.commit()
    client = FakeClient({"13800000000": "zhangsan"})
    result = run_class_reminders(db, now=datetime.combine(MON, time(7, 50)), client=client)
    assert result == {"sent": 0, "skipped": 0, "reason": "not_configured"}
    assert client.sent == []


def test_unpublished_and_out_of_semester_ignored(db):
    _seed(db, status=TimetableStatus.draft.value)
    client = FakeClient({"13800000000": "zhangsan"})
    assert run_class_reminders(db, now=datetime.combine(MON, time(7, 50)), client=client)["sent"] == 0

    _seed(db, sem_start=MON - timedelta(days=90), sem_end=MON - timedelta(days=60),
          year=2027, term=1)
    assert run_class_reminders(db, now=datetime.combine(MON, time(7, 50)), client=client)["sent"] == 0


def test_teacher_without_phone_or_userid_skipped(db):
    _seed(db, teacher_phone=None)
    client = FakeClient({})
    result = run_class_reminders(db, now=datetime.combine(MON, time(7, 50)), client=client)
    assert result["sent"] == 0 and result["skipped"] == 1
    assert client.sent == []

    # 有手机号但不在企业通讯录:解析回 None,同样跳过
    _seed(db, teacher_phone="13900000000", year=2027, term=1)
    result = run_class_reminders(db, now=datetime.combine(MON, time(7, 50)), client=client)
    assert result["sent"] == 0


def test_normalize_mobile():
    assert normalize_mobile("138 0000 0000") == "13800000000"
    assert normalize_mobile("+86 138-0000-0000") == "13800000000"
    assert normalize_mobile("8613800000000") == "13800000000"


@pytest.fixture
def admin(env):
    client, db = env
    make_user(db, "admin1", PW, roles=[Role.admin])
    client.post("/api/auth/login", json={"username": "admin1", "password": PW})
    return client, db


def test_dingtalk_app_settings_roundtrip(admin):
    client, db = admin
    r = client.get("/api/settings/dingtalk-app")
    assert r.status_code == 200
    assert r.json() == {
        "app_key": "", "agent_id": "", "configured": False,
        "has_app_secret": False, "lead_minutes": 15,
    }

    r = client.put("/api/settings/dingtalk-app", json={
        "app_key": "key1", "app_secret": "sec1", "agent_id": "123456", "lead_minutes": 10,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is True and body["has_app_secret"] is True
    assert body["lead_minutes"] == 10
    assert "sec1" not in r.text  # 密钥不明文回传

    # 密钥留空 = 不变更;提前分钟数越界被 422 挡下
    r = client.put("/api/settings/dingtalk-app", json={
        "app_key": "key1", "app_secret": "", "agent_id": "123456", "lead_minutes": 10,
    })
    assert r.json()["has_app_secret"] is True
    r = client.put("/api/settings/dingtalk-app", json={
        "app_key": "key1", "app_secret": "", "agent_id": "123456", "lead_minutes": 0,
    })
    assert r.status_code == 422

    cfg = app_settings.dingtalk_app_config(db)
    assert cfg.app_key == "key1" and cfg.agent_id == "123456" and cfg.lead_minutes == 10


def test_dingtalk_app_test_endpoint(admin, monkeypatch):
    from app.services.dingtalk_app import DingTalkAppClient

    client, _ = admin
    # 未配置时报 400
    r = client.post("/api/settings/dingtalk-app/test", json={
        "app_key": "", "app_secret": "", "agent_id": "", "lead_minutes": 15,
    })
    assert r.status_code == 400

    # token 取得到即通过,不给任何老师发消息
    monkeypatch.setattr(DingTalkAppClient, "token", property(lambda self: "tok"))
    r = client.post("/api/settings/dingtalk-app/test", json={
        "app_key": "key1", "app_secret": "sec1", "agent_id": "123456", "lead_minutes": 15,
    })
    assert r.status_code == 200 and r.json() == {"ok": True}
