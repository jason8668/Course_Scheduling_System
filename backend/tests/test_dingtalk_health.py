"""上课提醒健康端点:只读聚合,不发消息、不改设置。

不连真实钉钉、不连 Redis:排程状态在测试环境查不到时回 null,不断言其真值。
"""

from datetime import date, datetime, timezone

import pytest

from app.models.basedata import Teacher
from app.models.semester import Semester
from app.models.timetable import ClassReminderLog
from app.models.user import Role
from tests.conftest import make_user

PW = "password123"


@pytest.fixture
def admin(env):
    client, db = env
    make_user(db, "admin1", PW, roles=[Role.admin])
    client.post("/api/auth/login", json={"username": "admin1", "password": PW})
    return client, db


def test_health_empty(admin):
    client, _ = admin
    r = client.get("/api/settings/dingtalk-app/health")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is False
    assert body["job_scheduled"] in (None, False)
    assert body["last_sent_at"] is None
    assert body["sent_7d"] == 0
    assert body["teachers_with_phone"] == 0
    assert body["teachers_missing_phone"] == 0
    assert body["opted_out"] == []
    assert body["unresolved"] == []
    assert "secret" not in r.text


def test_health_teacher_buckets(admin):
    client, db = admin
    sem = Semester(academic_year=2026, term=1)
    db.add(sem)
    db.flush()
    teachers = [
        Teacher(semester_id=sem.id, name="已解析", phone="13800000001",
                dingtalk_userid="u1", reminder_enabled=True),
        Teacher(semester_id=sem.id, name="未解析", phone="13800000002",
                dingtalk_userid=None, reminder_enabled=True),
        Teacher(semester_id=sem.id, name="无手机", phone=None,
                dingtalk_userid=None, reminder_enabled=True),
        Teacher(semester_id=sem.id, name="关提醒", phone="13800000004",
                dingtalk_userid="u4", reminder_enabled=False),
    ]
    db.add_all(teachers)
    db.flush()
    # 测试库 SQLite 默认不开外键约束,用占位 entry_id 即可验证 sent 聚合。
    db.add(ClassReminderLog(
        entry_id=999999, class_date=date(2026, 10, 29), teacher_id=teachers[0].id,
        sent_at=datetime.now(timezone.utc),
    ))
    db.commit()

    r = client.get("/api/settings/dingtalk-app/health")
    assert r.status_code == 200
    body = r.json()
    assert body["teachers_with_phone"] == 3
    assert body["teachers_missing_phone"] == 1
    assert [t["name"] for t in body["opted_out"]] == ["关提醒"]
    assert [t["name"] for t in body["unresolved"]] == ["未解析"]
    assert body["sent_7d"] == 1
    assert body["last_sent_at"] is not None


def test_health_requires_admin(env):
    client, _ = env
    r = client.get("/api/settings/dingtalk-app/health")
    assert r.status_code == 401
