"""阅卷与成绩录入测试(KW-30~35):分工、录入权限、超满分、小分求和、导入原子性、
缺考作弊免考、进度看板三态、补考单独保存、S 型真按成绩排/无成绩警告全文。

本文件自带 app fixture(挂 auth + exam + exam_arrangement + exam_scores 路由),因为
conftest 的 env 尚未接线新路由(接线由协调员统一做,见汇报)。
"""

from datetime import date
from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import auth as auth_api
from app.api import exam as exam_api
from app.api import exam_arrangement as arr_api
from app.api import exam_scores as scores_api
from app.core.db import Base, get_db
from app.models.assignment import (
    AssignmentTeacher,
    CourseAssignment,
    SchedulingUnit,
    SchedulingUnitMember,
)
# noqa: F401 仅为建表:第 6 批 KW-37 锁定检查在录入/导入时查 exam_score_locks,
# 本文件须先 import 该模型,Base.metadata.create_all 才会建这张表。
from app.models import exam_publish  # noqa: F401
from app.models.audit import AuditLog
from app.models.basedata import ClassUnit, Room, Subject, Teacher
from app.models.exam_foundation import Student
from app.models.semester import Semester
from app.models.user import Role
from tests.conftest import make_user

PW = "password123"
MONDAY = "2026-11-16"  # 周一
S_SHAPE_WARNING = "暂无上次成绩，暂按学号顺序编排"


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
    app.include_router(arr_api.router, prefix="/api/exam")
    app.include_router(scores_api.router, prefix="/api/exam")
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
    r1 = Room(semester_id=sem.id, name="101 教室", capacity=30)
    r2 = Room(semester_id=sem.id, name="102 教室", capacity=30)
    db.add_all([math, chinese, cls701, cls702, r1, r2])
    db.flush()
    admin = make_user(db, "adm", PW, roles=[Role.admin])
    academic = make_user(db, "jiao", PW, roles=[Role.director])
    t1user = make_user(db, "t1", PW, roles=[Role.teacher])
    t2user = make_user(db, "t2", PW, roles=[Role.teacher])
    t1 = Teacher(semester_id=sem.id, name="王老师", user_id=t1user.id)
    t2 = Teacher(semester_id=sem.id, name="李老师", user_id=t2user.id)
    db.add_all([t1, t2])
    db.flush()
    # 配课:t1 教 701 班数学,t2 教 702 班数学;两人都不教语文。
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
    db.commit()
    return {
        "sem": sem, "math": math, "chinese": chinese,
        "cls701": cls701, "cls702": cls702, "r1": r1, "r2": r2,
        "admin": admin, "academic": academic,
        "t1": t1user, "t2": t2user, "t1t": t1, "t2t": t2,
        "s1": s1, "s2": s2, "s3": s3, "s4": s4, "s5": s5, "s6": s6,
    }


def login(client, username):
    r = client.post("/api/auth/login", json={"username": username, "password": PW})
    assert r.status_code == 200, r.text


