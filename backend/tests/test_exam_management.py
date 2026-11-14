"""考试管理测试(KW-08~14):建考、日程冲突、参试名单、状态流转、复制、命题信息、特殊考生安排、权限与审计。

本文件自带 app fixture(挂 auth + exam 路由),因为
conftest 的 env 尚未接线新路由(接线由协调员统一做,见汇报)。
"""

from datetime import date, time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import auth as auth_api
from app.api import exam as exam_api
from app.core.db import Base, get_db
from app.models.assignment import CourseAssignment, SchedulingUnit, SchedulingUnitMember
from app.models.audit import AuditLog
from app.models.basedata import ClassUnit, Subject, Teacher
from app.models.exam import Exam, ExamStatusChange
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
    english = Subject(semester_id=sem.id, name="英语")
    cls7 = ClassUnit(semester_id=sem.id, grade=7, name="701", track="junior_high")
    cls8 = ClassUnit(semester_id=sem.id, grade=8, name="801", track="junior_high")
    db.add_all([math, chinese, english, cls7, cls8])
    db.flush()
    admin = make_user(db, "adm", PW, roles=[Role.admin])
    academic = make_user(db, "jiao", PW, roles=[Role.director])
    t1user = make_user(db, "t1", PW, roles=[Role.teacher])
    t2user = make_user(db, "t2", PW, roles=[Role.teacher])
    t1 = Teacher(semester_id=sem.id, name="王老师", user_id=t1user.id)
    t2 = Teacher(semester_id=sem.id, name="李老师", user_id=t2user.id)
    t3 = Teacher(semester_id=sem.id, name="张老师")
    db.add_all([t1, t2, t3])
    db.flush()
    cls7.homeroom_teacher_id = t1.id
    cls8.homeroom_teacher_id = t2.id
    db.flush()
    s1 = Student(semester_id=sem.id, class_unit_id=cls7.id, student_no="20260101", name="张三", gender="男")
    s2 = Student(semester_id=sem.id, class_unit_id=cls7.id, student_no="20260102", name="李四", gender="女")
    s3 = Student(semester_id=sem.id, class_unit_id=cls8.id, student_no="20260201", name="王五", gender="男")
    s4 = Student(semester_id=sem.id, class_unit_id=cls7.id, student_no="20260103", name="赵六", gender="男", status="休学")
    s5 = Student(semester_id=sem.id, class_unit_id=cls8.id, student_no="20260202", name="钱七", gender="女", status="毕业")
    db.add_all([s1, s2, s3, s4, s5])
    db.commit()
    return {
        "sem": sem, "math": math, "chinese": chinese, "english": english,
        "cls7": cls7, "cls8": cls8,
        "admin": admin, "academic": academic,
        "t1": t1user, "t2": t2user, "t1t": t1, "t2t": t2, "t3t": t3,
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
        "description": "第一次月考",
    }
    body.update(over)
    r = client.post("/api/exam/exams", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def put_subjects(client, exam_id, subjects):
    r = client.put(f"/api/exam/exams/{exam_id}/subjects", json={"subjects": subjects})
    assert r.status_code == 200, r.text
    return r.json()


# ── KW-08 建考 ──────────────────────────────
def test_create_exam_201_draft_and_audit(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    body = make_exam(client, seed)
    assert body["status"] == "草稿"
    assert body["grades"] == [7]
    assert body["exam_type"] == "月考"
    assert body["semester_id"] == seed["sem"].id
    assert db.query(AuditLog).filter_by(action="exam_create").count() == 1
    # 详情含科目(空)与参试人数(0)
    detail = client.get(f"/api/exam/exams/{body['id']}").json()
    assert detail["subjects"] == []
    assert detail["participant_count"] == 0


def test_create_exam_invalid_type_400(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    r = client.post("/api/exam/exams", json={
        "semester_id": seed["sem"].id, "name": "坏类型",
        "exam_type": "随堂考", "grades": [7],
    })
    assert r.status_code == 400


def test_create_exam_teacher_403(client_db, seed):
    client, db = client_db
    login(client, "t1")
    r = client.post("/api/exam/exams", json={
        "semester_id": seed["sem"].id, "name": "越权",
        "exam_type": "月考", "grades": [7],
    })
    assert r.status_code == 403


def test_list_exams_filters_and_teacher_scope(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    e7 = make_exam(client, seed)
    e8 = make_exam(client, seed, name="八年级月考", grades=[8])
    assert client.get("/api/exam/exams").json()["total"] == 2
    assert client.get(f"/api/exam/exams?semester_id={seed['sem'].id}&status=草稿").json()["total"] == 2
    assert client.get("/api/exam/exams?q=八年级").json()["total"] == 1
    # t1 只看得到 701(7 年级)的考试,看不到 8 年级考试
    login(client, "t1")
    body = client.get("/api/exam/exams").json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == e7["id"]
    assert client.get(f"/api/exam/exams/{e8['id']}").status_code == 403


# ── KW-08 草稿可改 / 非草稿 409 ──────────────────────────────
def test_patch_draft_ok_and_nondraft_409(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    exam = make_exam(client, seed)
    eid = exam["id"]
    r = client.patch(f"/api/exam/exams/{eid}", json={"name": "改名后的月考", "grades": [7, 8]})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "改名后的月考"
    assert r.json()["grades"] == [7, 8]
    assert db.query(AuditLog).filter_by(action="exam_update").count() == 1
    # 发布后就不能再改
    assert client.post(f"/api/exam/exams/{eid}/status", json={"to_status": "已发布"}).status_code == 200
    r = client.patch(f"/api/exam/exams/{eid}", json={"name": "再改"})
    assert r.status_code == 409


# ── KW-11 状态流转 ──────────────────────────────
def test_status_flow_forward_only_and_rollback(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    exam = make_exam(client, seed)
    eid = exam["id"]
    # 跳级前进被挡
    r = client.post(f"/api/exam/exams/{eid}/status", json={"to_status": "进行中"})
    assert r.status_code == 400
    # 按顺序走完全程
    for nxt in ["已发布", "进行中", "成绩处理中", "已发布成绩", "已归档"]:
        r = client.post(f"/api/exam/exams/{eid}/status", json={"to_status": nxt})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == nxt
    # 已归档后无下一步
    assert client.post(f"/api/exam/exams/{eid}/status", json={"to_status": "已发布"}).status_code == 200  # 回退允许(admin/director)
    recs = db.query(ExamStatusChange).filter_by(exam_id=eid).order_by(ExamStatusChange.id).all()
    assert [r.to_status for r in recs] == ["草稿", "已发布", "进行中", "成绩处理中", "已发布成绩", "已归档", "已发布"]
    assert recs[1].from_status == "草稿" and recs[-1].from_status == "已归档"
    assert db.query(AuditLog).filter_by(action="exam_status_change").count() == 6


def test_status_rollback_teacher_forbidden(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    exam = make_exam(client, seed)
    eid = exam["id"]
    client.post(f"/api/exam/exams/{eid}/status", json={"to_status": "已发布"})
    # 教师连写接口都进不去(403);且同一状态流转被挡
    login(client, "t1")
    assert client.post(f"/api/exam/exams/{eid}/status", json={"to_status": "草稿"}).status_code == 403
    login(client, "jiao")
    assert client.post(f"/api/exam/exams/{eid}/status", json={"to_status": "已发布"}).status_code == 400


# ── KW-12 复制 ──────────────────────────────
def test_copy_exam_copies_subjects_not_participants(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    exam = make_exam(client, seed)
    eid = exam["id"]
    put_subjects(client, eid, [
        {"subject_id": seed["math"].id, "exam_date": MONDAY, "start_time": "08:00", "end_time": "09:30", "full_score": 120},
        {"subject_id": seed["chinese"].id, "exam_date": MONDAY, "start_time": "10:00", "end_time": "11:30"},
    ])
    client.post(f"/api/exam/exams/{eid}/participants/generate")
    r = client.post(f"/api/exam/exams/{eid}/copy", json={"name": "七年级 12 月月考"})
    assert r.status_code == 201, r.text
    new = r.json()
    assert new["status"] == "草稿"
    assert new["grades"] == [7]
    assert new["exam_type"] == "月考"
    detail = client.get(f"/api/exam/exams/{new['id']}").json()
    assert len(detail["subjects"]) == 2
    assert {s["subject_id"] for s in detail["subjects"]} == {seed["math"].id, seed["chinese"].id}
    assert detail["subjects"][0]["full_score"] == 120
    assert detail["participant_count"] == 0  # 名单不复制
    assert db.query(AuditLog).filter_by(action="exam_copy").count() == 1


# ── KW-09 日程与冲突 ──────────────────────────────
def test_subjects_upsert_and_nondraft_409(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    exam = make_exam(client, seed)
    eid = exam["id"]
    body = put_subjects(client, eid, [
        {"subject_id": seed["math"].id, "exam_date": MONDAY, "start_time": "08:00", "end_time": "09:30", "full_score": 100},
    ])
    assert body["items"][0]["subject_name"] == "数学"
    assert body["items"][0]["exam_date"] == MONDAY
    # 结束早于开始被挡
    r = client.put(f"/api/exam/exams/{eid}/subjects", json={"subjects": [
        {"subject_id": seed["math"].id, "exam_date": MONDAY, "start_time": "09:30", "end_time": "08:00"},
    ]})
    assert r.status_code == 400
    client.post(f"/api/exam/exams/{eid}/status", json={"to_status": "已发布"})
    r = client.put(f"/api/exam/exams/{eid}/subjects", json={"subjects": [
        {"subject_id": seed["math"].id, "exam_date": MONDAY, "start_time": "08:00", "end_time": "09:30"},
    ]})
    assert r.status_code == 409


def test_schedule_check_subject_overlap(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    exam = make_exam(client, seed)
    eid = exam["id"]
    put_subjects(client, eid, [
        {"subject_id": seed["math"].id, "exam_date": MONDAY, "start_time": "08:00", "end_time": "09:30"},
        {"subject_id": seed["chinese"].id, "exam_date": MONDAY, "start_time": "09:00", "end_time": "10:30"},
        {"subject_id": seed["english"].id, "exam_date": "2026-11-17", "start_time": "08:00", "end_time": "09:30"},
    ])
    body = client.post(f"/api/exam/exams/{eid}/schedule-check").json()
    assert len(body["conflicts"]) == 2  # 数学与语文互相提示,英语不同日不冲突
    assert {c["subject_name"] for c in body["conflicts"]} == {"数学", "语文"}
    assert all("重叠" in c["reason"] for c in body["conflicts"])


def test_schedule_check_published_timetable_conflict(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    sem = seed["sem"]
    # 节次表:周一第 2 节 08:50-09:35
    table = PeriodTable(semester_id=sem.id, name="默认节次表", is_default=True)
    db.add(table)
    db.flush()
    db.add(Period(period_table_id=table.id, weekday=1, period_no=2, name="第二节",
                  start_time=time(8, 50), end_time=time(9, 35), type="regular"))
    seed["cls7"].period_table_id = table.id
    # 已发布课表:701 班周一第 2 节数学课
    unit = SchedulingUnit(semester_id=sem.id, unit_type="single", name="701")
    db.add(unit)
    db.flush()
    db.add(SchedulingUnitMember(scheduling_unit_id=unit.id, class_unit_id=seed["cls7"].id))
    assign = CourseAssignment(semester_id=sem.id, scheduling_unit_id=unit.id,
                              subject_id=seed["math"].id, periods_per_week=4)
    db.add(assign)
    db.flush()
    tt = Timetable(semester_id=sem.id, name="2026 秋课表", status="published")
    db.add(tt)
    db.flush()
    db.add(ScheduleEntry(timetable_id=tt.id, course_assignment_id=assign.id, weekday=1, period_no=2))
    db.commit()
    exam = make_exam(client, seed)
    eid = exam["id"]
    put_subjects(client, eid, [
        {"subject_id": seed["chinese"].id, "exam_date": MONDAY, "start_time": "09:00", "end_time": "10:30"},
    ])
    body = client.post(f"/api/exam/exams/{eid}/schedule-check").json()
    assert len(body["conflicts"]) == 1
    assert body["conflicts"][0]["subject_name"] == "语文"
    assert "已发布课表" in body["conflicts"][0]["reason"]
    assert "701" in body["conflicts"][0]["reason"]


def test_schedule_check_no_published_timetable_only_subjects(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    exam = make_exam(client, seed)
    eid = exam["id"]
    put_subjects(client, eid, [
        {"subject_id": seed["math"].id, "exam_date": MONDAY, "start_time": "08:00", "end_time": "09:30"},
        {"subject_id": seed["chinese"].id, "exam_date": MONDAY, "start_time": "10:00", "end_time": "11:30"},
    ])
    body = client.post(f"/api/exam/exams/{eid}/schedule-check").json()
    assert body["conflicts"] == []  # 无已发布课表时只查科间冲突,无重叠即无提示


# ── KW-10 参试名单 ──────────────────────────────
def test_participant_generate_idempotent_and_excludes_non_active(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    exam = make_exam(client, seed)
    eid = exam["id"]
    r = client.post(f"/api/exam/exams/{eid}/participants/generate")
    assert r.status_code == 200, r.text
    assert r.json() == {"created": 2, "skipped": 0}  # 只含在读张三、李四;休学赵六不进
    r = client.post(f"/api/exam/exams/{eid}/participants/generate")
    assert r.json() == {"created": 0, "skipped": 2}  # 重复生成不产生重复名单
    body = client.get(f"/api/exam/exams/{eid}/participants").json()
    assert body["total"] == 2
    assert {i["student_name"] for i in body["items"]} == {"张三", "李四"}
    assert all(i["status"] == "正常" for i in body["items"])
    assert db.query(AuditLog).filter_by(action="exam_participant_generate").count() == 2


def test_participant_add_patch_delete(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    exam = make_exam(client, seed)
    eid = exam["id"]
    client.post(f"/api/exam/exams/{eid}/participants/generate")
    # 个别增补休学学生赵六
    r = client.post(f"/api/exam/exams/{eid}/participants",
                    json={"student_id": seed["s4"].id, "note": "休学返校参考"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert r.json()["student_name"] == "赵六"
    # 重复增补 409
    assert client.post(f"/api/exam/exams/{eid}/participants",
                       json={"student_id": seed["s4"].id}).status_code == 409
    # 预标记缺考
    r = client.patch(f"/api/exam/exams/{eid}/participants/{pid}", json={"status": "缺考"})
    assert r.status_code == 200
    assert r.json()["status"] == "缺考"
    assert r.json()["note"] == "休学返校参考"
    # 非法状态 400
    assert client.patch(f"/api/exam/exams/{eid}/participants/{pid}",
                        json={"status": "请假"}).status_code == 400
    # 删除
    assert client.delete(f"/api/exam/exams/{eid}/participants/{pid}").status_code == 204
    assert client.get(f"/api/exam/exams/{eid}/participants").json()["total"] == 2
    assert db.query(AuditLog).filter_by(action="exam_participant_update").count() == 3


def test_participant_list_scoped_for_teacher(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    exam = make_exam(client, seed, grades=[7, 8])
    eid = exam["id"]
    client.post(f"/api/exam/exams/{eid}/participants/generate")
    # t1 只看得到 701 班名单
    login(client, "t1")
    body = client.get(f"/api/exam/exams/{eid}/participants").json()
    assert body["total"] == 2
    assert {i["class_name"] for i in body["items"]} == {"701"}
    # 显式筛 801 班直接 403
    assert client.get(f"/api/exam/exams/{eid}/participants?class_unit_id={seed['cls8'].id}").status_code == 403
    # 教师不能写名单
    assert client.post(f"/api/exam/exams/{eid}/participants/generate").status_code == 403


def test_participant_list_multi_class_filter(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    exam = make_exam(client, seed, grades=[7, 8])
    eid = exam["id"]
    client.post(f"/api/exam/exams/{eid}/participants/generate")
    # 一次勾两个班:701 两人 + 801 一人
    body = client.get(
        f"/api/exam/exams/{eid}/participants"
        f"?class_unit_ids={seed['cls7'].id}&class_unit_ids={seed['cls8'].id}"
    ).json()
    assert body["total"] == 3
    assert {i["student_name"] for i in body["items"]} == {"张三", "李四", "王五"}
    # 只勾一个班仍只回该班
    body = client.get(
        f"/api/exam/exams/{eid}/participants?class_unit_ids={seed['cls7'].id}"
    ).json()
    assert body["total"] == 2
    # 旧的单个 class_unit_id 参数仍可用
    body = client.get(
        f"/api/exam/exams/{eid}/participants?class_unit_id={seed['cls8'].id}"
    ).json()
    assert body["total"] == 1
    assert body["items"][0]["student_name"] == "王五"
    # 教师多选里混进无权看的班直接 403
    login(client, "t1")
    assert client.get(
        f"/api/exam/exams/{eid}/participants"
        f"?class_unit_ids={seed['cls7'].id}&class_unit_ids={seed['cls8'].id}"
    ).status_code == 403


def test_participant_bulk_add(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    exam = make_exam(client, seed)
    eid = exam["id"]
    client.post(f"/api/exam/exams/{eid}/participants/generate")  # 张三、李四已在名单
    # 一次勾三个:休学赵六(新增)、801 班王五(新增,同学期可增补)、张三(已在名单,跳过)
    r = client.post(f"/api/exam/exams/{eid}/participants/bulk", json={
        "student_ids": [seed["s4"].id, seed["s3"].id, seed["s1"].id],
        "note": "批量增补",
    })
    assert r.status_code == 200, r.text
    assert r.json() == {"created": 2, "skipped": 1}
    body = client.get(f"/api/exam/exams/{eid}/participants").json()
    assert body["total"] == 4
    added = [i for i in body["items"] if i["student_name"] in ("赵六", "王五")]
    assert len(added) == 2
    assert all(i["note"] == "批量增补" for i in added)
    # 同一批里重复勾同一人只算一次
    r = client.post(f"/api/exam/exams/{eid}/participants/bulk", json={
        "student_ids": [seed["s4"].id, seed["s4"].id],
    })
    assert r.json() == {"created": 0, "skipped": 1}
    # 不存在的学生计入跳过,不中断整批
    r = client.post(f"/api/exam/exams/{eid}/participants/bulk", json={
        "student_ids": [999999, seed["s5"].id],
    })
    assert r.json() == {"created": 1, "skipped": 1}
    # 空列表 422
    assert client.post(f"/api/exam/exams/{eid}/participants/bulk",
                       json={"student_ids": []}).status_code == 422
    # 单人增补端点保留不动,仍 201/409
    assert client.post(f"/api/exam/exams/{eid}/participants",
                       json={"student_id": seed["s5"].id}).status_code == 409
    assert db.query(AuditLog).filter_by(action="exam_participant_update").count() == 3


# ── KW-13 命题信息 ──────────────────────────────
def test_paper_info_upsert(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    exam = make_exam(client, seed)
    eid = exam["id"]
    r = client.put(f"/api/exam/exams/{eid}/paper-info", json={"items": [
        {"subject_id": seed["math"].id, "setter_teacher_id": seed["t1t"].id,
         "reviewer_teacher_id": seed["t2t"].id, "paper_count": 60},
        {"subject_id": seed["chinese"].id, "setter_teacher_id": seed["t3t"].id, "paper_count": 58},
    ]})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 2
    math_row = next(i for i in items if i["subject_id"] == seed["math"].id)
    assert math_row["setter_teacher_name"] == "王老师"
    assert math_row["reviewer_teacher_name"] == "李老师"
    assert math_row["paper_count"] == 60
    # upsert 更新同一科
    r = client.put(f"/api/exam/exams/{eid}/paper-info", json={"items": [
        {"subject_id": seed["math"].id, "setter_teacher_id": seed["t1t"].id,
         "reviewer_teacher_id": seed["t2t"].id, "paper_count": 62},
    ]})
    assert r.status_code == 200
    assert len(r.json()["items"]) == 2
    math_row = next(i for i in r.json()["items"] if i["subject_id"] == seed["math"].id)
    assert math_row["paper_count"] == 62
    assert db.query(AuditLog).filter_by(action="exam_paper_info_update").count() == 2


# ── KW-14 特殊考生安排 ──────────────────────────────
def test_special_arrangement_crud_and_privacy(client_db, seed):
    client, db = client_db
    login(client, "jiao")
    exam = make_exam(client, seed, grades=[7, 8])  # 联考:t2 能看到考试,但名单按班级过滤
    eid = exam["id"]
    r = client.post(f"/api/exam/exams/{eid}/special-arrangements", json={
        "student_id": seed["s1"].id, "arrangement_type": "延长时限", "detail": "延长 30 分钟",
    })
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert r.json()["status"] == "已登记"
    assert r.json()["student_name"] == "张三"
    # 同学生同类安排重复 409
    assert client.post(f"/api/exam/exams/{eid}/special-arrangements", json={
        "student_id": seed["s1"].id, "arrangement_type": "延长时限",
    }).status_code == 409
    # 改为已安排
    r = client.patch(f"/api/exam/exams/{eid}/special-arrangements/{sid}",
                     json={"status": "已安排"})
    assert r.status_code == 200
    assert r.json()["status"] == "已安排"
    # t2(801 班主任)看不到 701 学生的特殊安排;t1(701 班主任)看得到
    login(client, "t2")
    assert client.get(f"/api/exam/exams/{eid}/special-arrangements").json()["items"] == []
    login(client, "t1")
    rows = client.get(f"/api/exam/exams/{eid}/special-arrangements").json()["items"]
    assert len(rows) == 1 and rows[0]["student_name"] == "张三"
    # 教师不能写
    assert client.post(f"/api/exam/exams/{eid}/special-arrangements", json={
        "student_id": seed["s2"].id, "arrangement_type": "单独考场",
    }).status_code == 403
    login(client, "jiao")
    assert client.delete(f"/api/exam/exams/{eid}/special-arrangements/{sid}").status_code == 204
    assert client.get(f"/api/exam/exams/{eid}/special-arrangements").json()["items"] == []
    assert db.query(AuditLog).filter_by(action="exam_special_arrangement_create").count() == 1
    assert db.query(AuditLog).filter_by(action="exam_special_arrangement_update").count() == 1
    assert db.query(AuditLog).filter_by(action="exam_special_arrangement_delete").count() == 1


# ── 审计登记册 ──────────────────────────────
def test_exam_audit_actions_registered():
    from app.services.exam_audit import EXAM_AUDIT_ACTIONS

    assert {
        "exam_create", "exam_update", "exam_status_change", "exam_copy",
        "exam_subject_update", "exam_participant_generate", "exam_participant_update",
        "exam_paper_info_update", "exam_special_arrangement_create",
        "exam_special_arrangement_update", "exam_special_arrangement_delete",
    } <= set(EXAM_AUDIT_ACTIONS)
