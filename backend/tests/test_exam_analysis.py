"""成绩分析测试(KW-41~51):汇总均分/标准差、排名并列两种规则、及格优秀率与
阈值覆盖、分段分布、临界生筛选、目标生达标与短板、进退步无上次考试提示、
质量对比越权 403、趋势排序、等第转换、报表包。

本文件自带 app fixture(挂 auth + exam + exam_scores + exam_analysis 路由),
因为 conftest 的 env 尚未接线新路由(接线由协调员统一做,见汇报)。
"""

from datetime import date
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
from app.api import exam_analysis as analysis_api
from app.api import exam_scores as scores_api
from app.core.db import Base, get_db
from app.models.assignment import (
    AssignmentTeacher,
    CourseAssignment,
    SchedulingUnit,
    SchedulingUnitMember,
)
# noqa: F401 仅为建表:成绩录入锁定检查与本批新表须先 import 对应模型,
# Base.metadata.create_all 才会建这些表。
from app.models import exam_analysis, exam_publish  # noqa: F401
from app.models.audit import AuditLog
from app.models.basedata import ClassUnit, Subject, Teacher
from app.models.exam_foundation import Student
from app.models.semester import Semester
from app.models.user import Role, UserGradeScope
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
# 上次考试成绩(数学/语文):s1 80/70=150, s2 90/80=170, s3 70/50=120,
# s4 60/50=110, s5 70/60=130, s6 30/30=60。
PREV_SCORES = {
    "s1": (80, 70), "s2": (90, 80), "s3": (70, 50),
    "s4": (60, 50), "s5": (70, 60), "s6": (30, 30),
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
    app.include_router(analysis_api.router, prefix="/api/exam")
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
    leader7 = make_user(db, "leader7", PW, roles=[Role.director])
    db.add(UserGradeScope(user_id=leader7.id, grade=7))
    leader8 = make_user(db, "leader8", PW, roles=[Role.director])
    db.add(UserGradeScope(user_id=leader8.id, grade=8))
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
    db.commit()
    return {
        "sem": sem, "math": math, "chinese": chinese,
        "cls701": cls701, "cls702": cls702,
        "admin": admin, "academic": academic,
        "leader7": leader7, "leader8": leader8,
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


# ── KW-41 汇总 ──────────────────────────────
def test_summary_grade_totals_and_subject_stats(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_scored_exam(client, seed)
    body = client.get(f"/api/exam/exams/{eid}/analysis/summary?scope=grade").json()
    assert body["scope"] == "grade"
    # 总分 170/160/140/140/100/50:均分 126.67,最高 170,最低 50
    assert body["totals"]["count"] == 6
    assert body["totals"]["avg"] == pytest.approx(126.67)
    assert body["totals"]["max"] == 170
    assert body["totals"]["min"] == 50
    assert body["totals"]["std"] == pytest.approx(40.69, abs=0.05)
    by_subject = {s["subject_name"]: s for s in body["subjects"]}
    math = by_subject["数学"]
    # 数学缺考 1 人不计入:90/80/80/70/60,均分 76,标准差 10.2
    assert math["count"] == 5
    assert math["avg"] == 76
    assert math["max"] == 90 and math["min"] == 60
    assert math["std"] == pytest.approx(10.2, abs=0.05)
    assert math["pass_rate"] == 100 and math["excellent_rate"] == 20
    assert math["low_rate"] == 0
    chinese = by_subject["语文"]
    assert chinese["count"] == 6
    assert chinese["avg"] == pytest.approx(63.33)
    assert chinese["pass_rate"] == pytest.approx(66.67)
    assert chinese["excellent_rate"] == 0
    assert chinese["low_rate"] == pytest.approx(33.33)


def test_summary_class_scope_and_absent_counts(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_scored_exam(client, seed)
    body = client.get(
        f"/api/exam/exams/{eid}/analysis/summary?scope=class"
        f"&class_unit_id={seed['cls701'].id}"
    ).json()
    assert body["scope"] == "class"
    assert body["totals"]["count"] == 4
    assert body["totals"]["avg"] == pytest.approx(142.5)
    # 缺考计入时数学按 0 分计:6 人均分 63.33
    client.put(f"/api/exam/exams/{eid}/score-settings", json={
        "entry_mode": "total_only", "makeup_mode": "separate",
        "cheating_score_mode": "zero", "absent_counts": True,
        "score_deadline": None,
    })
    body = client.get(f"/api/exam/exams/{eid}/analysis/summary?scope=grade").json()
    math = next(s for s in body["subjects"] if s["subject_name"] == "数学")
    assert math["count"] == 6
    assert math["avg"] == pytest.approx(63.33)


# ── KW-42 排名 ──────────────────────────────
def test_rankings_dense_default_and_competition(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_scored_exam(client, seed)
    # 总分 dense:170/160/140/140/100/50 -> 1/2/3/3/4/5
    body = client.get(f"/api/exam/exams/{eid}/analysis/rankings?scope=grade").json()
    assert body["total"] == 6
    ranks = {i["student_no"]: i["rank"] for i in body["items"]}
    assert ranks == {
        "20260101": 1, "20260102": 2, "20260103": 3,
        "20260201": 3, "20260104": 4, "20260202": 5,
    }
    # 数学 dense:90/80/80/70/60 -> 1/2/2/3/4(缺考不进排名)
    body = client.get(
        f"/api/exam/exams/{eid}/analysis/rankings?scope=grade"
        f"&subject_id={seed['math'].id}"
    ).json()
    assert body["total"] == 5
    ranks = {i["student_no"]: i["rank"] for i in body["items"]}
    assert ranks == {
        "20260101": 1, "20260102": 2, "20260103": 2,
        "20260201": 3, "20260104": 4,
    }
    # 切 competition:总分 1/2/3/3/5/6,数学 1/2/2/4/5
    r = client.put(f"/api/exam/exams/{eid}/analysis-settings", json={
        "rank_tie_rule": "competition", "segment_size": 10,
        "critical_total_line": None, "critical_margin": 5,
        "subject_critical_margin": 5,
    })
    assert r.status_code == 200, r.text
    assert r.json()["rank_tie_rule"] == "competition"
    body = client.get(f"/api/exam/exams/{eid}/analysis/rankings?scope=grade").json()
    ranks = {i["student_no"]: i["rank"] for i in body["items"]}
    assert ranks["20260201"] == 3 and ranks["20260104"] == 5 and ranks["20260202"] == 6
    body = client.get(
        f"/api/exam/exams/{eid}/analysis/rankings?scope=grade"
        f"&subject_id={seed['math'].id}"
    ).json()
    ranks = {i["student_no"]: i["rank"] for i in body["items"]}
    assert ranks == {
        "20260101": 1, "20260102": 2, "20260103": 2,
        "20260201": 4, "20260104": 5,
    }
    # 班级排名:701 班内总分 170/160/140/100 -> 1/2/3/4
    body = client.get(
        f"/api/exam/exams/{eid}/analysis/rankings?scope=class"
        f"&class_unit_id={seed['cls701'].id}"
    ).json()
    assert body["total"] == 4
    ranks = {i["student_no"]: i["rank"] for i in body["items"]}
    assert ranks == {
        "20260101": 1, "20260102": 2, "20260103": 3, "20260104": 4,
    }
    assert db.query(AuditLog).filter_by(action="exam_analysis_settings_update").count() == 1


def test_analysis_settings_defaults(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_exam(client, seed)
    body = client.get(f"/api/exam/exams/{eid}/analysis-settings").json()
    assert body == {
        "exam_id": eid, "rank_tie_rule": "dense", "segment_size": 10,
        "critical_total_line": None, "critical_margin": 5,
        "subject_critical_margin": 5,
    }
    assert client.put(f"/api/exam/exams/{eid}/analysis-settings", json={
        "rank_tie_rule": "bad", "segment_size": 10,
        "critical_total_line": None, "critical_margin": 5,
        "subject_critical_margin": 5,
    }).status_code == 400
    login(client, "t1")
    assert client.put(f"/api/exam/exams/{eid}/analysis-settings", json={
        "rank_tie_rule": "dense", "segment_size": 10,
        "critical_total_line": None, "critical_margin": 5,
        "subject_critical_margin": 5,
    }).status_code == 403


# ── KW-43 阈值覆盖 ──────────────────────────────
def test_threshold_override_changes_rates(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_scored_exam(client, seed)
    assert client.get(f"/api/exam/exams/{eid}/subject-thresholds").json() == {"items": []}
    r = client.put(f"/api/exam/exams/{eid}/subject-thresholds", json={"items": [
        {"subject_id": seed["math"].id, "pass_line": 70, "excellent_line": 90},
    ]})
    assert r.status_code == 200, r.text
    assert r.json()["items"][0]["subject_name"] == "数学"
    assert r.json()["items"][0]["pass_line"] == 70
    # 数学及格线 70:90/80/80/70 及格 4/5=80%,优秀线 90:1/5=20%
    body = client.get(f"/api/exam/exams/{eid}/analysis/summary?scope=grade").json()
    math = next(s for s in body["subjects"] if s["subject_name"] == "数学")
    assert math["pass_rate"] == 80
    assert math["excellent_rate"] == 20
    assert math["low_rate"] == 20
    # 语文未覆盖,仍按默认 60/85
    chinese = next(s for s in body["subjects"] if s["subject_name"] == "语文")
    assert chinese["pass_rate"] == pytest.approx(66.67)
    assert db.query(AuditLog).filter_by(action="exam_subject_threshold_update").count() == 1


# ── KW-44 分段 ──────────────────────────────
def test_segments_total_and_subject(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_scored_exam(client, seed)
    body = client.get(f"/api/exam/exams/{eid}/analysis/segments").json()
    by_label = {s["label"]: s for s in body["segments"]}
    assert by_label["140-150"]["count"] == 2
    assert by_label["140-150"]["pct"] == pytest.approx(33.33)
    assert by_label["170-180"]["count"] == 1
    assert by_label["50-60"]["count"] == 1
    assert by_label["0-10"]["count"] == 0
    assert len(body["segments"]) == 20  # 总分满分 200,每 10 分一段
    # 单科分段:数学 90-100 段 1 人,80-90 段 2 人
    body = client.get(
        f"/api/exam/exams/{eid}/analysis/segments?subject_id={seed['math'].id}"
    ).json()
    by_label = {s["label"]: s for s in body["segments"]}
    assert by_label["90-100"]["count"] == 1
    assert by_label["80-90"]["count"] == 2
    assert len(body["segments"]) == 10
    # 分段粒度改为 20:总分 0-200 共 10 段,140-160 段 2 人
    client.put(f"/api/exam/exams/{eid}/analysis-settings", json={
        "rank_tie_rule": "dense", "segment_size": 20,
        "critical_total_line": None, "critical_margin": 5,
        "subject_critical_margin": 5,
    })
    body = client.get(f"/api/exam/exams/{eid}/analysis/segments").json()
    assert len(body["segments"]) == 10
    by_label = {s["label"]: s for s in body["segments"]}
    assert by_label["140-160"]["count"] == 2


# ── KW-45 临界生 ──────────────────────────────
def test_critical_students(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_scored_exam(client, seed)
    # 未设总分临界线时只出单科临界:数学 60 分(s4,距及格线 0)、语文 60 分(s3)
    body = client.get(f"/api/exam/exams/{eid}/analysis/critical").json()
    nos = {i["student_no"] for i in body["items"]}
    assert nos == {"20260103", "20260104"}
    s4 = next(i for i in body["items"] if i["student_no"] == "20260104")
    assert s4["gap_to_line"] is None
    assert s4["subject_gaps"] == [
        {"subject_name": "数学", "score": 60, "gap": 0}
    ]
    # 设总分临界线 145、浮动 5:总分 140 的 s3、s5 进入临界
    client.put(f"/api/exam/exams/{eid}/analysis-settings", json={
        "rank_tie_rule": "dense", "segment_size": 10,
        "critical_total_line": 145, "critical_margin": 5,
        "subject_critical_margin": 5,
    })
    body = client.get(f"/api/exam/exams/{eid}/analysis/critical").json()
    nos = {i["student_no"] for i in body["items"]}
    assert nos == {"20260103", "20260104", "20260201"}
    s5 = next(i for i in body["items"] if i["student_no"] == "20260201")
    assert s5["total"] == 140 and s5["gap_to_line"] == -5
    assert s5["subject_gaps"] == []


# ── KW-46 目标生 ──────────────────────────────
def test_target_students_tracking(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_scored_exam(client, seed)
    r = client.post(f"/api/exam/exams/{eid}/target-students", json={
        "student_id": seed["s1"].id, "target_total": 170, "note": "冲刺",
    })
    assert r.status_code == 201, r.text
    assert r.json()["student_no"] == "20260101"
    assert r.json()["class_name"] == "701"
    # 重复加同一学生 409;不在参试名单的学生 404
    assert client.post(f"/api/exam/exams/{eid}/target-students", json={
        "student_id": seed["s1"].id, "target_total": 170,
    }).status_code == 409
    client.post(f"/api/exam/exams/{eid}/target-students", json={
        "student_id": seed["s4"].id, "target_total": 150,
    })
    client.post(f"/api/exam/exams/{eid}/target-students", json={
        "student_id": seed["s6"].id, "target_total": 100,
    })
    body = client.get(f"/api/exam/exams/{eid}/analysis/target-tracking").json()
    by_no = {i["student_no"]: i for i in body["items"]}
    assert by_no["20260101"]["reached"] is True
    assert by_no["20260101"]["weak_subjects"] == []
    assert by_no["20260104"]["reached"] is False
    assert by_no["20260104"]["total"] == 100
    assert by_no["20260104"]["weak_subjects"] == ["语文"]
    assert by_no["20260202"]["weak_subjects"] == ["语文"]  # 缺考数学不算短板
    # 删除目标生
    tid = client.get(f"/api/exam/exams/{eid}/target-students").json()["items"][0]["id"]
    assert client.delete(f"/api/exam/exams/{eid}/target-students/{tid}").status_code == 204
    assert len(client.get(f"/api/exam/exams/{eid}/target-students").json()["items"]) == 2
    assert db.query(AuditLog).filter_by(action="exam_target_student_create").count() == 3
    assert db.query(AuditLog).filter_by(action="exam_target_student_delete").count() == 1
    # 教师不能维护目标生
    login(client, "t1")
    assert client.post(f"/api/exam/exams/{eid}/target-students", json={
        "student_id": seed["s2"].id, "target_total": 160,
    }).status_code == 403


# ── KW-47 进退步 ──────────────────────────────
def test_progress_no_previous_exam_message(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_scored_exam(client, seed)
    body = client.get(f"/api/exam/exams/{eid}/analysis/progress").json()
    assert body["items"] == []
    assert body["top_improved"] == [] and body["top_declined"] == []
    assert body["message"] == "暂无上次同类考试，无法对比"


def test_progress_with_previous_exam(client_db, seed):
    client, db = client_db
    login(client, "adm")
    prev = setup_scored_exam(client, seed, name="七年级 10 月月考", table=PREV_SCORES)
    advance_to_published_scores(client, prev)
    eid = setup_scored_exam(client, seed, name="七年级 11 月月考")
    body = client.get(f"/api/exam/exams/{eid}/analysis/progress").json()
    assert body["message"] is None
    assert len(body["items"]) == 6
    by_no = {i["student_no"]: i for i in body["items"]}
    # 上次年级排名:s2 1、s1 2、s5 3、s3 4、s4 5、s6 6;
    # 本次:s1 1、s2 2、s3 3、s5 3、s4 4、s6 5
    assert by_no["20260101"]["prev_rank"] == 2 and by_no["20260101"]["rank"] == 1
    assert by_no["20260101"]["delta"] == 1
    assert by_no["20260101"]["prev_total"] == 150 and by_no["20260101"]["total"] == 170
    assert by_no["20260102"]["delta"] == -1
    assert by_no["20260103"]["delta"] == 1
    # 进步榜 4 人(均为 +1),退步榜只有 s2
    assert len(body["top_improved"]) == 4
    assert all(i["delta"] == 1 for i in body["top_improved"])
    assert [i["student_no"] for i in body["top_declined"]] == ["20260102"]


# ── KW-48 质量对比 ──────────────────────────────
def test_quality_compare_roles(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_scored_exam(client, seed)
    body = client.get(f"/api/exam/exams/{eid}/analysis/quality-compare").json()
    math = next(s for s in body["subjects"] if s["subject_name"] == "数学")
    by_class = {c["class_name"]: c for c in math["classes"]}
    assert by_class["701"]["avg"] == 77.5  # 701 数学 90/80/80/60
    assert by_class["702"]["avg"] == 70  # 702 数学 70,缺考不计入
    assert by_class["701"]["pass_rate"] == 100
    classes = {c["class_name"]: c for c in body["classes"]}
    assert classes["701"]["subjects"][0]["subject_name"] == "数学"
    # 任课教师 403;年级组长本年级可看,跨年级 403
    login(client, "t1")
    assert client.get(f"/api/exam/exams/{eid}/analysis/quality-compare").status_code == 403
    login(client, "leader8")
    assert client.get(
        f"/api/exam/exams/{eid}/analysis/quality-compare?grade=7"
    ).status_code == 403
    login(client, "leader7")
    assert client.get(
        f"/api/exam/exams/{eid}/analysis/quality-compare?grade=7"
    ).status_code == 200


# ── KW-49 个人趋势 ──────────────────────────────
def test_student_trend_order_and_scope(client_db, seed):
    client, db = client_db
    login(client, "adm")
    prev = setup_scored_exam(client, seed, name="七年级 10 月月考", table=PREV_SCORES)
    advance_to_published_scores(client, prev)
    eid = setup_scored_exam(client, seed, name="七年级 11 月月考")
    body = client.get(
        f"/api/exam/exams/{eid}/analysis/trend?student_id={seed['s1'].id}"
    ).json()
    assert body["student_id"] == seed["s1"].id
    assert body["student_name"] == "张三"
    assert len(body["exams"]) == 2
    # 按考试创建时间排序:上次在前,本次在后
    assert body["exams"][0]["exam_name"] == "七年级 10 月月考"
    assert body["exams"][0]["total"] == 150
    assert body["exams"][0]["subjects"] == {"数学": 80, "语文": 70}
    assert body["exams"][1]["exam_name"] == "七年级 11 月月考"
    assert body["exams"][1]["total"] == 170
    # 班主任(t1 是 701 班主任)只看本班学生:702 的 s5 403;任课 t2 看 702 可以
    login(client, "t1")
    assert client.get(
        f"/api/exam/exams/{eid}/analysis/trend?student_id={seed['s5'].id}"
    ).status_code == 403
    assert client.get(
        f"/api/exam/exams/{eid}/analysis/trend?student_id={seed['s1'].id}"
    ).status_code == 200
    login(client, "t2")
    assert client.get(
        f"/api/exam/exams/{eid}/analysis/trend?student_id={seed['s5'].id}"
    ).status_code == 200


# ── KW-50 等第 ──────────────────────────────
def test_grade_bands_defaults_and_distribution(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_scored_exam(client, seed)
    body = client.get(f"/api/exam/exams/{eid}/grade-bands").json()
    assert [(i["grade_label"], i["min_score"], i["max_score"]) for i in body["items"]] == [
        ("A", 90, 100), ("B", 80, 90), ("C", 70, 80), ("D", 60, 70), ("E", 0, 60),
    ]
    # 数学等第分布:90->A 1 人,80->B 2 人,70->C 1 人,60->D 1 人,E 0 人
    body = client.get(
        f"/api/exam/exams/{eid}/analysis/grade-distribution?subject_id={seed['math'].id}"
    ).json()
    by_label = {b["grade_label"]: b for b in body["bands"]}
    assert by_label["A"]["count"] == 1
    assert by_label["B"]["count"] == 2
    assert by_label["C"]["count"] == 1
    assert by_label["D"]["count"] == 1
    assert by_label["E"]["count"] == 0
    assert by_label["A"]["pct"] == 20
    # 自定义总分档:A>=150、B>=120、C>=90、D>=60、E<60
    r = client.put(f"/api/exam/exams/{eid}/grade-bands", json={"items": [
        {"subject_id": None, "grade_label": "A", "min_score": 150, "max_score": 200},
        {"subject_id": None, "grade_label": "B", "min_score": 120, "max_score": 150},
        {"subject_id": None, "grade_label": "C", "min_score": 90, "max_score": 120},
        {"subject_id": None, "grade_label": "D", "min_score": 60, "max_score": 90},
        {"subject_id": None, "grade_label": "E", "min_score": 0, "max_score": 60},
    ]})
    assert r.status_code == 200, r.text
    assert len(r.json()["items"]) == 5
    body = client.get(f"/api/exam/exams/{eid}/analysis/grade-distribution").json()
    by_label = {b["grade_label"]: b for b in body["bands"]}
    # 总分 170/160->A,140/140->B,100->C,50->E
    assert by_label["A"]["count"] == 2
    assert by_label["B"]["count"] == 2
    assert by_label["C"]["count"] == 1
    assert by_label["D"]["count"] == 0
    assert by_label["E"]["count"] == 1
    assert db.query(AuditLog).filter_by(action="exam_grade_band_update").count() == 1


# ── KW-51 报表包 ──────────────────────────────
def test_report_pack_excel(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_scored_exam(client, seed)
    client.post(f"/api/exam/exams/{eid}/target-students", json={
        "student_id": seed["s1"].id, "target_total": 170,
    })
    r = client.get(f"/api/exam/exams/{eid}/analysis/report-pack")
    assert r.status_code == 200, r.text
    assert "spreadsheetml.sheet" in r.headers["content-type"]
    assert "filename" in r.headers["content-disposition"]
    wb = load_workbook(BytesIO(r.content))
    assert wb.sheetnames == ["年级汇总", "班级对比", "学科分析", "临界生", "目标生"]
    ws = wb["年级汇总"]
    assert ws.cell(row=1, column=1).value == "科目"
    assert ws.cell(row=2, column=1).value == "总分"
    assert ws.cell(row=2, column=3).value == pytest.approx(126.67)
    ws = wb["目标生"]
    assert ws.cell(row=2, column=2).value == "张三"
    assert ws.cell(row=2, column=6).value == "是"
    assert db.query(AuditLog).filter_by(action="exam_report_pack_export").count() == 1
