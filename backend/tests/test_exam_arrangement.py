"""考场编排测试(KW-15~22):考场增删、规则、自动编排、S 型警告、特殊考生、
手动调整、锁定、导出、权限与审计。

本文件自带 app fixture(挂 auth + exam + exam_arrangement 路由),因为
conftest 的 env 尚未接线新路由(接线由协调员统一做,见汇报)。
"""

from io import BytesIO
from urllib.parse import unquote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import auth as auth_api
from app.api import exam as exam_api
from app.api import exam_arrangement as arr_api
from app.core.db import Base, get_db
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
    r1 = Room(semester_id=sem.id, name="101 教室", capacity=2)
    r2 = Room(semester_id=sem.id, name="102 教室", capacity=30)
    r3 = Room(semester_id=sem.id, name="103 特殊教室", capacity=30)
    db.add_all([math, chinese, cls701, cls702, r1, r2, r3])
    db.flush()
    admin = make_user(db, "adm", PW, roles=[Role.admin])
    academic = make_user(db, "jiao", PW, roles=[Role.director])
    t1user = make_user(db, "t1", PW, roles=[Role.teacher])
    t1 = Teacher(semester_id=sem.id, name="王老师", user_id=t1user.id)
    db.add(t1)
    db.flush()
    cls701.homeroom_teacher_id = t1.id
    db.flush()
    s1 = Student(semester_id=sem.id, class_unit_id=cls701.id, student_no="20260101", name="张三", gender="男", exam_no="202607001")
    s2 = Student(semester_id=sem.id, class_unit_id=cls701.id, student_no="20260102", name="李四", gender="女", exam_no="202607002")
    s3 = Student(semester_id=sem.id, class_unit_id=cls701.id, student_no="20260103", name="王五", gender="男", exam_no="202607003")
    s4 = Student(semester_id=sem.id, class_unit_id=cls702.id, student_no="20260201", name="赵六", gender="男", exam_no="202607004")
    s5 = Student(semester_id=sem.id, class_unit_id=cls702.id, student_no="20260202", name="钱七", gender="女", exam_no="202607005")
    db.add_all([s1, s2, s3, s4, s5])
    db.commit()
    return {
        "sem": sem, "math": math, "chinese": chinese,
        "cls701": cls701, "cls702": cls702,
        "r1": r1, "r2": r2, "r3": r3,
        "admin": admin, "academic": academic, "t1": t1user,
        "s1": s1, "s2": s2, "s3": s3, "s4": s4, "s5": s5,
    }


def login(client, username):
    r = client.post("/api/auth/login", json={"username": username, "password": PW})
    assert r.status_code == 200, r.text


