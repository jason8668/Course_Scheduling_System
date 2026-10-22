"""教师帐号绑定与联络信息测试。对应 M2-0 验收标准。"""

import io

import pytest
from openpyxl import Workbook

from app.api.imports import XLSX_MIME
from app.models.user import Role, User
from app.services.teachers import current_teacher
from tests.conftest import make_user

PW = "password123"


@pytest.fixture
def sched(env):
    """已登录教学组长 + 一个学期。回传 (client, semester_id, db)。"""
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    sem = client.post("/api/semesters", json={"academic_year": 2026, "term": 1}).json()
    return client, sem["id"], db


def _make_teacher_account(db, username: str) -> int:
    return make_user(db, username, PW, roles=[Role.teacher]).id


# ── 联络信息 ──────────────────────────
def test_contact_fields_crud(sched):
    client, sid, _ = sched
    r = client.post(
        f"/api/teachers?semester_id={sid}",
        json={"name": "王老师", "email": "wang@example.edu.tw", "phone": "0912345678",
              },
    )
    assert r.status_code == 201
    t = r.json()
    assert t["email"] == "wang@example.edu.tw"
    assert t["phone"] == "0912345678"
    # 更新联络信息
    r = client.patch(f"/api/teachers/{t['id']}", json={"name": "王老师", "email": "new@a.bc"})
    assert r.json()["email"] == "new@a.bc"
    assert r.json()["phone"] is None  # 未带入 → 清空


def test_invalid_email_rejected(sched):
    """验收④:Email 格式错误回报错误。"""
    client, sid, _ = sched
    r = client.post(
        f"/api/teachers?semester_id={sid}", json={"name": "王老师", "email": "not-an-email"}
    )
    assert r.status_code == 422


def test_empty_email_becomes_null(sched):
    client, sid, _ = sched
    r = client.post(f"/api/teachers?semester_id={sid}", json={"name": "王老师", "email": ""})
    assert r.status_code == 201
    assert r.json()["email"] is None


# ── 帐号绑定 ──────────────────────────
def test_bind_account_success(sched):
    client, sid, db = sched
    uid = _make_teacher_account(db, "wang001")
    r = client.post(f"/api/teachers?semester_id={sid}", json={"name": "王老师", "user_id": uid})
    assert r.status_code == 201
    assert r.json()["user_id"] == uid


def test_bind_nonexistent_account_400(sched):
    client, sid, _ = sched
    r = client.post(f"/api/teachers?semester_id={sid}", json={"name": "王老师", "user_id": 99999})
    assert r.status_code == 400


def test_bind_same_account_twice_409(sched):
    """验收③:同帐号在同学期绑第二位教师 → 409。"""
    client, sid, db = sched
    uid = _make_teacher_account(db, "wang001")
    assert client.post(
        f"/api/teachers?semester_id={sid}", json={"name": "王老师", "user_id": uid}
    ).status_code == 201
    r = client.post(f"/api/teachers?semester_id={sid}", json={"name": "李老师", "user_id": uid})
    assert r.status_code == 409


def test_rebind_same_teacher_ok(sched):
    """同一教师重存自己已绑的帐号不应被当成冲突。"""
    client, sid, db = sched
    uid = _make_teacher_account(db, "wang001")
    t = client.post(
        f"/api/teachers?semester_id={sid}", json={"name": "王老师", "user_id": uid}
    ).json()
    r = client.patch(f"/api/teachers/{t['id']}", json={"name": "王老师", "user_id": uid})
    assert r.status_code == 200
    assert r.json()["user_id"] == uid


def test_bindable_accounts_excludes_bound(sched):
    client, sid, db = sched
    u1 = _make_teacher_account(db, "wang001")
    u2 = _make_teacher_account(db, "lee001")
    # 绑定 u1 给某教师
    client.post(f"/api/teachers?semester_id={sid}", json={"name": "王老师", "user_id": u1})
    avail = client.get(f"/api/teachers/bindable-accounts?semester_id={sid}").json()
    ids = {a["id"] for a in avail}
    assert u2 in ids and u1 not in ids


def test_bindable_accounts_includes_current_in_edit(sched):
    client, sid, db = sched
    u1 = _make_teacher_account(db, "wang001")
    t = client.post(
        f"/api/teachers?semester_id={sid}", json={"name": "王老师", "user_id": u1}
    ).json()
    # 编辑情境:带 current_teacher_id → 应含目前绑定的 u1
    avail = client.get(
        f"/api/teachers/bindable-accounts?semester_id={sid}&current_teacher_id={t['id']}"
    ).json()
    assert u1 in {a["id"] for a in avail}


