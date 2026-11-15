"""考务地基测试(KW-01~04):学生档案、导入导出、异动、权限与审计。

本文件自带 app fixture(挂 auth + exam_students 路由),因为
conftest 的 env 尚未接线新路由(接线由协调员统一做,见汇报)。
"""

import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import auth as auth_api
from app.api import exam_students as exam_api
from app.core.db import Base, get_db
from app.models.audit import AuditLog
from app.models.basedata import ClassUnit, Subject, Teacher
from app.models.exam_foundation import Student, StudentStatusChange
from app.models.exam_scopes import SubjectLeader  # noqa: F401  # 注册模型
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
    t3user = make_user(db, "t3", PW, roles=[Role.teacher])
    t1 = Teacher(semester_id=sem.id, name="王老师", user_id=t1user.id)
    t2 = Teacher(semester_id=sem.id, name="李老师", user_id=t2user.id)
    t3 = Teacher(semester_id=sem.id, name="张老师", user_id=t3user.id)
    db.add_all([t1, t2, t3])
    db.flush()
    cls7.homeroom_teacher_id = t1.id
    cls8.homeroom_teacher_id = t2.id
    db.flush()
    s1 = Student(semester_id=sem.id, class_unit_id=cls7.id, student_no="20260101", name="张三", gender="男")
    s2 = Student(semester_id=sem.id, class_unit_id=cls7.id, student_no="20260102", name="李四", gender="女")
    s3 = Student(semester_id=sem.id, class_unit_id=cls8.id, student_no="20260201", name="王五", gender="男")
    db.add_all([s1, s2, s3])
    db.flush()
    db.commit()
    return {
        "sem": sem, "math": math, "chinese": chinese,
        "cls7": cls7, "cls8": cls8,
        "admin": admin, "academic": academic, "leader": leader,
        "t1": t1user, "t2": t2user, "t3": t3user,
        "s1": s1, "s2": s2, "s3": s3,
    }


def login(client, username):
    r = client.post("/api/auth/login", json={"username": username, "password": PW})
    assert r.status_code == 200, r.text


def students_url(sem_id, **kw):
    q = "&".join(f"{k}={v}" for k, v in kw.items())
    return f"/api/exam/students?semester_id={sem_id}" + (f"&{q}" if q else "")


