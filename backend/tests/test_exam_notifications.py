"""考务通知测试(KW-57~61):四类通知触发与接收人范围、开关关闭 409、
未发布时成绩发布通知 409、无截止时间时催录 409、成绩发布通知不含分数、
remind-due 去重 24 小时、失败记录重发、健康页能查到考务通知记录、越权 403。
钉钉发送全部 mock(只 patch app.services.exam_notifications.send_personal_dingtalk),
不连真实钉钉。

本文件自带 app fixture(挂 auth + exam + exam_scores + exam_publish +
exam_reports + exam_notifications + settings 路由),因为 conftest 的 env
尚未接线新路由(接线由协调员统一做,见汇报)。
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import auth as auth_api
from app.api import exam as exam_api
from app.api import exam_notifications as notif_api
from app.api import exam_publish as publish_api
from app.api import exam_reports as reports_api
from app.api import exam_scores as scores_api
from app.api import settings as settings_api
from app.core.db import Base, get_db
from app.models.assignment import (
    AssignmentTeacher,
    CourseAssignment,
    SchedulingUnit,
    SchedulingUnitMember,
)
# noqa: F401 仅为建表:本批新表须先 import 对应模型,
# Base.metadata.create_all 才会建这些表。
from app.models import exam_notifications  # noqa: F401
from app.models.basedata import ClassUnit, Room, Subject, Teacher
from app.models.exam_foundation import ParentContact, Student
from app.models.exam_invigilation import ExamInvigilation
from app.models.exam_scores import ExamScore, ExamScoreSetting
from app.models.semester import Semester
from app.models.user import Role
from app.services import settings as app_settings
from tests.conftest import make_user

PW = "password123"
EXAM_NAME = "七年级 11 月月考"
TAIPEI = ZoneInfo("Asia/Taipei")


@pytest.fixture
def client_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(auth_api.router, prefix="/api/auth")
    app.include_router(exam_api.router, prefix="/api/exam")
    app.include_router(scores_api.router, prefix="/api/exam")
    app.include_router(publish_api.router, prefix="/api/exam")
    app.include_router(reports_api.router, prefix="/api/exam")
    app.include_router(notif_api.router, prefix="/api/exam")
    app.include_router(settings_api.router, prefix="/api")
    app.dependency_overrides[get_db] = override_get_db
    setup_db = TestSession()
    client = TestClient(app)
    try:
        yield client, setup_db
    finally:
        setup_db.close()
        Base.metadata.drop_all(engine)


@pytest.fixture
def seed(client_db):
    client, db = client_db
    sem = Semester(academic_year=2026, term=1)
    db.add(sem)
    db.flush()
    math = Subject(semester_id=sem.id, name="数学")
    chinese = Subject(semester_id=sem.id, name="语文")
    cls701 = ClassUnit(semester_id=sem.id, grade=7, name="701", track="junior_high")
    cls702 = ClassUnit(semester_id=sem.id, grade=7, name="702", track="junior_high")
    room1 = Room(semester_id=sem.id, name="第一考场")
    db.add_all([math, chinese, cls701, cls702, room1])
    db.flush()
    admin = make_user(db, "adm", PW, roles=[Role.admin])
    academic = make_user(db, "jiao", PW, roles=[Role.director])
    t1user = make_user(db, "t1", PW, roles=[Role.teacher])
    t2user = make_user(db, "t2", PW, roles=[Role.teacher])
    t3user = make_user(db, "t3", PW, roles=[Role.teacher])
    t1 = Teacher(semester_id=sem.id, name="王老师", user_id=t1user.id, phone="13800000001")
    t2 = Teacher(semester_id=sem.id, name="李老师", user_id=t2user.id, phone="13800000002")
    t3 = Teacher(semester_id=sem.id, name="陈老师", user_id=t3user.id, phone="13800000003")
    db.add_all([t1, t2, t3])
    db.flush()
    cls701.homeroom_teacher_id = t1.id
    for teacher, cls in ((t1, cls701), (t2, cls702)):
        unit = SchedulingUnit(
            semester_id=sem.id, unit_type="single", name=cls.name
        )
        db.add(unit)
        db.flush()
        db.add(SchedulingUnitMember(scheduling_unit_id=unit.id, class_unit_id=cls.id))
        ca = CourseAssignment(
            semester_id=sem.id, scheduling_unit_id=unit.id,
            subject_id=math.id, periods_per_week=4,
        )
        db.add(ca)
        db.flush()
        db.add(AssignmentTeacher(course_assignment_id=ca.id, teacher_id=teacher.id))
    s1 = Student(semester_id=sem.id, class_unit_id=cls701.id, student_no="20260101", name="张三", gender="男")
    s2 = Student(semester_id=sem.id, class_unit_id=cls701.id, student_no="20260102", name="李四", gender="女")
    s3 = Student(semester_id=sem.id, class_unit_id=cls701.id, student_no="20260103", name="赵六", gender="男")
    s4 = Student(semester_id=sem.id, class_unit_id=cls701.id, student_no="20260104", name="孙七", gender="女")
    s5 = Student(semester_id=sem.id, class_unit_id=cls702.id, student_no="20260201", name="王五", gender="男")
    s6 = Student(semester_id=sem.id, class_unit_id=cls702.id, student_no="20260202", name="钱八", gender="女")
    db.add_all([s1, s2, s3, s4, s5, s6])
    db.flush()
    db.add_all([
        ParentContact(student_id=s1.id, name="张父", relation="父亲", phone="13800000001"),
        ParentContact(student_id=s2.id, name="张母", relation="母亲", phone="13800000001"),
        ParentContact(student_id=s5.id, name="王父", relation="父亲", phone="13800000005"),
    ])
    db.commit()
    return {
        "sem": sem, "math": math, "chinese": chinese,
        "cls701": cls701, "cls702": cls702, "room1": room1,
        "admin": admin, "academic": academic,
        "t1": t1user, "t2": t2user, "t3": t3user,
        "t1t": t1, "t2t": t2, "t3t": t3,
        "s1": s1, "s2": s2, "s3": s3, "s4": s4, "s5": s5, "s6": s6,
    }


def login(client, username, password=PW):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r


def setup_exam(client, seed, exam_date=None, start="08:00", end="09:30"):
    """建考 + 数学/语文日程 + 参试名单(6 人)。exam_date 默认为明天。"""
    if exam_date is None:
        exam_date = (datetime.now(TAIPEI).date() + timedelta(days=1)).isoformat()
    login(client, "adm")
    r = client.post("/api/exam/exams", json={
        "semester_id": seed["sem"].id, "name": EXAM_NAME,
        "exam_type": "月考", "grades": [7], "description": "",
    })
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    r = client.put(f"/api/exam/exams/{eid}/subjects", json={"subjects": [
        {"subject_id": seed["math"].id, "exam_date": exam_date,
         "start_time": start, "end_time": end, "full_score": 100},
        {"subject_id": seed["chinese"].id, "exam_date": exam_date,
         "start_time": "10:00", "end_time": "11:30", "full_score": 100},
    ]})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/exam/exams/{eid}/participants/generate")
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 6
    return eid


def list_logs(client, eid, params=""):
    r = client.get(f"/api/exam/exams/{eid}/notifications{params}")
    assert r.status_code == 200, r.text
    return r.json()


def configure_dingtalk(db, teacher=None):
    """配好企业应用;指定教师时给钉钉 userid,使发送走钉钉 mock。"""
    app_settings.save_dingtalk_app(db, "key", "sec", "123456", 15)
    if teacher is not None:
        teacher.dingtalk_userid = "dingtalk-userid"
    db.commit()


# ── 开关 ──────────────────────────────────────────────
def test_settings_default_and_put(client_db, seed):
    client, db = client_db
    eid = setup_exam(client, seed)
    login(client, "adm")
    r = client.get(f"/api/exam/exams/{eid}/notification-settings")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "exam_id": eid,
        "schedule_notify_enabled": True,
        "invigilation_remind_enabled": True,
        "score_deadline_remind_enabled": True,
        "publish_notify_enabled": True,
    }
    r = client.put(f"/api/exam/exams/{eid}/notification-settings", json={
        "schedule_notify_enabled": False,
        "invigilation_remind_enabled": True,
        "score_deadline_remind_enabled": False,
        "publish_notify_enabled": True,
    })
    assert r.status_code == 200, r.text
    assert r.json()["schedule_notify_enabled"] is False
    assert r.json()["score_deadline_remind_enabled"] is False


# ── KW-57 考试日程通知 ──────────────────────────────
def test_notify_schedule_to_homeroom_and_subject_teachers(client_db, seed):
    client, db = client_db
    eid = setup_exam(client, seed)
    login(client, "adm")
    # 未配钉钉企业应用:走站内,照样算成功。
    r = client.post(f"/api/exam/exams/{eid}/notify/schedule")
    assert r.status_code == 200, r.text
    assert r.json() == {"sent": 2, "failed": 0}
    body = list_logs(client, eid, "?type=考试日程")
    assert body["total"] == 2
    names = {item["recipient_name"] for item in body["items"]}
    assert names == {"王老师", "李老师"}
    assert all(item["channel"] == "站内" for item in body["items"])
    assert all(item["status"] == "成功" for item in body["items"])
    assert all("数学" in item["message"] and "语文" in item["message"]
               for item in body["items"])


def test_notify_schedule_via_dingtalk_mock(client_db, seed):
    client, db = client_db
    eid = setup_exam(client, seed)
    configure_dingtalk(db, seed["t1t"])
    login(client, "adm")
    with patch(
        "app.services.exam_notifications.send_personal_dingtalk",
        return_value=(True, None),
    ) as mock_send:
        r = client.post(f"/api/exam/exams/{eid}/notify/schedule")
    assert r.status_code == 200, r.text
    assert r.json() == {"sent": 2, "failed": 0}
    assert mock_send.call_count == 2
    body = list_logs(client, eid, "?type=考试日程")
    assert all(item["channel"] == "钉钉" for item in body["items"])


def test_notify_schedule_switch_off_409(client_db, seed):
    client, db = client_db
    eid = setup_exam(client, seed)
    login(client, "adm")
    client.put(f"/api/exam/exams/{eid}/notification-settings", json={
        "schedule_notify_enabled": False,
        "invigilation_remind_enabled": True,
        "score_deadline_remind_enabled": True,
        "publish_notify_enabled": True,
    })
    r = client.post(f"/api/exam/exams/{eid}/notify/schedule")
    assert r.status_code == 409, r.text


# ── KW-58 监考提醒 ──────────────────────────────────
def _seed_invigilation(db, seed, eid):
    db.add_all([
        ExamInvigilation(exam_id=eid, subject_id=seed["math"].id,
                         room_id=seed["room1"].id, teacher_id=seed["t1t"].id),
        ExamInvigilation(exam_id=eid, subject_id=seed["chinese"].id,
                         room_id=seed["room1"].id, teacher_id=seed["t3t"].id),
    ])
    db.commit()


def test_notify_invigilation_only_invigilators(client_db, seed):
    client, db = client_db
    eid = setup_exam(client, seed)
    _seed_invigilation(db, seed, eid)
    login(client, "adm")
    r = client.post(f"/api/exam/exams/{eid}/notify/invigilation")
    assert r.status_code == 200, r.text
    assert r.json() == {"sent": 2, "failed": 0}
    body = list_logs(client, eid, "?type=监考提醒")
    names = {item["recipient_name"] for item in body["items"]}
    assert names == {"王老师", "陈老师"}
    by_name = {item["recipient_name"]: item for item in body["items"]}
    assert "数学" in by_name["王老师"]["message"]
    assert "第一考场" in by_name["王老师"]["message"]
    assert "语文" in by_name["陈老师"]["message"]


def test_notify_invigilation_switch_off_409(client_db, seed):
    client, db = client_db
    eid = setup_exam(client, seed)
    _seed_invigilation(db, seed, eid)
    login(client, "adm")
    client.put(f"/api/exam/exams/{eid}/notification-settings", json={
        "schedule_notify_enabled": True,
        "invigilation_remind_enabled": False,
        "score_deadline_remind_enabled": True,
        "publish_notify_enabled": True,
    })
    r = client.post(f"/api/exam/exams/{eid}/notify/invigilation")
    assert r.status_code == 409, r.text


# ── KW-59 录分截止提醒 ──────────────────────────────
def _seed_scores(db, seed, eid, deadline):
    db.add(ExamScoreSetting(exam_id=eid, score_deadline=deadline))
    # 数学:s1 已提交,s2 未提交,s3 无成绩行,s4 已提交,s5 未提交,s6 已提交;
    # 语文:全部已提交。未录完只归 t1(701 班数学)与 t2(702 班数学)。
    submitted = {
        ("math", "s1"), ("math", "s4"), ("math", "s6"),
        ("chinese", "s1"), ("chinese", "s2"), ("chinese", "s3"),
        ("chinese", "s4"), ("chinese", "s5"), ("chinese", "s6"),
    }
    unsubmitted = {("math", "s2"), ("math", "s5")}
    for subject_key, subject in (("math", seed["math"]), ("chinese", seed["chinese"])):
        for skey in ("s1", "s2", "s3", "s4", "s5", "s6"):
            if (subject_key, skey) in submitted:
                db.add(ExamScore(
                    exam_id=eid, subject_id=subject.id,
                    student_id=seed[skey].id, score=80.0,
                    status="正常", submitted=True,
                ))
            elif (subject_key, skey) in unsubmitted:
                db.add(ExamScore(
                    exam_id=eid, subject_id=subject.id,
                    student_id=seed[skey].id, score=70.0,
                    status="正常", submitted=False,
                ))
    db.commit()


def test_notify_score_deadline_only_incomplete_teachers(client_db, seed):
    client, db = client_db
    eid = setup_exam(client, seed)
    deadline = datetime.now(timezone.utc) + timedelta(days=2)
    _seed_scores(db, seed, eid, deadline)
    login(client, "adm")
    r = client.post(f"/api/exam/exams/{eid}/notify/score-deadline")
    assert r.status_code == 200, r.text
    assert r.json() == {"sent": 2, "failed": 0}
    body = list_logs(client, eid, "?type=录分截止")
    names = {item["recipient_name"] for item in body["items"]}
    assert names == {"王老师", "李老师"}
    assert all("数学" in item["message"] for item in body["items"])


def test_notify_score_deadline_no_deadline_409(client_db, seed):
    client, db = client_db
    eid = setup_exam(client, seed)
    login(client, "adm")
    r = client.post(f"/api/exam/exams/{eid}/notify/score-deadline")
    assert r.status_code == 409, r.text


def test_notify_score_deadline_switch_off_409(client_db, seed):
    client, db = client_db
    eid = setup_exam(client, seed)
    _seed_scores(db, seed, eid, datetime.now(timezone.utc) + timedelta(days=2))
    login(client, "adm")
    client.put(f"/api/exam/exams/{eid}/notification-settings", json={
        "schedule_notify_enabled": True,
        "invigilation_remind_enabled": True,
        "score_deadline_remind_enabled": False,
        "publish_notify_enabled": True,
    })
    r = client.post(f"/api/exam/exams/{eid}/notify/score-deadline")
    assert r.status_code == 409, r.text


# ── KW-60 成绩发布通知 ──────────────────────────────
def test_notify_publish_not_published_409(client_db, seed):
    client, db = client_db
    eid = setup_exam(client, seed)
    login(client, "adm")
    r = client.post(f"/api/exam/exams/{eid}/notify/publish")
    assert r.status_code == 409, r.text


def test_notify_publish_switch_off_409(client_db, seed):
    client, db = client_db
    eid = setup_exam(client, seed)
    login(client, "adm")
    r = client.post(f"/api/exam/exams/{eid}/publish-batches", json={
        "scope_type": "年级", "scope_value": 7,
    })
    assert r.status_code == 201, r.text
    client.put(f"/api/exam/exams/{eid}/notification-settings", json={
        "schedule_notify_enabled": True,
        "invigilation_remind_enabled": True,
        "score_deadline_remind_enabled": True,
        "publish_notify_enabled": False,
    })
    r = client.post(f"/api/exam/exams/{eid}/notify/publish")
    assert r.status_code == 409, r.text


def test_notify_publish_only_queryable_no_scores(client_db, seed):
    client, db = client_db
    eid = setup_exam(client, seed)
    deadline = datetime.now(timezone.utc) + timedelta(days=2)
    _seed_scores(db, seed, eid, deadline)
    login(client, "adm")
    r = client.post(f"/api/exam/exams/{eid}/publish-batches", json={
        "scope_type": "年级", "scope_value": 7,
    })
    assert r.status_code == 201, r.text
    r = client.post(f"/api/exam/accounts/provision?semester_id={seed['sem'].id}")
    assert r.status_code == 200, r.text
    r = client.post(f"/api/exam/exams/{eid}/notify/publish")
    assert r.status_code == 200, r.text
    # 6 名学生账号 + 3 条家长关联(s1、s2 同一家长账号各一条,s5 一条)。
    assert r.json() == {"sent": 9, "failed": 0}
    body = list_logs(client, eid, "?type=成绩发布")
    assert body["total"] == 9
    for item in body["items"]:
        assert "成绩已可查询" in item["message"]
        assert "90" not in item["message"]
        assert "80" not in item["message"]
        assert "70" not in item["message"]
        assert "分" not in item["message"]


# ── 到期扫与去重 ────────────────────────────────────
def test_remind_due_day_before_and_dedup_24h(client_db, seed):
    client, db = client_db
    eid = setup_exam(client, seed)  # 考试日期默认为明天
    _seed_invigilation(db, seed, eid)
    login(client, "adm")
    r = client.post("/api/exam/notifications/remind-due")
    assert r.status_code == 200, r.text
    assert r.json() == {"sent": 2, "failed": 0}
    body = list_logs(client, eid, "?type=监考提醒")
    assert body["total"] == 2
    assert all("明天" in item["message"] for item in body["items"])
    # 24 小时内再扫:同一提醒不重复发。
    r = client.post("/api/exam/notifications/remind-due")
    assert r.status_code == 200, r.text
    assert r.json() == {"sent": 0, "failed": 0}
    assert list_logs(client, eid, "?type=监考提醒")["total"] == 2


def test_remind_due_day_of_within_lead(client_db, seed):
    client, db = client_db
    wall_now = datetime.now(TAIPEI)
    start = (wall_now + timedelta(minutes=10)).strftime("%H:%M")
    end = (wall_now + timedelta(minutes=100)).strftime("%H:%M")
    eid = setup_exam(
        client, seed, exam_date=wall_now.date().isoformat(), start=start, end=end,
    )
    # 只排数学一场(语文固定 10:00,是否在窗口内取决于跑测试的时刻,不稳定)。
    db.add(ExamInvigilation(exam_id=eid, subject_id=seed["math"].id,
                            room_id=seed["room1"].id, teacher_id=seed["t1t"].id))
    db.commit()
    login(client, "adm")
    r = client.post("/api/exam/notifications/remind-due")
    assert r.status_code == 200, r.text
    # 当天开考前(默认提前 30 分钟,10 分钟后开考)在窗口内,发 1 人。
    assert r.json() == {"sent": 1, "failed": 0}
    body = list_logs(client, eid, "?type=监考提醒")
    assert all("今天" in item["message"] for item in body["items"])


def test_remind_due_score_deadline_24h_and_dedup(client_db, seed):
    client, db = client_db
    eid = setup_exam(client, seed)
    deadline = datetime.now(timezone.utc) + timedelta(hours=23)
    _seed_scores(db, seed, eid, deadline)
    login(client, "adm")
    r = client.post("/api/exam/notifications/remind-due")
    assert r.status_code == 200, r.text
    assert r.json() == {"sent": 2, "failed": 0}
    r = client.post("/api/exam/notifications/remind-due")
    assert r.status_code == 200, r.text
    assert r.json() == {"sent": 0, "failed": 0}
    assert list_logs(client, eid, "?type=录分截止")["total"] == 2


def test_remind_due_score_deadline_2h(client_db, seed):
    client, db = client_db
    eid = setup_exam(client, seed)
    deadline = datetime.now(timezone.utc) + timedelta(hours=1)
    _seed_scores(db, seed, eid, deadline)
    login(client, "adm")
    r = client.post("/api/exam/notifications/remind-due")
    assert r.status_code == 200, r.text
    assert r.json() == {"sent": 2, "failed": 0}


def test_remind_due_forbidden_for_teacher(client_db, seed):
    client, db = client_db
    setup_exam(client, seed)
    login(client, "t1")
    r = client.post("/api/exam/notifications/remind-due")
    assert r.status_code == 403, r.text


# ── 失败记录重发 ────────────────────────────────────
def test_failed_log_resend(client_db, seed):
    client, db = client_db
    eid = setup_exam(client, seed)
    configure_dingtalk(db, seed["t1t"])
    db.refresh(seed["t1t"])
    login(client, "adm")
    with patch(
        "app.services.exam_notifications.send_personal_dingtalk",
        side_effect=RuntimeError("钉钉网关超时"),
    ):
        r = client.post(f"/api/exam/exams/{eid}/notify/schedule")
    assert r.status_code == 200, r.text
    # t1 走钉钉失败,t2 无钉钉 userid 但有手机号,同样走钉钉 mock 也失败。
    assert r.json() == {"sent": 0, "failed": 2}
    body = list_logs(client, eid, "?status=失败")
    assert body["total"] == 2
    assert all(item["error"] for item in body["items"])
    failed_id = body["items"][0]["id"]
    # 重发时钉钉恢复:成功。
    with patch(
        "app.services.exam_notifications.send_personal_dingtalk",
        return_value=(True, None),
    ):
        r = client.post(f"/api/exam/exams/{eid}/notifications/{failed_id}/resend")
    assert r.status_code == 200, r.text
    assert r.json() == {"sent": True, "status": "成功"}
    body = list_logs(client, eid, "?status=成功")
    assert any(item["id"] == failed_id for item in body["items"])
    # 成功记录不可重发。
    r = client.post(f"/api/exam/exams/{eid}/notifications/{failed_id}/resend")
    assert r.status_code == 409, r.text


# ── KW-61 健康页 ────────────────────────────────────
def test_health_page_shows_exam_notifications(client_db, seed):
    client, db = client_db
    eid = setup_exam(client, seed)
    login(client, "adm")
    r = client.get("/api/settings/dingtalk-app/health")
    assert r.status_code == 200, r.text
    assert r.json()["exam_notifications_7d"] == 0
    client.post(f"/api/exam/exams/{eid}/notify/schedule")
    r = client.get("/api/settings/dingtalk-app/health")
    assert r.status_code == 200, r.text
    assert r.json()["exam_notifications_7d"] == 2
    assert r.json()["exam_notifications_failed"] == 0
    assert r.json()["exam_notifications_last_sent_at"] is not None


# ── 权限与列表过滤 ──────────────────────────────────
def test_notify_forbidden_for_teacher(client_db, seed):
    client, db = client_db
    eid = setup_exam(client, seed)
    login(client, "t1")
    for path in ("schedule", "invigilation", "score-deadline", "publish"):
        r = client.post(f"/api/exam/exams/{eid}/notify/{path}")
        assert r.status_code == 403, (path, r.text)


def test_list_logs_filters_and_teacher_scope(client_db, seed):
    client, db = client_db
    eid = setup_exam(client, seed)
    _seed_invigilation(db, seed, eid)
    login(client, "adm")
    client.post(f"/api/exam/exams/{eid}/notify/schedule")
    client.post(f"/api/exam/exams/{eid}/notify/invigilation")
    body = list_logs(client, eid)
    assert body["total"] == 4
    assert list_logs(client, eid, "?type=监考提醒")["total"] == 2
    assert list_logs(client, eid, "?q=陈老师")["total"] == 1
    assert list_logs(client, eid, "?status=失败")["total"] == 0
    # 教师本人只看得到发给自己的记录。
    login(client, "t1")
    body = list_logs(client, eid)
    assert body["total"] == 2
    assert {item["recipient_name"] for item in body["items"]} == {"王老师"}
    login(client, "t2")
    body = list_logs(client, eid)
    assert body["total"] == 1
    assert body["items"][0]["recipient_name"] == "李老师"