def make_exam(client, seed, name="七年级 11 月月考", exam_type="月考"):
    r = client.post("/api/exam/exams", json={
        "semester_id": seed["sem"].id, "name": name,
        "exam_type": exam_type, "grades": [7], "description": "",
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


def setup_exam(client, seed, name="七年级 11 月月考", exam_type="月考"):
    """建考 + 数学日程(满分 100)+ 参试名单(6 人)。"""
    eid = make_exam(client, seed, name, exam_type)
    r = client.put(f"/api/exam/exams/{eid}/subjects", json={"subjects": [
        {"subject_id": seed["math"].id, "exam_date": MONDAY,
         "start_time": "08:00", "end_time": "09:30", "full_score": 100},
    ]})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/exam/exams/{eid}/participants/generate")
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 6
    return eid


def advance_to_published_scores(client, eid):
    for st in ("已发布", "进行中", "成绩处理中", "已发布成绩"):
        r = client.post(f"/api/exam/exams/{eid}/status", json={"to_status": st})
        assert r.status_code == 200, r.text


def put_scores(client, eid, subject_id, scores):
    return client.put(f"/api/exam/exams/{eid}/scores", json={
        "subject_id": subject_id, "scores": scores,
    })


def get_scores(client, eid, subject_id, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"/api/exam/exams/{eid}/scores?subject_id={subject_id}"
    if qs:
        url += "&" + qs
    return client.get(url)


def build_import_file(rows):
    """rows:数据行(学号, 姓名, 班级, 成绩, 状态);前三行为模板头。"""
    wb = Workbook()
    ws = wb.active
    ws.append(["学号", "姓名", "班级", "成绩", "状态"])
    ws.append(["必填", "仅供核对", "仅供核对", "正常必填", "选填"])
    ws.append(["20260101", "张三", "701", "88", "正常"])
    for row in rows:
        ws.append(list(row))
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── KW-30 阅卷分工 ──────────────────────────────
def test_marking_assignments_crud(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_exam(client, seed)
    body = {"subject_id": seed["math"].id, "teacher_id": seed["t1t"].id,
            "role": "阅卷组长", "scope_type": "按班", "scope_value": "701"}
    r = client.post(f"/api/exam/exams/{eid}/marking-assignments", json=body)
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "阅卷组长"
    assert r.json()["teacher_name"] == "王老师"
    assert r.json()["subject_name"] == "数学"
    mid = r.json()["id"]
    # 同一教师同一科目重复登记 409
    assert client.post(
        f"/api/exam/exams/{eid}/marking-assignments", json=body
    ).status_code == 409
    items = client.get(
        f"/api/exam/exams/{eid}/marking-assignments?subject_id={seed['math'].id}"
    ).json()
    assert items["total"] == 1
    assert client.delete(f"/api/exam/exams/{eid}/marking-assignments/{mid}").status_code == 204
    assert client.get(
        f"/api/exam/exams/{eid}/marking-assignments?subject_id={seed['math'].id}"
    ).json()["total"] == 0
    assert db.query(AuditLog).filter_by(action="exam_marking_assignment_create").count() == 1


def test_marking_assignments_teacher_forbidden(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_exam(client, seed)
    login(client, "t1")
    r = client.post(f"/api/exam/exams/{eid}/marking-assignments", json={
        "subject_id": seed["math"].id, "teacher_id": seed["t1t"].id,
        "role": "阅卷教师", "scope_type": "按题", "scope_value": "第一大题",
    })
    assert r.status_code == 403


# ── 成绩设置 ──────────────────────────────
def test_score_settings_defaults_and_update(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_exam(client, seed)
    body = client.get(f"/api/exam/exams/{eid}/score-settings").json()
    assert body == {
        "exam_id": eid, "entry_mode": "total_only", "makeup_mode": "separate",
        "cheating_score_mode": "zero", "absent_counts": False,
        "score_deadline": None,
    }
    r = client.put(f"/api/exam/exams/{eid}/score-settings", json={
        "entry_mode": "itemized", "makeup_mode": "max",
        "cheating_score_mode": "null", "absent_counts": True,
        "score_deadline": "2026-11-20T17:00:00",
    })
    assert r.status_code == 200, r.text
    assert r.json()["entry_mode"] == "itemized"
    assert r.json()["makeup_mode"] == "max"
    assert r.json()["score_deadline"] is not None
    assert client.put(f"/api/exam/exams/{eid}/score-settings", json={
        "entry_mode": "bad", "makeup_mode": "separate",
        "cheating_score_mode": "zero", "absent_counts": False,
        "score_deadline": None,
    }).status_code == 400
    login(client, "t1")
    assert client.put(f"/api/exam/exams/{eid}/score-settings", json={
        "entry_mode": "total_only", "makeup_mode": "separate",
        "cheating_score_mode": "zero", "absent_counts": False,
        "score_deadline": None,
    }).status_code == 403


# ── KW-31 录入权限与超满分 ──────────────────────────────
def test_put_scores_own_class_ok_other_class_403(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_exam(client, seed)
    # 把语文也设为本次考试科目(满分 100),供"不教本科目"越权用例使用
    r = client.put(f"/api/exam/exams/{eid}/subjects", json={"subjects": [
        {"subject_id": seed["math"].id, "exam_date": MONDAY,
         "start_time": "08:00", "end_time": "09:30", "full_score": 100},
        {"subject_id": seed["chinese"].id, "exam_date": MONDAY,
         "start_time": "10:00", "end_time": "11:30", "full_score": 100},
    ]})
    assert r.status_code == 200, r.text
    login(client, "t1")
    # t1 只教 701 数学:录 701 的分可以
    r = put_scores(client, eid, seed["math"].id, [
        {"student_id": seed["s1"].id, "score": 88},
        {"student_id": seed["s2"].id, "score": 92},
    ])
    assert r.status_code == 200, r.text
    assert r.json() == {"updated": 2}
    # 混入 702 学生(非本人班级)整批 403,且一行都不写
    r = put_scores(client, eid, seed["math"].id, [
        {"student_id": seed["s1"].id, "score": 88},
        {"student_id": seed["s5"].id, "score": 70},
    ])
    assert r.status_code == 403
    login(client, "adm")
    rows = {i["student_no"]: i for i in get_scores(client, eid, seed["math"].id).json()["items"]}
    assert rows["20260201"]["score"] is None
    # t1 不教语文:录语文 403
    login(client, "t1")
    r = put_scores(client, eid, seed["chinese"].id, [
        {"student_id": seed["s1"].id, "score": 88},
    ])
    assert r.status_code == 403
    # t2 教 702 数学:录 702 可以
    login(client, "t2")
    r = put_scores(client, eid, seed["math"].id, [
        {"student_id": seed["s5"].id, "score": 70},
    ])
    assert r.status_code == 200, r.text
    assert db.query(AuditLog).filter_by(action="exam_score_update").count() >= 2


def test_put_scores_over_full_422(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_exam(client, seed)
    r = put_scores(client, eid, seed["math"].id, [
        {"student_id": seed["s1"].id, "score": 101},
    ])
    assert r.status_code == 422
    r = put_scores(client, eid, seed["math"].id, [
        {"student_id": seed["s1"].id, "score": -1},
    ])
    assert r.status_code == 422
    # 超满分一行都不写
    assert get_scores(client, eid, seed["math"].id).json()["items"][0]["score"] is None


def test_list_scores_teacher_scope(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_exam(client, seed)
    assert put_scores(client, eid, seed["math"].id, [
        {"student_id": seed["s1"].id, "score": 88},
        {"student_id": seed["s5"].id, "score": 70},
    ]).status_code == 200
    login(client, "t1")
    body = get_scores(client, eid, seed["math"].id).json()
    assert body["total"] == 4  # 只看 701 班 4 人
    assert {i["student_no"] for i in body["items"]} == {
        "20260101", "20260102", "20260103", "20260104",
    }
    assert {i["grade"] for i in body["items"]} == {7}
    # 显式筛 702 班直接 403
    assert get_scores(
        client, eid, seed["math"].id, class_unit_id=seed["cls702"].id
    ).status_code == 403


# ── KW-31 itemized ──────────────────────────────
def test_itemized_sum_and_item_validation(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_exam(client, seed)
    client.put(f"/api/exam/exams/{eid}/score-settings", json={
        "entry_mode": "itemized", "makeup_mode": "separate",
        "cheating_score_mode": "zero", "absent_counts": False,
        "score_deadline": None,
    })
    r = client.post(f"/api/exam/exams/{eid}/score-items", json={
        "subject_id": seed["math"].id, "name": "第一大题", "max_score": 60,
    })
    assert r.status_code == 201, r.text
    item1 = r.json()["id"]
    r = client.post(f"/api/exam/exams/{eid}/score-items", json={
        "subject_id": seed["math"].id, "name": "第二大题", "max_score": 40,
    })
    assert r.status_code == 201, r.text
    item2 = r.json()["id"]
    # 同名大题 409
    assert client.post(f"/api/exam/exams/{eid}/score-items", json={
        "subject_id": seed["math"].id, "name": "第一大题", "max_score": 10,
    }).status_code == 409
    # 小分之和 90 = 总分 90,通过;总分自动等于小分之和
    r = put_scores(client, eid, seed["math"].id, [
        {"student_id": seed["s1"].id, "score": 90,
         "items": [{"item_id": item1, "value": 55}, {"item_id": item2, "value": 35}]},
    ])
    assert r.status_code == 200, r.text
    row = get_scores(client, eid, seed["math"].id).json()["items"][0]
    assert row["score"] == 90
    assert {i["name"]: i["value"] for i in row["items"]} == {"第一大题": 55, "第二大题": 35}
    # 总分与小分之和不一致 422
    r = put_scores(client, eid, seed["math"].id, [
        {"student_id": seed["s2"].id, "score": 91,
         "items": [{"item_id": item1, "value": 55}, {"item_id": item2, "value": 35}]},
    ])
    assert r.status_code == 422
    # 单题超满分 422
    r = put_scores(client, eid, seed["math"].id, [
        {"student_id": seed["s2"].id, "score": 95,
         "items": [{"item_id": item1, "value": 61}, {"item_id": item2, "value": 34}]},
    ])
    assert r.status_code == 422
    # 已有录入数据的大题删不得 409;无数据的大题可删
    assert client.delete(f"/api/exam/exams/{eid}/score-items/{item1}").status_code == 409


# ── KW-32 导入 ──────────────────────────────
def test_scores_template_and_import_ok(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_exam(client, seed)
    r = client.get(f"/api/exam/exams/{eid}/scores/template?subject_id={seed['math'].id}")
    assert r.status_code == 200, r.text
    wb = load_workbook(BytesIO(r.content))
    ws = wb.active
    assert ws.cell(row=1, column=1).value == "学号"
    assert ws.cell(row=1, column=4).value == "成绩"
    assert ws.cell(row=4, column=1).value is None  # 第 4 行起读数据,模板无数据行
    data = build_import_file([
        ("20260101", "张三", "701", 88, "正常"),
        ("20260102", "李四", "701", 92, "正常"),
        ("20260201", "王五", "702", 70, "正常"),
    ])
    r = client.post(
        f"/api/exam/exams/{eid}/scores/import?subject_id={seed['math'].id}",
        files={"file": ("scores.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"created": 3, "updated": 0, "errors": []}
    rows = {i["student_no"]: i["score"] for i in get_scores(client, eid, seed["math"].id).json()["items"]}
    assert rows["20260101"] == 88 and rows["20260201"] == 70
    # 再次导入同一学号为更新
    data = build_import_file([("20260101", "张三", "701", 90, "正常")])
    r = client.post(
        f"/api/exam/exams/{eid}/scores/import?subject_id={seed['math'].id}",
        files={"file": ("scores.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r.json() == {"created": 0, "updated": 1, "errors": []}
    assert db.query(AuditLog).filter_by(action="exam_score_import").count() == 2


def test_scores_import_errors_atomic(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_exam(client, seed)
    data = build_import_file([
        ("20260101", "张三", "701", 88, "正常"),
        ("20260102", "李四", "701", 150, "正常"),  # 超满分
        ("20269999", "无人", "701", 80, "正常"),  # 学号不在名单
        ("20260101", "张三", "701", 90, "正常"),  # 文件内重复
        ("20260103", "赵六", "701", 80, "缺考"),  # 缺考却填了分
    ])
    r = client.post(
        f"/api/exam/exams/{eid}/scores/import?subject_id={seed['math'].id}",
        files={"file": ("scores.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 0 and body["updated"] == 0
    assert len(body["errors"]) == 4
    assert {e["row"] for e in body["errors"]} == {5, 6, 7, 8}
    # 有错一行都不写:连正确的第一行也没入库
    rows = get_scores(client, eid, seed["math"].id).json()["items"]
    assert all(i["score"] is None for i in rows)


def test_scores_import_teacher_class_limit(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_exam(client, seed)
    login(client, "t1")
    data = build_import_file([
        ("20260101", "张三", "701", 88, "正常"),
        ("20260201", "王五", "702", 70, "正常"),  # 非本人班级
    ])
    r = client.post(
        f"/api/exam/exams/{eid}/scores/import?subject_id={seed['math'].id}",
        files={"file": ("scores.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 0
    assert len(r.json()["errors"]) == 1
    assert "不在你所教班级内" in r.json()["errors"][0]["message"]


# ── KW-33 缺考/作弊/免考 ──────────────────────────────
def test_special_status_marks(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_exam(client, seed)
    r = put_scores(client, eid, seed["math"].id, [
        {"student_id": seed["s1"].id, "score": 88, "status": "正常"},
        {"student_id": seed["s2"].id, "status": "缺考"},
        {"student_id": seed["s3"].id, "score": 95, "status": "作弊"},
        {"student_id": seed["s4"].id, "status": "免考"},
    ])
    assert r.status_code == 200, r.text
    rows = {i["student_no"]: i for i in get_scores(client, eid, seed["math"].id).json()["items"]}
    assert rows["20260101"]["score"] == 88 and rows["20260101"]["status"] == "正常"
    assert rows["20260102"]["score"] is None and rows["20260102"]["status"] == "缺考"
    assert rows["20260103"]["score"] == 0 and rows["20260103"]["status"] == "作弊"
    assert rows["20260104"]["score"] is None and rows["20260104"]["status"] == "免考"
    # 状态筛
    body = get_scores(client, eid, seed["math"].id, status="缺考").json()
    assert body["total"] == 1 and body["items"][0]["student_no"] == "20260102"
    # 作弊记空模式:cheating_score_mode=null 时作弊 score 为空
    client.put(f"/api/exam/exams/{eid}/score-settings", json={
        "entry_mode": "total_only", "makeup_mode": "separate",
        "cheating_score_mode": "null", "absent_counts": False,
        "score_deadline": None,
    })
    assert put_scores(client, eid, seed["math"].id, [
        {"student_id": seed["s3"].id, "status": "作弊"},
    ]).status_code == 200
    rows = {i["student_no"]: i for i in get_scores(client, eid, seed["math"].id).json()["items"]}
    assert rows["20260103"]["score"] is None and rows["20260103"]["status"] == "作弊"


# ── KW-34 进度看板 ──────────────────────────────
def test_score_progress_three_states(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_exam(client, seed)
    body = client.get(f"/api/exam/exams/{eid}/score-progress").json()
    assert len(body["subjects"]) == 1
    assert body["subjects"][0]["subject_name"] == "数学"
    by_class = {c["class_name"]: c for c in body["subjects"][0]["classes"]}
    assert by_class["701"] == {
        "class_unit_id": seed["cls701"].id, "class_name": "701", "grade": 7,
        "total": 4, "entered": 0, "submitted": 0, "status": "未开始",
    }
    assert by_class["702"]["status"] == "未开始"
    # 701 录 2 人 -> 录入中;702 仍未开始
    assert put_scores(client, eid, seed["math"].id, [
        {"student_id": seed["s1"].id, "score": 88},
        {"student_id": seed["s2"].id, "status": "缺考"},
    ]).status_code == 200
    body = client.get(f"/api/exam/exams/{eid}/score-progress").json()
    by_class = {c["class_name"]: c for c in body["subjects"][0]["classes"]}
    assert by_class["701"]["entered"] == 2 and by_class["701"]["status"] == "录入中"
    assert by_class["702"]["status"] == "未开始"
    # 701 录完并提交 -> 已提交
    assert put_scores(client, eid, seed["math"].id, [
        {"student_id": seed["s3"].id, "score": 70},
        {"student_id": seed["s4"].id, "score": 60},
    ]).status_code == 200
    r = client.post(f"/api/exam/exams/{eid}/scores/submit", json={
        "subject_id": seed["math"].id, "class_unit_id": seed["cls701"].id,
    })
    assert r.status_code == 200, r.text
    assert r.json() == {"submitted": 4}
    body = client.get(f"/api/exam/exams/{eid}/score-progress").json()
    by_class = {c["class_name"]: c for c in body["subjects"][0]["classes"]}
    assert by_class["701"]["status"] == "已提交"
    assert by_class["701"]["submitted"] == 4
    assert by_class["702"]["status"] == "未开始"


# ── KW-35 补考 ──────────────────────────────
def test_makeup_scores_separate_from_regular(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_exam(client, seed)
    assert put_scores(client, eid, seed["math"].id, [
        {"student_id": seed["s1"].id, "score": 40},
    ]).status_code == 200
    r = client.post(f"/api/exam/exams/{eid}/makeups", json={
        "name": "数学补考", "exam_date": "2026-11-20", "note": "不及格学生参加",
    })
    assert r.status_code == 201, r.text
    mid = r.json()["id"]
    r = client.put(f"/api/exam/exams/{eid}/makeups/{mid}/scores", json={
        "subject_id": seed["math"].id,
        "scores": [{"student_id": seed["s1"].id, "score": 75}],
    })
    assert r.status_code == 200, r.text
    assert r.json() == {"updated": 1}
    body = client.get(
        f"/api/exam/exams/{eid}/makeups/{mid}/scores?subject_id={seed['math'].id}"
    ).json()
    assert body["total"] == 6
    row = next(i for i in body["items"] if i["student_no"] == "20260101")
    assert row["score"] == 75
    assert row["grade"] == 7
    # 正考成绩仍为 40,不被补考覆盖(separate 口径)
    rows = {i["student_no"]: i for i in get_scores(client, eid, seed["math"].id).json()["items"]}
    assert rows["20260101"]["score"] == 40
    # 补考超满分 422;补考作弊状态不合法 422
    assert client.put(f"/api/exam/exams/{eid}/makeups/{mid}/scores", json={
        "subject_id": seed["math"].id,
        "scores": [{"student_id": seed["s1"].id, "score": 120}],
    }).status_code == 422
    assert client.put(f"/api/exam/exams/{eid}/makeups/{mid}/scores", json={
        "subject_id": seed["math"].id,
        "scores": [{"student_id": seed["s1"].id, "status": "作弊"}],
    }).status_code == 422
    # 任课教师只能录本人班级的补考成绩
    login(client, "t1")
    assert client.put(f"/api/exam/exams/{eid}/makeups/{mid}/scores", json={
        "subject_id": seed["math"].id,
        "scores": [{"student_id": seed["s5"].id, "score": 60}],
    }).status_code == 403
    # 补考场次只允许教务建,教师 403;删除后列表为空
    assert client.post(f"/api/exam/exams/{eid}/makeups", json={
        "name": "语文补考", "exam_date": "2026-11-21",
    }).status_code == 403
    login(client, "adm")
    assert client.delete(f"/api/exam/exams/{eid}/makeups/{mid}").status_code == 204
    assert client.get(f"/api/exam/exams/{eid}/makeups").json()["total"] == 0


# ── S 型编排接真实成绩 ──────────────────────────────
def _setup_rooms_and_rule(client, seed, eid, mode="s_shape", max_per_room=3):
    for room in (seed["r1"], seed["r2"]):
        rr = client.post(f"/api/exam/exams/{eid}/rooms", json={
            "room_id": room.id, "capacity": 3,
        })
        assert rr.status_code == 201, rr.text
    r = client.put(f"/api/exam/exams/{eid}/arrangement-rule", json={
        "mode": mode, "scatter_same_class": False, "max_per_room": max_per_room,
    })
    assert r.status_code == 200, r.text


def test_s_shape_with_previous_scores_snakes(client_db, seed):
    client, db = client_db
    login(client, "adm")
    # 上一次月考:6 人数学成绩 90/80/70/60/50/40,状态走到已发布成绩
    prev = setup_exam(client, seed, name="七年级 10 月月考")
    totals = {
        seed["s1"].id: 90, seed["s2"].id: 80, seed["s3"].id: 70,
        seed["s4"].id: 60, seed["s5"].id: 50, seed["s6"].id: 40,
    }
    assert put_scores(client, prev, seed["math"].id, [
        {"student_id": sid, "score": sc} for sid, sc in totals.items()
    ]).status_code == 200
    advance_to_published_scores(client, prev)
    # 本次月考:S 型编排,两间考场各 3 人
    eid = setup_exam(client, seed, name="七年级 11 月月考")
    _setup_rooms_and_rule(client, seed, eid)
    r = client.post(f"/api/exam/exams/{eid}/arrange",
                    json={"subject_id": seed["math"].id})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["assigned"] == 6
    assert body["warnings"] == []  # 有成绩,不写无成绩警告
    items = client.get(
        f"/api/exam/exams/{eid}/arrangements?subject_id={seed['math'].id}"
    ).json()["items"]
    by_room = {}
    for it in items:
        by_room.setdefault(it["room_name"], []).append(it["student_no"])
    # 蛇形:第 1 名进 101,第 2 名进 102,第 3 名进 102,第 4 名进 101,
    # 第 5 名进 101,第 6 名进 102
    assert sorted(by_room["101 教室"]) == ["20260101", "20260104", "20260201"]
    assert sorted(by_room["102 教室"]) == ["20260102", "20260103", "20260202"]


def test_s_shape_no_previous_scores_warning_kept(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_exam(client, seed)
    _setup_rooms_and_rule(client, seed, eid)
    r = client.post(f"/api/exam/exams/{eid}/arrange",
                    json={"subject_id": seed["math"].id})
    assert r.status_code == 200, r.text
    assert r.json()["warnings"] == [S_SHAPE_WARNING]
    assert r.json()["assigned"] == 6