# ── 事后补开帐号(#9)与重设密码(#10)──────────
def test_create_account_for_existing_teacher(sched):
    """导入时没建帐号的老师,事后可以直接补:建好即绑定,且首次登录必须改密码。"""
    client, sid, db = sched
    t = client.post(f"/api/teachers?semester_id={sid}", json={"name": "王老师"}).json()
    assert t["user_id"] is None

    r = client.post(f"/api/teachers/{t['id']}/account", json={"username": "wang001"})
    assert r.status_code == 201, r.json()
    acc = r.json()
    assert acc["username"] == "wang001" and acc["must_change_password"] is True
    assert acc["display_name"] == "王老师"
    assert client.get(f"/api/teachers?semester_id={sid}").json()[0]["user_id"] == acc["id"]

    # 新帐号用默认密码登录得了(密码未指定时用部署设置的默认值)
    client.post("/api/auth/logout")
    assert client.post(
        "/api/auth/login", json={"username": "wang001", "password": "admin"}
    ).status_code == 200


def test_create_account_rejects_duplicate_username_and_second_account(sched):
    client, sid, db = sched
    _make_teacher_account(db, "wang001")
    t = client.post(f"/api/teachers?semester_id={sid}", json={"name": "王老师"}).json()

    dup = client.post(f"/api/teachers/{t['id']}/account", json={"username": "wang001"})
    assert dup.status_code == 409 and "已存在" in dup.json()["detail"]

    assert client.post(
        f"/api/teachers/{t['id']}/account",
        json={"username": "wang002", "password": "teacherpw123"},
    ).status_code == 201
    again = client.post(f"/api/teachers/{t['id']}/account", json={"username": "wang003"})
    assert again.status_code == 409 and "已绑定" in again.json()["detail"]


def test_create_account_rejects_short_password(sched):
    client, sid, _ = sched
    t = client.post(f"/api/teachers?semester_id={sid}", json={"name": "王老师"}).json()
    r = client.post(
        f"/api/teachers/{t['id']}/account", json={"username": "wang001", "password": "short"}
    )
    assert r.status_code == 400 and "至少" in r.json()["detail"]


def test_reset_teacher_password(sched):
    """重设后:新密码可登录、旧密码不行,且对方下次登录要自行改密码。"""
    client, sid, db = sched
    t = client.post(f"/api/teachers?semester_id={sid}", json={"name": "王老师"}).json()
    client.post(
        f"/api/teachers/{t['id']}/account",
        json={"username": "wang001", "password": "oldpassword1"},
    )

    r = client.post(
        f"/api/teachers/{t['id']}/account/reset-password", json={"password": "newpassword1"}
    )
    assert r.status_code == 200 and r.json()["must_change_password"] is True

    client.post("/api/auth/logout")
    assert client.post(
        "/api/auth/login", json={"username": "wang001", "password": "oldpassword1"}
    ).status_code == 401
    assert client.post(
        "/api/auth/login", json={"username": "wang001", "password": "newpassword1"}
    ).status_code == 200


def test_reset_password_refuses_non_teacher_account(sched):
    """绑定的帐号若不只是教师角色(例如兼任组长),这条路不给改,避免越权。"""
    client, sid, db = sched
    boss = make_user(db, "boss", PW, roles=[Role.teacher, Role.scheduler])
    t = client.post(
        f"/api/teachers?semester_id={sid}", json={"name": "主任老师", "user_id": boss.id}
    ).json()
    r = client.post(f"/api/teachers/{t['id']}/account/reset-password", json={})
    assert r.status_code == 403 and "系统管理员" in r.json()["detail"]


def test_reset_password_without_account_is_404(sched):
    client, sid, _ = sched
    t = client.post(f"/api/teachers?semester_id={sid}", json={"name": "王老师"}).json()
    r = client.post(f"/api/teachers/{t['id']}/account/reset-password", json={})
    assert r.status_code == 404 and "尚未绑定" in r.json()["detail"]


# ── 停用/启用帐号与删除教师的连带影响(#19)──────────
def _teacher_with_account(client, sid, name="王老师", username="wang001", pw="teacherpw123"):
    t = client.post(f"/api/teachers?semester_id={sid}", json={"name": name}).json()
    acc = client.post(f"/api/teachers/{t['id']}/account",
                      json={"username": username, "password": pw}).json()
    return t, acc


def test_disable_and_enable_teacher_account(sched):
    """离职教师要的是「资料留著、人进不来」:停用后登不进来,重新启用又可以。"""
    client, sid, _ = sched
    t, _ = _teacher_with_account(client, sid)

    r = client.post(f"/api/teachers/{t['id']}/account/active", json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False

    client.post("/api/auth/logout")
    blocked = client.post("/api/auth/login",
                          json={"username": "wang001", "password": "teacherpw123"})
    assert blocked.status_code == 403 and "停用" in blocked.json()["detail"]

    # 重新启用(需要重新以组长登录)
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    assert client.post(f"/api/teachers/{t['id']}/account/active",
                       json={"is_active": True}).json()["is_active"] is True
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login",
                       json={"username": "wang001", "password": "teacherpw123"}).status_code == 200


def test_account_active_refuses_non_teacher_account(sched):
    """只能停用单纯教师身分的帐号,不会动到主任/组长/管理员。"""
    client, sid, db = sched
    boss = make_user(db, "boss2", PW, roles=[Role.teacher, Role.director])
    t = client.post(f"/api/teachers?semester_id={sid}",
                    json={"name": "主任老师", "user_id": boss.id}).json()
    r = client.post(f"/api/teachers/{t['id']}/account/active", json={"is_active": False})
    assert r.status_code == 403


