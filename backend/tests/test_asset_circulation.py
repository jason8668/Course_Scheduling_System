"""第 3 批后端测试:领用/借用/预约/归还/团体保管/调拨/移交。

自建测试 app:auth + asset_foundation + asset_intake + asset_sync_select
+ asset_circulation + asset_transfer + asset_workspace,SQLite 记忆体库,
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
from app.models.audit import AuditLog
from app.models.user import Role
from app.services import dingtalk_students
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


def _create_card(client, category="A0203", **overrides):
    body = {"name": "示例资产", "category_code": category}
    body.update(overrides)
    resp = client.post("/api/asset/assets", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _booked_card(client, **overrides):
    _login(client, "am")
    card = _create_card(client, **overrides)
    _login(client, "fin")
    resp = client.post(f"/api/asset/assets/{card['id']}/book",
                       json={"voucher_no": f"PZ-示例-{card['id']}"})
    assert resp.status_code == 200, resp.text
    _login(client, "am")
    return resp.json()


def _approve_issue(client, instance_id):
    """通用流(金额<5000):部门管理员 → 资产管理员,两步通过。"""
    _login(client, "da")
    resp = client.post(f"/api/asset/approval-instances/{instance_id}/act",
                       json={"action": "approve"})
    assert resp.status_code == 200, resp.text
    _login(client, "am")
    resp = client.post(f"/api/asset/approval-instances/{instance_id}/act",
                       json={"action": "approve"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "已通过"


def _card(db, card_id):
    row = db.get(AssetCard, card_id)
    db.refresh(row)
    return row


# ── #30/#31 领用全流程 ──────────────────────────────
def test_issue_full_flow(env, users):
    client, db = env
    card = _booked_card(client, original_value=3000)
    _login(client, "tea")
    resp = client.post("/api/asset/issues", json={
        "asset_id": card["id"], "use_dept": "示例教研组", "reason": "示例教学使用"})
    assert resp.status_code == 201, resp.text
    order = resp.json()
    assert order["doc_no"].startswith("LY-")
    assert order["status"] == "申请中"
    inst_id = order["approval_instance_id"]
    assert inst_id

    # 岗位分离:申请人自己审批 → 403。
    resp = client.post(f"/api/asset/approval-instances/{inst_id}/act",
                       json={"action": "approve"})
    assert resp.status_code == 403, resp.text

    # 审批通过后待发放;发放前扫码确认应被拒。
    _approve_issue(client, inst_id)
    _login(client, "tea")
    resp = client.post(f"/api/asset/issues/{order['id']}/confirm-scan",
                       json={"label_code": card["label_code"]})
    assert resp.status_code == 400, resp.text
    resp = client.get(f"/api/asset/issues/{order['id']}")
    assert resp.json()["status"] == "待发放"

    # 发放:状态 在库→在用,保管人变更,写 last_used_at。
    _login(client, "am")
    resp = client.post(f"/api/asset/issues/{order['id']}/issue")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "已发放"
    row = _card(db, card["id"])
    assert row.status == "在用"
    assert row.custodian_user_id == users["tea"].id
    assert row.custodian_name == "tea"
    assert row.use_dept == "示例教研组"
    assert row.last_used_at is not None

    # 扫码确认:他人扫码 → 403;标签码不符 → 400;本人扫码 → 已确认。
    _login(client, "tea2")
    resp = client.post(f"/api/asset/issues/{order['id']}/confirm-scan",
                       json={"label_code": card["label_code"]})
    assert resp.status_code == 403, resp.text
    _login(client, "tea")
    resp = client.post(f"/api/asset/issues/{order['id']}/confirm-scan",
                       json={"label_code": "错的标签码"})
    assert resp.status_code == 400, resp.text
    resp = client.post(f"/api/asset/issues/{order['id']}/confirm-scan",
                       json={"label_code": card["label_code"]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "已确认"
    assert resp.json()["confirmed_at"] is not None
    row = _card(db, card["id"])
    assert row.last_used_at is not None


def test_issue_unbooked_rejected(env, users):
    client, db = env
    _login(client, "am")
    card = _create_card(client)
    assert card["is_booked"] is False
    _login(client, "tea")
    resp = client.post("/api/asset/issues", json={"asset_id": card["id"]})
    assert resp.status_code == 400, resp.text
    assert "未入账" in resp.text


# ── #32 借用与逾期扫描 ──────────────────────────────
def test_borrow_overdue_scan_and_escalation(env, users):
    client, db = env
    card = _booked_card(client)
    _login(client, "tea")
    due = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    resp = client.post("/api/asset/borrows", json={
        "asset_id": card["id"], "reason": "示例借用", "due_at": due})
    assert resp.status_code == 201, resp.text
    order = resp.json()
    assert order["doc_no"].startswith("JY-")
    assert _card(db, card["id"]).status == "借出"

    # 同一资产重复借用 → 400。
    resp = client.post("/api/asset/borrows", json={
        "asset_id": card["id"], "reason": "重复借用", "due_at": due})
    assert resp.status_code == 400, resp.text

    # 把归还时间改到 3 天前,扫描:逾期 + 升级(阈值 3 天)。
    from app.models.asset_circulation import AssetBorrowOrder

    borrow = db.get(AssetBorrowOrder, order["id"])
    borrow.due_at = datetime.now(UTC) - timedelta(days=3)
    db.commit()
    _login(client, "am")
    resp = client.post("/api/asset/workspace/scan-overdue")
    assert resp.status_code == 200, resp.text
    assert order["id"] in resp.json()["overdue"]
    assert order["id"] in resp.json()["escalated"]
    db.refresh(borrow)
    assert borrow.status == "已逾期"
    assert borrow.is_overdue is True
    assert borrow.overdue_days == 3
    # 借用人收到逾期提醒;资产管理员收到升级提醒(user_id 为空)。
    mine = db.query(AssetReminder).filter_by(
        kind="借用逾期", target_id=order["id"], user_id=users["tea"].id).first()
    assert mine is not None and mine.level == "逾期"
    escalated = db.query(AssetReminder).filter_by(
        kind="借用逾期", target_id=order["id"], user_id=None).first()
    assert escalated is not None
    # 逾期清单可见。
    resp = client.get("/api/asset/borrows/overdue")
    assert resp.status_code == 200, resp.text
    assert [b["id"] for b in resp.json()] == [order["id"]]


def test_borrow_due_soon_reminder(env, users):
    client, db = env
    card = _booked_card(client)
    _login(client, "tea")
    due = (datetime.now(UTC) + timedelta(hours=12)).isoformat()
    resp = client.post("/api/asset/borrows", json={
        "asset_id": card["id"], "reason": "示例借用", "due_at": due})
    assert resp.status_code == 201, resp.text
    _login(client, "am")
    resp = client.post("/api/asset/workspace/scan-overdue")
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["reminded"]) == 1
    rem = db.query(AssetReminder).filter_by(kind="借用到期").first()
    assert rem is not None and rem.user_id == users["tea"].id


def test_dingtalk_failure_does_not_block_scan(env, users, monkeypatch):
    """#7:钉钉推送失败只记日志,不阻塞逾期扫描。"""
    client, db = env
    card = _booked_card(client)
    _login(client, "tea")
    due = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    resp = client.post("/api/asset/borrows", json={
        "asset_id": card["id"], "reason": "示例借用", "due_at": due})
    order = resp.json()
    from app.models.asset_circulation import AssetBorrowOrder

    borrow = db.get(AssetBorrowOrder, order["id"])
    borrow.due_at = datetime.now(UTC) - timedelta(days=1)
    db.commit()

    def _boom(_db):
        raise RuntimeError("示例钉钉未配置")

    monkeypatch.setattr(dingtalk_students, "get_client", _boom)
    _login(client, "am")
    resp = client.post("/api/asset/workspace/scan-overdue")
    assert resp.status_code == 200, resp.text
    assert order["id"] in resp.json()["overdue"]
    assert db.query(AssetReminder).filter_by(kind="借用逾期").first() is not None


