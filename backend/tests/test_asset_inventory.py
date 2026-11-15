"""第 4 批后端测试:盘点清查(#48/#49/#51/#52)。

自建测试 app:auth + asset_foundation + asset_circulation
+ asset_inventory + asset_workspace,SQLite 记忆体库,种子经
seed_asset_foundation 写入。
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import (
    asset_circulation,
    asset_foundation,
    asset_inventory,
    asset_workspace,
    auth,
)
from app.core.db import Base, get_db
from app.models.asset_card import AssetCard
from app.models.user import Role
from app.services.asset_seed import seed_asset_foundation
from app.services.users import create_user

PW = "pw-123456"


@pytest.fixture
def env():
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

    application = FastAPI()
    application.include_router(auth.router, prefix="/api/auth")
    application.include_router(asset_foundation.router, prefix="/api/asset")
    application.include_router(asset_circulation.router, prefix="/api/asset")
    application.include_router(asset_inventory.router, prefix="/api/asset")
    application.include_router(asset_workspace.router, prefix="/api/asset")
    application.dependency_overrides[get_db] = override_get_db

    setup_db = TestSession()
    seed_asset_foundation(setup_db)
    setup_db.commit()
    client = TestClient(application)
    try:
        yield client, setup_db
    finally:
        setup_db.close()
        Base.metadata.drop_all(engine)


@pytest.fixture
def users(env):
    client, db = env
    made = {}
    for username, roles in [
        ("adm", [Role.admin]),
        ("am", [Role.asset_admin]),
        ("da", [Role.asset_dept_admin]),
        ("dir", [Role.director]),
        ("fin", [Role.asset_finance]),
        ("tea", [Role.teacher]),
        ("tea2", [Role.teacher]),
    ]:
        made[username] = create_user(
            db, username=username, password=PW, roles=list(roles),
            must_change_password=False,
        )
    db.commit()
    return made


def _login(client, username):
    resp = client.post("/api/auth/login", json={"username": username, "password": PW})
    assert resp.status_code == 200, resp.text


def _create_card(client, name="示例资产", **overrides):
    body = {"name": name, "category_code": "A0203"}
    body.update(overrides)
    resp = client.post("/api/asset/assets", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _card(db, card_id):
    row = db.get(AssetCard, card_id)
    db.refresh(row)
    return row


def _plan(client, plan_type="全校盘点", name="示例盘点方案"):
    _login(client, "am")
    resp = client.post("/api/asset/inventory/plans",
                       json={"name": name, "plan_type": plan_type})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _task(client, plan_id, users, due_in_days=1, **scope):
    _login(client, "am")
    due = (datetime.now(UTC) + timedelta(days=due_in_days)).isoformat()
    body = {"assignee_id": users["tea"].id, "due_at": due}
    body.update(scope)
    resp = client.post(f"/api/asset/inventory/plans/{plan_id}/tasks", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _scan(client, task_id, label_code, **extra):
    _login(client, "tea")
    body = {"label_code": label_code}
    body.update(extra)
    resp = client.post(f"/api/asset/inventory/tasks/{task_id}/scan", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _diffs(client, plan_id, diff_type=None):
    _login(client, "am")
    suffix = f"?diff_type={diff_type}" if diff_type else ""
    resp = client.get(f"/api/asset/inventory/plans/{plan_id}/differences{suffix}")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _resolve(client, diff_id, action, resolution="示例处理说明", **extra):
    _login(client, "am")
    body = {"action": action, "resolution": resolution}
    body.update(extra)
    resp = client.post(f"/api/asset/inventory/differences/{diff_id}/resolve",
                       json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── #48 盘点方案与任务拆分 ──────────────────────────────
def test_plan_and_task_split_with_reminder(env, users):
    client, db = env
    plan = _plan(client)
    assert plan["plan_no"].startswith("PD-")
    assert plan["status"] == "草稿"
    task = _task(client, plan["id"], users, scope_dept="示例总务处",
                 scope_room_name="示例机房")
    assert task["assignee_name"]
    assert task["scope_dept"] == "示例总务处"
    # 方案随首个任务进入进行中;盘点人收到盘点任务提醒
    _login(client, "am")
    resp = client.get(f"/api/asset/inventory/plans/{plan['id']}")
    assert resp.json()["status"] == "进行中"
    _login(client, "tea")
    resp = client.get("/api/asset/workspace/reminders?kind=盘点任务")
    assert resp.status_code == 200, resp.text
    assert any(r["target_id"] == task["id"] for r in resp.json())


# ── #49 手机扫码盘点 ──────────────────────────────
def test_scan_in_scope_out_of_scope_and_unlabelled(env, users):
    client, db = env
    _login(client, "am")
    in_card = _create_card(client, "示例在范围资产", manage_dept="示例总务处",
                           room_name="示例机房",
                           custodian_user_id=users["tea"].id)
    out_card = _create_card(client, "示例范围外资产", manage_dept="示例教务处",
                            room_name="示例教室")
    plan = _plan(client)
    task = _task(client, plan["id"], users, scope_dept="示例总务处")
    # 范围内扫码:计入并写 last_used_at
    out = _scan(client, task["id"], in_card["label_code"],
                room_name="示例机房", custodian_id=users["tea"].id)
    assert out["in_scope"] is True
    assert _card(db, in_card["id"]).last_used_at is not None
    # 重复扫码不重复建记录
    _scan(client, task["id"], in_card["label_code"], room_name="示例机房")
    _login(client, "am")
    resp = client.get(f"/api/asset/inventory/tasks/{task['id']}/records")
    assert len(resp.json()) == 1
    # 范围外扫码:明确提示,不静默计入
    out = _scan(client, task["id"], out_card["label_code"])
    assert out["in_scope"] is False
    assert "不在本次盘点任务范围内" in out["message"]
    resp = client.get(f"/api/asset/inventory/tasks/{task['id']}/records")
    assert len(resp.json()) == 1
    # 未知标签码:提示走补录
    _login(client, "tea")
    resp = client.post(f"/api/asset/inventory/tasks/{task['id']}/scan",
                       json={"label_code": "ZC2099XXXXZ"})
    assert resp.status_code == 404
    # 未贴标补录拍照:进待核实清单
    _login(client, "tea")
    resp = client.post(f"/api/asset/inventory/tasks/{task['id']}/unlabelled",
                       json={"name": "示例未贴标资产", "description": "示例补录",
                             "photo_url": "https://example.invalid/p.jpg",
                             "room_name": "示例机房", "is_offline": True})
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "待核实"
    assert resp.json()["is_offline"] is True


# ── #51 五类差异自动比对 ──────────────────────────────
def _five_type_setup(client, users):
    """A 正常/B 盘亏/C 位置不符/D 保管人不符 + 1 条未贴标补录。"""
    _login(client, "am")
    a = _create_card(client, "示例正常资产", manage_dept="示例总务处",
                     room_name="示例机房", custodian_user_id=users["tea"].id,
                     custodian_name="示例保管人")
    b = _create_card(client, "示例盘亏资产", manage_dept="示例总务处",
                     room_name="示例机房", custodian_user_id=users["tea"].id)
    c = _create_card(client, "示例位置不符资产", manage_dept="示例总务处",
                     room_name="示例机房", custodian_user_id=users["tea"].id)
    d = _create_card(client, "示例保管人不符资产", manage_dept="示例总务处",
                     room_name="示例机房", custodian_user_id=users["tea"].id,
                     custodian_name="示例保管人")
    plan = _plan(client)
    task = _task(client, plan["id"], users, scope_dept="示例总务处")
    _scan(client, task["id"], a["label_code"], room_name="示例机房",
          custodian_id=users["tea"].id)
    _scan(client, task["id"], c["label_code"], room_name="示例实验室",
          custodian_id=users["tea"].id)
    _scan(client, task["id"], d["label_code"], room_name="示例机房",
          custodian_id=users["tea2"].id, custodian_name="示例他人")
    _login(client, "tea")
    client.post(f"/api/asset/inventory/tasks/{task['id']}/unlabelled",
                json={"name": "示例未贴标资产", "description": "示例补录"})
    _login(client, "am")
    resp = client.post(f"/api/asset/inventory/tasks/{task['id']}/compute-diffs")
    assert resp.status_code == 200, resp.text
    return plan, task, {"a": a, "b": b, "c": c, "d": d}, resp.json()["counts"]


def test_five_diff_types(env, users):
    client, db = env
    plan, task, cards, counts = _five_type_setup(client, users)
    assert counts == {"正常": 1, "盘亏": 1, "盘盈": 1, "位置不符": 1, "保管人不符": 1}
    diffs = _diffs(client, plan["id"])
    assert len(diffs) == 5
    shortage = _diffs(client, plan["id"], "盘亏")[0]
    assert shortage["asset_code"] == cards["b"]["asset_code"]
    surplus = _diffs(client, plan["id"], "盘盈")[0]
    assert surplus["asset_id"] is None
    assert surplus["asset_name"] == "示例未贴标资产"


# ── #52 差异核实与处理 ──────────────────────────────
def test_resolve_shortage_location_custodian(env, users):
    client, db = env
    plan, task, cards, _ = _five_type_setup(client, users)
    # 盘亏查责任:说明为空拦截
    shortage = _diffs(client, plan["id"], "盘亏")[0]
    _login(client, "am")
    resp = client.post(
        f"/api/asset/inventory/differences/{shortage['id']}/resolve",
        json={"action": "shortage", "resolution": ""})
    assert resp.status_code == 400
    out = _resolve(client, shortage["id"], "shortage", "示例责任:已查明去向")
    assert out["status"] == "已处理"
    # 位置不符直接更正并留痕
    loc = _diffs(client, plan["id"], "位置不符")[0]
    out = _resolve(client, loc["id"], "correct_location", "示例更正:以实盘为准")
    assert out["status"] == "已处理"
    assert _card(db, cards["c"]["id"]).room_name == "示例实验室"
    # 保管人不符直接更正并留痕
    cus = _diffs(client, plan["id"], "保管人不符")[0]
    out = _resolve(client, cus["id"], "correct_custodian", "示例更正:以实盘为准")
    assert out["status"] == "已处理"
    assert _card(db, cards["d"]["id"]).custodian_user_id == users["tea2"].id
    # 已处理差异重算后不再重建
    _login(client, "am")
    resp = client.post(f"/api/asset/inventory/tasks/{task['id']}/compute-diffs")
    assert resp.json()["counts"]["盘亏"] == 0
    assert resp.json()["counts"]["位置不符"] == 0


def test_resolve_surplus_creates_card_via_intake_24(env, users):
    client, db = env
    plan, task, cards, _ = _five_type_setup(client, users)
    surplus = _diffs(client, plan["id"], "盘盈")[0]
    out = _resolve(client, surplus["id"], "surplus_create",
                   "示例核实:确为盘盈,补建卡",
                   name="示例盘盈资产", category_code="A0203",
                   original_value=1200, room_name="示例机房")
    assert out["status"] == "已处理"
    assert out["asset_code"] is not None
    assert out["acceptance_id"] is not None
    new_card = _card(db, out["asset_id"])
    assert new_card.acquire_method == "inventory_surplus"
    assert new_card.sync_status == "未同步"
    # 验收单确为 #24 盘盈补记入口
    from app.models.asset_ledger import AssetAcceptance, IntakeType
    acc = db.get(AssetAcceptance, out["acceptance_id"])
    assert acc.intake_type == IntakeType.INVENTORY_SURPLUS
    assert acc.source_doc["inventory_no"] == plan["plan_no"]


def test_close_requires_leader_and_all_diffs_handled(env, users):
    client, db = env
    plan, task, cards, _ = _five_type_setup(client, users)
    # 非领导关闭 → 403
    _login(client, "am")
    resp = client.post(f"/api/asset/inventory/plans/{plan['id']}/close",
                       json={"confirm_note": "示例确认"})
    assert resp.status_code == 403
    # 领导关闭但差异未处理完 → 400
    _login(client, "dir")
    resp = client.post(f"/api/asset/inventory/plans/{plan['id']}/close",
                       json={"confirm_note": "示例确认"})
    assert resp.status_code == 400
    # 逐条处理:盘亏/位置/保管人处理,正常写说明,盘盈补建卡
    for diff in _diffs(client, plan["id"]):
        if diff["diff_type"] == "盘亏":
            _resolve(client, diff["id"], "shortage", "示例责任说明")
        elif diff["diff_type"] == "位置不符":
            _resolve(client, diff["id"], "correct_location", "示例更正")
        elif diff["diff_type"] == "保管人不符":
            _resolve(client, diff["id"], "correct_custodian", "示例更正")
        elif diff["diff_type"] == "盘盈":
            _resolve(client, diff["id"], "surplus_create", "示例补建卡",
                     name="示例盘盈资产", category_code="A0203")
        else:
            _resolve(client, diff["id"], "note", "示例说明:实盘与台账一致")
    # 领导确认关闭
    _login(client, "dir")
    resp = client.post(f"/api/asset/inventory/plans/{plan['id']}/close",
                       json={"confirm_note": "示例确认关闭"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "已关闭"


def test_close_allowed_with_note_only(env, users):
    client, db = env
    plan, task, cards, _ = _five_type_setup(client, users)
    for diff in _diffs(client, plan["id"]):
        _resolve(client, diff["id"], "note", "示例说明:已核实,暂不处理")
    _login(client, "dir")
    resp = client.post(f"/api/asset/inventory/plans/{plan['id']}/close",
                       json={"confirm_note": "示例确认"})
    assert resp.status_code == 200, resp.text


# ── 盘点到期扫描与报告 ──────────────────────────────
def test_scan_due_and_report_marks_synced(env, users):
    client, db = env
    _login(client, "am")
    card = _create_card(client, "示例已同步资产", manage_dept="示例总务处",
                        room_name="示例机房")
    _card(db, card["id"]).sync_status = "已同步"
    db.commit()
    plan = _plan(client)
    task = _task(client, plan["id"], users, due_in_days=-1,
                 scope_dept="示例总务处")
    # 未扫码即比对:已同步资产记盘亏且标注涉及已同步
    _login(client, "am")
    client.post(f"/api/asset/inventory/tasks/{task['id']}/compute-diffs")
    resp = client.get(f"/api/asset/inventory/plans/{plan['id']}/report")
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["diff_counts"]["盘亏"] == 1
    assert len(report["synced_differences"]) == 1
    assert "不自动同步" in report["note"]
    # 到期扫描:盘点人收到逾期提醒
    resp = client.post("/api/asset/inventory/scan-due")
    assert resp.status_code == 200, resp.text
    assert task["id"] in resp.json()["reminded_tasks"]
    _login(client, "tea")
    resp = client.get("/api/asset/workspace/reminders?kind=盘点任务")
    assert any(r["level"] == "逾期" for r in resp.json())
