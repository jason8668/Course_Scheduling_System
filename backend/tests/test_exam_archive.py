"""考试归档、历史对比与备份导出测试(KW-65~67)。

本文件自带 app fixture(挂 auth + exam + exam_scores + exam_arrangement +
exam_invigilation + exam_publish + exam_archive 路由),因为 conftest 的
env 尚未接线新路由(接线由协调员统一做,见汇报)。
"""

import zipfile
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
from app.api import exam_archive as archive_api
from app.api import exam_arrangement as arrangement_api
from app.api import exam_invigilation as invigilation_api
from app.api import exam_publish as publish_api
from app.api import exam_scores as scores_api
from app.core.db import Base, get_db
# noqa: F401 仅为建表:本批新表与关联表须先 import 对应模型,
# Base.metadata.create_all 才会建这些表。
from app.models import (  # noqa: F401
    exam_analysis,
    exam_archive,
    exam_arrangement,
    exam_invigilation,
    exam_publish,
    exam_reports,
    exam_scores,
)
from app.models.basedata import ClassUnit, Room, Subject, Teacher
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
# 对比考试成绩:数学均分 66.0、语文均分 53.33、总分均分 108.33。
COMPARE_SCORES = {
    "s1": (80, 70), "s2": (70, 70), "s3": (70, 50),
    "s4": (50, 30), "s5": (60, 60), "s6": (None, 40),
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
    app.include_router(arrangement_api.router, prefix="/api/exam")
    app.include_router(invigilation_api.router, prefix="/api/exam")
    app.include_router(publish_api.router, prefix="/api/exam")
    app.include_router(archive_api.router, prefix="/api/exam")
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
    cls701 = ClassUnit(semester_id=sem.id, grade=7, name="701", track="junior_high")
    cls702 = ClassUnit(semester_id=sem.id, grade=7, name="702", track="junior_high")
    room101 = Room(semester_id=sem.id, name="101", capacity=30)
    db.add_all([math, chinese, english, cls701, cls702, room101])
    db.flush()
    admin = make_user(db, "adm", PW, roles=[Role.admin])
    academic = make_user(db, "jiao", PW, roles=[Role.director])
    t1user = make_user(db, "t1", PW, roles=[Role.teacher])
    t1 = Teacher(semester_id=sem.id, name="王老师", user_id=t1user.id)
    db.add(t1)
    db.flush()
    s1 = Student(semester_id=sem.id, class_unit_id=cls701.id, student_no="20260101", name="张三", gender="男")
    s2 = Student(semester_id=sem.id, class_unit_id=cls701.id, student_no="20260102", name="李四", gender="女")
    s3 = Student(semester_id=sem.id, class_unit_id=cls701.id, student_no="20260103", name="赵六", gender="男")
    s4 = Student(semester_id=sem.id, class_unit_id=cls701.id, student_no="20260104", name="孙七", gender="女")
    s5 = Student(semester_id=sem.id, class_unit_id=cls702.id, student_no="20260201", name="王五", gender="男")
    s6 = Student(semester_id=sem.id, class_unit_id=cls702.id, student_no="20260202", name="钱八", gender="女")
    db.add_all([s1, s2, s3, s4, s5, s6])
    db.flush()
    db.add_all([
        ParentContact(student_id=s1.id, name="张父", relation="父亲", phone="13800000001"),
        ParentContact(student_id=s2.id, name="张母", relation="母亲", phone="13800000001"),
        ParentContact(student_id=s5.id, name="王父", relation="父亲", phone="13800000005"),
    ])
    db.commit()
    return {
        "sem": sem, "math": math, "chinese": chinese, "english": english,
        "cls701": cls701, "cls702": cls702, "room101": room101,
        "admin": admin, "academic": academic,
        "t1": t1user, "t1t": t1,
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


def setup_exam(client, seed, name="七年级 11 月月考", subjects=("math", "chinese")):
    """建考 + 日程(满分各 100)+ 参试名单(6 人)。"""
    eid = make_exam(client, seed, name)
    items = []
    for key in subjects:
        items.append({
            "subject_id": seed[key].id, "exam_date": MONDAY,
            "start_time": "08:00" if key != "chinese" else "10:00",
            "end_time": "09:30" if key != "chinese" else "11:30",
            "full_score": 100,
        })
    r = client.put(f"/api/exam/exams/{eid}/subjects", json={"subjects": items})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/exam/exams/{eid}/participants/generate")
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 6
    return eid


def enter_scores(client, seed, eid, table, subjects=("math", "chinese")):
    """table:{s1..s6: (分或 None, ...)};None 表示该科缺考。"""
    for subject_key, idx in zip(subjects, range(len(subjects))):
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


def setup_scored_exam(client, seed, name="七年级 11 月月考", table=CURRENT_SCORES,
                      subjects=("math", "chinese")):
    eid = setup_exam(client, seed, name, subjects)
    enter_scores(client, seed, eid, table, subjects)
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


def archive_exam(client, eid, note="期末归档"):
    r = client.post(f"/api/exam/exams/{eid}/archive", json={"note": note})
    assert r.status_code == 201, r.text
    return r.json()


# ── KW-65 归档前置状态校验与归档后状态 ──────────────────────────────
def test_archive_requires_published_scores(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_scored_exam(client, seed)
    # 草稿与已发布都不能归档。
    r = client.post(f"/api/exam/exams/{eid}/archive", json={})
    assert r.status_code == 409, r.text
    r = client.post(f"/api/exam/exams/{eid}/status", json={"to_status": "已发布"})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/exam/exams/{eid}/archive", json={})
    assert r.status_code == 409, r.text
    # 发布一个班级批次,再推进到已发布成绩,归档成功。
    publish_class(client, eid, seed["cls701"].id)
    for st in ("进行中", "成绩处理中", "已发布成绩"):
        r = client.post(f"/api/exam/exams/{eid}/status", json={"to_status": st})
        assert r.status_code == 200, r.text
    body = archive_exam(client, eid)
    assert body["exam_id"] == eid
    assert body["archived_by"] == seed["admin"].id
    assert body["archived_at"] is not None
    manifest = body["manifest"]
    assert manifest["participant_count"] == 6
    assert manifest["arrangement_count"] == 0
    assert manifest["invigilation_count"] == 0
    assert manifest["score_count"] == 12
    assert len(manifest["publish_batches"]) == 1
    assert manifest["publish_batches"][0]["scope_type"] == "班级"
    assert manifest["publish_batches"][0]["status"] == "已发布"
    avgs = {s["subject_name"]: s["avg"] for s in manifest["subject_avgs"]}
    assert avgs == {"数学": 76.0, "语文": 63.33}
    assert manifest["total_avg"] == 126.67
    # 归档后考试状态为已归档。
    assert client.get(f"/api/exam/exams/{eid}").json()["status"] == "已归档"
    # 再次归档 409。
    r = client.post(f"/api/exam/exams/{eid}/archive", json={})
    assert r.status_code == 409, r.text


def test_get_archive_404_before_and_200_after(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_scored_exam(client, seed)
    r = client.get(f"/api/exam/exams/{eid}/archive")
    assert r.status_code == 404, r.text
    advance_to_published_scores(client, eid)
    archive_exam(client, eid, note="期末归档")
    body = client.get(f"/api/exam/exams/{eid}/archive").json()
    assert body["exam_id"] == eid
    assert body["note"] == "期末归档"
    assert body["manifest"]["participant_count"] == 6


def test_archive_download_zip(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_scored_exam(client, seed)
    r = client.get(f"/api/exam/exams/{eid}/archive/download")
    assert r.status_code == 404, r.text
    advance_to_published_scores(client, eid)
    archive_exam(client, eid)
    r = client.get(f"/api/exam/exams/{eid}/archive/download")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(BytesIO(r.content))
    assert zf.namelist() == [
        "参试名单.xlsx", "考场编排.xlsx", "监考表.xlsx", "成绩册.xlsx", "分析报表.xlsx",
    ]
    ws = load_workbook(BytesIO(zf.read("参试名单.xlsx")))["参试名单"]
    assert [c.value for c in ws[1]] == ["学号", "姓名", "班级", "参试状态", "备注"]
    assert ws.max_row == 7  # 表头 + 6 人
    assert "数学" in load_workbook(BytesIO(zf.read("考场编排.xlsx"))).sheetnames
    assert "监考表" in load_workbook(BytesIO(zf.read("监考表.xlsx"))).sheetnames
    assert "成绩册" in load_workbook(BytesIO(zf.read("成绩册.xlsx"))).sheetnames
    assert "年级汇总" in load_workbook(BytesIO(zf.read("分析报表.xlsx"))).sheetnames


# ── KW-65 归档后只读 ──────────────────────────────
def test_archived_readonly_writes_403(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_scored_exam(client, seed)
    advance_to_published_scores(client, eid)
    archive_exam(client, eid)
    # 成绩录入 403。
    r = client.put(f"/api/exam/exams/{eid}/scores", json={
        "subject_id": seed["math"].id,
        "scores": [{"student_id": seed["s1"].id, "score": 95}],
    })
    assert r.status_code == 403, r.text
    # 考场编排写接口 403。
    r = client.post(f"/api/exam/exams/{eid}/rooms", json={
        "room_id": seed["room101"].id, "capacity": 30,
        "room_type": "普通", "is_special": False,
    })
    assert r.status_code == 403, r.text
    # 监考写接口 403。
    r = client.post(f"/api/exam/exams/{eid}/invigilations", json={
        "subject_id": seed["math"].id, "room_id": seed["room101"].id,
        "teacher_id": seed["t1t"].id, "role": "主监考",
    })
    assert r.status_code == 403, r.text
    # 考试修改 PATCH 403。
    r = client.patch(f"/api/exam/exams/{eid}", json={"name": "改名"})
    assert r.status_code == 403, r.text
    # 读接口仍可用。
    r = client.get(f"/api/exam/exams/{eid}/scores?subject_id={seed['math'].id}")
    assert r.status_code == 200, r.text
    r = client.get(f"/api/exam/exams/{eid}/archive")
    assert r.status_code == 200, r.text


def test_unarchive_restores_status_and_writes(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_scored_exam(client, seed)
    advance_to_published_scores(client, eid)
    archive_exam(client, eid)
    r = client.delete(f"/api/exam/exams/{eid}/archive")
    assert r.status_code == 204, r.text
    assert client.get(f"/api/exam/exams/{eid}").json()["status"] == "已发布成绩"
    r = client.get(f"/api/exam/exams/{eid}/archive")
    assert r.status_code == 404, r.text
    # 取消归档后成绩录入恢复。
    r = client.put(f"/api/exam/exams/{eid}/scores", json={
        "subject_id": seed["math"].id,
        "scores": [{"student_id": seed["s1"].id, "score": 95}],
    })
    assert r.status_code == 200, r.text
    # 可再次归档。
    body = archive_exam(client, eid)
    assert body["exam_id"] == eid


# ── KW-66 历史查询与对比 ──────────────────────────────
def test_archive_list_and_status_filter(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid_a = setup_scored_exam(client, seed, "七年级 11 月月考")
    eid_b = setup_scored_exam(client, seed, "七年级 12 月月考")
    advance_to_published_scores(client, eid_a)
    archive_exam(client, eid_a)
    body = client.get("/api/exam/archives").json()
    assert body["total"] == 2
    by_id = {i["exam_id"]: i for i in body["items"]}
    assert by_id[eid_a]["status"] == "已归档"
    assert by_id[eid_a]["archived_by"] == seed["admin"].id
    assert by_id[eid_a]["archived_at"] is not None
    assert by_id[eid_b]["status"] == "草稿"
    assert by_id[eid_b]["archived_at"] is None
    body = client.get("/api/exam/archives?status=已归档").json()
    assert body["total"] == 1
    assert body["items"][0]["exam_id"] == eid_a
    body = client.get("/api/exam/archives?status=未归档").json()
    assert body["total"] == 1
    assert body["items"][0]["exam_id"] == eid_b
    body = client.get("/api/exam/archives?q=12 月").json()
    assert body["total"] == 1
    assert body["items"][0]["exam_id"] == eid_b
    body = client.get(
        f"/api/exam/archives?semester_id={seed['sem'].id}"
    ).json()
    assert body["total"] == 2
    r = client.get("/api/exam/archives?status=草稿")
    assert r.status_code == 400, r.text


def test_compare_exams(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid_a = setup_scored_exam(client, seed, "七年级 11 月月考")
    eid_b = setup_scored_exam(
        client, seed, "七年级 12 月月考", table=COMPARE_SCORES
    )
    body = client.get(
        f"/api/exam/archives/compare?exam_a={eid_a}&exam_b={eid_b}"
    ).json()
    assert body["exam_a"] == {"id": eid_a, "name": "七年级 11 月月考"}
    assert body["exam_b"] == {"id": eid_b, "name": "七年级 12 月月考"}
    assert body["total_avg_a"] == 126.67
    assert body["total_avg_b"] == 108.33
    assert body["delta_total_avg"] == -18.34
    assert body["message"] is None
    by_name = {s["subject_name"]: s for s in body["subjects"]}
    assert set(by_name) == {"数学", "语文"}
    math = by_name["数学"]
    assert math["avg_a"] == 76.0 and math["avg_b"] == 66.0
    assert math["delta_avg"] == -10.0
    assert math["pass_rate_a"] == 100.0 and math["pass_rate_b"] == 80.0
    assert math["delta_pass_rate"] == -20.0
    assert math["excellent_rate_a"] == 20.0 and math["excellent_rate_b"] == 0.0
    assert math["delta_excellent_rate"] == -20.0
    chinese = by_name["语文"]
    assert chinese["avg_a"] == 63.33 and chinese["avg_b"] == 53.33
    assert chinese["delta_avg"] == -10.0


def test_compare_no_common_subjects(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid_a = setup_scored_exam(client, seed, "七年级 11 月月考")
    # 只考英语的考试,与 A 无共同科目。
    eid_c = setup_exam(client, seed, "七年级英语测验", subjects=("english",))
    enter_scores(client, seed, eid_c, {
        "s1": (88,), "s2": (77,), "s3": (66,),
        "s4": (55,), "s5": (44,), "s6": (33,),
    }, subjects=("english",))
    body = client.get(
        f"/api/exam/archives/compare?exam_a={eid_a}&exam_b={eid_c}"
    ).json()
    assert body["subjects"] == []
    assert body["message"] == "两次考试无共同科目，无法对比"
    assert body["total_avg_a"] == 126.67
    assert body["total_avg_b"] == 60.5


# ── KW-67 备份导出 ──────────────────────────────
def test_backup_export(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_scored_exam(client, seed)
    publish_class(client, eid, seed["cls701"].id)
    r = client.get(f"/api/exam/backup/export?semester_id={seed['sem'].id}")
    assert r.status_code == 200, r.text
    assert "spreadsheetml.sheet" in r.headers["content-type"]
    wb = load_workbook(BytesIO(r.content))
    assert wb.sheetnames == [
        "学生", "家长", "考试", "参试名单", "考场编排",
        "监考安排", "成绩", "发布批次", "考风考纪", "通知记录",
    ]
    assert wb["学生"].max_row == 7  # 表头 + 6 人
    assert wb["家长"].max_row == 4  # 表头 + 3 条
    assert wb["考试"].max_row == 2
    assert wb["参试名单"].max_row == 7
    assert wb["成绩"].max_row == 13  # 表头 + 12 条
    assert wb["发布批次"].max_row == 2
    # 不指定学期导出全部,同样 200。
    r = client.get("/api/exam/backup/export")
    assert r.status_code == 200, r.text
    wb = load_workbook(BytesIO(r.content))
    assert wb["学生"].max_row == 7
    # 不存在的学期 404。
    r = client.get("/api/exam/backup/export?semester_id=99999")
    assert r.status_code == 404, r.text


# ── 越权 ──────────────────────────────
def test_archive_permissions(client_db, seed):
    client, db = client_db
    login(client, "adm")
    eid = setup_scored_exam(client, seed)
    advance_to_published_scores(client, eid)
    # 教师无权归档、取消归档、备份导出。
    login(client, "t1")
    r = client.post(f"/api/exam/exams/{eid}/archive", json={})
    assert r.status_code == 403, r.text
    r = client.delete(f"/api/exam/exams/{eid}/archive")
    assert r.status_code == 403, r.text
    r = client.get("/api/exam/backup/export")
    assert r.status_code == 403, r.text
    # 教师可读历史查询与对比。
    r = client.get("/api/exam/archives")
    assert r.status_code == 200, r.text
    # 教务可归档。
    login(client, "jiao")
    body = archive_exam(client, eid)
    assert body["exam_id"] == eid
    # 教师无权下载归档包。
    login(client, "t1")
    r = client.get(f"/api/exam/exams/{eid}/archive/download")
    assert r.status_code == 403, r.text