# ── #33 预约冲突与自动释放 ──────────────────────────────
def test_reservation_conflict_and_release(env, users):
    client, db = env
    card = _booked_card(client)
    _login(client, "tea")
    start = datetime.now(UTC) + timedelta(hours=1)
    end = start + timedelta(hours=2)
    resp = client.post("/api/asset/reservations", json={
        "asset_id": card["id"], "start_at": start.isoformat(),
        "end_at": end.isoformat(), "purpose": "示例会议"})
    assert resp.status_code == 201, resp.text
    first = resp.json()
    assert first["doc_no"].startswith("YY-")
    # 重叠时段 → 409 明确错误;不重叠 → 通过。
    resp = client.post("/api/asset/reservations", json={
        "asset_id": card["id"],
        "start_at": (start + timedelta(minutes=30)).isoformat(),
        "end_at": (end + timedelta(hours=1)).isoformat(), "purpose": "冲突预约"})
    assert resp.status_code == 409, resp.text
    assert "时间冲突" in resp.text
    resp = client.post("/api/asset/reservations", json={
        "asset_id": card["id"],
        "start_at": (end + timedelta(hours=1)).isoformat(),
        "end_at": (end + timedelta(hours=2)).isoformat(), "purpose": "不冲突预约"})
    assert resp.status_code == 201, resp.text
    second = resp.json()
    # 领用:转为借用单,资产→借出。
    resp = client.post(f"/api/asset/reservations/{first['id']}/checkout")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "已领用"
    assert _card(db, card["id"]).status == "借出"
    # 到期未领用的预约自动释放:把第二笔的结束时间改到过去再扫描。
    from app.models.asset_circulation import AssetReservation

    row = db.get(AssetReservation, second["id"])
    row.end_at = datetime.now(UTC) - timedelta(hours=1)
    row.start_at = datetime.now(UTC) - timedelta(hours=2)
    db.commit()
    _login(client, "am")
    resp = client.post("/api/asset/reservations/scan-release")
    assert resp.status_code == 200, resp.text
    assert second["id"] in resp.json()["released"]
    db.refresh(row)
    assert row.status == "已释放"
    assert db.query(AuditLog).filter_by(
        action="asset_reservation_release", target_id=second["id"]).first() is not None


