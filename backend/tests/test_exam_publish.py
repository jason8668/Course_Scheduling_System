"""成绩发布与校对锁定测试(KW-36~40):发布设置、双人校对、成绩锁定、改分审批、发布批次、成绩异议。

本文件自带 app fixture(挂 auth + exam + exam_scores + exam_publish 路由),
因为 conftest 的 env 尚未接线新路由(接线由协调员统一做,见汇报)。
"""

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import auth as auth_api
from app.api import exam as exam_api
from app.api import exam_publish as publish_api
from app.api import exam_scores as scores_api
from app.core.db import Base, get_db
from app.models.assignment import (
    AssignmentTeacher,
    CourseAssignment,
    SchedulingUnit,
    SchedulingUnitMember,
)
from app.models.audit import AuditLog
from app.models.basedata import ClassUnit, Subject, Teacher
from app.models.exam import Exam
from app.models.exam_foundation import Student
from app.models.exam_publish import ExamPublishBatch
from app.models.exam_scores import ExamScore
from app.models.exam_scopes import SubjectLeader
from app.models.semester import Semester
from app.models.user import Role, UserGradeScope
from app.services import exam_publish as publish_svc
from tests.conftest import make_user

PW = "password123"


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
    cls7 = ClassUnit(semester_id=sem.id, grade=7, name="701", track="junior_high")
    cls8 = ClassUnit(semester_id=sem.id, grade=8, name="801", track="junior_high")
    db.add_all([math, chinese, cls7, cls8])
    db.flush()
    admin = make_user(db, "adm", PW, roles=[Role.admin])
    academic = make_user(db, "jiao", PW, roles=[Role.director])
    grade_leader = make_user(db, "nzb", PW, roles=[Role.director])
    db.add(UserGradeScope(user_id=grade_leader.id, grade=7))
    t1user = make_user(db, "t1", PW, roles=[Role.teacher])
    t2user = make_user(db, "t2", PW, roles=[Role.teacher])
    t3user = make_user(db, "t3", PW, roles=[Role.teacher])
    t1 = Teacher(semester_id=sem.id, name="王老师", user_id=t1user.id)
    t2 = Teacher(semester_id=sem.id, name="李老师", user_id=t2user.id)
    t3 = Teacher(semester_id=sem.id, name="张老师", user_id=t3user.id)
    db.add_all([t1, t2, t3])
    db.flush()
    cls7.homeroom_teacher_id = t1.id
    cls8.homeroom_teacher_id = t2.id
    db.flush()
    # t2 为数学教研组长;t1、t3 任教数学 701 班,t2 任教数学 801 班。
    db.add(SubjectLeader(semester_id=sem.id, teacher_id=t2.id, subject_id=math.id))
    unit7 = SchedulingUnit(semester_id=sem.id, name="701")
    unit8 = SchedulingUnit(semester_id=sem.id, name="801")
    db.add_all([unit7, unit8])
    db.flush()
    db.add_all([
        SchedulingUnitMember(scheduling_unit_id=unit7.id, class_unit_id=cls7.id),
        SchedulingUnitMember(scheduling_unit_id=unit8.id, class_unit_id=cls8.id),
    ])
    db.flush()
    ca_math7 = CourseAssignment(
        semester_id=sem.id, scheduling_unit_id=unit7.id,
        subject_id=math.id, periods_per_week=4,
    )
    ca_math8 = CourseAssignment(
        semester_id=sem.id, scheduling_unit_id=unit8.id,
        subject_id=math.id, periods_per_week=4,
    )
    db.add_all([ca_math7, ca_math8])
    db.flush()
    db.add_all([
        AssignmentTeacher(course_assignment_id=ca_math7.id, teacher_id=t1.id),
        AssignmentTeacher(course_assignment_id=ca_math7.id, teacher_id=t3.id),
        AssignmentTeacher(course_assignment_id=ca_math8.id, teacher_id=t2.id),
    ])
    s1 = Student(semester_id=sem.id, class_unit_id=cls7.id, student_no="20260101", name="张三", gender="男")
    s2 = Student(semester_id=sem.id, class_unit_id=cls7.id, student_no="20260102", name="李四", gender="女")
    s3 = Student(semester_id=sem.id, class_unit_id=cls8.id, student_no="20260201", name="王五", gender="男")
    db.add_all([s1, s2, s3])
    db.commit()
    return {
        "sem": sem, "math": math, "chinese": chinese,
        "cls7": cls7, "cls8": cls8,
        "admin": admin, "academic": academic, "grade_leader": grade_leader,
        "t1": t1user, "t2": t2user, "t3": t3user,
        "t1t": t1, "t2t": t2, "t3t": t3,
        "s1": s1, "s2": s2, "s3": s3,
    }