def make_import_file(rows):
    wb = Workbook()
    ws = wb.active
    ws.append(["学号", "姓名", "性别", "班级", "状态", "考号"])
    ws.append(["必填", "必填", "选填", "必填", "选填", "选填"])
    ws.append(["20260101", "张三", "男", "701", "在读", ""])
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── KW-01 建/查/改 ──────────────────────────────
def test_create_student_201_and_audit(client_db, seed):
    client, db = client_db
    login(client, "adm")
    r = client.post("/api/exam/students", json={
        "semester_id": seed["sem"].id, "class_unit_id": seed["cls7"].id,
        "student_no": "20260103", "name": "赵六", "gender": "男",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["student_no"] == "20260103"
    assert body["class_name"] == "701"
    assert body["grade"] == 7
    assert body["status"] == "在读"
    assert db.query(AuditLog).filter_by(action="exam_student_create").count() == 1


def test_create_duplicate_student_no_409(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    r = client.post("/api/exam/students", json={
        "semester_id": seed["sem"].id, "class_unit_id": seed["cls7"].id,
        "student_no": "20260101", "name": "重名", "gender": "男",
    })
    assert r.status_code == 409
    assert db.query(Student).filter_by(student_no="20260101").count() == 1


def test_list_filters_and_total(client_db, seed):
    client, db = client_db
    login(client, "adm")
    sem = seed["sem"].id
    assert client.get(students_url(sem)).json()["total"] == 3
    assert client.get(students_url(sem, grade=7)).json()["total"] == 2
    assert client.get(students_url(sem, class_unit_id=seed["cls8"].id)).json()["total"] == 1
    assert client.get(students_url(sem, q="张三")).json()["total"] == 1
    assert client.get(students_url(sem, q="202602")).json()["total"] == 1
    assert client.get(students_url(sem, status="休学")).json()["total"] == 0
    page = client.get(students_url(sem, limit=2, offset=2)).json()
    assert page["total"] == 3 and len(page["items"]) == 1


def test_teacher_list_scoped_to_own_class(client_db, seed):
    client, db = client_db
    login(client, "t1")
    body = client.get(students_url(seed["sem"].id)).json()
    assert body["total"] == 2
    assert {i["class_name"] for i in body["items"]} == {"701"}
    # 显式筛别的班直接 403
    assert client.get(students_url(seed["sem"].id, class_unit_id=seed["cls8"].id)).status_code == 403
    assert client.get(students_url(seed["sem"].id, grade=8)).status_code == 403


def test_teacher_cannot_create_student_403(client_db, seed):
    client, db = client_db
    login(client, "t1")
    r = client.post("/api/exam/students", json={
        "semester_id": seed["sem"].id, "class_unit_id": seed["cls7"].id,
        "student_no": "20260199", "name": "越权", "gender": "男",
    })
    assert r.status_code == 403


def test_patch_updates_name_and_writes_transfer_record(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    s1 = seed["s1"].id
    r = client.patch(f"/api/exam/students/{s1}", json={
        "name": "张三三", "class_unit_id": seed["cls8"].id,
    })
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "张三三"
    assert r.json()["class_name"] == "801"
    assert r.json()["status"] == "在读"  # PATCH 不改 status
    recs = db.query(StudentStatusChange).filter_by(student_id=s1).all()
    assert len(recs) == 1
    assert recs[0].change_type == "转班"
    assert recs[0].from_class_unit_id == seed["cls7"].id
    assert recs[0].to_class_unit_id == seed["cls8"].id
    assert db.query(AuditLog).filter_by(action="exam_student_update").count() == 1


# ── KW-04 状态与异动 ──────────────────────────────
def test_status_change_leave_and_return(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    s2 = seed["s2"].id
    r = client.post(f"/api/exam/students/{s2}/status", json={
        "to_status": "休学", "note": "生病休学", "change_type": "休学",
    })
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "休学"
    r = client.post(f"/api/exam/students/{s2}/status", json={
        "to_status": "在读", "note": "康复复学", "change_type": "复学",
    })
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "在读"
    recs = client.get(f"/api/exam/students/{s2}/status-changes").json()["items"]
    assert [x["change_type"] for x in recs] == ["休学", "复学"]
    assert recs[0]["from_status"] == "在读" and recs[0]["to_status"] == "休学"
    assert recs[0]["note"] == "生病休学"
    assert db.query(AuditLog).filter_by(action="exam_student_status_change").count() == 2


def test_status_change_transfer_keeps_old_records(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    s1 = seed["s1"].id
    # 先休学留一条记录,再转班:旧记录的 from/to 班级不被改写
    client.post(f"/api/exam/students/{s1}/status", json={
        "to_status": "休学", "change_type": "休学",
    })
    r = client.post(f"/api/exam/students/{s1}/status", json={
        "to_status": "休学", "note": "转班", "change_type": "转班",
        "new_class_unit_id": seed["cls8"].id,
    })
    assert r.status_code == 200, r.text
    assert r.json()["class_name"] == "801"
    assert r.json()["grade"] == 8
    assert r.json()["status"] == "休学"
    recs = client.get(f"/api/exam/students/{s1}/status-changes").json()["items"]
    assert len(recs) == 2
    assert recs[0].get("from_class_name") == "701"
    assert recs[1]["change_type"] == "转班"
    assert recs[1]["from_class_name"] == "701"
    assert recs[1]["from_grade"] == 7
    assert recs[1]["to_class_name"] == "801"
    assert recs[1]["to_grade"] == 8


def test_status_change_validation_errors(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    s1 = seed["s1"].id
    # 转班不给新班级
    assert client.post(f"/api/exam/students/{s1}/status", json={
        "to_status": "在读", "change_type": "转班",
    }).status_code == 400
    # 休学配在读目标
    assert client.post(f"/api/exam/students/{s1}/status", json={
        "to_status": "在读", "change_type": "休学",
    }).status_code == 400
    # 在读学生复学
    assert client.post(f"/api/exam/students/{s1}/status", json={
        "to_status": "在读", "change_type": "复学",
    }).status_code == 400
    # 状态没有变化
    assert client.post(f"/api/exam/students/{s1}/status", json={
        "to_status": "在读",
    }).status_code == 400
    assert db.query(StudentStatusChange).count() == 0


# ── KW-02 导入 ──────────────────────────────
def test_template_download(client_db, seed):
    client, db = client_db
    login(client, "adm")
    r = client.get("/api/exam/students/template")
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers["content-type"]
    wb = load_workbook(io.BytesIO(r.content), data_only=True)
    ws = wb.active
    assert [c.value for c in ws[1]][:4] == ["学号", "姓名", "性别", "班级"]
    assert [c.value for c in ws[2]][0] == "必填,同一学期内唯一"


def test_import_creates_and_is_idempotent(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    sem = seed["sem"].id
    data = make_import_file([
        ["20260103", "赵六", "男", "701", "在读", ""],
        ["20260104", "钱七", "女", "801", "在读", ""],
    ])
    r = client.post(f"/api/exam/students/import?semester_id={sem}",
                    files={"file": ("students.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    assert r.json() == {"created": 2, "updated": 0, "skipped": 0, "errors": []}
    assert db.query(Student).filter_by(student_no="20260103").one().name == "赵六"
    # 再导一次同一文件:全部更新,不产生重复学生
    r = client.post(f"/api/exam/students/import?semester_id={sem}",
                    files={"file": ("students.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.json() == {"created": 0, "updated": 2, "skipped": 0, "errors": []}
    assert db.query(Student).filter_by(student_no="20260103").count() == 1
    assert db.query(AuditLog).filter_by(action="exam_student_import").count() == 2


def test_import_errors_report_all_rows_and_write_nothing(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    sem = seed["sem"].id
    before = db.query(Student).count()
    data = make_import_file([
        ["20260103", "", "男", "701", "在读", ""],          # 缺姓名
        ["20260104", "钱七", "女", "不存在的班", "在读", ""],  # 班级不存在
        ["20260105", "孙八", "未知", "701", "在读", ""],      # 性别无效
        ["20260105", "孙八", "男", "701", "在读", ""],        # 文件内学号重复
    ])
    r = client.post(f"/api/exam/students/import?semester_id={sem}",
                    files={"file": ("students.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 0 and body["updated"] == 0
    assert len(body["errors"]) == 4
    assert any("第 4 行" in e for e in body["errors"])
    assert any("不存在" in e for e in body["errors"])
    assert db.query(Student).count() == before  # 全对才写入:零写入


def test_import_bad_file_400(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    r = client.post(f"/api/exam/students/import?semester_id={seed['sem'].id}",
                    files={"file": ("bad.xlsx", b"not an excel file", "application/octet-stream")})
    assert r.status_code == 400


# ── KW-03 导出 ──────────────────────────────
def test_export_headers_and_audit(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    r = client.get(f"/api/exam/students/export?semester_id={seed['sem'].id}&grade=7")
    assert r.status_code == 200
    wb = load_workbook(io.BytesIO(r.content), data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    assert rows[0] == ("学号", "姓名", "性别", "班级", "年级", "状态", "考号")
    assert len(rows) == 3  # 表头 + 2 名 7 年级学生
    assert db.query(AuditLog).filter_by(action="exam_student_export").count() == 1


def test_export_scoped_for_homeroom_teacher(client_db, seed):
    client, db = client_db
    login(client, "t1")
    r = client.get(f"/api/exam/students/export?semester_id={seed['sem'].id}")
    assert r.status_code == 200
    wb = load_workbook(io.BytesIO(r.content), data_only=True)
    rows = list(wb.active.iter_rows(values_only=True))
    assert len(rows) == 3  # 只导出本班 2 人
