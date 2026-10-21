"""设置精灵与资料摘要测试。对应 M1-4 验收标准。"""

import pytest

from app.models.user import Role
from tests.conftest import make_user

PW = "password123"


@pytest.fixture
def scheduler(env):
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    return client


def test_initial_state_is_step0_incomplete(scheduler):
    """全新系统:精灵在第 0 步、未完成、无学期。"""
    r = scheduler.get("/api/wizard/state")
    assert r.status_code == 200
    body = r.json()
    assert body["current_step"] == 0
    assert body["completed"] is False
    assert body["has_semesters"] is False
    assert body["total_steps"] == 5


def test_progress_persists(scheduler):
    """验收②:更新步骤后再读,状态保留(模拟关浏览器后续作)。"""
    sem = scheduler.post("/api/semesters", json={"academic_year": 2026, "term": 1}).json()
    scheduler.patch("/api/wizard/state", json={"current_step": 3, "semester_id": sem["id"]})
    body = scheduler.get("/api/wizard/state").json()
    assert body["current_step"] == 3
    assert body["semester_id"] == sem["id"]
    assert body["has_semesters"] is True


def test_complete_and_reset(scheduler):
    scheduler.patch("/api/wizard/state", json={"completed": True, "current_step": 4})
    assert scheduler.get("/api/wizard/state").json()["completed"] is True
    # 重新启动精灵
    r = scheduler.post("/api/wizard/reset")
    body = r.json()
    assert body["completed"] is False
    assert body["current_step"] == 0
    assert body["semester_id"] is None


def test_step_clamped_to_valid_range(scheduler):
    scheduler.patch("/api/wizard/state", json={"current_step": 99})
    assert scheduler.get("/api/wizard/state").json()["current_step"] == 4  # TOTAL_STEPS-1


def test_semester_summary_counts(scheduler):
    """验收①:摘要显示教师/班级等数量。"""
    # 用空白学期(不带范本)使计数可预期
    sem = scheduler.post("/api/semesters", json={"academic_year": 2026, "term": 1}).json()
    sid = sem["id"]
    scheduler.post(f"/api/subjects?semester_id={sid}", json={"name": "数学"})
    scheduler.post(f"/api/teachers?semester_id={sid}", json={"name": "王老师"})
    scheduler.post(f"/api/teachers?semester_id={sid}", json={"name": "李老师"})
    scheduler.post(
        f"/api/class-units?semester_id={sid}",
        json={"grade": 1, "name": "甲", "track": "junior_high"},
    )
    summary = scheduler.get(f"/api/semesters/{sid}/summary").json()
    assert summary == {"subjects": 1, "teachers": 2, "classes": 1, "rooms": 0}


def test_teacher_cannot_write_wizard(env):
    client, db = env
    make_user(db, "t", PW, roles=[Role.teacher])
    client.post("/api/auth/login", json={"username": "t", "password": PW})
    assert client.patch("/api/wizard/state", json={"current_step": 2}).status_code == 403
