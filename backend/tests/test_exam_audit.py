"""考务审计日志测试(KW-64):写入、动作名登记册、日志不可删除。"""

from app.models.audit import AuditLog
from app.models.user import Role
from app.services.exam_audit import EXAM_AUDIT_ACTIONS, log_exam_action
from tests.conftest import make_user

PW = "password123"

REQUIRED_ACTIONS = {
    "exam_student_create",
    "exam_student_update",
    "exam_student_import",
    "exam_student_export",
    "exam_student_status_change",
    "exam_subject_setting_update",
    "exam_number_rule_update",
    "exam_number_generate",
    "exam_subject_leader_assign",
    "exam_subject_leader_remove",
}


def test_exam_audit_actions_registered():
    assert REQUIRED_ACTIONS <= set(EXAM_AUDIT_ACTIONS)


def test_log_exam_action_writes_record(db):
    user = make_user(db, "adm", PW, roles=[Role.admin])
    log = log_exam_action(
        db, user, "exam_student_create",
        target_type="exam_student", target_id=7, detail="新增学生张三",
    )
    db.commit()
    assert isinstance(log, AuditLog)
    assert log.id is not None
    assert log.user_id == user.id
    assert log.username == "adm"
    assert log.action == "exam_student_create"
    assert log.target_type == "exam_student"
    assert log.target_id == 7
    assert log.detail == "新增学生张三"
    assert log.created_at is not None
    assert db.query(AuditLog).count() == 1


def test_log_exam_action_detail_truncated_to_500(db):
    user = make_user(db, "adm", PW, roles=[Role.admin])
    log = log_exam_action(db, user, "exam_student_update", detail="改" * 600)
    db.commit()
    assert len(log.detail) == 500


def test_audit_log_has_no_delete_route(env):
    """审计日志不可删除:audit 查询接口只有 GET,没有任何删除路由。"""
    client, db = env
    admin = make_user(db, "adm", PW, roles=[Role.admin])
    log_exam_action(
        db, admin, "exam_student_create",
        target_type="exam_student", target_id=7, detail="新增学生张三",
    )
    log_exam_action(
        db, admin, "exam_subject_setting_update",
        target_type="subject", target_id=3, detail="改数学满分",
    )
    db.commit()
    client.post("/api/auth/login", json={"username": "adm", "password": PW})

    rows = client.get("/api/audit-logs?action=exam_student_create").json()
    assert len(rows) == 1
    assert rows[0]["target_id"] == 7
    assert rows[0]["username"] == "adm"

    rows = client.get("/api/audit-logs?target_type=subject&target_id=3").json()
    assert len(rows) == 1
    assert rows[0]["action"] == "exam_subject_setting_update"

    rows = client.get("/api/audit-logs?target_type=subject&target_id=7").json()
    assert rows == []

    log_id = client.get("/api/audit-logs").json()[0]["id"]
    assert client.delete(f"/api/audit-logs/{log_id}").status_code in (404, 405)
    assert client.delete("/api/audit-logs").status_code in (404, 405)
    assert db.query(AuditLog).count() == 2
