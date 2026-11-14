"""成绩单与查询测试(KW-52~56):班级成绩单含排名、个人成绩单家长版默认不含
年级排名、教师端范围限定、学生只能看自己、家长只能看关联孩子、未发布 403、
teachers_first 下家长须等状态到已发布成绩、账号开通幂等与初始口令只返回一次、
重置口令后须改密、成绩册导出 200 且为 Excel、越权 403。

本文件自带 app fixture(挂 auth + exam + exam_scores + exam_publish +
exam_reports 路由),因为 conftest 的 env 尚未接线新路由(接线由协调员统一做,见汇报)。
"""

from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import auth as auth_api
from app.api import exam as exam_api
from app.api import exam_publish as publish_api
from app.api import exam_reports as reports_api
from app.api import exam_scores as scores_api
from app.core.db import Base, get_db
from app.models.assignment import (
    AssignmentTeacher,
    CourseAssignment,
    SchedulingUnit,
    SchedulingUnitMember,
)
# noqa: F401 仅为建表:本批新表与发布批次表须先 import 对应模型,
# Base.metadata.create_all 才会建这些表。
from app.models import exam_publish, exam_reports  # noqa: F401
from app.models.basedata import ClassUnit, Subject, Teacher
from app.models.exam_foundation import ParentContact, Student
from app.models.semester import Semester
from app.models.user import Role
from tests.conftest import make_user

PW = "password123"
MONDAY = "2026-11-16"  # 周一

# 当前考试成绩(数学/语文,满分各 100):
# s1 90/80=170, s2 80/80=160, s3 80/60=140, s4 60/40=100,
# s5 70/70=140, s6 缺考/50=50(数学缺考默认不计入)。
CURRENT_SCORES = {
    "s1": (90, 80), "s2": (80, 80), "s3": (80, 60),
    "s4": (60, 40), "s5": (70, 70), "s6": (None, 50),
}
# 年级排名 dense:170/160/140/140/100/50 -> 1/2/3/3/4/5
GRADE_RANKS = {
    "20260101": 1, "20260102": 2, "20260103": 3,
    "20260201": 3, "20260104": 4, "20260202": 5,
}
# 701 班排名:s1 1, s2 2, s3 3, s4 4;702 班:s5 1, s6 2。
CLASS_RANKS_701 = {
    "20260101": 1, "20260102": 2, "20260103": 3, "20260104": 4,
}


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
    db.add_all([math, chinese, cls701, cls702])
    db.flush()
    admin = make_user(db, "adm", PW, roles=[Role.admin])
    academic = make_user(db, "jiao", PW, roles=[Role.director])
    t1user = make_user(db, "t1", PW, roles=[Role.teacher])
    t2user = make_user(db, "t2", PW, roles=[Role.teacher])
    t1 = Teacher(semester_id=sem.id, name="王老师", user_id=t1user.id)
    t2 = Teacher(semester_id=sem.id, name="李老师", user_id=t2user.id)
    db.add_all([t1, t2])
    db.flush()
    # t1 是 701 班班主任,教 701 班数学;t2 教 702 班数学。
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
    # s1 与 s2 同一家长手机号(只建一个家长账号,关联两个孩子);
    # s5 另有一个家长。
    db.add_all([
        ParentContact(student_id=s1.id, name="张父", relation="父亲", phone="13800000001"),
        ParentContact(student_id=s2.id, name="张母", relation="母亲", phone="13800000001"),
        ParentContact(student_id=s5.id, name="王父", relation="父亲", phone="13800000005"),
    ])
    db.commit()
    return {
        "sem": sem, "math": math, "chinese": chinese,
        "cls701": cls701, "cls702": cls702,
        "admin": admin, "academic": academic,
        "t1": t1user, "t2": t2user, "t1t": t1, "t2t": t2,
        "s1": s1, "s2": s2, "s3": s3, "s4": s4, "s5": s5, "s6": s6,
    }


def login(client, username, password=PW):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r


