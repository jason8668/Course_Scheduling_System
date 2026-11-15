"""资产收尾批测试(学校资产管理系统一期第 6 批)。

覆盖本批新增/核查内容:
- #83 备份覆盖:0039~0043 全部资产表都在 ORM 元数据里(整库 pg_dump
  按构造覆盖),保留份数 >= 30,每日备份排程存在。
- #84 二次确认:同步批次 confirm=false 必 400;导出/核销/同步的审计
  动作名均在登记册内。
- #113 移动端接口复用:四件事所用的路由均已注册,无新后端逻辑。
- #114 钉钉通知:移交预警/保修到期/审批超时三处扫描现会推送钉钉
  (以 monkeypatch 截获 push_to_user/push_to_role 断言)。
- #115 共用底座:资产卡外键复用智慧教务 rooms/users,无自建部门表。

自建测试 app(不改共用 conftest):auth + asset_sync 两个路由,
SQLite 记忆体库,种子数据经 seed_asset_foundation 写入。
扫描类断言直接调 service 函数(与手动触发端点同一函数)。
"""

import inspect
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import asset_sync, auth
from app.core.config import settings
from app.core.db import Base, get_db
from app.models.asset_approval import ApprovalFlow, ApprovalInstance, ApprovalNode
from app.models.asset_card import AssetCard
from app.models.asset_circulation import AssetHandoverOrder, HandoverStatus
from app.models.user import Role
from app.services import asset_circulation as circ_svc
from app.services import backup as backup_svc
from app.services.asset_audit import ASSET_AUDIT_ACTIONS
from app.services.asset_seed import seed_asset_foundation
from app.services.users import create_user

PW = "pw-123456"

#: 迁移 0039~0043 建的资产表(ORM 元数据里的全部 asset_* 表)。
EXPECTED_ASSET_TABLES = [
    "asset_acceptances", "asset_approval_flows", "asset_approval_instances",
    "asset_approval_nodes", "asset_attachments", "asset_batches",
    "asset_borrow_orders", "asset_cards", "asset_categories",
    "asset_category_finance_map", "asset_code_rules", "asset_dictionaries",
    "asset_disposal_appraisals", "asset_disposal_orders",
    "asset_disposal_packages", "asset_disposal_recoveries",
    "asset_field_mappings", "asset_group_custodies", "asset_handover_items",
    "asset_handover_orders", "asset_inventory_differences",
    "asset_inventory_plans", "asset_inventory_records",
    "asset_inventory_tasks", "asset_issue_orders", "asset_params",
    "asset_reminders", "asset_repair_orders", "asset_reservations",
    "asset_return_orders", "asset_room_extensions", "asset_sync_batch_items",
    "asset_sync_batches", "asset_sync_logs", "asset_sync_selections",
    "asset_transfer_orders",
]


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
    application.include_router(asset_sync.router, prefix="/api/asset")
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


def _make_user(db, username, roles):
    user = create_user(
        db, username=username, password=PW, roles=list(roles),
        must_change_password=False,
    )
    db.commit()
    return user


def _login(client, username):
    resp = client.post("/api/auth/login", json={"username": username, "password": PW})
    assert resp.status_code == 200, resp.text


@pytest.fixture
def users(env):
    client, db = env
    made = {
        "asset_admin": _make_user(db, "am", [Role.asset_admin]),
        "custodian": _make_user(db, "cu", [Role.asset_custodian]),
        "teacher": _make_user(db, "tea", [Role.teacher]),
    }
    return made


# ── #83 备份覆盖核查 ──────────────────────────────
def test_backup_covers_all_asset_tables():
    """整库 pg_dump 按构造覆盖全部资产表:ORM 元数据里的 36 张 asset_*
    表一个不少;create_backup 是无表过滤的全库 dump。"""
    tables = {t for t in Base.metadata.tables if t.startswith("asset_")}
    assert tables == set(EXPECTED_ASSET_TABLES)
    src = inspect.getsource(backup_svc.create_backup)
    assert "pg_dump" in src and "-Fc" in src
    assert "--table" not in src and "--exclude-table" not in src


def test_backup_retention_at_least_30_days():
    """保留不少于 30 天/30 份(#83):默认 backup_keep=30,每日一份。"""
    assert settings.backup_keep >= 30
    assert settings.backup_hour in range(24)


def test_daily_backup_job_scheduled():
    """每日自动备份排程存在:worker-ops 调度器会排 daily-backup。"""
    from app.workers.backup_job import daily_backup_job
    from app.workers.scheduler import _next_backup_time, schedule_daily_backup

    assert callable(daily_backup_job)
    assert callable(schedule_daily_backup)
    nxt = _next_backup_time()
    assert nxt.hour == settings.backup_hour


# ── #84 二次确认核查 ──────────────────────────────
def test_sync_batch_requires_confirm(env, users):
    """同步执行二次确认(#94):confirm=false 时后端直接 400,不到建批次。"""
    client, _db = env
    _login(client, "am")
    resp = client.post("/api/asset/sync/batches", json={
        "confirm": False, "selection_batch_no": "GX-示例",
    })
    assert resp.status_code == 400
    assert "二次确认" in resp.text


def test_second_confirm_audit_actions_registered():
    """二次确认的三类关键操作(导出/核销/同步执行)审计动作名均在册。"""
    for action in (
        "asset_ledger_export",      # 台账导出(#9,前端二次确认)
        "asset_card_retire",        # 核销(#58,前端二次确认)
        "asset_sync_confirm",       # 同步结果确认(#97)
        "asset_sync_execute_denied",  # 同步执行分岗拦截(#80)
        "asset_card_update",        # 改价值(PATCH,前后值对照留痕)
    ):
        assert action in ASSET_AUDIT_ACTIONS, action