def login(client, username):
    r = client.post("/api/auth/login", json={"username": username, "password": PW})
    assert r.status_code == 200, r.text


def make_exam(client, seed):
    login(client, "adm")
    r = client.post("/api/exam/exams", json={
        "semester_id": seed["sem"].id, "name": "七年级 11 月月考",
        "exam_type": "月考", "grades": [7, 8],
    })
    assert r.status_code == 201, r.text
    exam_id = r.json()["id"]
    r = client.put(f"/api/exam/exams/{exam_id}/subjects", json={"subjects": [
        {"subject_id": seed["math"].id, "exam_date": "2026-11-16",
         "start_time": "09:00:00", "end_time": "11:00:00", "full_score": 100},
        {"subject_id": seed["chinese"].id, "exam_date": "2026-11-17",
         "start_time": "09:00:00", "end_time": "11:00:00", "full_score": 100},
    ]})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/exam/exams/{exam_id}/participants/generate")
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 3
    return exam_id


def enter_and_submit(client, seed, exam_id, subject_id, class_unit_id, entries):
    """以 t1 身份录入并提交某班某科成绩,返回成绩 id 列表。"""
    login(client, "t1")
    r = client.put(f"/api/exam/exams/{exam_id}/scores", json={
        "subject_id": subject_id,
        "scores": [{"student_id": s, "score": v} for s, v in entries],
    })
    assert r.status_code == 200, r.text
    r = client.post(f"/api/exam/exams/{exam_id}/scores/submit", json={
        "subject_id": subject_id, "class_unit_id": class_unit_id,
    })
    assert r.status_code == 200, r.text
    return r.json()["submitted"]


def score_id_of(db, exam_id, subject_id, student_id):
    row = db.query(ExamScore).filter_by(
        exam_id=exam_id, subject_id=subject_id, student_id=student_id,
    ).first()
    assert row is not None
    return row.id