def make_exam(client, seed, **over):
    body = {
        "semester_id": seed["sem"].id,
        "name": "七年级 11 月月考",
        "exam_type": "月考",
        "grades": [7],
    }
    body.update(over)
    r = client.post("/api/exam/exams", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def setup_exam(client, seed, with_rooms=True):
    """建考 + 两科日程 + 参试名单(5 人);可选建两间普通考场。"""
    exam = make_exam(client, seed)
    eid = exam["id"]
    r = client.put(f"/api/exam/exams/{eid}/subjects", json={"subjects": [
        {"subject_id": seed["math"].id, "exam_date": MONDAY, "start_time": "08:00", "end_time": "09:30"},
        {"subject_id": seed["chinese"].id, "exam_date": MONDAY, "start_time": "10:00", "end_time": "11:30"},
    ]})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/exam/exams/{eid}/participants/generate")
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 5
    if with_rooms:
        for room in (seed["r1"], seed["r2"]):
            rr = client.post(f"/api/exam/exams/{eid}/rooms", json={"room_id": room.id})
            assert rr.status_code == 201, rr.text
    return eid


def arrange(client, eid, subject_id=None):
    body = {} if subject_id is None else {"subject_id": subject_id}
    r = client.post(f"/api/exam/exams/{eid}/arrange", json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ── KW-15 考场增删 ──────────────────────────────
def test_rooms_create_list_delete(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed, with_rooms=False)
    r = client.post(f"/api/exam/exams/{eid}/rooms", json={"room_id": seed["r1"].id})
    assert r.status_code == 201, r.text
    assert r.json()["room_name"] == "101 教室"
    assert r.json()["capacity"] is None  # 未填时空,编排时取教室 capacity
    assert r.json()["room_type"] == "普通"
    assert r.json()["is_special"] is False
    # 同一教室重复设考场 409;不存在的教室 404
    assert client.post(f"/api/exam/exams/{eid}/rooms",
                       json={"room_id": seed["r1"].id}).status_code == 409
    assert client.post(f"/api/exam/exams/{eid}/rooms",
                       json={"room_id": 99999}).status_code == 404
    body = client.get(f"/api/exam/exams/{eid}/rooms").json()
    assert body["total"] == 1
    rid = body["items"][0]["id"]
    assert client.delete(f"/api/exam/exams/{eid}/rooms/{rid}").status_code == 204
    assert client.get(f"/api/exam/exams/{eid}/rooms").json()["total"] == 0
    assert db.query(AuditLog).filter_by(action="exam_room_create").count() == 1
    assert db.query(AuditLog).filter_by(action="exam_room_delete").count() == 1


def test_rooms_bulk_create(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed, with_rooms=False)
    # 一次勾选三间:不填人数上限,每间用各自教室容量(r1=2,r2=30,r3=30)
    r = client.post(f"/api/exam/exams/{eid}/rooms/bulk", json={
        "room_ids": [seed["r1"].id, seed["r2"].id, seed["r3"].id],
    })
    assert r.status_code == 200, r.text
    assert r.json() == {"created": 3, "skipped": 0}
    body = client.get(f"/api/exam/exams/{eid}/rooms").json()
    assert body["total"] == 3
    assert {i["room_name"]: i["capacity"] for i in body["items"]} == {
        "101 教室": 2, "102 教室": 30, "103 特殊教室": 30,
    }
    assert {i["room_type"] for i in body["items"]} == {"普通"}
    assert db.query(AuditLog).filter_by(action="exam_room_create").count() == 1


def test_rooms_bulk_partial_skip_and_validation(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed, with_rooms=False)
    # 先单加一间,再批量:已加过的与不存在的计入跳过,不中断整批
    r = client.post(f"/api/exam/exams/{eid}/rooms",
                    json={"room_id": seed["r1"].id})
    assert r.status_code == 201, r.text
    r = client.post(f"/api/exam/exams/{eid}/rooms/bulk", json={
        "room_ids": [seed["r1"].id, seed["r2"].id, 99999],
        "capacity": 40, "room_type": "特殊", "is_special": True,
    })
    assert r.status_code == 200, r.text
    assert r.json() == {"created": 1, "skipped": 2}
    body = client.get(f"/api/exam/exams/{eid}/rooms").json()
    assert body["total"] == 2
    added = next(i for i in body["items"] if i["room_name"] == "102 教室")
    assert added["capacity"] == 40  # 手动填的上限对所选全部生效
    assert added["room_type"] == "特殊"
    assert added["is_special"] is True
    # 空列表 422;非法类型 400;教师越权 403
    r = client.post(f"/api/exam/exams/{eid}/rooms/bulk", json={"room_ids": []})
    assert r.status_code == 422, r.text
    r = client.post(f"/api/exam/exams/{eid}/rooms/bulk", json={
        "room_ids": [seed["r2"].id], "room_type": "normal",
    })
    assert r.status_code == 400, r.text
    login(client, "t1")
    r = client.post(f"/api/exam/exams/{eid}/rooms/bulk", json={
        "room_ids": [seed["r2"].id],
    })
    assert r.status_code == 403, r.text


def test_delete_room_with_assignments_409(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed)
    arrange(client, eid, subject_id=seed["math"].id)
    rid = client.get(f"/api/exam/exams/{eid}/rooms").json()["items"][0]["id"]
    assert client.delete(f"/api/exam/exams/{eid}/rooms/{rid}").status_code == 409


# ── KW-16 规则 ──────────────────────────────
def test_rule_default_and_save(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed, with_rooms=False)
    body = client.get(f"/api/exam/exams/{eid}/arrangement-rule").json()
    assert body == {
        "exam_id": eid, "mode": "whole_class",
        "scatter_same_class": True, "max_per_room": 30,
    }
    r = client.put(f"/api/exam/exams/{eid}/arrangement-rule", json={
        "mode": "s_shape", "scatter_same_class": False, "max_per_room": 2,
    })
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "s_shape"
    assert r.json()["max_per_room"] == 2
    assert client.get(f"/api/exam/exams/{eid}/arrangement-rule").json()["mode"] == "s_shape"
    # 旧模式 student_no / class_mixed 已不再合法,400
    assert client.put(f"/api/exam/exams/{eid}/arrangement-rule", json={
        "mode": "student_no", "scatter_same_class": True, "max_per_room": 30,
    }).status_code == 400
    assert client.put(f"/api/exam/exams/{eid}/arrangement-rule", json={
        "mode": "class_mixed", "scatter_same_class": True, "max_per_room": 30,
    }).status_code == 400
    assert db.query(AuditLog).filter_by(action="exam_arrangement_rule_update").count() == 1


# ── KW-17 自动编排 ──────────────────────────────
def test_arrange_whole_class(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed)
    client.put(f"/api/exam/exams/{eid}/arrangement-rule", json={
        "mode": "whole_class", "scatter_same_class": False, "max_per_room": 30,
    })
    body = arrange(client, eid, subject_id=seed["math"].id)
    assert body["assigned"] == 5
    assert body["rooms_used"] == 2  # 101 教室容量 2,余下 3 人进 102 教室
    assert body["warnings"] == []
    items = client.get(
        f"/api/exam/exams/{eid}/arrangements?subject_id={seed['math'].id}"
    ).json()
    assert items["total"] == 5
    by_room = {}
    for it in items["items"]:
        by_room.setdefault(it["room_name"], []).append(it)
    # 整班入考场:701 班先填满 101 教室,再进 102 教室
    assert [i["student_no"] for i in sorted(by_room["101 教室"], key=lambda x: x["seat_no"])] == ["20260101", "20260102"]
    assert [i["student_no"] for i in sorted(by_room["102 教室"], key=lambda x: x["seat_no"])] == ["20260103", "20260201", "20260202"]
    assert by_room["101 教室"][0]["seat_no"] == 1
    assert by_room["101 教室"][0]["student_name"] == "张三"
    assert by_room["101 教室"][0]["class_name"] == "701"
    assert by_room["101 教室"][0]["subject_name"] == "数学"
    assert by_room["101 教室"][0]["exam_no"] == "202607001"
    # 座位表里也有考号(KW-21 桌贴用)
    seatmap = client.get(
        f"/api/exam/exams/{eid}/seat-map?subject_id={seed['math'].id}"
    ).json()
    all_seats = [s for r in seatmap["rooms"] for s in r["seats"]]
    assert {s["student_no"]: s["exam_no"] for s in all_seats}["20260101"] == "202607001"


def test_arrange_random_deterministic(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed)
    client.put(f"/api/exam/exams/{eid}/arrangement-rule", json={
        "mode": "random", "scatter_same_class": True, "max_per_room": 30,
    })
    body = arrange(client, eid, subject_id=seed["math"].id)
    assert body["assigned"] == 5

    def seating():
        items = client.get(
            f"/api/exam/exams/{eid}/arrangements?subject_id={seed['math'].id}"
        ).json()["items"]
        return {
            i["student_no"]: (i["room_name"], i["seat_no"]) for i in items
        }

    first = seating()
    # 种子 exam_id * 1000 + subject_id,同一科目重复编排结果一致,
    # 且顺序与学号顺序不同(确为随机混排,不是学号顺序)
    assert first["20260103"] == ("101 教室", 1)
    assert first["20260201"] == ("101 教室", 2)
    assert first["20260101"] == ("102 教室", 3)
    arrange(client, eid, subject_id=seed["math"].id)
    assert seating() == first


def test_arrange_no_rooms_or_no_participants_400(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed, with_rooms=False)
    assert client.post(f"/api/exam/exams/{eid}/arrange", json={}).status_code == 400
    # 有考场无名单也 400
    exam2 = make_exam(client, seed, name="空名单考试")
    e2 = exam2["id"]
    client.put(f"/api/exam/exams/{e2}/subjects", json={"subjects": [
        {"subject_id": seed["math"].id, "exam_date": MONDAY, "start_time": "08:00", "end_time": "09:30"},
    ]})
    client.post(f"/api/exam/exams/{e2}/rooms", json={"room_id": seed["r1"].id})
    assert client.post(f"/api/exam/exams/{e2}/arrange", json={}).status_code == 400


def test_arrange_s_shape_no_score_warning(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed)
    client.put(f"/api/exam/exams/{eid}/arrangement-rule", json={
        "mode": "s_shape", "scatter_same_class": True, "max_per_room": 30,
    })
    body = arrange(client, eid, subject_id=seed["math"].id)
    assert body["assigned"] == 5
    assert body["warnings"] == [S_SHAPE_WARNING]
    # 暂按学号顺序编(打散开):101 教室第一座仍是学号最小的张三,第二座是另一班的赵六
    items = client.get(
        f"/api/exam/exams/{eid}/arrangements?subject_id={seed['math'].id}&room_id={seed['r1'].id}"
    ).json()
    assert [i["student_no"] for i in sorted(items["items"], key=lambda x: x["seat_no"])] == ["20260101", "20260201"]


def test_arrange_capacity_warning(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed)
    client.put(f"/api/exam/exams/{eid}/arrangement-rule", json={
        "mode": "whole_class", "scatter_same_class": False, "max_per_room": 2,
    })
    body = arrange(client, eid, subject_id=seed["math"].id)
    assert body["assigned"] == 4
    assert any("容量不足" in w for w in body["warnings"])


def test_rearrange_clears_previous(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed)
    arrange(client, eid, subject_id=seed["math"].id)
    body = arrange(client, eid, subject_id=seed["math"].id)
    assert body["assigned"] == 5
    items = client.get(
        f"/api/exam/exams/{eid}/arrangements?subject_id={seed['math'].id}"
    ).json()
    assert items["total"] == 5  # 重排不产生重复编排


# ── KW-19 准考证数据 ──────────────────────────────
def test_admission_tickets(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed)
    # 只编数学,语文未编排:语文科考场与座位号为空
    arrange(client, eid, subject_id=seed["math"].id)
    body = client.get(f"/api/exam/exams/{eid}/admission-tickets").json()
    assert body["total"] == 5
    first = next(i for i in body["items"] if i["student_no"] == "20260101")
    assert first["exam_no"] == "202607001"
    assert first["student_name"] == "张三"
    assert first["class_name"] == "701"
    assert len(first["subjects"]) == 2
    math_sub = next(s for s in first["subjects"] if s["subject_name"] == "数学")
    assert math_sub["subject_id"] == seed["math"].id
    assert math_sub["exam_date"] == MONDAY
    assert math_sub["start_time"] == "08:00"
    assert math_sub["end_time"] == "09:30"
    assert math_sub["room_name"] == "101 教室"
    assert math_sub["seat_no"] == 1
    ch_sub = next(s for s in first["subjects"] if s["subject_name"] == "语文")
    assert ch_sub["room_name"] == ""
    assert ch_sub["seat_no"] is None
    # 按班级筛选供按班级分发打印:701 班 3 人
    assert client.get(
        f"/api/exam/exams/{eid}/admission-tickets"
        f"?class_unit_id={seed['cls701'].id}"
    ).json()["total"] == 3
    # 按考场筛选:数学在 101 教室的只有张三、李四
    room_body = client.get(
        f"/api/exam/exams/{eid}/admission-tickets?room_id={seed['r1'].id}"
    ).json()
    assert room_body["total"] == 2
    assert {i["student_no"] for i in room_body["items"]} == {"20260101", "20260102"}
    # 教师只看得到本人可见班级
    login(client, "t1")
    assert client.get(f"/api/exam/exams/{eid}/admission-tickets").json()["total"] == 3


# ── KW-21 特殊考生预留 ──────────────────────────────
def test_special_student_to_special_room(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed)
    client.post(f"/api/exam/exams/{eid}/rooms",
                json={"room_id": seed["r3"].id, "room_type": "特殊", "is_special": True})
    r = client.post(f"/api/exam/exams/{eid}/special-arrangements", json={
        "student_id": seed["s1"].id, "arrangement_type": "单独考场",
    })
    assert r.status_code == 201, r.text
    r = client.post(f"/api/exam/exams/{eid}/special-arrangements", json={
        "student_id": seed["s2"].id, "arrangement_type": "延长时限", "detail": "延长 30 分钟",
    })
    assert r.status_code == 201, r.text
    body = arrange(client, eid, subject_id=seed["math"].id)
    assert body["assigned"] == 5
    items = client.get(
        f"/api/exam/exams/{eid}/arrangements?subject_id={seed['math'].id}"
    ).json()["items"]
    s1_row = next(i for i in items if i["student_no"] == "20260101")
    assert s1_row["room_name"] == "103 特殊教室"
    s2_row = next(i for i in items if i["student_no"] == "20260102")
    assert "延长时限" in s2_row["special_note"]
    # 座位表里延长时限有备注
    seatmap = client.get(
        f"/api/exam/exams/{eid}/seat-map?subject_id={seed['math'].id}"
    ).json()
    special_room = next(r for r in seatmap["rooms"] if r["room_name"] == "103 特殊教室")
    assert [s["student_no"] for s in special_room["seats"]] == ["20260101"]
    normal_room = next(r for r in seatmap["rooms"] if r["room_name"] == "101 教室")
    s2_seat = next(s for s in normal_room["seats"] if s["student_no"] == "20260102")
    assert "延长时限" in s2_seat["special_note"]
    # 特殊安排状态变为已安排
    rows = client.get(f"/api/exam/exams/{eid}/special-arrangements").json()["items"]
    assert all(r["status"] == "已安排" for r in rows)


def test_special_student_no_special_room_warning(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed)  # 只有两间普通考场
    client.post(f"/api/exam/exams/{eid}/special-arrangements", json={
        "student_id": seed["s1"].id, "arrangement_type": "单独考场",
    })
    body = arrange(client, eid, subject_id=seed["math"].id)
    assert body["assigned"] == 5
    assert any("没有特殊考场可用" in w for w in body["warnings"])


# ── KW-18 手动调整 ──────────────────────────────
def test_move_and_swap(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed)
    client.put(f"/api/exam/exams/{eid}/arrangement-rule", json={
        "mode": "whole_class", "scatter_same_class": False, "max_per_room": 30,
    })
    arrange(client, eid, subject_id=seed["math"].id)
    # 整班入考场:101 教室张三 1 号、李四 2 号;102 教室王五 1 号、赵六 2 号、钱七 3 号
    items = client.get(
        f"/api/exam/exams/{eid}/arrangements?subject_id={seed['math'].id}"
    ).json()["items"]
    by_no = {i["student_no"]: i for i in items}
    # 换场:把 101 教室的李四换到 102 教室(不指定座位,自动排到末位)
    r = client.post(f"/api/exam/exams/{eid}/arrangements/move", json={
        "assignment_id": by_no["20260102"]["id"], "to_room_id": seed["r2"].id,
    })
    assert r.status_code == 200, r.text
    assert r.json()["room_name"] == "102 教室"
    assert r.json()["seat_no"] == 4
    # 换到满员考场 409:101 教室现剩 1 人(容量 2),先把赵六换进 101 填满,
    # 再换钱七进 101 应被挡
    r = client.post(f"/api/exam/exams/{eid}/arrangements/move", json={
        "assignment_id": by_no["20260201"]["id"], "to_room_id": seed["r1"].id,
    })
    assert r.status_code == 200, r.text
    r = client.post(f"/api/exam/exams/{eid}/arrangements/move", json={
        "assignment_id": by_no["20260202"]["id"], "to_room_id": seed["r1"].id,
    })
    assert r.status_code == 409
    # 目标座位已被占用 409
    r = client.post(f"/api/exam/exams/{eid}/arrangements/move", json={
        "assignment_id": by_no["20260202"]["id"], "to_room_id": seed["r2"].id, "seat_no": 1,
    })
    assert r.status_code == 409
    # 互换:张三(101 教室 1 号)与钱七(102 教室)互换座位
    items = client.get(
        f"/api/exam/exams/{eid}/arrangements?subject_id={seed['math'].id}"
    ).json()["items"]
    by_no = {i["student_no"]: i for i in items}
    a, b = by_no["20260101"], by_no["20260202"]
    r = client.post(f"/api/exam/exams/{eid}/arrangements/swap", json={
        "assignment_id_a": a["id"], "assignment_id_b": b["id"],
    })
    assert r.status_code == 200, r.text
    swapped = {i["student_no"]: i for i in r.json()["items"]}
    assert swapped["20260101"]["room_id"] == b["room_id"]
    assert swapped["20260101"]["seat_no"] == b["seat_no"]
    assert swapped["20260202"]["room_id"] == a["room_id"]
    assert swapped["20260202"]["seat_no"] == a["seat_no"]
    # 不同科目互换 400:先编语文,再拿数学与语文记录互换
    arrange(client, eid, subject_id=seed["chinese"].id)
    math_items = client.get(
        f"/api/exam/exams/{eid}/arrangements?subject_id={seed['math'].id}"
    ).json()["items"]
    ch_items = client.get(
        f"/api/exam/exams/{eid}/arrangements?subject_id={seed['chinese'].id}"
    ).json()["items"]
    r = client.post(f"/api/exam/exams/{eid}/arrangements/swap", json={
        "assignment_id_a": math_items[0]["id"], "assignment_id_b": ch_items[0]["id"],
    })
    assert r.status_code == 400
    assert db.query(AuditLog).filter_by(action="exam_arrangement_move").count() == 2
    assert db.query(AuditLog).filter_by(action="exam_arrangement_swap").count() == 1


# ── KW-22 锁定 ──────────────────────────────
def test_lock_blocks_and_unlock_audit(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed)
    arrange(client, eid, subject_id=seed["math"].id)
    items = client.get(
        f"/api/exam/exams/{eid}/arrangements?subject_id={seed['math'].id}"
    ).json()["items"]
    assert client.get(f"/api/exam/exams/{eid}/arrangement-lock").json() == {
        "locked": False, "locked_by": None, "locked_at": None,
    }
    r = client.post(f"/api/exam/exams/{eid}/arrangement-lock", json={"note": "考前锁定"})
    assert r.status_code == 200, r.text
    assert r.json()["locked"] is True
    assert r.json()["locked_by"] == "jiao"
    # 重复锁定 409;锁定后自动编排、换场、互换全部 409
    assert client.post(f"/api/exam/exams/{eid}/arrangement-lock", json={}).status_code == 409
    assert client.post(f"/api/exam/exams/{eid}/arrange",
                       json={"subject_id": seed["math"].id}).status_code == 409
    assert client.post(f"/api/exam/exams/{eid}/arrangements/move", json={
        "assignment_id": items[0]["id"], "to_room_id": seed["r2"].id,
    }).status_code == 409
    assert client.post(f"/api/exam/exams/{eid}/arrangements/swap", json={
        "assignment_id_a": items[0]["id"], "assignment_id_b": items[1]["id"],
    }).status_code == 409
    # 解锁后恢复;解锁记审计
    r = client.post(f"/api/exam/exams/{eid}/arrangement-unlock", json={})
    assert r.status_code == 200, r.text
    assert r.json()["locked"] is False
    assert client.post(f"/api/exam/exams/{eid}/arrange",
                       json={"subject_id": seed["math"].id}).status_code == 200
    assert db.query(AuditLog).filter_by(action="exam_arrangement_lock").count() == 1
    assert db.query(AuditLog).filter_by(action="exam_arrangement_unlock").count() == 1


# ── KW-20 导出 ──────────────────────────────
def test_export_xlsx(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed)
    arrange(client, eid)  # 全科编排
    r = client.get(f"/api/exam/exams/{eid}/arrangements/export")
    assert r.status_code == 200, r.text
    assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in r.headers["content-type"]
    assert r.content[:2] == b"PK"  # xlsx 是 zip 格式
    assert "考场安排表" in unquote(r.headers["content-disposition"])
    wb = load_workbook(BytesIO(r.content))
    assert set(wb.sheetnames) == {"数学", "语文"}
    ws = wb["数学"]
    assert [c.value for c in ws[1]] == ["考场", "座位号", "学号", "姓名", "班级", "备注"]
    assert ws.max_row == 6  # 表头 + 5 名考生
    names = {ws.cell(row=i, column=4).value for i in range(2, 7)}
    assert names == {"张三", "李四", "王五", "赵六", "钱七"}
    # 指定科目只出一表
    r = client.get(
        f"/api/exam/exams/{eid}/arrangements/export?subject_id={seed['chinese'].id}"
    )
    assert r.status_code == 200
    assert load_workbook(BytesIO(r.content)).sheetnames == ["语文"]


# ── 权限与可见范围 ──────────────────────────────
def test_teacher_forbidden_writes_and_scoped_read(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed)
    arrange(client, eid, subject_id=seed["math"].id)
    login(client, "t1")  # 701 班班主任,只看得到 701 班
    assert client.post(f"/api/exam/exams/{eid}/rooms",
                       json={"room_id": seed["r3"].id}).status_code == 403
    assert client.post(f"/api/exam/exams/{eid}/arrange", json={}).status_code == 403
    assert client.put(f"/api/exam/exams/{eid}/arrangement-rule", json={
        "mode": "whole_class", "scatter_same_class": True, "max_per_room": 30,
    }).status_code == 403
    assert client.post(f"/api/exam/exams/{eid}/arrangement-lock", json={}).status_code == 403
    body = client.get(
        f"/api/exam/exams/{eid}/arrangements?subject_id={seed['math'].id}"
    ).json()
    assert body["total"] == 3
    assert {i["class_name"] for i in body["items"]} == {"701"}
    seatmap = client.get(
        f"/api/exam/exams/{eid}/seat-map?subject_id={seed['math'].id}"
    ).json()
    assert sum(len(r["seats"]) for r in seatmap["rooms"]) == 3


# ── 审计登记册 ──────────────────────────────
def test_exam_arrangement_audit_actions_registered():
    from app.services.exam_audit import EXAM_AUDIT_ACTIONS

    assert {
        "exam_room_create", "exam_room_delete",
        "exam_arrangement_rule_update", "exam_arrange",
        "exam_arrangement_move", "exam_arrangement_swap",
        "exam_arrangement_lock", "exam_arrangement_unlock",
    } <= set(EXAM_AUDIT_ACTIONS)