# ── #113 移动端接口复用 ──────────────────────────────
def test_mobile_endpoints_reuse_existing_routes():
    """四件事复用的后端路由均已存在,本批未新增后端逻辑。"""
    from app.api import asset_circulation, asset_inventory, asset_ledger, asset_repair

    def paths(router):
        out = set()
        for r in router.routes:
            out.add(getattr(r, "path", ""))
        return out

    assert "/ledger/search" in paths(asset_ledger.router)          # 扫码查卡
    assert "/repairs/scan" in paths(asset_repair.router)           # 扫码报修
    assert any("confirm-scan" in p for p in paths(asset_circulation.router))  # 领用确认
    assert any("/inventory/tasks/" in p and p.endswith("/scan")
               for p in paths(asset_inventory.router))              # 扫码盘点


# ── #114 钉钉通知:三处扫描补推送 ──────────────────────────────
def _patch_notify(monkeypatch):
    calls: list[tuple[str, object]] = []
    from app.services import asset_notify

    def fake_user(db, user_id, title, text):
        calls.append(("user", user_id, title))
        return {"sent": 1, "skipped": 0, "failed": 0}

    def fake_role(db, role, title, text):
        calls.append(("role", role, title))
        return {"sent": 1, "skipped": 0, "failed": 0}

    monkeypatch.setattr(asset_notify, "push_to_user", fake_user)
    monkeypatch.setattr(asset_notify, "push_to_role", fake_role)
    return calls


def test_handover_warning_scan_pushes_dingtalk(env, users, monkeypatch):
    """移交预警扫描(#40):第 6 批前只写站内提醒,现钉钉推给移交双方。"""
    _client, db = env
    calls = _patch_notify(monkeypatch)
    order = AssetHandoverOrder(
        doc_no="YJ-示例-001", from_user_id=users["custodian"].id,
        from_user_name="示例移出人", to_user_id=users["teacher"].id,
        to_user_name="示例接收人", reason_type="离职",
        status=HandoverStatus.PENDING,
        created_at=datetime.now(UTC) - timedelta(days=10),
    )
    db.add(order)
    db.commit()
    result = circ_svc.scan_handover_warnings(db, None)
    assert result["warned"] == [order.id]
    pushed_uids = {c[1] for c in calls if c[0] == "user"}
    assert users["custodian"].id in pushed_uids
    assert users["teacher"].id in pushed_uids


def test_warranty_scan_pushes_dingtalk(env, users, monkeypatch):
    """保修到期扫描(#3):第 6 批前只写站内提醒,现钉钉推给保管人。"""
    _client, db = env
    calls = _patch_notify(monkeypatch)
    card = AssetCard(
        asset_code="ZC2026A02030001", label_code="ZC2026A02030001X",
        name="示例资产", category_code="A0203",
        custodian_user_id=users["custodian"].id, custodian_name="示例保管人",
        ext={"warranty_until": (datetime.now(UTC) + timedelta(days=5)).strftime("%Y-%m-%d")},
    )
    db.add(card)
    db.commit()
    result = circ_svc.scan_warranty(db, None)
    assert result["reminded"] == [card.id]
    assert any(c[0] == "user" and c[1] == users["custodian"].id for c in calls)


def test_approval_overdue_scan_pushes_dingtalk(env, users, monkeypatch):
    """审批超时扫描(#3/#5):文档曾称已推送但代码未推;现推申请人 + 当前节点角色。"""
    _client, db = env
    calls = _patch_notify(monkeypatch)
    flow = ApprovalFlow(doc_type="领用单", name="示例流",
                        nodes=[{"step": 1, "role": "asset_admin"}])
    db.add(flow)
    db.flush()
    inst = ApprovalInstance(
        flow_id=flow.id, doc_type="领用单", doc_id=1, doc_no="LY-示例-001",
        applicant_id=users["custodian"].id, applicant_name="示例申请人",
        status="进行中", current_step=1, is_overdue=True,
    )
    db.add(inst)
    db.flush()
    node = ApprovalNode(instance_id=inst.id, step=1, role="asset_admin",
                        status="待审批")
    db.add(node)
    db.commit()
    result = circ_svc.scan_approval_overdue_reminders(db, None)
    assert result["reminded_instances"] == [inst.id]
    assert any(c[0] == "user" and c[1] == users["custodian"].id for c in calls)
    assert any(c[0] == "role" and c[1] == "asset_admin" for c in calls)


# ── #115 共用底座复用点 ──────────────────────────────
def test_shared_base_reuse():
    """资产卡复用智慧教务 rooms/users,无自建组织/部门表。"""
    fks = {str(fk.column) for fk in AssetCard.__table__.foreign_keys}
    assert "rooms.id" in fks
    assert "users.id" in fks
    assert "asset_departments" not in Base.metadata.tables
    assert "asset_rooms" not in Base.metadata.tables
    assert "asset_teachers" not in Base.metadata.tables
    asset_roles = {r for r in Role if r.value.startswith("asset_")}
    assert asset_roles == {
        Role.asset_admin, Role.asset_finance, Role.asset_dept_admin,
        Role.asset_custodian, Role.asset_inspector, Role.asset_auditor,
    }
