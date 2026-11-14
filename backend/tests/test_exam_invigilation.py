"""监考安排测试(KW-23~29):规则与默认值、教师池停用、自动排监考均衡场次、
回避班主任本班与任课本科、时间冲突进 warnings、手工替补换人、巡考增删、
两视图数据、工作量统计与导出、考风考纪登记与越权 403。

本文件自带 app fixture(挂 auth + exam + exam_arrangement +
exam_invigilation 路由),因为 conftest 的 env 尚未接线新路由
(接线由协调员统一做,见汇报)。
"""

from datetime import time
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
from app.api import exam_arrangement as arr_api
from app.api import exam_invigilation as inv_api
from app.core.db import Base, get_db
from app.models.assignment import (
    AssignmentTeacher,
    CourseAssignment,
    SchedulingUnit,
    SchedulingUnitMember,
)
from app.models.audit import AuditLog
from app.models.basedata import ClassUnit, Room, Subject, Teacher
from app.models.exam_foundation import Student
from app.models.period import Period, PeriodTable
from app.models.semester import Semester
from app.models.timetable import ScheduleEntry, Timetable
from app.models.user import Role
from tests.conftest import make_user

PW = "password123"
MONDAY = "2026-11-16"  # 周一


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
    app.include_router(inv_api.router, prefix="/api/exam")
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
    db.add_all([math, chinese, cls701, cls702, r1, r2])
    db.flush()
    admin = make_user(db, "adm", PW, roles=[Role.admin])
    academic = make_user(db, "jiao", PW, roles=[Role.director])
    t1user = make_user(db, "t1", PW, roles=[Role.teacher])
    t3user = make_user(db, "t3", PW, roles=[Role.teacher])
    t1 = Teacher(semester_id=sem.id, name="王老师", user_id=t1user.id)
    t2 = Teacher(semester_id=sem.id, name="李老师")
    t3 = Teacher(semester_id=sem.id, name="张老师", user_id=t3user.id)
    t4 = Teacher(semester_id=sem.id, name="刘老师")
    t5 = Teacher(semester_id=sem.id, name="陈老师")
    t6 = Teacher(semester_id=sem.id, name="赵老师")
    t7 = Teacher(semester_id=sem.id, name="孙老师")
    db.add_all([t1, t2, t3, t4, t5, t6, t7])
    db.flush()
    cls701.homeroom_teacher_id = t1.id  # 王老师是 701 班主任
    t2.subjects.append(math)  # 李老师任教数学
    # 张老师任教语文(701 班),只为让其账号可见 7 年级考试,不影响回避判定
    unit = SchedulingUnit(semester_id=sem.id, unit_type="single", name="701")
    db.add(unit)
    db.flush()
    db.add(SchedulingUnitMember(scheduling_unit_id=unit.id, class_unit_id=cls701.id))
    assign = CourseAssignment(
        semester_id=sem.id, scheduling_unit_id=unit.id,
        subject_id=chinese.id, periods_per_week=4,
    )
    db.add(assign)
    db.flush()
    db.add(AssignmentTeacher(course_assignment_id=assign.id, teacher_id=t3.id))
    s1 = Student(semester_id=sem.id, class_unit_id=cls701.id, student_no="20260101", name="张三", gender="男")
    s2 = Student(semester_id=sem.id, class_unit_id=cls701.id, student_no="20260102", name="李四", gender="女")
    s3 = Student(semester_id=sem.id, class_unit_id=cls701.id, student_no="20260103", name="王五", gender="男")
    s4 = Student(semester_id=sem.id, class_unit_id=cls702.id, student_no="20260201", name="赵六", gender="男")
    s5 = Student(semester_id=sem.id, class_unit_id=cls702.id, student_no="20260202", name="钱七", gender="女")
    db.add_all([s1, s2, s3, s4, s5])
    db.commit()
    return {
        "sem": sem, "math": math, "chinese": chinese,
        "cls701": cls701, "cls702": cls702,
        "r1": r1, "r2": r2,
        "admin": admin, "academic": academic,
        "t1": t1, "t2": t2, "t3": t3, "t4": t4, "t5": t5, "t6": t6, "t7": t7,
        "t1user": t1user, "t3user": t3user,
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


def invigilate(client, eid, subject_id=None):
    body = {} if subject_id is None else {"subject_id": subject_id}
    r = client.post(f"/api/exam/exams/{eid}/invigilate", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def list_invigilations(client, eid, **params):
    r = client.get(f"/api/exam/exams/{eid}/invigilations", params=params)
    assert r.status_code == 200, r.text
    return r.json()


# ── KW-23 规则与教师池 ──────────────────────────────
def test_rule_defaults_and_save(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed)
    r = client.get(f"/api/exam/exams/{eid}/invigilation-rule")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "exam_id": eid,
        "avoid_own_class": True,
        "avoid_own_subject": True,
        "invigilators_per_room": 2,
    }
    r = client.put(f"/api/exam/exams/{eid}/invigilation-rule", json={
        "avoid_own_class": False,
        "avoid_own_subject": True,
        "invigilators_per_room": 1,
    })
    assert r.status_code == 200, r.text
    assert r.json()["avoid_own_class"] is False
    assert r.json()["invigilators_per_room"] == 1
    r = client.get(f"/api/exam/exams/{eid}/invigilation-rule")
    assert r.json()["avoid_own_class"] is False
    assert r.json()["invigilators_per_room"] == 1


def test_pool_default_all_active_and_disable(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed)
    r = client.get(f"/api/exam/exams/{eid}/invigilators")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 7
    assert all(i["eligible"] for i in body["items"])
    assert {i["teacher_name"] for i in body["items"]} == {
        "王老师", "李老师", "张老师", "刘老师", "陈老师", "赵老师", "孙老师",
    }
    # 停用张老师
    items = [
        {"teacher_id": i["teacher_id"], "eligible": i["teacher_name"] != "张老师"}
        for i in body["items"]
    ]
    r = client.put(f"/api/exam/exams/{eid}/invigilators", json={"items": items})
    assert r.status_code == 200, r.text
    disabled = next(i for i in r.json()["items"] if i["teacher_name"] == "张老师")
    assert disabled["eligible"] is False
    # 自动排监考不再排停用的张老师;仍能排满 8 人次(每科 2 考场 x 2 人)
    client.post(f"/api/exam/exams/{eid}/arrange", json={})
    result = invigilate(client, eid)
    assert result["assigned"] == 8
    rows = list_invigilations(client, eid)
    assert all(i["teacher_name"] != "张老师" for i in rows["items"])
    # 语文 102 考场补位时,李老师因已监考语文 101 考场被跳过,应进 warnings
    assert any("李老师" in w and "同一时段已有监考" in w
               for w in result["warnings"]), result


def test_rule_and_pool_write_forbidden_for_teacher(client_db, seed):
    client, db = client_db
    # t1 账号无建考权限,先用教务建考再切回教师账号
    login(client, "jiao")
    eid = setup_exam(client, seed)
    login(client, "t1")
    r = client.put(f"/api/exam/exams/{eid}/invigilation-rule", json={
        "avoid_own_class": True, "avoid_own_subject": True,
        "invigilators_per_room": 2,
    })
    assert r.status_code == 403, r.text
    r = client.post(f"/api/exam/exams/{eid}/invigilate", json={})
    assert r.status_code == 403, r.text
    # 读接口教师可用
    r = client.get(f"/api/exam/exams/{eid}/invigilation-rule")
    assert r.status_code == 200, r.text


# ── KW-24 自动排监考 ──────────────────────────────
def test_auto_invigilate_balanced_and_avoidance(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed)
    r = client.post(f"/api/exam/exams/{eid}/arrange", json={})
    assert r.status_code == 200, r.text
    result = invigilate(client, eid)
    assert result["assigned"] == 8, result  # 2 科 x 2 考场 x 每场 2 人
    rows = list_invigilations(client, eid)
    assert rows["total"] == 8
    from collections import Counter
    counts = Counter(i["teacher_name"] for i in rows["items"])
    # 王老师是 701 班主任,两间考场都有 701 考生,应全避开
    assert counts.get("王老师", 0) == 0
    # 李老师任教数学,数学 4 个名额应全避开,语文可排
    math_rows = [i for i in rows["items"] if i["subject_name"] == "数学"]
    assert all(i["teacher_name"] != "李老师" for i in math_rows)
    # 均衡:其余六人场次极差 <=1(李老师只剩语文可排,故 1 场)
    assert counts["李老师"] == 1
    assert counts["张老师"] == 2
    assert counts["刘老师"] == 2
    assert counts["陈老师"] == 1
    assert counts["赵老师"] == 1
    assert counts["孙老师"] == 1
    # 语文 102 考场补位时李老师因已监考语文 101 考场被跳过,应进 warnings
    assert len(result["warnings"]) == 1, result
    assert "李老师" in result["warnings"][0]
    assert "同一时段已有监考" in result["warnings"][0]
    # 每考场每科恰好 2 人,role 统一为监考
    assert all(i["role"] == "监考" for i in rows["items"])
    for subj in ("数学", "语文"):
        for room in ("101 教室", "102 教室"):
            assert len([i for i in rows["items"]
                        if i["subject_name"] == subj and i["room_name"] == room]) == 2


def test_auto_invigilate_avoid_own_subject_only(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed)
    result = invigilate(client, eid, subject_id=seed["chinese"].id)
    assert result["assigned"] == 4  # 语文 2 考场 x 2 人
    rows = list_invigilations(client, eid)
    # 语文场李老师可以排(只避本科数学);场次均衡优先排未排过的教师,
    # 102 考场由刘老师、陈老师补位,无人因冲突被跳过,故无警告
    assert any(i["teacher_name"] == "李老师" for i in rows["items"])
    assert result["warnings"] == [], result


def test_auto_invigilate_idempotent(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed)
    first = invigilate(client, eid)
    assert first["assigned"] == 8
    second = invigilate(client, eid)
    assert second["assigned"] == 0
    assert list_invigilations(client, eid)["total"] == 8


def test_auto_invigilate_timetable_conflict_in_warnings(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    sem = seed["sem"]
    # 已发布课表:张老师周一第 1 节 08:00-09:30 在 701 班上数学课
    table = PeriodTable(semester_id=sem.id, name="默认节次表", is_default=True)
    db.add(table)
    db.flush()
    db.add(Period(period_table_id=table.id, weekday=1, period_no=1, name="第一节",
                  start_time=time(8, 0), end_time=time(9, 30), type="regular"))
    seed["cls701"].period_table_id = table.id
    unit = SchedulingUnit(semester_id=sem.id, unit_type="single", name="701-数学")
    db.add(unit)
    db.flush()
    db.add(SchedulingUnitMember(scheduling_unit_id=unit.id, class_unit_id=seed["cls701"].id))
    assign = CourseAssignment(semester_id=sem.id, scheduling_unit_id=unit.id,
                              subject_id=seed["math"].id, periods_per_week=4)
    db.add(assign)
    db.flush()
    db.add(AssignmentTeacher(course_assignment_id=assign.id, teacher_id=seed["t3"].id))
    tt = Timetable(semester_id=sem.id, name="2026 秋课表", status="published")
    db.add(tt)
    db.flush()
    db.add(ScheduleEntry(timetable_id=tt.id, course_assignment_id=assign.id, weekday=1, period_no=1))
    db.commit()
    eid = setup_exam(client, seed)
    # 只排数学:王老师避本班、李老师避本科、张老师课表冲突,仍可排满 4 人
    result = invigilate(client, eid, subject_id=seed["math"].id)
    assert result["assigned"] == 4, result
    assert any("张老师" in w and "课表" in w for w in result["warnings"]), result
    assert not any("缺少" in w for w in result["warnings"]), result
    rows = list_invigilations(client, eid)
    assert all(i["teacher_name"] != "张老师" for i in rows["items"])
    # 语文 10:00 不与课表冲突,张老师可以排
    result = invigilate(client, eid, subject_id=seed["chinese"].id)
    assert any(i["teacher_name"] == "张老师"
               for i in list_invigilations(client, eid)["items"])


def test_auto_invigilate_same_slot_conflict_in_warnings(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed)
    # 先手工把刘老师排进数学 101 考场
    r = client.post(f"/api/exam/exams/{eid}/invigilations", json={
        "subject_id": seed["math"].id, "room_id": seed["r1"].id,
        "teacher_id": seed["t4"].id,
    })
    assert r.status_code == 201, r.text
    # 教师池只留刘老师、陈老师两人:数学 102 考场无人可排,两人都在同一时段已有监考
    r = client.put(f"/api/exam/exams/{eid}/invigilators", json={"items": [
        {"teacher_id": seed["t4"].id, "eligible": True},
        {"teacher_id": seed["t5"].id, "eligible": True},
    ]})
    assert r.status_code == 200, r.text
    # 数学 101 考场补 1 人(陈老师),102 考场 2 人都排不上
    result = invigilate(client, eid, subject_id=seed["math"].id)
    assert result["assigned"] == 1, result
    assert any("刘老师" in w and "同一时段已有监考" in w
               for w in result["warnings"]), result
    assert any("陈老师" in w and "同一时段已有监考" in w
               for w in result["warnings"]), result
    assert any("缺少2人" in w for w in result["warnings"]), result
    rows = list_invigilations(client, eid, subject_id=seed["math"].id)
    assert len([i for i in rows["items"] if i["teacher_name"] == "刘老师"]) == 1


# ── KW-25 手工调整与替补 ──────────────────────────────
def test_manual_create_patch_delete(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed)
    r = client.post(f"/api/exam/exams/{eid}/invigilations", json={
        "subject_id": seed["math"].id, "room_id": seed["r1"].id,
        "teacher_id": seed["t4"].id,
    })
    assert r.status_code == 201, r.text
    iid = r.json()["id"]
    assert r.json()["role"] == "监考"
    # 重复排同一人同一场 -> 409
    r = client.post(f"/api/exam/exams/{eid}/invigilations", json={
        "subject_id": seed["math"].id, "room_id": seed["r1"].id,
        "teacher_id": seed["t4"].id,
    })
    assert r.status_code == 409, r.text
    # 同一教师本科目另一考场 -> 409
    r = client.post(f"/api/exam/exams/{eid}/invigilations", json={
        "subject_id": seed["math"].id, "room_id": seed["r2"].id,
        "teacher_id": seed["t4"].id,
    })
    assert r.status_code == 409, r.text
    # 替补换人:刘老师 -> 陈老师
    r = client.patch(f"/api/exam/exams/{eid}/invigilations/{iid}", json={
        "teacher_id": seed["t5"].id,
    })
    assert r.status_code == 200, r.text
    assert r.json()["teacher_name"] == "陈老师"
    # 换人后旧教师可重新排入
    r = client.post(f"/api/exam/exams/{eid}/invigilations", json={
        "subject_id": seed["math"].id, "room_id": seed["r1"].id,
        "teacher_id": seed["t4"].id,
    })
    assert r.status_code == 201, r.text
    # 删除
    r = client.delete(f"/api/exam/exams/{eid}/invigilations/{iid}")
    assert r.status_code == 204, r.text
    rows = list_invigilations(client, eid)
    assert all(i["id"] != iid for i in rows["items"])


def test_manual_create_disabled_pool_teacher_rejected(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed)
    pool = client.get(f"/api/exam/exams/{eid}/invigilators").json()
    items = [
        {"teacher_id": i["teacher_id"],
         "eligible": i["teacher_name"] != "张老师"}
        for i in pool["items"]
    ]
    client.put(f"/api/exam/exams/{eid}/invigilators", json={"items": items})
    r = client.post(f"/api/exam/exams/{eid}/invigilations", json={
        "subject_id": seed["math"].id, "room_id": seed["r1"].id,
        "teacher_id": seed["t3"].id,
    })
    assert r.status_code == 409, r.text


def test_invigilations_teacher_only_sees_own(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed)
    invigilate(client, eid)
    login(client, "t1")
    # 王老师被回避,一条监考也没有,只能看到空列表(不 403)
    rows = list_invigilations(client, eid)
    assert rows["total"] == 0
    login(client, "t3")
    rows = list_invigilations(client, eid)
    assert rows["total"] == 2
    assert all(i["teacher_name"] == "张老师" for i in rows["items"])


# ── KW-26 巡考 ──────────────────────────────
def test_patrol_crud(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed)
    r = client.post(f"/api/exam/exams/{eid}/patrols", json={
        "exam_date": MONDAY, "teacher_id": seed["t4"].id,
        "scope": "2楼东侧", "note": "重点巡查",
    })
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert r.json()["teacher_name"] == "刘老师"
    assert r.json()["scope"] == "2楼东侧"
    r = client.get(f"/api/exam/exams/{eid}/patrols")
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 1
    r = client.patch(f"/api/exam/exams/{eid}/patrols/{pid}", json={"scope": "2楼东侧、3楼"})
    assert r.status_code == 200, r.text
    assert r.json()["scope"] == "2楼东侧、3楼"
    r = client.delete(f"/api/exam/exams/{eid}/patrols/{pid}")
    assert r.status_code == 204, r.text
    r = client.get(f"/api/exam/exams/{eid}/patrols")
    assert r.json()["total"] == 0


def test_patrol_teacher_only_sees_own(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed)
    client.post(f"/api/exam/exams/{eid}/patrols", json={
        "exam_date": MONDAY, "teacher_id": seed["t3"].id, "scope": "2楼",
    })
    client.post(f"/api/exam/exams/{eid}/patrols", json={
        "exam_date": MONDAY, "teacher_id": seed["t4"].id, "scope": "3楼",
    })
    login(client, "t3")
    r = client.get(f"/api/exam/exams/{eid}/patrols")
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["teacher_name"] == "张老师"


# ── KW-27 监考表两视图 ──────────────────────────────
def test_invigilation_sheets_two_views(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed)
    invigilate(client, eid)
    r = client.get(f"/api/exam/exams/{eid}/invigilation-sheets", params={"view": "teacher"})
    assert r.status_code == 200, r.text
    teachers = r.json()["teachers"]
    assert len(teachers) == 6  # 王老师 0 场,不出现在教师视图
    by_name = {t["teacher_name"]: t for t in teachers}
    assert len(by_name["李老师"]["sessions"]) == 1
    sess = by_name["李老师"]["sessions"][0]
    assert set(sess) == {"subject_name", "exam_date", "start_time", "end_time", "room_name"}
    assert sess["subject_name"] == "语文"
    assert sess["exam_date"] == MONDAY
    assert sess["start_time"] == "10:00" and sess["end_time"] == "11:30"
    r = client.get(f"/api/exam/exams/{eid}/invigilation-sheets", params={"view": "room"})
    assert r.status_code == 200, r.text
    rooms = r.json()["rooms"]
    assert len(rooms) == 2
    by_room = {rm["room_name"]: rm for rm in rooms}
    assert len(by_room["101 教室"]["sessions"]) == 2
    math_sess = next(s for s in by_room["101 教室"]["sessions"]
                     if s["subject_name"] == "数学")
    assert len(math_sess["teachers"]) == 2
    # 按科目过滤
    r = client.get(f"/api/exam/exams/{eid}/invigilation-sheets",
                   params={"view": "teacher", "subject_id": seed["math"].id})
    assert all(s["subject_name"] == "数学"
               for t in r.json()["teachers"] for s in t["sessions"])
    # view 非法 -> 400
    r = client.get(f"/api/exam/exams/{eid}/invigilation-sheets", params={"view": "bad"})
    assert r.status_code == 400, r.text


# ── KW-28 工作量统计 ──────────────────────────────
def test_workload_and_export(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed)
    invigilate(client, eid)
    r = client.get(f"/api/exam/exams/{eid}/invigilation-workload")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 6
    by_name = {i["teacher_name"]: i for i in body["items"]}
    assert by_name["李老师"]["sessions"] == 1
    assert by_name["李老师"]["minutes"] == 90  # 语文 90 分钟 x 1 场
    assert by_name["张老师"]["sessions"] == 2
    assert by_name["张老师"]["minutes"] == 180  # 数学 90 + 语文 90
    assert "王老师" not in by_name
    # 导出 Excel
    r = client.get(f"/api/exam/exams/{eid}/invigilation-workload/export")
    assert r.status_code == 200, r.text
    assert "application/vnd.openxmlformats" in r.headers["content-type"]
    wb = load_workbook(BytesIO(r.content))
    ws = wb.active
    assert [c.value for c in ws[1]] == ["教师", "监考场次", "总时长(分钟)"]
    rows = [[c.value for c in row] for row in ws.iter_rows(min_row=2)]
    assert len(rows) == 6
    assert {tuple(row[1:]) for row in rows} == {(1, 90), (2, 180)}


def test_workload_teacher_only_sees_own(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed)
    invigilate(client, eid)
    login(client, "t3")
    r = client.get(f"/api/exam/exams/{eid}/invigilation-workload")
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["teacher_name"] == "张老师"


# ── KW-29 考风考纪 ──────────────────────────────
def _manual_invigilation(client, eid, seed):
    """王老师手工监考数学 101 考场(张三、李四所在考场)。"""
    r = client.post(f"/api/exam/exams/{eid}/invigilations", json={
        "subject_id": seed["math"].id, "room_id": seed["r1"].id,
        "teacher_id": seed["t1"].id,
    })
    assert r.status_code == 201, r.text


def test_discipline_teacher_create_and_forbidden(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed)
    client.post(f"/api/exam/exams/{eid}/arrange", json={})
    _manual_invigilation(client, eid, seed)
    # 王老师登记本人监考考场的张三 -> 201
    login(client, "t1")
    r = client.post(f"/api/exam/exams/{eid}/discipline", json={
        "subject_id": seed["math"].id, "student_id": seed["s1"].id,
        "type": "作弊", "description": "夹带小抄", "handling": "本科目记零分",
    })
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    assert r.json()["student_name"] == "张三"
    assert r.json()["class_name"] == "701"
    assert r.json()["recorded_by_name"] == "t1"
    # 赵六在 102 考场,不在王老师监考考场 -> 403
    r = client.post(f"/api/exam/exams/{eid}/discipline", json={
        "subject_id": seed["math"].id, "student_id": seed["s4"].id,
        "type": "违纪",
    })
    assert r.status_code == 403, r.text
    # 张老师没有监考数学 -> 403
    login(client, "t3")
    r = client.post(f"/api/exam/exams/{eid}/discipline", json={
        "subject_id": seed["math"].id, "student_id": seed["s1"].id,
        "type": "违纪",
    })
    assert r.status_code == 403, r.text
    # 教务可登记任意参试考生,也可改、删;教师改 -> 403
    login(client, "jiao")
    r = client.patch(f"/api/exam/exams/{eid}/discipline/{did}",
                     json={"handling": "本科目记零分,通报批评"})
    assert r.status_code == 200, r.text
    assert r.json()["handling"] == "本科目记零分,通报批评"
    login(client, "t1")
    r = client.patch(f"/api/exam/exams/{eid}/discipline/{did}",
                     json={"handling": "改"})
    assert r.status_code == 403, r.text
    login(client, "jiao")
    r = client.delete(f"/api/exam/exams/{eid}/discipline/{did}")
    assert r.status_code == 204, r.text
    # 类型非法 -> 400
    r = client.post(f"/api/exam/exams/{eid}/discipline", json={
        "subject_id": seed["math"].id, "student_id": seed["s1"].id,
        "type": "迟到",
    })
    assert r.status_code == 400, r.text


def test_discipline_list_visible_scope(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed)
    r = client.post(f"/api/exam/exams/{eid}/discipline", json={
        "subject_id": seed["math"].id, "student_id": seed["s4"].id,
        "type": "违纪", "description": "交头接耳",
    })
    assert r.status_code == 201, r.text
    # 王老师是 701 班主任,702 班的记录不在其可见班级 -> 看不到
    login(client, "t1")
    r = client.get(f"/api/exam/exams/{eid}/discipline")
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 0
    # 教务全可见
    login(client, "jiao")
    r = client.get(f"/api/exam/exams/{eid}/discipline")
    assert r.json()["total"] == 1


# ── 审计 ──────────────────────────────
def test_audit_logged_for_rule_update(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    eid = setup_exam(client, seed)
    client.put(f"/api/exam/exams/{eid}/invigilation-rule", json={
        "avoid_own_class": True, "avoid_own_subject": False,
        "invigilators_per_room": 2,
    })
    client.post(f"/api/exam/exams/{eid}/invigilate", json={})
    logs = db.query(AuditLog).filter(
        AuditLog.target_type == "exam", AuditLog.target_id == eid
    ).all()
    actions = {log.action for log in logs}
    assert "exam_invigilation_rule_update" in actions
    assert "exam_invigilate" in actions