def proofread_and_lock(client, seed, exam_id, subject_id, class_unit_id):
    """走完校对通过+锁定,返回锁定 id。"""
    login(client, "t1")
    r = client.post(f"/api/exam/exams/{exam_id}/proofreading", json={
        "subject_id": subject_id, "class_unit_id": class_unit_id,
    })
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    login(client, "t2")
    r = client.post(
        f"/api/exam/exams/{exam_id}/proofreading/{pid}/decide",
        json={"decision": "通过"},
    )
    assert r.status_code == 200, r.text
    login(client, "adm")
    r = client.post(f"/api/exam/exams/{exam_id}/locks", json={
        "subject_id": subject_id, "class_unit_id": class_unit_id,
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ── 发布设置 ──────────────────────────────
def test_publish_settings_defaults_and_update(client_db, seed):
    client, db = client_db
    exam_id = make_exam(client, seed)
    login(client, "t1")
    r = client.get(f"/api/exam/exams/{exam_id}/publish-settings")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "exam_id": exam_id, "proofreader_role": "subject_leader",
        "approval_levels": 1, "publish_order": "teachers_first",
        "objection_open": True,
    }
    login(client, "t1")
    r = client.put(f"/api/exam/exams/{exam_id}/publish-settings", json={
        "proofreader_role": "peer_teacher", "approval_levels": 2,
        "publish_order": "sync", "objection_open": False,
    })
    assert r.status_code == 403, r.text  # 教师无权改设置
    login(client, "adm")
    r = client.put(f"/api/exam/exams/{exam_id}/publish-settings", json={
        "proofreader_role": "peer_teacher", "approval_levels": 2,
        "publish_order": "sync", "objection_open": False,
    })
    assert r.status_code == 200, r.text
    assert r.json()["approval_levels"] == 2
    assert r.json()["objection_open"] is False
    r = client.put(f"/api/exam/exams/{exam_id}/publish-settings", json={
        "proofreader_role": "subject_leader", "approval_levels": 3,
        "publish_order": "teachers_first", "objection_open": True,
    })
    assert r.status_code == 422, r.text


# ── 双人校对(KW-36) ──────────────────────────────
def test_proofreading_requires_submitted_scores(client_db, seed):
    client, db = client_db
    exam_id = make_exam(client, seed)
    login(client, "t1")
    r = client.post(f"/api/exam/exams/{exam_id}/proofreading", json={
        "subject_id": seed["math"].id, "class_unit_id": seed["cls7"].id,
    })
    assert r.status_code == 409, r.text  # 成绩未提交,不能校对
    enter_and_submit(
        client, seed, exam_id, seed["math"].id, seed["cls7"].id,
        [(seed["s1"].id, 88), (seed["s2"].id, 92)],
    )
    r = client.post(f"/api/exam/exams/{exam_id}/proofreading", json={
        "subject_id": seed["math"].id, "class_unit_id": seed["cls7"].id,
    })
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "待校对"
    assert r.json()["proofreader_name"] == "李老师"  # 数学教研组长 t2
    assert r.json()["submitted_by_name"] == "王老师"
    r = client.post(f"/api/exam/exams/{exam_id}/proofreading", json={
        "subject_id": seed["math"].id, "class_unit_id": seed["cls7"].id,
    })
    assert r.status_code == 409, r.text  # 重复提交


def test_proofreading_decide_permissions(client_db, seed):
    client, db = client_db
    exam_id = make_exam(client, seed)
    enter_and_submit(
        client, seed, exam_id, seed["math"].id, seed["cls7"].id,
        [(seed["s1"].id, 88), (seed["s2"].id, 92)],
    )
    login(client, "t1")
    r = client.post(f"/api/exam/exams/{exam_id}/proofreading", json={
        "subject_id": seed["math"].id, "class_unit_id": seed["cls7"].id,
    })
    pid = r.json()["id"]
    # 录入人本人不能校对
    r = client.post(
        f"/api/exam/exams/{exam_id}/proofreading/{pid}/decide",
        json={"decision": "通过"},
    )
    assert r.status_code == 403, r.text
    # 非指定校对人的同组教师不能决定
    login(client, "t3")
    r = client.post(
        f"/api/exam/exams/{exam_id}/proofreading/{pid}/decide",
        json={"decision": "通过"},
    )
    assert r.status_code == 403, r.text
    # 指定校对人(教研组长)通过
    login(client, "t2")
    r = client.post(
        f"/api/exam/exams/{exam_id}/proofreading/{pid}/decide",
        json={"decision": "通过"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "通过"
    # 已决定不能重复决定
    r = client.post(
        f"/api/exam/exams/{exam_id}/proofreading/{pid}/decide",
        json={"decision": "退回"},
    )
    assert r.status_code == 409, r.text


def test_proofreading_reject_then_resubmit(client_db, seed):
    client, db = client_db
    exam_id = make_exam(client, seed)
    enter_and_submit(
        client, seed, exam_id, seed["math"].id, seed["cls7"].id,
        [(seed["s1"].id, 88), (seed["s2"].id, 92)],
    )
    login(client, "t1")
    r = client.post(f"/api/exam/exams/{exam_id}/proofreading", json={
        "subject_id": seed["math"].id, "class_unit_id": seed["cls7"].id,
    })
    pid = r.json()["id"]
    login(client, "t2")
    r = client.post(
        f"/api/exam/exams/{exam_id}/proofreading/{pid}/decide",
        json={"decision": "退回", "note": "有一人分数疑似登错"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "退回"
    login(client, "t1")
    r = client.post(f"/api/exam/exams/{exam_id}/proofreading", json={
        "subject_id": seed["math"].id, "class_unit_id": seed["cls7"].id,
    })
    assert r.status_code == 201, r.text  # 退回后可重新提交


def test_proofreading_peer_teacher_mode(client_db, seed):
    client, db = client_db
    exam_id = make_exam(client, seed)
    login(client, "adm")
    r = client.put(f"/api/exam/exams/{exam_id}/publish-settings", json={
        "proofreader_role": "peer_teacher", "approval_levels": 1,
        "publish_order": "teachers_first", "objection_open": True,
    })
    assert r.status_code == 200, r.text
    enter_and_submit(
        client, seed, exam_id, seed["math"].id, seed["cls7"].id,
        [(seed["s1"].id, 88), (seed["s2"].id, 92)],
    )
    login(client, "t1")
    r = client.post(f"/api/exam/exams/{exam_id}/proofreading", json={
        "subject_id": seed["math"].id, "class_unit_id": seed["cls7"].id,
    })
    assert r.status_code == 201, r.text
    # 同组教师取 id 最小且非提交人的一位:李老师(t2,任教数学 801 班)
    assert r.json()["proofreader_name"] == "李老师"


# ── 成绩锁定(KW-37) ──────────────────────────────
def test_lock_requires_proofreading_passed(client_db, seed):
    client, db = client_db
    exam_id = make_exam(client, seed)
    enter_and_submit(
        client, seed, exam_id, seed["math"].id, seed["cls7"].id,
        [(seed["s1"].id, 88), (seed["s2"].id, 92)],
    )
    login(client, "adm")
    r = client.post(f"/api/exam/exams/{exam_id}/locks", json={
        "subject_id": seed["math"].id, "class_unit_id": seed["cls7"].id,
    })
    assert r.status_code == 409, r.text  # 校对未通过,不能锁
    proofread_and_lock(client, seed, exam_id, seed["math"].id, seed["cls7"].id)
    login(client, "adm")
    r = client.post(f"/api/exam/exams/{exam_id}/locks", json={
        "subject_id": seed["math"].id, "class_unit_id": seed["cls7"].id,
    })
    assert r.status_code == 409, r.text  # 重复锁定
    login(client, "t1")
    r = client.post(f"/api/exam/exams/{exam_id}/locks", json={
        "subject_id": seed["math"].id, "class_unit_id": seed["cls7"].id,
    })
    assert r.status_code == 403, r.text  # 锁定只允许教务
    r = client.get(f"/api/exam/exams/{exam_id}/locks")
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["locked_by_name"] == "adm"


def test_locked_scores_reject_put(client_db, seed):
    client, db = client_db
    exam_id = make_exam(client, seed)
    enter_and_submit(
        client, seed, exam_id, seed["math"].id, seed["cls7"].id,
        [(seed["s1"].id, 88), (seed["s2"].id, 92)],
    )
    lid = proofread_and_lock(client, seed, exam_id, seed["math"].id, seed["cls7"].id)
    login(client, "t1")
    r = client.put(f"/api/exam/exams/{exam_id}/scores", json={
        "subject_id": seed["math"].id,
        "scores": [{"student_id": seed["s1"].id, "score": 90}],
    })
    assert r.status_code == 403, r.text  # 锁定后本人不能直接改
    login(client, "adm")
    r = client.put(f"/api/exam/exams/{exam_id}/scores", json={
        "subject_id": seed["math"].id,
        "scores": [{"student_id": seed["s1"].id, "score": 90}],
    })
    assert r.status_code == 403, r.text  # 教务也不能直接改,只能走改分审批
    # 解锁后恢复可改
    r = client.delete(f"/api/exam/exams/{exam_id}/locks/{lid}")
    assert r.status_code == 204, r.text
    login(client, "t1")
    r = client.put(f"/api/exam/exams/{exam_id}/scores", json={
        "subject_id": seed["math"].id,
        "scores": [{"student_id": seed["s1"].id, "score": 90}],
    })
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 1


def test_unlock_forbidden_for_teacher(client_db, seed):
    client, db = client_db
    exam_id = make_exam(client, seed)
    enter_and_submit(
        client, seed, exam_id, seed["math"].id, seed["cls7"].id,
        [(seed["s1"].id, 88), (seed["s2"].id, 92)],
    )
    lid = proofread_and_lock(client, seed, exam_id, seed["math"].id, seed["cls7"].id)
    login(client, "t1")
    r = client.delete(f"/api/exam/exams/{exam_id}/locks/{lid}")
    assert r.status_code == 403, r.text


# ── 改分审批(KW-38) ──────────────────────────────
def _locked_score_id(client_db, seed, exam_id):
    client, db = client_db
    enter_and_submit(
        client, seed, exam_id, seed["math"].id, seed["cls7"].id,
        [(seed["s1"].id, 88), (seed["s2"].id, 92)],
    )
    proofread_and_lock(client, seed, exam_id, seed["math"].id, seed["cls7"].id)
    return score_id_of(db, exam_id, seed["math"].id, seed["s1"].id)


def test_change_request_requires_lock(client_db, seed):
    client, db = client_db
    exam_id = make_exam(client, seed)
    enter_and_submit(
        client, seed, exam_id, seed["math"].id, seed["cls7"].id,
        [(seed["s1"].id, 88), (seed["s2"].id, 92)],
    )
    sid = score_id_of(db, exam_id, seed["math"].id, seed["s1"].id)
    login(client, "t1")
    r = client.post(f"/api/exam/exams/{exam_id}/score-change-requests", json={
        "score_id": sid, "new_score": 90, "reason": "登错分",
    })
    assert r.status_code == 409, r.text  # 未锁定,无需审批


def test_change_request_one_level_approve(client_db, seed):
    client, db = client_db
    exam_id = make_exam(client, seed)
    sid = _locked_score_id(client_db, seed, exam_id)
    login(client, "t1")
    r = client.post(f"/api/exam/exams/{exam_id}/score-change-requests", json={
        "score_id": sid, "new_score": 90, "reason": "登错分",
    })
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert r.json()["old_score"] == 88
    assert r.json()["status"] == "待审批"
    # 普通同组教师无权审批
    login(client, "t3")
    r = client.post(
        f"/api/exam/exams/{exam_id}/score-change-requests/{rid}/decide",
        json={"decision": "通过"},
    )
    assert r.status_code == 403, r.text
    # 教研组长一层通过即生效
    login(client, "t2")
    r = client.post(
        f"/api/exam/exams/{exam_id}/score-change-requests/{rid}/decide",
        json={"decision": "通过", "note": "核对无误"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "已通过"
    assert r.json()["approvals"][0]["approver_name"] == "李老师"
    assert r.json()["approvals"][0]["decision"] == "通过"
    db.expire_all()
    row = db.query(ExamScore).filter_by(id=sid).first()
    assert row.score == 90
    # 审计留痕:申请与审批各一条
    logs = db.query(AuditLog).filter(
        AuditLog.action.in_(
            ["exam_score_change_request_create", "exam_score_change_decide"]
        )
    ).all()
    assert len(logs) == 2
    assert "88" in logs[1].detail and "90" in logs[1].detail


def test_change_request_two_levels_order_and_reject(client_db, seed):
    client, db = client_db
    exam_id = make_exam(client, seed)
    login(client, "adm")
    r = client.put(f"/api/exam/exams/{exam_id}/publish-settings", json={
        "proofreader_role": "subject_leader", "approval_levels": 2,
        "publish_order": "teachers_first", "objection_open": True,
    })
    assert r.status_code == 200, r.text
    sid = _locked_score_id(client_db, seed, exam_id)
    login(client, "t1")
    r = client.post(f"/api/exam/exams/{exam_id}/score-change-requests", json={
        "score_id": sid, "new_score": 95, "reason": "登错分",
    })
    rid = r.json()["id"]
    # 第一层教务不能批,只允许教研组长
    login(client, "jiao")
    r = client.post(
        f"/api/exam/exams/{exam_id}/score-change-requests/{rid}/decide",
        json={"decision": "通过"},
    )
    assert r.status_code == 403, r.text
    # 第一层教研组长通过,仍待审批(未生效)
    login(client, "t2")
    r = client.post(
        f"/api/exam/exams/{exam_id}/score-change-requests/{rid}/decide",
        json={"decision": "通过"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "待审批"
    db.expire_all()
    assert db.query(ExamScore).filter_by(id=sid).first().score == 88
    # 第二层教研组长不能批,只允许教务
    r = client.post(
        f"/api/exam/exams/{exam_id}/score-change-requests/{rid}/decide",
        json={"decision": "通过"},
    )
    assert r.status_code == 403, r.text
    # 第二层教务通过即生效
    login(client, "jiao")
    r = client.post(
        f"/api/exam/exams/{exam_id}/score-change-requests/{rid}/decide",
        json={"decision": "通过"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "已通过"
    assert len(r.json()["approvals"]) == 2
    db.expire_all()
    assert db.query(ExamScore).filter_by(id=sid).first().score == 95


def test_change_request_reject_is_terminal(client_db, seed):
    client, db = client_db
    exam_id = make_exam(client, seed)
    sid = _locked_score_id(client_db, seed, exam_id)
    login(client, "t1")
    r = client.post(f"/api/exam/exams/{exam_id}/score-change-requests", json={
        "score_id": sid, "new_score": 95, "reason": "登错分",
    })
    rid = r.json()["id"]
    login(client, "t2")
    r = client.post(
        f"/api/exam/exams/{exam_id}/score-change-requests/{rid}/decide",
        json={"decision": "驳回", "note": "理由不充分"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "已驳回"
    db.expire_all()
    assert db.query(ExamScore).filter_by(id=sid).first().score == 88
    # 驳回后不能再审批
    r = client.post(
        f"/api/exam/exams/{exam_id}/score-change-requests/{rid}/decide",
        json={"decision": "通过"},
    )
    assert r.status_code == 409, r.text


# ── 发布批次(KW-39) ──────────────────────────────
def test_publish_batches_and_withdraw(client_db, seed):
    client, db = client_db
    exam_id = make_exam(client, seed)
    login(client, "t1")
    r = client.post(f"/api/exam/exams/{exam_id}/publish-batches", json={
        "scope_type": "年级", "scope_value": 7,
    })
    assert r.status_code == 403, r.text  # 教师无权发布
    login(client, "adm")
    r = client.post(f"/api/exam/exams/{exam_id}/publish-batches", json={
        "scope_type": "年级", "scope_value": 7,
    })
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "已发布"  # 无 publish_at = 立即发布
    bid = r.json()["id"]
    # 同一范围重复发布
    r = client.post(f"/api/exam/exams/{exam_id}/publish-batches", json={
        "scope_type": "年级", "scope_value": 7,
    })
    assert r.status_code == 409, r.text
    # 不在参试年级内
    r = client.post(f"/api/exam/exams/{exam_id}/publish-batches", json={
        "scope_type": "年级", "scope_value": 9,
    })
    assert r.status_code == 422, r.text
    # 撤回
    r = client.post(
        f"/api/exam/exams/{exam_id}/publish-batches/{bid}/withdraw",
        json={"note": "发现数据问题"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "已撤回"
    r = client.post(
        f"/api/exam/exams/{exam_id}/publish-batches/{bid}/withdraw", json={},
    )
    assert r.status_code == 409, r.text  # 重复撤回
    # 撤回后可重新发布
    r = client.post(f"/api/exam/exams/{exam_id}/publish-batches", json={
        "scope_type": "年级", "scope_value": 7,
    })
    assert r.status_code == 201, r.text


def test_publish_scheduled_and_due(client_db, seed):
    client, db = client_db
    exam_id = make_exam(client, seed)
    login(client, "adm")
    r = client.post(f"/api/exam/exams/{exam_id}/publish-batches", json={
        "scope_type": "班级", "scope_value": seed["cls7"].id,
        "publish_at": "2030-01-01T00:00:00",
    })
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "待发布"  # 定时未到
    bid = r.json()["id"]
    r = client.post(f"/api/exam/exams/{exam_id}/publish-due")
    assert r.status_code == 200, r.text
    assert r.json() == {"published": 0}  # 未到时间,不翻转
    # 把定时改到过去,再跑 publish-due
    row = db.query(ExamPublishBatch).filter_by(id=bid).first()
    row.publish_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    db.commit()
    r = client.post(f"/api/exam/exams/{exam_id}/publish-due")
    assert r.json() == {"published": 1}
    r = client.get(f"/api/exam/exams/{exam_id}/publish-batches")
    assert r.json()["items"][0]["status"] == "已发布"


def test_publish_status_and_is_score_published(client_db, seed):
    client, db = client_db
    exam_id = make_exam(client, seed)
    login(client, "adm")
    r = client.get(f"/api/exam/exams/{exam_id}/publish-status")
    assert r.json() == {"exam_id": exam_id, "batches": [], "all_published": False}
    client.post(f"/api/exam/exams/{exam_id}/publish-batches", json={
        "scope_type": "年级", "scope_value": 7,
    })
    r = client.get(f"/api/exam/exams/{exam_id}/publish-status")
    assert r.json()["all_published"] is False  # 8 年级尚未发布
    assert publish_svc.is_score_published(db, exam_id, 7, seed["cls7"].id) is True
    assert publish_svc.is_score_published(db, exam_id, 8, seed["cls8"].id) is False
    client.post(f"/api/exam/exams/{exam_id}/publish-batches", json={
        "scope_type": "班级", "scope_value": seed["cls8"].id,
    })
    r = client.get(f"/api/exam/exams/{exam_id}/publish-status")
    assert r.json()["all_published"] is True
    assert publish_svc.is_score_published(db, exam_id, 8, seed["cls8"].id) is True


# ── 成绩异议(KW-40) ──────────────────────────────
def _objection_flow_setup(client_db, seed, exam_id):
    client, db = client_db
    enter_and_submit(
        client, seed, exam_id, seed["math"].id, seed["cls7"].id,
        [(seed["s1"].id, 88), (seed["s2"].id, 92)],
    )
    return score_id_of(db, exam_id, seed["math"].id, seed["s1"].id)


def test_objection_full_flow(client_db, seed):
    client, db = client_db
    exam_id = make_exam(client, seed)
    sid = _objection_flow_setup(client_db, seed, exam_id)
    login(client, "t1")
    r = client.post(f"/api/exam/exams/{exam_id}/objections", json={
        "score_id": sid, "content": "家长认为加分有误,请复核",
    })
    assert r.status_code == 201, r.text
    oid = r.json()["id"]
    assert r.json()["status"] == "待复核"
    assert r.json()["student_name"] == "张三"
    assert r.json()["raised_by_role"] == "教师"
    # 未复核不能直接关闭
    r = client.post(f"/api/exam/exams/{exam_id}/objections/{oid}/close")
    assert r.status_code == 409, r.text
    # 非任课教师(只教 801 班数学的 t2)不能回复 701 班异议
    login(client, "t2")
    r = client.post(f"/api/exam/exams/{exam_id}/objections/{oid}/reply", json={
        "reply": "已核对,无误",
    })
    assert r.status_code == 403, r.text
    # 任课教师回复
    login(client, "t1")
    r = client.post(f"/api/exam/exams/{exam_id}/objections/{oid}/reply", json={
        "reply": "已复核,加分无误,已向家长说明",
    })
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "已回复"
    assert r.json()["replied_by_name"] == "王老师"
    # 重复回复
    r = client.post(f"/api/exam/exams/{exam_id}/objections/{oid}/reply", json={
        "reply": "再回一次",
    })
    assert r.status_code == 409, r.text
    # 关闭
    r = client.post(f"/api/exam/exams/{exam_id}/objections/{oid}/close")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "已关闭"
    # 列表按状态过滤
    r = client.get(f"/api/exam/exams/{exam_id}/objections?status=已关闭")
    assert r.json()["total"] == 1
    r = client.get(f"/api/exam/exams/{exam_id}/objections?status=待复核")
    assert r.json()["total"] == 0


def test_objection_closed_when_disabled(client_db, seed):
    client, db = client_db
    exam_id = make_exam(client, seed)
    sid = _objection_flow_setup(client_db, seed, exam_id)
    login(client, "adm")
    r = client.put(f"/api/exam/exams/{exam_id}/publish-settings", json={
        "proofreader_role": "subject_leader", "approval_levels": 1,
        "publish_order": "teachers_first", "objection_open": False,
    })
    assert r.status_code == 200, r.text
    login(client, "t1")
    r = client.post(f"/api/exam/exams/{exam_id}/objections", json={
        "score_id": sid, "content": "请复核",
    })
    assert r.status_code == 403, r.text  # 异议入口关闭


def test_exam_status_can_advance_to_published(client_db, seed):
    """KW-39 口径:发布后考试状态可用已有状态机推进到“已发布成绩”,不另造状态。"""
    client, db = client_db
    exam_id = make_exam(client, seed)
    login(client, "adm")
    exam = db.query(Exam).filter_by(id=exam_id).first()
    assert exam.status == "草稿"
    for nxt in ["已发布", "进行中", "成绩处理中", "已发布成绩"]:
        r = client.post(f"/api/exam/exams/{exam_id}/status", json={
            "to_status": nxt,
        })
        assert r.status_code == 200, r.text
    db.expire_all()
    assert db.query(Exam).filter_by(id=exam_id).first().status == "已发布成绩"
