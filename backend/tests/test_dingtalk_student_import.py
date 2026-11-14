"""从钉钉导入学生名单测试:部门树、成员预览(角色过滤)、确认导入、去重。

不连真实钉钉:monkeypatch dingtalk_students.DingTalkAppClient,
以固定夹具回部门、成员与家校身份。
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
from app.models.basedata import ClassUnit
from app.models.exam_foundation import Student
from app.models.semester import Semester
from app.models.user import Role
from app.services import dingtalk_students as ding
from app.services import settings as app_settings
from tests.conftest import make_user

PW = "password123"

DEPTS = {
    1: [{"dept_id": 10, "name": "校区一", "parent_id": 1}],
    10: [{"dept_id": 20, "name": "初中", "parent_id": 10}],
    20: [{"dept_id": 30, "name": "七年级 2026级", "parent_id": 20}],
    30: [
        {"dept_id": 40, "name": "七年级 1班", "parent_id": 30},
        {"dept_id": 41, "name": "七年级 2班", "parent_id": 30},
    ],
    40: [],
    41: [],
}

# 七年级 1班钉钉成员:学生 4 人(更新/待补学号/同名/新增各 1)、家长 1、老师 1、身份不明 1
MEMBERS_40 = [
    {"userid": "U-s1", "name": "张三", "mobile": "13800000001"},
    {"userid": "U-s2", "name": "王小五", "mobile": ""},
    {"userid": "U-s3", "name": "李四", "mobile": "13800000002"},
    {"userid": "U-s4", "name": "赵小六", "mobile": "13800000003"},
    {"userid": "U-p1", "name": "张父", "mobile": "13800000004"},
    {"userid": "U-t1", "name": "陈老师", "mobile": "13800000005"},
    {"userid": "U-u1", "name": "未知人", "mobile": ""},
]

ROLES_40 = {
    "U-s1": {"role": "student", "class_id": 40, "userid": "U-s1",
             "unionid": "un1", "student_no": "20260101"},
    "U-s2": {"role": "student", "class_id": 40, "userid": "U-s2",
             "unionid": "un2", "student_no": ""},
    "U-s3": {"role": "student", "class_id": 40, "userid": "U-s3",
             "unionid": "un3", "student_no": "20260999"},
    "U-s4": {"role": "student", "class_id": 40, "userid": "U-s4",
             "unionid": "un4", "student_no": "20260103"},
    "U-p1": {"role": "guardian", "class_id": 40, "userid": "U-p1", "unionid": "un5"},
    "U-t1": {"role": "teacher", "class_id": 40, "userid": "U-t1",
             "unionid": "un6", "is_adviser": 1},
}


class FakeDingTalkClient:
    """固定夹具:部门树、成员一页、身份按表回;U-u1 身份接口失败。"""

    def __init__(self, app_key, app_secret, agent_id):
        self.app_key = app_key

    def list_sub_departments(self, dept_id):
        return DEPTS.get(dept_id, [])

    def list_department_users(self, dept_id, cursor=0, size=100):
        if dept_id == 41:
            # 分页:第一页 1 人带 next_cursor,第二页 1 人结束
            if cursor == 0:
                return {"has_more": True, "next_cursor": 1,
                        "list": [{"userid": "U-x1", "name": "钱七", "mobile": ""}]}
            return {"has_more": False, "next_cursor": 0,
                    "list": [{"userid": "U-x2", "name": "孙八", "mobile": ""}]}
        if dept_id == 40:
            return {"has_more": False, "next_cursor": 0, "list": MEMBERS_40}
        return {"has_more": False, "next_cursor": 0, "list": []}

    def get_edu_user(self, class_id, userid):
        if userid == "U-u1":
            raise RuntimeError("钉钉取家校人员身份失败:系统繁忙")
        if userid in ("U-x1", "U-x2"):
            return {"role": "student", "class_id": class_id, "userid": userid,
                    "unionid": "unx", "student_no": ""}
        return ROLES_40[userid]


class FakeDingTalkNoEduPermission(FakeDingTalkClient):
    """家校身份接口全部报权限不足。"""

    def get_edu_user(self, class_id, userid):
        raise RuntimeError("钉钉取家校人员身份失败:权限不足")


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
    cls1 = ClassUnit(semester_id=sem.id, grade=7, name="1班", track="junior_high")
    cls2 = ClassUnit(semester_id=sem.id, grade=7, name="2班", track="junior_high")
    cls11 = ClassUnit(semester_id=sem.id, grade=7, name="11班", track="junior_high")
    db.add_all([cls1, cls2, cls11])
    db.flush()
    admin = make_user(db, "adm", PW, roles=[Role.admin])
    s1 = Student(semester_id=sem.id, class_unit_id=cls1.id,
                 student_no="20260101", name="张三", gender="男")
    s2 = Student(semester_id=sem.id, class_unit_id=cls1.id,
                 student_no="20260102", name="李四", gender="女")
    db.add_all([s1, s2])
    db.commit()
    return {"sem": sem, "cls1": cls1, "cls2": cls2, "cls11": cls11,
            "admin": admin, "s1": s1, "s2": s2}


def login(client, username="adm"):
    r = client.post("/api/auth/login", json={"username": username, "password": PW})
    assert r.status_code == 200, r.text


@pytest.fixture
def configured(client_db, seed, monkeypatch):
    client, db = client_db
    monkeypatch.setattr(ding, "DingTalkAppClient", FakeDingTalkClient)
    app_settings.save_dingtalk_app(
        db, app_key="KEY", app_secret="SEC", agent_id="123", lead_minutes=15)
    db.commit()
    return client, db


def _preview_body(sem_id, dept_id, dept_path, class_unit_id=None):
    body = {"semester_id": sem_id, "dept_id": dept_id, "dept_path": dept_path}
    if class_unit_id is not None:
        body["class_unit_id"] = class_unit_id
    return body


def test_dept_tree(configured, seed):
    client, _db = configured
    login(client)
    r = client.get("/api/exam/students/dingtalk/departments")
    assert r.status_code == 200, r.text
    tree = r.json()
    assert [d["name"] for d in tree] == ["校区一"]
    grade = tree[0]["children"][0]["children"][0]
    assert grade["name"] == "七年级 2026级"
    assert [d["name"] for d in grade["children"]] == ["七年级 1班", "七年级 2班"]


def test_preview_filters_roles_and_suggests_class(configured, seed):
    client, _db = configured
    login(client)
    sem = seed["sem"]
    r = client.post("/api/exam/students/dingtalk/preview", json=_preview_body(
        sem.id, 40, ["校区一", "初中", "七年级 2026级", "七年级 1班"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_members"] == 7
    assert body["student_count"] == 4
    assert body["guardian_count"] == 1
    assert body["teacher_count"] == 1
    assert body["unknown_count"] == 1
    assert body["suggested_class_unit_id"] == seed["cls1"].id
    assert body["suggested_class_name"] == "1班"
    rows = {s["userid"]: s for s in body["students"]}
    assert set(rows) == {"U-s1", "U-s2", "U-s3", "U-s4"}
    assert rows["U-s1"]["exists"] == "update"  # 学号 20260101 已存在
    assert rows["U-s1"]["student_no"] == "20260101"
    assert rows["U-s2"]["exists"] == "new"
    assert rows["U-s2"]["student_no_missing"] is True
    assert rows["U-s2"]["missing_fields"] == ["学号"]
    assert rows["U-s3"]["exists"] == "same_name"  # 李四同名已在 1 班
    assert rows["U-s4"]["exists"] == "new"
    assert rows["U-s4"]["mobile"] == "13800000003"
    assert [u["userid"] for u in body["unconfirmed"]] == ["U-u1"]


def test_preview_suggests_longest_suffix(configured, seed):
    """“七年级 11班”应建议 11班,而不是后缀也对得上的 1班。"""
    client, _db = configured
    login(client)
    sem = seed["sem"]
    r = client.post("/api/exam/students/dingtalk/preview", json=_preview_body(
        sem.id, 41, ["校区一", "初中", "七年级 2026级", "七年级 11班"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["suggested_class_unit_id"] == seed["cls11"].id
    assert body["suggested_class_name"] == "11班"
    # 分页成员拉满:两页共 2 人,都是学生
    assert body["total_members"] == 2
    assert body["student_count"] == 2


def test_preview_no_suggest_when_no_match(configured, seed):
    client, _db = configured
    login(client)
    sem = seed["sem"]
    r = client.post("/api/exam/students/dingtalk/preview", json=_preview_body(
        sem.id, 40, ["校区一", "初中", "七年级 2026级", "七年级 3班"]))
    assert r.status_code == 200, r.text
    assert r.json()["suggested_class_unit_id"] is None


def test_preview_no_suggest_on_grade_mismatch(configured, seed):
    """部门路径是八年级、系统里只有七年级 1班时,不猜,等管理员选。"""
    client, _db = configured
    login(client)
    sem = seed["sem"]
    r = client.post("/api/exam/students/dingtalk/preview", json=_preview_body(
        sem.id, 40, ["校区一", "初中", "八年级 2026级", "八年级 1班"]))
    assert r.status_code == 200, r.text
    assert r.json()["suggested_class_unit_id"] is None


def test_preview_not_configured(client_db, seed):
    client, _db = client_db
    login(client)
    sem = seed["sem"]
    r = client.post("/api/exam/students/dingtalk/preview", json=_preview_body(
        sem.id, 40, ["校区一", "初中", "七年级 2026级", "七年级 1班"]))
    assert r.status_code == 400, r.text
    assert "系统管理" in r.json()["detail"]


def test_preview_edu_permission_denied(client_db, seed, monkeypatch):
    """家校身份接口全部报权限不足:502,明示缺家校通讯录读权限。"""
    client, db = client_db
    monkeypatch.setattr(ding, "DingTalkAppClient", FakeDingTalkNoEduPermission)
    app_settings.save_dingtalk_app(
        db, app_key="KEY", app_secret="SEC", agent_id="123", lead_minutes=15)
    db.commit()
    login(client)
    sem = seed["sem"]
    r = client.post("/api/exam/students/dingtalk/preview", json=_preview_body(
        sem.id, 40, ["校区一", "初中", "七年级 2026级", "七年级 1班"]))
    assert r.status_code == 502, r.text
    assert "钉钉教育家校通讯录读" in r.json()["detail"]


def test_import_creates_updates_and_skips(configured, seed):
    client, db = configured
    login(client)
    sem = seed["sem"]
    cls1 = seed["cls1"]
    r = client.post("/api/exam/students/dingtalk/import", json={
        "semester_id": sem.id, "dept_id": 40, "class_unit_id": cls1.id,
        "students": [
            {"userid": "U-s1", "name": "张三", "student_no": "20260101"},
            {"userid": "U-s4", "name": "赵小六", "student_no": "20260103"},
            {"userid": "U-s3", "name": "李四", "student_no": "20260999"},
            {"userid": "U-p1", "name": "张父", "student_no": "20260998"},
        ],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 1
    assert body["updated"] == 1
    assert body["skipped"] == 2
    assert body["errors"] == []
    assert any("李四" in d for d in body["skipped_detail"])
    assert any("张父" in d for d in body["skipped_detail"])
    # 新建的赵小六:性别为空,状态在读
    created = db.query(Student).filter_by(student_no="20260103").one()
    assert created.name == "赵小六" and created.class_unit_id == cls1.id
    assert created.gender is None and created.status == "在读"
    # 家长绝不能进学生表
    assert db.query(Student).filter_by(student_no="20260998").count() == 0
    assert db.query(Student).filter_by(student_no="20260999").count() == 0
    # 审计日志
    assert db.query(AuditLog).filter(
        AuditLog.action == "exam_student_dingtalk_import").count() == 1


def test_import_missing_student_no_writes_nothing(configured, seed):
    client, db = configured
    login(client)
    sem = seed["sem"]
    cls1 = seed["cls1"]
    r = client.post("/api/exam/students/dingtalk/import", json={
        "semester_id": sem.id, "dept_id": 40, "class_unit_id": cls1.id,
        "students": [
            {"userid": "U-s4", "name": "赵小六", "student_no": "20260103"},
            {"userid": "U-s2", "name": "王小五", "student_no": ""},
        ],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 0 and body["updated"] == 0
    assert body["errors"], "学号待补应报错且零写入"
    assert db.query(Student).filter_by(student_no="20260103").count() == 0


def test_import_duplicate_student_no_writes_nothing(configured, seed):
    client, db = configured
    login(client)
    sem = seed["sem"]
    cls1 = seed["cls1"]
    r = client.post("/api/exam/students/dingtalk/import", json={
        "semester_id": sem.id, "dept_id": 40, "class_unit_id": cls1.id,
        "students": [
            {"userid": "U-s4", "name": "赵小六", "student_no": "20260103"},
            {"userid": "U-s2", "name": "王小五", "student_no": "20260103"},
        ],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 0 and body["errors"]
    assert db.query(Student).filter_by(student_no="20260103").count() == 0


def test_import_not_configured(client_db, seed):
    client, _db = client_db
    login(client)
    sem = seed["sem"]
    r = client.post("/api/exam/students/dingtalk/import", json={
        "semester_id": sem.id, "dept_id": 40,
        "class_unit_id": seed["cls1"].id,
        "students": [{"userid": "U-s4", "name": "赵小六", "student_no": "20260103"}],
    })
    assert r.status_code == 400, r.text
    assert "系统管理" in r.json()["detail"]


def test_departments_not_configured(client_db, seed):
    client, _db = client_db
    login(client)
    r = client.get("/api/exam/students/dingtalk/departments")
    assert r.status_code == 400, r.text
    assert "系统管理" in r.json()["detail"]
