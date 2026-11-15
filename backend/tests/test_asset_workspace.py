"""第 3 批后端测试:个人工作台(#1/#2/#3/#6)与提醒/履历。

自建测试 app 与 test_asset_circulation.py 相同(复用同一套路由挂载),
种子经 seed_asset_foundation 写入。
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
    asset_intake,
    asset_sync_select,
    asset_transfer,
    asset_workspace,
    auth,
)
from app.core.db import Base, get_db
from app.models.asset_card import AssetCard
from app.models.asset_circulation import AssetReminder
from app.models.asset_disposal import AssetDisposalOrder
from app.models.asset_approval import ApprovalInstance
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
    application.include_router(asset_intake.router, prefix="/api/asset")
    application.include_router(asset_sync_select.router, prefix="/api/asset")
    application.include_router(asset_circulation.router, prefix="/api/asset")
    application.include_router(asset_transfer.router, prefix="/api/asset")
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
        ("da2", [Role.asset_dept_admin]),
        ("dir", [Role.director]),
        ("fin", [Role.asset_finance]),
        ("tea", [Role.teacher]),
        ("tea2", [Role.teacher]),
    ]:
        made[username] = create_user(
            db, username=username, password=PW, roles=list(roles),
            must_change_password=False
        )
    db.commit()
    return made


def _login(client, username):
    resp = client.post("/api/auth/login", json={"username": username, "password": PW})
    assert resp.status_code == 200, resp.text


def _booked_card(client, **overrides):
    _login(client, "am")
    body = {"name": "示例资产", "category_code": "A0203"}
    body.update(overrides)
    resp = client.post("/api/asset/assets", json=body)
    assert resp.status_code == 201, resp.text
    card = resp.json()
    _login(client, "fin")
    resp = client.post(f"/api/asset/assets/{card['id']}/book",
                       json={"voucher_no": f"PZ-示例-{card['id']}"})
    assert resp.status_code == 200, resp.text
    _login(client, "am")
    return resp.json()


def _borrow(client, asset_id, days=1):
    _login(client, "tea")
    due = (datetime.now(UTC) + timedelta(days=days)).isoformat()
    resp = client.post("/api/asset/borrows", json={
        "asset_id": asset_id, "reason": "示例借用", "due_at": due})
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── #1 我的待办只见本人、按紧急程度排序 ──────────────────────────────
def test_todos_only_mine_and_urgency_order(env, users):
    client, db = env
    card_overdue = _booked_card(client)
    card_today = _booked_card(client)
    card_issue = _booked_card(client, original_value=3000)
    # tea:一笔逾期借用 + 一笔今天到期借用。
    overdue = _borrow(client, card_overdue["id"], days=1)
    today = _borrow(client, card_today["id"], days=1)
    from app.models.asset_circulation import AssetBorrowOrder

    for borrow_id, delta in ((overdue["id"], -2), (today["id"], 0)):
        row = db.get(AssetBorrowOrder, borrow_id)
        row.due_at = datetime.now(UTC) + timedelta(days=delta)
        if delta == 0:
            row.due_at = datetime.now(UTC) + timedelta(hours=2)
    db.commit()
    # tea 申请领用 → da 的待办里有该审批,tea 的待办里没有(申请人排除)。
    _login(client, "tea")
    resp = client.post("/api/asset/issues", json={"asset_id": card_issue["id"]})
    assert resp.status_code == 201, resp.text
    _login(client, "am")
    client.post("/api/asset/workspace/scan-overdue")

    _login(client, "tea")
    resp = client.get("/api/asset/workspace/todos")
    assert resp.status_code == 200, resp.text
    todos = resp.json()
    kinds = [t["kind"] for t in todos]
    assert "借用逾期" in kinds
    assert "借用当天到期" in kinds
    assert "待审批" not in kinds
    # 逾期排在当天到期之前。
    assert kinds.index("借用逾期") < kinds.index("借用当天到期")
    assert all(t["urgency_rank"] >= 0 for t in todos)

    _login(client, "da")
    resp = client.get("/api/asset/workspace/todos")
    kinds = [t["kind"] for t in resp.json()]
    assert "待审批" in kinds
    assert "借用逾期" not in kinds
    assert "借用当天到期" not in kinds


# ── #2 我的资产与报修占位 ──────────────────────────────
def test_my_assets_and_report_repair(env, users):
    client, db = env
    card = _booked_card(client)
    _login(client, "tea")
    resp = client.post("/api/asset/issues", json={"asset_id": card["id"]})
    order = resp.json()
    _login(client, "da")
    client.post(f"/api/asset/approval-instances/{order['approval_instance_id']}/act",
                json={"action": "approve"})
    _login(client, "am")
    client.post(f"/api/asset/approval-instances/{order['approval_instance_id']}/act",
                json={"action": "approve"})
    client.post(f"/api/asset/issues/{order['id']}/issue")
    # tea 名下有该资产;tea2 名下没有。
    _login(client, "tea")
    resp = client.get("/api/asset/workspace/my-assets")
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["asset_code"] == card["asset_code"]
    _login(client, "tea2")
    resp = client.get("/api/asset/workspace/my-assets")
    assert resp.json()["total"] == 0
    # 报修入口:生成维修占位单(B4 接入工单);重复报修返回同一单。
    _login(client, "tea")
    resp = client.post(
        f"/api/asset/workspace/my-assets/{card['id']}/report-repair",
        json={"description": "示例无法开机"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] is True
    assert resp.json()["doc_no"].startswith("WX-")
    resp2 = client.post(
        f"/api/asset/workspace/my-assets/{card['id']}/report-repair",
        json={"description": "重复报修"})
    assert resp2.json()["created"] is False
    assert resp2.json()["doc_no"] == resp.json()["doc_no"]
    # 非保管人报修 → 403。
    _login(client, "tea2")
    resp = client.post(
        f"/api/asset/workspace/my-assets/{card['id']}/report-repair",
        json={"description": "越权报修"})
    assert resp.status_code == 403, resp.text


# ── #3 提醒中心 ──────────────────────────────
def test_reminder_center_read_and_scope(env, users):
    client, db = env
    card = _booked_card(client)
    _borrow(client, card["id"], days=1)
    from app.models.asset_circulation import AssetBorrowOrder

    borrow = db.query(AssetBorrowOrder).first()
    borrow.due_at = datetime.now(UTC) - timedelta(days=1)
    db.commit()
    _login(client, "am")
    client.post("/api/asset/workspace/scan-overdue")
    _login(client, "tea")
    resp = client.get("/api/asset/workspace/reminders")
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 1
    rem = resp.json()[0]
    assert rem["kind"] == "借用逾期"
    assert rem["is_read"] is False
    # 本人标记已读;他人标记 → 403。
    resp = client.post(f"/api/asset/workspace/reminders/{rem['id']}/read")
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_read"] is True
    _login(client, "tea2")
    resp = client.post(f"/api/asset/workspace/reminders/{rem['id']}/read")
    assert resp.status_code == 403, resp.text
    _login(client, "tea")
    resp = client.get("/api/asset/workspace/reminders?is_read=true")
    assert len(resp.json()) == 1
    _login(client, "tea2")
    assert client.get("/api/asset/workspace/reminders").json() == []


def test_warranty_reminder_scan(env, users):
    client, db = env
    card = _booked_card(client)
    row = db.get(AssetCard, card["id"])
    row.custodian_user_id = users["tea"].id
    row.ext = {"warranty_until": (datetime.now(UTC) + timedelta(days=10)).strftime("%Y-%m-%d")}
    db.commit()
    _login(client, "am")
    resp = client.post("/api/asset/workspace/scan-warranty")
    assert resp.status_code == 200, resp.text
    assert resp.json()["reminded"] == [card["id"]]
    rem = db.query(AssetReminder).filter_by(kind="保修到期").first()
    assert rem is not None and rem.user_id == users["tea"].id


def test_approval_overdue_scan(env, users):
    client, db = env
    card = _booked_card(client, original_value=3000)
    _login(client, "tea")
    resp = client.post("/api/asset/issues", json={"asset_id": card["id"]})
    inst_id = resp.json()["approval_instance_id"]
    inst = db.get(ApprovalInstance, inst_id)
    inst.deadline = datetime.now(UTC) - timedelta(hours=1)
    db.commit()
    _login(client, "am")
    resp = client.post("/api/asset/workspace/scan-approval-overdue")
    assert resp.status_code == 200, resp.text
    assert inst_id in resp.json()["marked"]
    db.refresh(inst)
    assert inst.is_overdue is True
    rem = db.query(AssetReminder).filter_by(
        kind="审批超时", target_id=inst_id).first()
    assert rem is not None and rem.user_id == users["tea"].id


# ── #6 履历时间轴 ──────────────────────────────
def test_timeline_contains_full_history(env, users):
    client, db = env
    card = _booked_card(client, original_value=3000)
    _login(client, "tea")
    resp = client.post("/api/asset/issues", json={"asset_id": card["id"]})
    order = resp.json()
    _login(client, "da")
    client.post(f"/api/asset/approval-instances/{order['approval_instance_id']}/act",
                json={"action": "approve"})
    _login(client, "am")
    client.post(f"/api/asset/approval-instances/{order['approval_instance_id']}/act",
                json={"action": "approve"})
    client.post(f"/api/asset/issues/{order['id']}/issue")
    _login(client, "tea")
    client.post(f"/api/asset/issues/{order['id']}/confirm-scan",
                json={"label_code": card["label_code"]})
    resp = client.get(f"/api/asset/assets/{card['id']}/timeline")
    assert resp.status_code == 200, resp.text
    entries = resp.json()
    titles = " | ".join(e["title"] for e in entries)
    assert "建卡" in titles
    assert "领用单" in titles
    # 复核补 #6:处置单须有结构化条目,不只走审计日志。
    db.add(AssetDisposalOrder(
        doc_no="CZ-20261115-0001", asset_id=card["id"],
        disposal_type="scrap", reason="复核", status="待鉴定",
    ))
    db.commit()
    resp = client.get(f"/api/asset/assets/{card['id']}/timeline")
    assert resp.status_code == 200, resp.text
    titles = " | ".join(e["title"] for e in resp.json())
    assert "处置单 CZ-20261115-0001" in titles
    assert "asset_status_transition" in titles
    assert "asset_card_create" in titles
    # 按时间倒序。
    times = [e["time"] for e in entries if e["time"]]
    assert times == sorted(times, reverse=True)
    # 不存在的资产 → 404。
    assert client.get("/api/asset/assets/99999/timeline").status_code == 404


# ── Portal 首页资产提示汇总 ──────────────────────────────
def _portal_hints_setup(client, db, users):
    """tea:1 笔逾期借用 + 1 笔 3 天后到期借用 + 1 张待确认维修单。"""
    from app.models.asset_circulation import AssetBorrowOrder, AssetRepairOrder, RepairStatus

    card_overdue = _booked_card(client)
    card_soon = _booked_card(client)
    overdue = _borrow(client, card_overdue["id"], days=1)
    _borrow(client, card_soon["id"], days=3)
    row = db.get(AssetBorrowOrder, overdue["id"])
    row.due_at = datetime.now(UTC) - timedelta(days=2)
    db.add(AssetRepairOrder(
        doc_no="WX-TEST-1", asset_id=card_overdue["id"],
        reporter_id=users["tea"].id, reporter_name="tea",
        description="测试报修", status=RepairStatus.PENDING_CONFIRM,
    ))
    db.commit()
    return card_overdue, card_soon


def test_portal_hints_teacher_only_mine(env, users):
    client, db = env
    _portal_hints_setup(client, db, users)
    _login(client, "tea")
    resp = client.get("/api/asset/workspace/portal-hints")
    assert resp.status_code == 200, resp.text
    h = resp.json()
    assert h["my_assets_total"] == 2
    assert h["my_borrow_overdue"] == 1
    assert h["my_borrow_due_soon"] == 1
    assert h["my_repair_open"] == 1
    assert h["my_repair_pending_confirm"] == 1
    for key in ("admin_pending_approval", "admin_borrow_overdue",
                "admin_repair_pending_confirm", "admin_inventory_open_plans",
                "admin_inventory_open_tasks", "admin_disposal_open",
                "admin_sync_pending", "leader_idle_count", "leader_idle_value",
                "leader_disposal_open", "leader_disposal_by_status"):
        assert h[key] is None, key


def test_portal_hints_admin_and_leader(env, users):
    client, db = env
    from app.models.asset_card import SyncStatus
    from app.models.asset_disposal import AssetDisposalOrder
    from app.models.asset_inventory import (
        AssetInventoryPlan,
        AssetInventoryTask,
        InventoryPlanStatus,
        InventoryTaskStatus,
    )

    card_overdue, card_soon = _portal_hints_setup(client, db, users)
    card_issue = _booked_card(client, original_value=3000)
    # tea 申请领用 → 产生进行中审批,admin(超级用户)待审批数为 1。
    _login(client, "tea")
    resp = client.post("/api/asset/issues", json={"asset_id": card_issue["id"]})
    assert resp.status_code == 201, resp.text
    # 进行中盘点方案 + 待盘点任务 + 待鉴定处置单 + 待同步池 + 闲置卡。
    db.add(AssetInventoryPlan(
        plan_no="PD-TEST-1", name="测试盘点",
        status=InventoryPlanStatus.IN_PROGRESS))
    db.flush()
    plan = db.query(AssetInventoryPlan).filter_by(plan_no="PD-TEST-1").one()
    db.add(AssetInventoryTask(
        plan_id=plan.id, assignee_id=users["am"].id, assignee_name="am",
        due_at=datetime.now(UTC) + timedelta(days=7),
        status=InventoryTaskStatus.PENDING))
    db.add(AssetDisposalOrder(
        doc_no="CZ-TEST-1", asset_id=card_soon["id"],
        disposal_type="scrap", status="待鉴定"))
    idle_card = db.get(AssetCard, card_soon["id"])
    idle_card.is_idle = True
    idle_card.original_value = 8000
    sync_card = db.get(AssetCard, card_issue["id"])
    sync_card.sync_status = SyncStatus.pending.value
    db.commit()

    _login(client, "adm")
    resp = client.get("/api/asset/workspace/portal-hints")
    assert resp.status_code == 200, resp.text
    h = resp.json()
    # adm 为超级用户,待审批看到全流程当前节点(含部门岗节点)。
    assert h["admin_pending_approval"] == 1
    assert h["admin_borrow_overdue"] == 1
    assert h["admin_repair_pending_confirm"] == 1
    assert h["admin_inventory_open_plans"] == 1
    assert h["admin_inventory_open_tasks"] == 1
    assert h["admin_disposal_open"] == 1
    assert h["admin_sync_pending"] == 1
    assert h["leader_idle_count"] == 1
    assert h["leader_idle_value"] == 8000
    assert h["leader_disposal_open"] == 1
    assert h["leader_disposal_by_status"] == {
        "待鉴定": 1, "待审批": 0, "审批通过": 0, "待官方批复": 0, "已批复": 0}

    # 资产管理员同样看到管理口径;但待审批是本人待办口径——领用单当前
    # 节点在部门岗,am 的待审批为 0,全校借用逾期仍为 1。
    _login(client, "am")
    resp = client.get("/api/asset/workspace/portal-hints")
    assert resp.status_code == 200, resp.text
    h = resp.json()
    assert h["admin_pending_approval"] == 0
    assert h["admin_borrow_overdue"] == 1
    assert h["admin_sync_pending"] == 1
    assert h["leader_idle_count"] is None

    # 校领导只见领导口径,管理字段为 null,本人无资产则我的口径为 0。
    _login(client, "dir")
    resp = client.get("/api/asset/workspace/portal-hints")
    assert resp.status_code == 200, resp.text
    h = resp.json()
    assert h["my_assets_total"] == 0
    assert h["my_borrow_overdue"] == 0
    assert h["my_borrow_due_soon"] == 0
    assert h["my_repair_open"] == 0
    for key in ("admin_pending_approval", "admin_borrow_overdue",
                "admin_repair_pending_confirm", "admin_inventory_open_plans",
                "admin_inventory_open_tasks", "admin_disposal_open",
                "admin_sync_pending"):
        assert h[key] is None, key
    assert h["leader_idle_count"] == 1
    assert h["leader_disposal_open"] == 1
