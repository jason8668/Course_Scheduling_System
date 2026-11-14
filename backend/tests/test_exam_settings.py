"""考务地基测试(KW-06~07):学科分值设置、考号编排规则与生成。

本文件自带 app fixture(挂 auth + exam_students 路由),因为
conftest 的 env 尚未接线新路由(接线由协调员统一做,见汇报)。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import auth as auth_api
from app.api import exam_students as exam_api
from app.core.db import Base, get_db
from app.models.audit import AuditLog
from app.models.basedata import ClassUnit, Subject, Teacher
from app.models.exam_foundation import ExamNumberRule, Student, SubjectScoreSetting
from app.models.exam_scopes import SubjectLeader
from app.models.semester import Semester
from app.models.user import Role, UserGradeScope
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
    leader = make_user(db, "nzb", PW, roles=[Role.director])
    db.add(UserGradeScope(user_id=leader.id, grade=7))
    t1user = make_user(db, "t1", PW, roles=[Role.teacher])
    t2user = make_user(db, "t2", PW, roles=[Role.teacher])
    t1 = Teacher(semester_id=sem.id, name="王老师", user_id=t1user.id)
    t2 = Teacher(semester_id=sem.id, name="李老师", user_id=t2user.id)
    db.add_all([t1, t2])
    db.flush()
    db.add(SubjectLeader(semester_id=sem.id, teacher_id=t1.id, subject_id=math.id))
    s1 = Student(semester_id=sem.id, class_unit_id=cls7.id, student_no="20260102", name="张三", gender="男")
    s2 = Student(semester_id=sem.id, class_unit_id=cls7.id, student_no="20260101", name="李四", gender="女")
    s3 = Student(semester_id=sem.id, class_unit_id=cls7.id, student_no="20260103", name="王五", gender="男", status="休学")
    s4 = Student(semester_id=sem.id, class_unit_id=cls8.id, student_no="20260201", name="赵六", gender="男")
    db.add_all([s1, s2, s3, s4])
    db.commit()
    return {
        "sem": sem, "math": math, "chinese": chinese,
        "cls7": cls7, "cls8": cls8,
        "admin": admin, "academic": academic, "leader": leader,
        "t1": t1user, "t2": t2user,
        "s1": s1, "s2": s2, "s3": s3, "s4": s4,
    }


def login(client, username):
    r = client.post("/api/auth/login", json={"username": username, "password": PW})
    assert r.status_code == 200, r.text


# ── KW-06 学科分值 ──────────────────────────────
def test_subject_settings_defaults(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    items = client.get(f"/api/exam/subject-settings?semester_id={seed['sem'].id}").json()["items"]
    assert len(items) == 2
    by_name = {i["subject_name"]: i for i in items}
    assert by_name["数学"] == {
        "subject_id": seed["math"].id, "subject_name": "数学",
        "full_score": 100, "pass_line": 60, "excellent_line": 85,
        "counts_toward_total": True, "conversion_ratio": 1.0,
    }


def test_subject_settings_batch_upsert_and_audit(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    sem = seed["sem"].id
    r = client.put("/api/exam/subject-settings", json={
        "semester_id": sem,
        "settings": [
            {"subject_id": seed["math"].id, "full_score": 120, "pass_line": 72,
             "excellent_line": 102, "counts_toward_total": True, "conversion_ratio": 1.0},
            {"subject_id": seed["chinese"].id, "full_score": 100, "pass_line": 60,
             "excellent_line": 85, "counts_toward_total": False, "conversion_ratio": 0.5},
        ],
    })
    assert r.status_code == 200, r.text
    items = {i["subject_name"]: i for i in r.json()["items"]}
    assert items["数学"]["full_score"] == 120
    assert items["语文"]["counts_toward_total"] is False
    assert items["语文"]["conversion_ratio"] == 0.5
    assert db.query(SubjectScoreSetting).count() == 2
    assert db.query(AuditLog).filter_by(action="exam_subject_setting_update").count() == 1
    # 再改一次只改数学:语文的设置不被覆盖
    client.put("/api/exam/subject-settings", json={
        "semester_id": sem,
        "settings": [
            {"subject_id": seed["math"].id, "full_score": 150, "pass_line": 90,
             "excellent_line": 127, "counts_toward_total": True, "conversion_ratio": 1.0},
        ],
    })
    items = client.get(f"/api/exam/subject-settings?semester_id={sem}").json()["items"]
    by_name = {i["subject_name"]: i for i in items}
    assert by_name["数学"]["full_score"] == 150
    assert by_name["语文"]["full_score"] == 100
    assert by_name["语文"]["counts_toward_total"] is False


def test_subject_settings_validation(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    sem = seed["sem"].id
    base = {"subject_id": seed["math"].id, "full_score": 100, "pass_line": 60,
            "excellent_line": 85, "counts_toward_total": True, "conversion_ratio": 1.0}
    # 及格线高于满分
    bad = dict(base, pass_line=120)
    assert client.put("/api/exam/subject-settings", json={
        "semester_id": sem, "settings": [bad]}).status_code == 400
    # 及格线高于优秀线
    bad = dict(base, pass_line=90, excellent_line=85)
    assert client.put("/api/exam/subject-settings", json={
        "semester_id": sem, "settings": [bad]}).status_code == 400
    # 跨学期/不存在的科目
    bad = dict(base, subject_id=99999)
    assert client.put("/api/exam/subject-settings", json={
        "semester_id": sem, "settings": [bad]}).status_code == 400
    assert db.query(SubjectScoreSetting).count() == 0


def test_subject_leader_only_own_subject(client_db, seed):
    client, db = client_db
    login(client, "t1")  # 数学教研组长
    sem = seed["sem"].id
    math_row = {"subject_id": seed["math"].id, "full_score": 120, "pass_line": 72,
                "excellent_line": 102, "counts_toward_total": True, "conversion_ratio": 1.0}
    assert client.put("/api/exam/subject-settings", json={
        "semester_id": sem, "settings": [math_row]}).status_code == 200
    chinese_row = {"subject_id": seed["chinese"].id, "full_score": 120, "pass_line": 72,
                   "excellent_line": 102, "counts_toward_total": True, "conversion_ratio": 1.0}
    assert client.put("/api/exam/subject-settings", json={
        "semester_id": sem, "settings": [chinese_row]}).status_code == 403
    # 普通教师(非组长)一律 403
    login(client, "t2")
    assert client.put("/api/exam/subject-settings", json={
        "semester_id": sem, "settings": [math_row]}).status_code == 403


# ── KW-07 考号规则 ──────────────────────────────
def test_exam_number_rule_default_and_put(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    sem = seed["sem"].id
    body = client.get(f"/api/exam/exam-number-rule?semester_id={sem}&grade=7").json()
    assert body == {"semester_id": sem, "grade": 7, "rule_type": "by_student_no"}
    r = client.put("/api/exam/exam-number-rule", json={
        "semester_id": sem, "grade": 7, "rule_type": "sequential",
    })
    assert r.status_code == 200, r.text
    assert r.json()["rule_type"] == "sequential"
    assert db.query(ExamNumberRule).count() == 1
    assert db.query(AuditLog).filter_by(action="exam_number_rule_update").count() == 1
    # 全校通用规则(grade 为空)与年级规则并存
    r = client.put("/api/exam/exam-number-rule", json={
        "semester_id": sem, "grade": None, "rule_type": "by_student_no",
    })
    assert r.status_code == 200, r.text
    assert db.query(ExamNumberRule).count() == 2
    # 无效类型 400
    assert client.put("/api/exam/exam-number-rule", json={
        "semester_id": sem, "grade": 7, "rule_type": "random",
    }).status_code == 400


def test_generate_by_student_no(client_db, seed):
    client, db = client_db
    login(client, "adm")
    sem = seed["sem"].id
    r = client.post("/api/exam/exam-number-rule/generate", json={
        "semester_id": sem, "grade": 7,
    })
    assert r.status_code == 200, r.text
    assert r.json() == {"generated": 2, "warning": ""}  # 休学的王五不编
    db.expire_all()  # API 用另一 session 写库,本 session 须刷新缓存再读
    assert db.get(Student, seed["s1"].id).exam_no == "20260102"
    assert db.get(Student, seed["s2"].id).exam_no == "20260101"
    assert db.get(Student, seed["s3"].id).exam_no is None
    assert db.get(Student, seed["s4"].id).exam_no is None  # 8 年级不动
    assert db.query(AuditLog).filter_by(action="exam_number_generate").count() == 1


def test_generate_sequential(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    sem = seed["sem"].id
    client.put("/api/exam/exam-number-rule", json={
        "semester_id": sem, "grade": 7, "rule_type": "sequential",
    })
    r = client.post("/api/exam/exam-number-rule/generate", json={
        "semester_id": sem, "grade": 7,
    })
    assert r.json() == {"generated": 2, "warning": ""}
    db.expire_all()  # API 用另一 session 写库,本 session 须刷新缓存再读
    # 按班名+学号排序:李四(20260101)->070001,张三(20260102)->070002
    assert db.get(Student, seed["s2"].id).exam_no == "070001"
    assert db.get(Student, seed["s1"].id).exam_no == "070002"


def test_generate_s_shape_warns_without_scores(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    sem = seed["sem"].id
    client.put("/api/exam/exam-number-rule", json={
        "semester_id": sem, "grade": 7, "rule_type": "s_shape",
    })
    r = client.post("/api/exam/exam-number-rule/generate", json={
        "semester_id": sem, "grade": 7,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["generated"] == 2
    assert body["warning"] == "暂无上次成绩，暂按学号顺序编排"
    db.expire_all()  # API 用另一 session 写库,本 session 须刷新缓存再读
    # 暂按学号顺序编排:学号最小的先编
    assert db.get(Student, seed["s2"].id).exam_no == "070001"
    assert db.get(Student, seed["s1"].id).exam_no == "070002"


def test_generate_forbidden_for_teacher(client_db, seed):
    client, db = client_db
    login(client, "t1")
    assert client.post("/api/exam/exam-number-rule/generate", json={
        "semester_id": seed["sem"].id, "grade": 7,
    }).status_code == 403
    assert client.put("/api/exam/exam-number-rule", json={
        "semester_id": seed["sem"].id, "grade": 7, "rule_type": "sequential",
    }).status_code == 403