def make_exam(client, seed, name="七年级 11 月月考", exam_type="月考"):
    r = client.post("/api/exam/exams", json={
        "semester_id": seed["sem"].id, "name": name,
        "exam_type": exam_type, "grades": [7], "description": "",
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


def setup_exam(client, seed, name="七年级 11 月月考", exam_type="月考"):
    """建考 + 数学/语文日程(满分各 100)+ 参试名单(6 人)。"""
    eid = make_exam(client, seed, name, exam_type)
    r = client.put(f"/api/exam/exams/{eid}/subjects", json={"subjects": [
        {"subject_id": seed["math"].id, "exam_date": MONDAY,
         "start_time": "08:00", "end_time": "09:30", "full_score": 100},
        {"subject_id": seed["chinese"].id, "exam_date": MONDAY,
         "start_time": "10:00", "end_time": "11:30", "full_score": 100},
    ]})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/exam/exams/{eid}/participants/generate")
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 6
    return eid


def enter_scores(client, seed, eid, table):
    """table:{s1..s6: (数学分或 None, 语文分)};None 表示该科缺考。"""
    for subject_key, idx in (("math", 0), ("chinese", 1)):
        entries = []
        for skey, pair in table.items():
            score = pair[idx]
            entry = {"student_id": seed[skey].id}
            if score is None:
                entry["status"] = "缺考"
            else:
                entry["score"] = score
            entries.append(entry)
        r = client.put(f"/api/exam/exams/{eid}/scores", json={
            "subject_id": seed[subject_key].id, "scores": entries,
        })
        assert r.status_code == 200, r.text


def setup_scored_exam(client, seed, name="七年级 11 月月考", table=CURRENT_SCORES):
    eid = setup_exam(client, seed, name)
    enter_scores(client, seed, eid, table)
    return eid


def advance_to_published_scores(client, eid):
    for st in ("已发布", "进行中", "成绩处理中", "已发布成绩"):
        r = client.post(f"/api/exam/exams/{eid}/status", json={"to_status": st})
        assert r.status_code == 200, r.text


def publish_class(client, eid, class_unit_id):
    r = client.post(f"/api/exam/exams/{eid}/publish-batches", json={
        "scope_type": "班级", "scope_value": class_unit_id,
    })
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "已发布"


def set_publish_order(client, eid, order):
    r = client.put(f"/api/exam/exams/{eid}/publish-settings", json={
        "proofreader_role": "subject_leader", "approval_levels": 1,
        "publish_order": order, "objection_open": True,
    })
    assert r.status_code == 200, r.text


def provision(client, seed):
    r = client.post(f"/api/exam/accounts/provision?semester_id={seed['sem'].id}")
    assert r.status_code == 200, r.text
    return r.json()


# ── KW-52 班级成绩单 ──────────────────────────────
def test_class_report_card_with_ranks(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_scored_exam(client, seed)
    publish_class(client, eid, seed["cls701"].id)
    body = client.get(
        f"/api/exam/exams/{eid}/report-cards/class"
        f"?class_unit_id={seed['cls701'].id}"
    ).json()
    assert body["class_name"] == "701"
    assert len(body["students"]) == 4
    by_no = {s["student_no"]: s for s in body["students"]}
    assert by_no["20260101"]["total"] == 170
    assert by_no["20260101"]["class_rank"] == 1
    assert by_no["20260101"]["grade_rank"] == 1
    assert by_no["20260103"]["class_rank"] == 3
    assert by_no["20260103"]["grade_rank"] == 3
    subs = {s["subject_name"]: s for s in by_no["20260101"]["subjects"]}
    assert subs["数学"]["score"] == 90 and subs["数学"]["status"] == "正常"
    assert subs["语文"]["score"] == 80
    # 缺考学生:数学缺考,总分只计语文 50 分。
    login(client, "adm")
    publish_class(client, eid, seed["cls702"].id)
    body = client.get(
        f"/api/exam/exams/{eid}/report-cards/class"
        f"?class_unit_id={seed['cls702'].id}"
    ).json()
    by_no = {s["student_no"]: s for s in body["students"]}
    assert by_no["20260202"]["total"] == 50
    assert by_no["20260202"]["class_rank"] == 2
    assert by_no["20260202"]["grade_rank"] == 5
    subs = {s["subject_name"]: s for s in by_no["20260202"]["subjects"]}
    assert subs["数学"]["score"] is None and subs["数学"]["status"] == "缺考"


def test_class_report_card_homeroom_only(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_scored_exam(client, seed)
    publish_class(client, eid, seed["cls701"].id)
    publish_class(client, eid, seed["cls702"].id)
    # t1 是 701 班主任,能看本班。
    login(client, "t1")
    r = client.get(
        f"/api/exam/exams/{eid}/report-cards/class"
        f"?class_unit_id={seed['cls701'].id}"
    )
    assert r.status_code == 200, r.text
    # t1 不是 702 班主任,不能看 702 班成绩单。
    r = client.get(
        f"/api/exam/exams/{eid}/report-cards/class"
        f"?class_unit_id={seed['cls702'].id}"
    )
    assert r.status_code == 403, r.text
    # t2 不是 701 班主任,也不能看。
    login(client, "t2")
    r = client.get(
        f"/api/exam/exams/{eid}/report-cards/class"
        f"?class_unit_id={seed['cls701'].id}"
    )
    assert r.status_code == 403, r.text


# ── KW-53 个人成绩单 ──────────────────────────────
def test_student_report_card_full_for_teacher(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_scored_exam(client, seed)
    publish_class(client, eid, seed["cls701"].id)
    # 教师完整版含排名。
    login(client, "t1")
    body = client.get(
        f"/api/exam/exams/{eid}/report-cards/student"
        f"?student_id={seed['s1'].id}"
    ).json()
    assert body["student_name"] == "张三"
    assert body["class_name"] == "701"
    assert body["total"] == 170
    assert body["class_rank"] == 1 and body["grade_rank"] == 1
    # t2 教 702 班数学,看不到 701 班学生。
    login(client, "t2")
    r = client.get(
        f"/api/exam/exams/{eid}/report-cards/student"
        f"?student_id={seed['s1'].id}"
    )
    assert r.status_code == 403, r.text


def test_report_settings_default_and_update(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_scored_exam(client, seed)
    body = client.get(f"/api/exam/exams/{eid}/report-settings").json()
    assert body == {
        "exam_id": eid,
        "parent_show_grade_rank": False,
        "parent_show_class_rank": False,
    }
    r = client.put(f"/api/exam/exams/{eid}/report-settings", json={
        "parent_show_grade_rank": True, "parent_show_class_rank": True,
    })
    assert r.status_code == 200, r.text
    assert r.json()["parent_show_grade_rank"] is True
    assert r.json()["parent_show_class_rank"] is True
    # 教师无权改设置。
    login(client, "t1")
    r = client.put(f"/api/exam/exams/{eid}/report-settings", json={
        "parent_show_grade_rank": False, "parent_show_class_rank": False,
    })
    assert r.status_code == 403, r.text


# ── KW-54 教师端成绩查询 ──────────────────────────────
def test_teacher_scores_scope(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_scored_exam(client, seed)
    publish_class(client, eid, seed["cls701"].id)
    publish_class(client, eid, seed["cls702"].id)
    # t1 教 701 班数学、是 701 班主任:不筛科目时看 701 班全部科目(4 人 x 2 科)。
    login(client, "t1")
    body = client.get(f"/api/exam/exams/{eid}/teacher-scores").json()
    assert body["total"] == 8
    assert {(i["student_no"], i["subject_name"]) for i in body["items"]} == {
        (no, subj) for no in
        ("20260101", "20260102", "20260103", "20260104")
        for subj in ("数学", "语文")
    }
    # t1 筛语文:班主任可看本班全部科目,只出 701 班语文 4 行。
    body = client.get(
        f"/api/exam/exams/{eid}/teacher-scores?subject_id={seed['chinese'].id}"
    ).json()
    assert body["total"] == 4
    assert all(i["subject_name"] == "语文" for i in body["items"])
    # t2 只教 702 班数学:不筛科目只出 702 班数学 2 行;筛语文 403。
    login(client, "t2")
    body = client.get(f"/api/exam/exams/{eid}/teacher-scores").json()
    assert body["total"] == 2
    assert all(i["subject_name"] == "数学" for i in body["items"])
    assert all(i["class_name"] == "702" for i in body["items"])
    r = client.get(
        f"/api/exam/exams/{eid}/teacher-scores?subject_id={seed['chinese'].id}"
    )
    assert r.status_code == 403, r.text
    # t2 显式筛 701 班 403(不在可见班级内)。
    r = client.get(
        f"/api/exam/exams/{eid}/teacher-scores"
        f"?class_unit_id={seed['cls701'].id}"
    )
    assert r.status_code == 403, r.text
    # q 按姓名筛。
    body = client.get(
        f"/api/exam/exams/{eid}/teacher-scores?q=王五"
    ).json()
    assert body["total"] == 1
    assert body["items"][0]["student_name"] == "王五"
    assert body["items"][0]["total"] == 140
    assert body["items"][0]["grade_rank"] == 3


def test_teacher_scores_unpublished_class_hidden(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_scored_exam(client, seed)
    publish_class(client, eid, seed["cls701"].id)
    # 702 班未发布:t2 不筛时看不到任何行;显式筛 702 班 403。
    login(client, "t2")
    body = client.get(f"/api/exam/exams/{eid}/teacher-scores").json()
    assert body["total"] == 0
    r = client.get(
        f"/api/exam/exams/{eid}/teacher-scores"
        f"?class_unit_id={seed['cls702'].id}"
    )
    assert r.status_code == 403, r.text
    # 教务不受发布限制。
    login(client, "jiao")
    body = client.get(f"/api/exam/exams/{eid}/teacher-scores").json()
    assert body["total"] == 12


# ── KW-55 学生/家长账号与自助查询 ──────────────────────────────
def test_provision_idempotent_and_password_once(client_db, seed):
    client, db = client_db
    login(client, "adm")
    first = provision(client, seed)
    assert first["students_created"] == 6
    assert first["parents_created"] == 2
    creds = {(c["username"], c["role"]): c for c in first["credentials"]}
    assert len(creds) == 8
    # 学生账号用户名=学号;家长账号用户名=手机号,同一手机号只建一个。
    assert ("20260101", "student") in creds
    assert ("13800000001", "parent") in creds
    assert ("13800000005", "parent") in creds
    assert creds[("13800000001", "parent")]["student_name"] == "张三、李四"
    assert all(len(c["initial_password"]) >= 8 for c in first["credentials"])
    # 第二次开通:幂等,新建 0 个,初始口令不再返回。
    second = provision(client, seed)
    assert second["students_created"] == 0
    assert second["parents_created"] == 0
    assert second["credentials"] == []
    # 账号清单:按学期查,学生 6 个、家长 2 个。
    body = client.get(
        f"/api/exam/accounts?semester_id={seed['sem'].id}"
    ).json()
    assert body["total"] == 8
    body = client.get(
        f"/api/exam/accounts?semester_id={seed['sem'].id}&role=parent"
    ).json()
    assert body["total"] == 2
    parent = next(i for i in body["items"] if i["username"] == "13800000001")
    assert parent["student_names"] == ["张三", "李四"]
    assert parent["must_change_password"] is True
    # 教师无权开通与查看账号。
    login(client, "t1")
    r = client.post(f"/api/exam/accounts/provision?semester_id={seed['sem'].id}")
    assert r.status_code == 403, r.text
    r = client.get("/api/exam/accounts")
    assert r.status_code == 403, r.text


def test_student_login_must_change_password_first(client_db, seed):
    client, db = client_db
    login(client, "adm")
    first = provision(client, seed)
    pw = next(
        c["initial_password"] for c in first["credentials"]
        if c["username"] == "20260101"
    )
    # 学生走同一登录入口,初始口令能登录,但须先改密才能调功能接口。
    login(client, "20260101", password=pw)
    me = client.get("/api/auth/me").json()
    assert me["roles"] == ["student"]
    assert me["must_change_password"] is True
    r = client.get("/api/exam/my-scores?exam_id=1")
    assert r.status_code == 403, r.text
    # 改密后恢复正常。
    r = client.post("/api/auth/change-password", json={
        "old_password": pw, "new_password": "newpass123",
    })
    assert r.status_code == 200, r.text
    assert r.json()["must_change_password"] is False


def test_my_scores_parent_default_no_grade_rank(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_scored_exam(client, seed)
    first = provision(client, seed)
    parent_pw = next(
        c["initial_password"] for c in first["credentials"]
        if c["username"] == "13800000001"
    )
    # 未发布:家长 403。
    login(client, "13800000001", password=parent_pw)
    client.post("/api/auth/change-password", json={
        "old_password": parent_pw, "new_password": "parentpass1",
    })
    r = client.get(f"/api/exam/my-scores?exam_id={eid}")
    assert r.status_code == 403, r.text
    # 发布 701 班、状态推进到已发布成绩后可见;家长有两个孩子,出两行。
    login(client, "adm")
    publish_class(client, eid, seed["cls701"].id)
    advance_to_published_scores(client, eid)
    login(client, "13800000001", password="parentpass1")
    body = client.get(f"/api/exam/my-scores?exam_id={eid}").json()
    assert len(body["items"]) == 2
    by_no = {i["student_no"]: i for i in body["items"]}
    assert by_no["20260101"]["total"] == 170
    # 家长版默认不含年级排名与班级排名。
    assert "grade_rank" not in by_no["20260101"]
    assert "class_rank" not in by_no["20260101"]
    # 个人成绩单家长版同样默认不含年级排名。
    body = client.get(
        f"/api/exam/my-report-card?exam_id={eid}&student_id={seed['s1'].id}"
    ).json()
    assert body["student_name"] == "张三"
    assert body["total"] == 170
    assert "grade_rank" not in body
    # 教务把两项都打开后,家长版出现排名。
    login(client, "adm")
    client.put(f"/api/exam/exams/{eid}/report-settings", json={
        "parent_show_grade_rank": True, "parent_show_class_rank": True,
    })
    login(client, "13800000001", password="parentpass1")
    body = client.get(
        f"/api/exam/my-report-card?exam_id={eid}&student_id={seed['s1'].id}"
    ).json()
    assert body["grade_rank"] == 1 and body["class_rank"] == 1


def test_student_only_self_and_parent_only_linked(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_scored_exam(client, seed)
    publish_class(client, eid, seed["cls701"].id)
    publish_class(client, eid, seed["cls702"].id)
    advance_to_published_scores(client, eid)
    first = provision(client, seed)
    pw_of = {
        c["username"]: c["initial_password"] for c in first["credentials"]
    }
    # 学生本人:只能看自己,看他人 403;my-scores 只有自己一行。
    login(client, "20260101", password=pw_of["20260101"])
    client.post("/api/auth/change-password", json={
        "old_password": pw_of["20260101"], "new_password": "stupass123",
    })
    r = client.get(
        f"/api/exam/my-report-card?exam_id={eid}&student_id={seed['s2'].id}"
    )
    assert r.status_code == 403, r.text
    body = client.get(f"/api/exam/my-scores?exam_id={eid}").json()
    assert len(body["items"]) == 1
    assert body["items"][0]["student_no"] == "20260101"
    # 家长(13800000005,只关联王五):看张三 403,看王五 200。
    login(client, "13800000005", password=pw_of["13800000005"])
    client.post("/api/auth/change-password", json={
        "old_password": pw_of["13800000005"], "new_password": "parpass12",
    })
    r = client.get(
        f"/api/exam/my-report-card?exam_id={eid}&student_id={seed['s1'].id}"
    )
    assert r.status_code == 403, r.text
    body = client.get(
        f"/api/exam/my-report-card?exam_id={eid}&student_id={seed['s5'].id}"
    ).json()
    assert body["student_name"] == "王五"
    # 教师调学生自助接口 403。
    login(client, "t1")
    r = client.get(f"/api/exam/my-scores?exam_id={eid}")
    assert r.status_code == 403, r.text
    r = client.get(
        f"/api/exam/my-report-card?exam_id={eid}&student_id={seed['s1'].id}"
    )
    assert r.status_code == 403, r.text


def test_teachers_first_requires_published_status(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_scored_exam(client, seed)
    first = provision(client, seed)
    parent_pw = next(
        c["initial_password"] for c in first["credentials"]
        if c["username"] == "13800000001"
    )
    login(client, "13800000001", password=parent_pw)
    client.post("/api/auth/change-password", json={
        "old_password": parent_pw, "new_password": "parentpass1",
    })
    # 默认 teachers_first:批次已发布、状态未到已发布成绩,家长仍 403。
    login(client, "adm")
    publish_class(client, eid, seed["cls701"].id)
    login(client, "13800000001", password="parentpass1")
    r = client.get(f"/api/exam/my-scores?exam_id={eid}")
    assert r.status_code == 403, r.text
    # 状态推进到已发布成绩后可见。
    login(client, "adm")
    advance_to_published_scores(client, eid)
    login(client, "13800000001", password="parentpass1")
    r = client.get(f"/api/exam/my-scores?exam_id={eid}")
    assert r.status_code == 200, r.text


def test_sync_order_visible_without_published_status(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_scored_exam(client, seed)
    first = provision(client, seed)
    parent_pw = next(
        c["initial_password"] for c in first["credentials"]
        if c["username"] == "13800000001"
    )
    login(client, "13800000001", password=parent_pw)
    client.post("/api/auth/change-password", json={
        "old_password": parent_pw, "new_password": "parentpass1",
    })
    # sync:只要批次覆盖即可见,状态未到已发布成绩也不拦。
    login(client, "adm")
    set_publish_order(client, eid, "sync")
    publish_class(client, eid, seed["cls701"].id)
    login(client, "13800000001", password="parentpass1")
    r = client.get(f"/api/exam/my-scores?exam_id={eid}")
    assert r.status_code == 200, r.text
    assert len(r.json()["items"]) == 2


def test_reset_password_requires_change(client_db, seed):
    client, db = client_db
    login(client, "adm")
    first = provision(client, seed)
    pw = next(
        c["initial_password"] for c in first["credentials"]
        if c["username"] == "20260101"
    )
    # 学生先改掉初始口令。
    login(client, "20260101", password=pw)
    client.post("/api/auth/change-password", json={
        "old_password": pw, "new_password": "stupass123",
    })
    # 教务重置口令后,旧口令失效、新口令能登录且须改密。
    login(client, "adm")
    body = client.get(
        f"/api/exam/accounts?semester_id={seed['sem'].id}&role=student"
    ).json()
    uid = next(
        i["user_id"] for i in body["items"] if i["username"] == "20260101"
    )
    r = client.post(
        f"/api/exam/accounts/{uid}/reset-password",
        json={"new_password": "resetpass1"},
    )
    assert r.status_code == 200, r.text
    r = client.post("/api/auth/login", json={
        "username": "20260101", "password": "stupass123",
    })
    assert r.status_code == 401, r.text
    login(client, "20260101", password="resetpass1")
    assert client.get("/api/auth/me").json()["must_change_password"] is True
    r = client.get("/api/exam/my-scores?exam_id=1")
    assert r.status_code == 403, r.text
    # 重置不存在的账号 404;教师无权重置。
    login(client, "adm")
    r = client.post(
        "/api/exam/accounts/99999/reset-password",
        json={"new_password": "resetpass1"},
    )
    assert r.status_code == 404, r.text
    login(client, "t1")
    r = client.post(
        f"/api/exam/accounts/{uid}/reset-password",
        json={"new_password": "resetpass1"},
    )
    assert r.status_code == 403, r.text


# ── KW-56 成绩归档表导出 ──────────────────────────────
def test_grade_book_export(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_scored_exam(client, seed)
    r = client.get(f"/api/exam/exams/{eid}/grade-book/export")
    assert r.status_code == 200, r.text
    assert "spreadsheetml.sheet" in r.headers["content-type"]
    wb = load_workbook(BytesIO(r.content))
    ws = wb["成绩册"]
    headers = [c.value for c in ws[1]]
    assert headers == [
        "学号", "姓名", "班级", "数学", "语文", "总分", "班级排名", "年级排名",
    ]
    rows = {r[0]: r for r in ws.iter_rows(min_row=2, values_only=True)}
    assert len(rows) == 6
    assert rows["20260101"][3] == 90 and rows["20260101"][4] == 80
    assert rows["20260101"][5] == 170
    assert rows["20260101"][6] == 1 and rows["20260101"][7] == 1
    assert rows["20260202"][3] is None  # 缺考无原始分
    assert rows["20260202"][5] == 50
    assert rows["20260202"][7] == 5
    # 教师无权导出成绩册。
    login(client, "t1")
    r = client.get(f"/api/exam/exams/{eid}/grade-book/export")
    assert r.status_code == 403, r.text