# ── #34 归还完好/损坏两路 ──────────────────────────────
def _borrowed_card(client, db, users):
    card = _booked_card(client)
    # 设为已同步,验证归还后 sync_status 保持原值。
    row = _card(db, card["id"])
    row.sync_status = "已同步"
    db.commit()
    _login(client, "tea")
    due = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    resp = client.post("/api/asset/borrows", json={
        "asset_id": card["id"], "reason": "示例借用", "due_at": due})
    assert resp.status_code == 201, resp.text
    return card, resp.json()


def test_return_good_keeps_sync_status(env, users):
    client, db = env
    card, borrow = _borrowed_card(client, db, users)
    resp = client.post("/api/asset/returns", json={
        "asset_id": card["id"], "source_doc_type": "借用单",
        "source_doc_id": borrow["id"]})
    assert resp.status_code == 201, resp.text
    ret = resp.json()
    assert ret["doc_no"].startswith("GH-")
    resp = client.post(f"/api/asset/returns/{ret['id']}/scan", json={
        "label_code": card["label_code"], "result": "完好"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "已完成"
    row = _card(db, card["id"])
    assert row.status == "在库"
    assert row.sync_status == "已同步"
    assert row.last_used_at is not None
    from app.models.asset_circulation import AssetBorrowOrder

    assert db.get(AssetBorrowOrder, borrow["id"]).status == "已归还"


def test_return_damaged_creates_repair_placeholder(env, users):
    client, db = env
    card, borrow = _borrowed_card(client, db, users)
    resp = client.post("/api/asset/returns", json={
        "asset_id": card["id"], "source_doc_type": "借用单",
        "source_doc_id": borrow["id"]})
    ret = resp.json()
    resp = client.post(f"/api/asset/returns/{ret['id']}/scan", json={
        "label_code": card["label_code"], "result": "损坏",
        "damage_note": "示例屏幕破裂"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "已转维修"
    assert resp.json()["repair_order_id"] is not None
    row = _card(db, card["id"])
    assert row.status == "维修中"
    resp = client.get(f"/api/asset/repairs/{resp.json()['repair_order_id']}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["doc_no"].startswith("WX-")
    assert resp.json()["source"] == "归还验收"
    assert resp.json()["status"] == "待处理"


# ── #35 团体保管 ──────────────────────────────
def test_group_custody_no_student_account(env, users):
    client, db = env
    card = _booked_card(client)
    before = db.query(AssetCard).count()
    from app.models.user import User

    user_count = db.query(User).count()
    _login(client, "am")
    resp = client.post("/api/asset/group-custodies", json={
        "asset_id": card["id"], "group_type": "班级",
        "group_name": "示例七年级1班", "teacher_id": users["tea"].id,
        "note": "示例团体保管"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["doc_no"].startswith("TB-")
    assert resp.json()["teacher_name"] == "tea"
    row = _card(db, card["id"])
    assert row.custodian_user_id == users["tea"].id
    assert row.use_dept == "示例七年级1班"
    # 不新建学生账号:用户数不变。
    assert db.query(User).count() == user_count
    assert db.query(AssetCard).count() == before


# ── #37 调拨三方确认与待同步变更标记 ──────────────────────────────
def test_transfer_three_party_and_pending_sync_change(env, users):
    client, db = env
    card = _booked_card(client, manage_dept="示例总务处", original_value=3000)
    row = _card(db, card["id"])
    row.sync_status = "已同步"
    db.commit()
    # 调出部门发起(部门管理员)。
    _login(client, "da")
    resp = client.post("/api/asset/transfers", json={
        "asset_id": card["id"], "to_dept": "示例教务处",
        "to_custodian_id": users["tea2"].id, "to_room_name": "示例教室",
        "reason": "示例调拨"})
    assert resp.status_code == 201, resp.text
    order = resp.json()
    assert order["doc_no"].startswith("DB-")
    assert order["status"] == "待调入确认"
    inst_id = order["approval_instance_id"]
    # 未调入确认先完成 → 400。
    _login(client, "am")
    resp = client.post(f"/api/asset/transfers/{order['id']}/finalize")
    assert resp.status_code == 400, resp.text
    # 调入部门确认。
    _login(client, "da2")
    resp = client.post(f"/api/asset/transfers/{order['id']}/confirm-in")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "待审批"
    # 审批:发起人 da 不能自审(403);da2(部门) → am(资产管理员) 通过。
    _login(client, "da")
    resp = client.post(f"/api/asset/approval-instances/{inst_id}/act",
                       json={"action": "approve"})
    assert resp.status_code == 403, resp.text
    _login(client, "da2")
    resp = client.post(f"/api/asset/approval-instances/{inst_id}/act",
                       json={"action": "approve"})
    assert resp.status_code == 200, resp.text
    _login(client, "am")
    resp = client.post(f"/api/asset/approval-instances/{inst_id}/act",
                       json={"action": "approve"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "已通过"
    # 完成:责任与位置变更;已同步资产打待同步变更标记,同步状态仍为已同步。
    resp = client.post(f"/api/asset/transfers/{order['id']}/finalize")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "已完成"
    row = _card(db, card["id"])
    assert row.manage_dept == "示例教务处"
    assert row.custodian_user_id == users["tea2"].id
    assert row.room_name == "示例教室"
    assert row.status == "在库"
    assert row.sync_status == "已同步"
    assert row.pending_sync_change is True
    assert "调拨" in (row.pending_sync_change_reason or "")


# ── #39/#40 移交 ──────────────────────────────
def _give_cards_to(db, users, username, count=2):
    ids = []
    for _ in range(count):
        card = AssetCard(
            asset_code=f"ZC2026A0203{1000 + len(ids)}",
            label_code=f"ZC2026A0203{1000 + len(ids)}X",
            name="示例资产", category_code="A0203",
            status="在用", is_booked=True,
            custodian_user_id=users[username].id,
            custodian_name=username,
        )
        db.add(card)
        db.flush()
        ids.append(card.id)
    db.commit()
    return ids


def test_handover_generate_and_item_confirm(env, users):
    client, db = env
    ids = _give_cards_to(db, users, "tea", 2)
    _login(client, "am")
    resp = client.post("/api/asset/handovers/generate", json={
        "from_user_id": users["tea"].id, "to_user_id": users["tea2"].id,
        "reason_type": "离职"})
    assert resp.status_code == 201, resp.text
    order = resp.json()
    assert order["doc_no"].startswith("YJ-")
    assert len(order["items"]) == 2
    item1, item2 = order["items"]
    # 标签码不符 → 400;逐件确认后保管人转移,未确认件仍属原保管人。
    _login(client, "tea2")
    resp = client.post(
        f"/api/asset/handovers/{order['id']}/items/{item1['id']}/confirm",
        json={"label_code": "错的标签码"})
    assert resp.status_code == 400, resp.text
    card1 = _card(db, item1["asset_id"])
    resp = client.post(
        f"/api/asset/handovers/{order['id']}/items/{item1['id']}/confirm",
        json={"label_code": card1.label_code})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "部分确认"
    assert _card(db, item1["asset_id"]).custodian_user_id == users["tea2"].id
    assert _card(db, item2["asset_id"]).custodian_user_id == users["tea"].id
    card2 = _card(db, item2["asset_id"])
    resp = client.post(
        f"/api/asset/handovers/{order['id']}/items/{item2['id']}/confirm",
        json={"label_code": card2.label_code})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "已完成"


def test_handover_generate_no_assets(env, users):
    client, db = env
    _login(client, "am")
    resp = client.post("/api/asset/handovers/generate", json={
        "from_user_id": users["tea"].id, "to_user_id": users["tea2"].id,
        "reason_type": "调岗"})
    assert resp.status_code == 400, resp.text


def test_handover_warning_threshold(env, users):
    client, db = env
    _give_cards_to(db, users, "tea", 1)
    _login(client, "am")
    resp = client.post("/api/asset/handovers/generate", json={
        "from_user_id": users["tea"].id, "to_user_id": users["tea2"].id,
        "reason_type": "退休"})
    order = resp.json()
    from app.models.asset_circulation import AssetHandoverOrder

    row = db.get(AssetHandoverOrder, order["id"])
    row.created_at = datetime.now(UTC) - timedelta(days=8)
    db.commit()
    resp = client.post("/api/asset/workspace/scan-handover-warnings")
    assert resp.status_code == 200, resp.text
    assert order["id"] in resp.json()["warned"]
    assert resp.json()["threshold_days"] == 7
    db.refresh(row)
    assert row.is_overdue is True
    rem = db.query(AssetReminder).filter_by(
        kind="移交预警", target_id=order["id"]).first()
    assert rem is not None
    resp = client.get("/api/asset/workspace/handover-warnings")
    assert resp.json()["total"] == 1