def test_delete_teacher_disables_bound_account(sched):
    """删除教师后帐号不该还能登录;帐号本身保留(稽核轨迹)。"""
    client, sid, db = sched
    t, acc = _teacher_with_account(client, sid)

    assert client.delete(f"/api/teachers/{t['id']}").status_code == 204
    user = db.get(User, acc["id"])
    db.refresh(user)
    assert user is not None and user.is_active is False  # 帐号还在,但停用

    client.post("/api/auth/logout")
    assert client.post("/api/auth/login",
                       json={"username": "wang001", "password": "teacherpw123"}).status_code == 403


def test_delete_impact_lists_what_will_be_lost(sched):
    """删除前先告诉用户会连带失去什么。"""
    client, sid, _ = sched
    t, _ = _teacher_with_account(client, sid)
    # 一张请假单(学期要有起讫日期才建得了)
    client.patch(f"/api/semesters/{sid}",
                 json={"start_date": "2026-08-30", "end_date": "2027-01-20"})
    r = client.post(f"/api/leaves?semester_id={sid}", json={
        "teacher_id": t["id"], "leave_type": "sick",
        "start_date": "2026-10-07", "end_date": "2026-10-07"})
    assert r.status_code == 201, r.json()

    impact = client.get(f"/api/teachers/{t['id']}/delete-impact").json()
    assert impact["teacher_name"] == "王老师"
    assert impact["leave_requests"] == 1
    assert impact["account_username"] == "wang001"
    assert impact["homeroom_classes"] == 0


# ── current_teacher helper ──────────────
def test_current_teacher_helper(sched):
    client, sid, db = sched
    uid = _make_teacher_account(db, "wang001")
    client.post(f"/api/teachers?semester_id={sid}", json={"name": "王老师", "user_id": uid})
    user = db.get(User, uid)
    t = current_teacher(db, user, sid)
    assert t is not None and t.name == "王老师"
    # 未绑定学期回 None
    assert current_teacher(db, user, 99999) is None


# ── Excel 导入绑定 ──────────────────────
def _make_xlsx(rows: list[list], ncols: int) -> bytes:
    wb = Workbook()
    ws = wb.active
    for _ in range(3):
        ws.append(["表头"] * ncols)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _upload_teachers(client, sid, rows, ncols=11, create_accounts=True):
    content = _make_xlsx(rows, ncols)
    url = f"/api/import/teachers?semester_id={sid}"
    if create_accounts:
        url += "&create_accounts=true"
    return client.post(url, files={"file": ("t.xlsx", content, XLSX_MIME)})


def test_import_binds_account(sched):
    """验收①:导入教师勾建立帐号 → user_id 正确绑定;含联络栏位。"""
    client, sid, _ = sched
    rows = [
        ["王小明", "1234", "", 20, "", "", "否", "wang001", "wang@a.bc", "0911", "wl"],
        ["李小华", "5678", "", 18, "", "", "否", "lee001", "", "", ""],
    ]
    r = _upload_teachers(client, sid, rows)
    assert r.json()["imported"] == 2
    teachers = client.get(f"/api/teachers?semester_id={sid}").json()
    wang = next(t for t in teachers if t["name"] == "王小明")
    assert wang["user_id"] is not None
    assert wang["email"] == "wang@a.bc"
    assert wang["phone"] == "0911"
    # 绑定帐号可用默认密码登录
    client.post("/api/auth/logout")
    login = client.post("/api/auth/login", json={"username": "wang001", "password": "admin"})
    assert login.status_code == 200


def test_import_invalid_email_zero_write(sched):
    client, sid, _ = sched
    rows = [["王小明", "", "", "", "", "", "", "", "坏掉的email", "", ""]]
    body = _upload_teachers(client, sid, rows, create_accounts=False).json()
    assert body["imported"] == 0
    assert any("Email" in e for e in body["errors"])
    assert client.get(f"/api/teachers?semester_id={sid}").json() == []


# ── 开新学期复制保留绑定 ──────────────
def test_copy_preserves_binding_and_contact(sched):
    """验收②:复制后新学期教师仍绑同一帐号、联络信息完整。"""
    client, sid, db = sched
    uid = _make_teacher_account(db, "wang001")
    client.post(
        f"/api/teachers?semester_id={sid}",
        json={"name": "王老师", "user_id": uid, "email": "wang@a.bc", "phone": "0911"},
    )
    r = client.post(
        f"/api/semesters/{sid}/copy",
        json={"academic_year": 2027, "term": 1, "grade_promotion": False},
    )
    assert r.status_code == 201
    nid = r.json()["id"]
    nt = client.get(f"/api/teachers?semester_id={nid}").json()[0]
    assert nt["user_id"] == uid
    assert nt["email"] == "wang@a.bc"
    assert nt["phone"] == "0911"
