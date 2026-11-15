"""手动勾选核心测试(学校资产管理系统一期第 2 批 #87~#90)。

自建测试 app:auth + asset_foundation + asset_intake + asset_sync_select,
SQLite 记忆体库,种子经 seed_asset_foundation 写入。
覆盖:单件勾选与权限、批量勾选逐条校验(已同步/已核销/未回填凭证号
不得勾选)、取消勾选回状态、待同步池统计与按批次分组。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import asset_foundation, asset_intake, asset_sync_select, auth
from app.core.db import Base, get_db
from app.models.audit import AuditLog
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
    for username, roles in [
        ("adm", [Role.admin]),
        ("am", [Role.asset_admin]),
        ("da", [Role.asset_dept_admin]),
        ("fin", [Role.asset_finance]),
        ("tea", [Role.teacher]),
    ]:
        create_user(db, username=username, password=PW, roles=list(roles),
                    must_change_password=False)
    db.commit()


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
    """建卡 + 财务回填凭证号(可勾选状态)。"""
    _login(client, "am")
    card = _create_card(client, **overrides)
    _login(client, "fin")
    resp = client.post(f"/api/asset/assets/{card['id']}/book",
                       json={"voucher_no": f"PZ-示例-{card['id']}"})
    assert resp.status_code == 200, resp.text
    _login(client, "am")
    return resp.json()


def _pool(client):
    resp = client.get("/api/asset/sync/pool")
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── #87 单件勾选 ──────────────────────────────
def test_single_select_and_audit(env, users):
    client, db = env
    card = _booked_card(client, original_value=3000)
    resp = client.post("/api/asset/sync/select", json={"asset_ids": [card["id"]]})
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["succeeded"]) == 1
    assert resp.json()["batch_no"].startswith("GX")
    resp = client.get(f"/api/asset/assets/{card['id']}")
    assert resp.json()["sync_status"] == "待同步"
    row = db.query(AuditLog).filter_by(
        action="asset_sync_select", target_id=card["id"]).first()
    assert row is not None and "勾选同步" in row.detail
    # 池中有该件,总价值对得上
    pool = _pool(client)
    assert pool["total"] == 1 and pool["total_value"] == 3000
    assert pool["items"][0]["asset_code"] == card["asset_code"]
    assert pool["items"][0]["selected_by"] is not None
    # 重复勾选逐条回告
    resp = client.post("/api/asset/sync/select", json={"asset_ids": [card["id"]]})
    assert len(resp.json()["succeeded"]) == 0
    assert "已在待同步池" in resp.json()["failed"][0]["reason"]


def test_select_requires_booking(env, users):
    client, db = env
    _login(client, "am")
    card = _create_card(client)  # 未回填凭证号
    resp = client.post("/api/asset/sync/select", json={"asset_ids": [card["id"]]})
    assert len(resp.json()["succeeded"]) == 0
    assert "未回填入账凭证号" in resp.json()["failed"][0]["reason"]
    resp = client.get(f"/api/asset/assets/{card['id']}")
    assert resp.json()["sync_status"] == "未同步"  # 状态不变


def test_select_retired_rejected(env, users):
    client, db = env
    card = _booked_card(client)
    client.post(f"/api/asset/assets/{card['id']}/transition", json={
        "to_status": "待处置", "doc_type": "处置", "doc_no": "CZ-示例-201"})
    client.post(f"/api/asset/assets/{card['id']}/retire?doc_no=CZ-示例-201")
    resp = client.post("/api/asset/sync/select", json={"asset_ids": [card["id"]]})
    assert len(resp.json()["failed"]) == 1
    assert "已核销" in resp.json()["failed"][0]["reason"]


def test_select_permission_only_asset_admin(env, users):
    client, db = env
    card = _booked_card(client)
    for username in ("tea", "da", "fin"):
        _login(client, username)
        resp = client.post("/api/asset/sync/select", json={"asset_ids": [card["id"]]})
        assert resp.status_code == 403, (username, resp.text)
    # 系统管理员可勾选(admin 一律通过)
    _login(client, "adm")
    resp = client.post("/api/asset/sync/select", json={"asset_ids": [card["id"]]})
    assert resp.status_code == 200
    assert len(resp.json()["succeeded"]) == 1


# ── #88 批量勾选 ──────────────────────────────
def test_select_by_filter(env, users):
    client, db = env
    a = _booked_card(client, name="示例甲", manage_dept="教务处",
                     original_value=1000)
    _booked_card(client, name="示例乙", manage_dept="总务处",
                 original_value=2000)
    _login(client, "am")
    unbooked = _create_card(client, name="示例未入账", manage_dept="教务处")
    resp = client.post("/api/asset/sync/select-by-filter",
                       json={"manage_dept": "教务处"})
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["succeeded"]) == 1  # 只勾上已入账的甲
    assert len(resp.json()["failed"]) == 1  # 未入账的逐条回告
    assert "未回填入账凭证号" in resp.json()["failed"][0]["reason"]
    pool = _pool(client)
    assert pool["total"] == 1
    assert pool["items"][0]["asset_code"] == a["asset_code"]


def test_bulk_select_mixed_results(env, users):
    client, db = env
    a = _booked_card(client, original_value=1000)
    _login(client, "am")
    b = _create_card(client)  # 未入账
    resp = client.post("/api/asset/sync/select",
                       json={"asset_ids": [a["id"], b["id"], 99999]})
    assert len(resp.json()["succeeded"]) == 1
    assert len(resp.json()["failed"]) == 2
    reasons = [f["reason"] for f in resp.json()["failed"]]
    assert any("不存在" in r for r in reasons)
    assert any("未回填入账凭证号" in r for r in reasons)


# ── #89 取消勾选 ──────────────────────────────
def test_unselect_returns_to_unsynced(env, users):
    client, db = env
    card = _booked_card(client)
    client.post("/api/asset/sync/select", json={"asset_ids": [card["id"]]})
    resp = client.post("/api/asset/sync/unselect", json={"asset_ids": [card["id"]]})
    assert resp.status_code == 200
    assert len(resp.json()["succeeded"]) == 1
    resp = client.get(f"/api/asset/assets/{card['id']}")
    assert resp.json()["sync_status"] == "未同步"  # 回到未同步,不影响台账
    assert _pool(client)["total"] == 0
    row = db.query(AuditLog).filter_by(
        action="asset_sync_unselect", target_id=card["id"]).first()
    assert row is not None
    # 不在池中的资产取消 → 逐条失败
    resp = client.post("/api/asset/sync/unselect", json={"asset_ids": [card["id"]]})
    assert len(resp.json()["failed"]) == 1
    assert "不在待同步池" in resp.json()["failed"][0]["reason"]


# ── #90 待同步池统计与分组 ──────────────────────────────
def test_sync_pool_groups_by_batch(env, users):
    client, db = env
    a = _booked_card(client, original_value=1000)
    b = _booked_card(client, original_value=2000)
    c = _booked_card(client, original_value=4000)
    # 两次勾选操作 → 两个批次
    client.post("/api/asset/sync/select", json={"asset_ids": [a["id"], b["id"]]})
    client.post("/api/asset/sync/select", json={"asset_ids": [c["id"]]})
    pool = _pool(client)
    assert pool["total"] == 3
    assert pool["total_value"] == 7000
    assert len(pool["groups"]) == 2
    assert sorted(g["count"] for g in pool["groups"].values()) == [1, 2]
    # 按批次筛选
    batch_no = pool["items"][0]["selection_batch_no"]
    resp = client.get(f"/api/asset/sync/pool?selection_batch_no={batch_no}")
    assert resp.json()["total"] >= 1
    assert all(i["selection_batch_no"] == batch_no for i in resp.json()["items"])
