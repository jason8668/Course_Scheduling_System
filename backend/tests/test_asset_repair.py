"""第 4 批后端测试:维修保养(#42/#43/#44)。

自建测试 app:auth + asset_foundation + asset_intake + asset_circulation
+ asset_repair + asset_workspace,SQLite 记忆体库,种子经 seed_asset_foundation
写入(含 approval.repair_threshold=5000 与通用/维修审批流)。
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import pytest

from app.api import (
    asset_circulation,
    asset_foundation,
    asset_intake,
    asset_repair,
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
    application.include_router(asset_intake.router, prefix="/api/asset")
    application.include_router(asset_circulation.router, prefix="/api/asset")
    application.include_router(asset_repair.router, prefix="/api/asset")
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


def _create_card(client, category="A0203", **overrides):
    body = {"name": "示例资产", "category_code": category}
    body.update(overrides)
    resp = client.post("/api/asset/assets", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _card(db, card_id):
    row = db.get(AssetCard, card_id)
    db.refresh(row)
    return row


def _report(client, users, card, **overrides):
    """保管人 tea 扫码报修,返回扫码回显。"""
    _login(client, "tea")
    body = {"label_code": card["label_code"], "description": "示例故障:无法开机",
            "photo_url": "https://example.invalid/fault.jpg"}
    body.update(overrides)
    resp = client.post("/api/asset/repairs/scan", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _approve_all(client, instance_id):
    """通用/维修审批流全流程:部门管理员 → 资产管理员 → 分管领导。"""
    for username in ("da", "am", "dir"):
        _login(client, username)
        resp = client.post(f"/api/asset/approval-instances/{instance_id}/act",
                           json={"action": "approve"})
        assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "已通过"


def _transition(client, card_id, to_status):
    _login(client, "am")
    resp = client.post(f"/api/asset/assets/{card_id}/transition",
                       json={"to_status": to_status, "doc_type": "维修单",
                             "doc_no": "WX-TEST-0001"})
    assert resp.status_code == 200, resp.text


# ── #42 扫码报修 ──────────────────────────────
def test_scan_repair_in_warranty(env, users):
    client, db = env
    _login(client, "am")
    card = _create_card(client, custodian_user_id=users["tea"].id,
                        custodian_name="示例保管人",
                        ext={"warranty_until": "2030-06-01"})
    out = _report(client, users, card)
    assert out["created"] is True
    assert out["in_warranty"] is True
    assert "厂商保修" in out["warranty_hint"]
    assert out["warranty_until"] == "2030-06-01"
    assert out["asset_code"] == card["asset_code"]
    assert out["doc_no"].startswith("WX-")
    # 同一资产重复报修不重复建单
    out2 = _report(client, users, card)
    assert out2["created"] is False
    assert out2["doc_no"] == out["doc_no"]


def test_scan_repair_out_of_warranty_and_unknown_label(env, users):
    client, db = env
    _login(client, "am")
    card = _create_card(client, custodian_user_id=users["tea"].id,
                        ext={"warranty_until": "2020-01-01"})
    out = _report(client, users, card)
    assert out["in_warranty"] is False
    assert "已过保" in out["warranty_hint"]
    _login(client, "tea")
    resp = client.post("/api/asset/repairs/scan",
                       json={"label_code": "ZC2099XXXXZ", "description": "x"})
    assert resp.status_code == 404
    # 非保管人、非资产管理员不可报修
    _login(client, "tea2")
    resp = client.post("/api/asset/repairs/scan",
                       json={"label_code": card["label_code"], "description": "x"})
    assert resp.status_code == 403


# ── #43 派单/费用/结果/报修人确认全流程(低于阈值) ──────────────────────────────
def test_repair_full_flow_under_threshold(env, users):
    client, db = env
    _login(client, "am")
    card = _create_card(client, custodian_user_id=users["tea"].id,
                        room_name="示例机房")
    out = _report(client, users, card)
    order_id = out["repair_order_id"]
    # 管理员派单并送修:资产转维修中
    _login(client, "am")
    resp = client.post(f"/api/asset/repairs/{order_id}/dispatch",
                       json={"assignee_name": "示例维修员", "vendor": "示例厂商",
                             "send_to_repair": True})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "维修中"
    assert _card(db, card["id"]).status == "维修中"
    # 登记费用 800 元(<5000):直接进待确认,不走审批
    resp = client.post(f"/api/asset/repairs/{order_id}/record",
                       json={"vendor": "示例厂商", "cost": 800,
                             "result": "示例维修:更换电源"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "待确认"
    assert resp.json()["approval_instance_id"] is None
    # 非报修人不可确认
    _login(client, "am")
    resp = client.post(f"/api/asset/repairs/{order_id}/confirm")
    assert resp.status_code == 403
    # 报修人确认关闭:资产回在库,费用累计
    _login(client, "tea")
    resp = client.post(f"/api/asset/repairs/{order_id}/confirm")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "已关闭"
    assert _card(db, card["id"]).status == "在库"
    assert float(_card(db, card["id"]).total_repair_cost) == 800
    _login(client, "am")
    resp = client.get(f"/api/asset/repairs/summary/by-asset?asset_id={card['id']}")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"asset_id": card["id"], "total_cost": 800,
                           "closed_count": 1, "open_count": 0, "threshold": 5000}


def test_repair_back_to_in_use_and_dispatch_only(env, users):
    client, db = env
    _login(client, "am")
    card = _create_card(client, custodian_user_id=users["tea"].id)
    _transition(client, card["id"], "在用")
    assert _card(db, card["id"]).status == "在用"
    out = _report(client, users, card)
    order_id = out["repair_order_id"]
    # 只派单不送修:资产仍在用
    _login(client, "am")
    resp = client.post(f"/api/asset/repairs/{order_id}/dispatch",
                       json={"assignee_name": "示例维修员", "send_to_repair": False})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "已派单"
    assert _card(db, card["id"]).status == "在用"
    resp = client.post(f"/api/asset/repairs/{order_id}/record",
                       json={"cost": 100, "result": "示例维修:现场处理"})
    assert resp.json()["status"] == "待确认"
    _login(client, "tea")
    resp = client.post(f"/api/asset/repairs/{order_id}/confirm")
    assert resp.status_code == 200, resp.text
    # 修前在用 → 修好回在用
    assert _card(db, card["id"]).status == "在用"


# ── #43 超阈值维修走审批 ──────────────────────────────
def test_repair_over_threshold_requires_approval(env, users):
    client, db = env
    _login(client, "am")
    card = _create_card(client, custodian_user_id=users["tea"].id)
    out = _report(client, users, card)
    order_id = out["repair_order_id"]
    _login(client, "am")
    resp = client.post(f"/api/asset/repairs/{order_id}/dispatch",
                       json={"send_to_repair": True})
    assert resp.status_code == 200, resp.text
    # 费用 6000 元(≥5000):入待审批并建审批实例
    resp = client.post(f"/api/asset/repairs/{order_id}/record",
                       json={"vendor": "示例厂商", "cost": 6000,
                             "result": "示例维修:更换主板"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "待审批"
    instance_id = resp.json()["approval_instance_id"]
    assert instance_id is not None
    # 审批通过前报修人不可确认关闭
    _login(client, "tea")
    resp = client.post(f"/api/asset/repairs/{order_id}/confirm")
    assert resp.status_code == 400
    _approve_all(client, instance_id)
    _login(client, "tea")
    resp = client.post(f"/api/asset/repairs/{order_id}/confirm")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "已关闭"
    assert float(_card(db, card["id"]).total_repair_cost) == 6000


# ── #44 维修履历沉淀 ──────────────────────────────
def test_repair_appears_in_timeline(env, users):
    client, db = env
    _login(client, "am")
    card = _create_card(client, custodian_user_id=users["tea"].id)
    out = _report(client, users, card)
    order_id = out["repair_order_id"]
    _login(client, "am")
    client.post(f"/api/asset/repairs/{order_id}/dispatch",
                json={"send_to_repair": True})
    client.post(f"/api/asset/repairs/{order_id}/record",
                json={"cost": 200, "result": "示例维修"})
    _login(client, "tea")
    client.post(f"/api/asset/repairs/{order_id}/confirm")
    _login(client, "am")
    resp = client.get(f"/api/asset/assets/{card['id']}/timeline")
    assert resp.status_code == 200, resp.text
    entries = resp.json()
    assert any(e["type"] == "维修单" and out["doc_no"] in e["title"]
               for e in entries)
    # 报修/派单/登记/确认的审计日志以维修单为目标,不直接进资产卡时间轴;
    # #44 要求的是维修单据出现在时间轴上,上面一条即满足。
