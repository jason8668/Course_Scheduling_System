"""第 5 批后端测试:处置与报废(M8 #54~#58)。

自建测试 app:auth + asset_foundation + asset_intake + asset_circulation
+ asset_sync_select + asset_disposal,SQLite 记忆体库,种子经
seed_asset_foundation 写入(含处置审批流与 disposal.materials 参数)。
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import pytest

from app.api import (
    asset_circulation,
    asset_disposal,
    asset_foundation,
    asset_intake,
    asset_sync_select,
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
    application.include_router(asset_sync_select.router, prefix="/api/asset")
    application.include_router(asset_disposal.router, prefix="/api/asset")
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
        ("insp", [Role.asset_inspector]),
        ("tea", [Role.teacher]),
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


def _create_card(client, **overrides):
    _login(client, "am")
    body = {"name": "示例资产", "category_code": "A0203"}
    body.update(overrides)
    resp = client.post("/api/asset/assets", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _to_pending(client, card):
    _login(client, "am")
    resp = client.post(
        f"/api/asset/assets/{card['id']}/transition",
        json={"to_status": "待处置", "doc_type": "处置单", "doc_no": "TEST-001"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _disposal(client, card, disposal_type="scrap", materials=None):
    _login(client, "am")
    resp = client.post("/api/asset/disposals", json={
        "asset_id": card["id"], "disposal_type": disposal_type,
        "reason": "示例处置", "materials": materials or [],
    })
    return resp


def _approved_disposal(client, users, value=6000):
    """走完鉴定 + 三级审批的处置单(金额 6000,分管领导节点不跳过)。
    返回 (处置单, 资产卡)。"""
    card = _create_card(client, original_value=value,
                        acquire_method="purchase", funding_source="fiscal")
    _to_pending(client, card)
    resp = _disposal(client, card, "scrap",
                     ["技术鉴定单", "资产卡片", "购置凭证"])
    assert resp.status_code == 201, resp.text
    order = resp.json()
    _login(client, "insp")
    resp = client.post(f"/api/asset/disposals/{order['id']}/appraise",
                       json={"conclusion": "建议处置", "detail": "示例鉴定:已损坏"})
    assert resp.status_code == 201, resp.text
    _login(client, "am")
    resp = client.post(f"/api/asset/disposals/{order['id']}/submit-approval")
    assert resp.status_code == 200, resp.text
    inst_id = resp.json()["approval_instance_id"]
    assert inst_id
    # 申请人自审 → 403 岗位分离。
    _login(client, "am")
    resp = client.post(f"/api/asset/approval-instances/{inst_id}/act",
                       json={"action": "approve"})
    assert resp.status_code == 403, resp.text
    for username in ("da", "am", "dir"):
        # 注意:第二步 asset_admin 由另一位资产管理员审,避免自审;
        # 此处 am 为申请人,故第二步换 adm(超级用户可代审)。
        actor = "adm" if username == "am" else username
        _login(client, actor)
        resp = client.post(f"/api/asset/approval-instances/{inst_id}/act",
                           json={"action": "approve"})
        assert resp.status_code == 200, resp.text
    _login(client, "am")
    resp = client.get(f"/api/asset/disposals/{order['id']}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "审批通过", resp.text
    return resp.json(), card


# ── #54 多类型处置申请 ──────────────────────────────
def test_disposal_requires_pending_status(env, users):
    client, db = env
    card = _create_card(client)  # 在库,未转待处置
    resp = _disposal(client, card, "scrap",
                     ["技术鉴定单", "资产卡片", "购置凭证"])
    assert resp.status_code == 400
    assert "待处置" in resp.text


def test_disposal_materials_differ_by_type(env, users):
    client, db = env
    card = _create_card(client)
    _to_pending(client, card)
    # 报废缺"技术鉴定单" → 不得提交。
    resp = _disposal(client, card, "scrap", ["资产卡片", "购置凭证"])
    assert resp.status_code == 400
    assert "技术鉴定单" in resp.text
    # 报废材料齐全 → 通过;丢失赔偿材料清单不同。
    resp = _disposal(client, card, "scrap",
                     ["技术鉴定单", "资产卡片", "购置凭证"])
    assert resp.status_code == 201, resp.text
    assert resp.json()["doc_no"].startswith("CZ-")
    _login(client, "am")
    resp = client.get("/api/asset/disposals/materials?disposal_type=loss_compensation")
    assert resp.status_code == 200
    assert "丢失情况说明" in resp.json()["materials_required"]
    assert "技术鉴定单" not in resp.json()["materials_required"]


def test_disposal_unknown_type_rejected(env, users):
    client, db = env
    card = _create_card(client)
    _to_pending(client, card)
    resp = _disposal(client, card, "not_a_type", ["资产卡片"])
    assert resp.status_code == 400


# ── #55 处置前技术鉴定 ──────────────────────────────
def test_appraisal_reusable_closes_disposal_and_returns_stock(env, users):
    client, db = env
    card = _create_card(client)
    _to_pending(client, card)
    resp = _disposal(client, card, "scrap",
                     ["技术鉴定单", "资产卡片", "购置凭证"])
    assert resp.status_code == 201, resp.text
    order = resp.json()
    _login(client, "insp")
    resp = client.post(f"/api/asset/disposals/{order['id']}/appraise",
                       json={"conclusion": "可继续使用", "detail": "示例鉴定:尚可使用"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["doc_no"].startswith("JD-")
    _login(client, "am")
    resp = client.get(f"/api/asset/disposals/{order['id']}")
    assert resp.json()["status"] == "已关闭"
    resp = client.get(f"/api/asset/assets/{card['id']}")
    assert resp.json()["status"] == "在库"


def test_appraisal_requires_inspector_role(env, users):
    client, db = env
    card = _create_card(client)
    _to_pending(client, card)
    resp = _disposal(client, card, "scrap",
                     ["技术鉴定单", "资产卡片", "购置凭证"])
    order = resp.json()
    _login(client, "tea")
    resp = client.post(f"/api/asset/disposals/{order['id']}/appraise",
                       json={"conclusion": "建议处置"})
    assert resp.status_code == 403


def test_appraisal_suggest_disposal_moves_to_approval(env, users):
    client, db = env
    card = _create_card(client)
    _to_pending(client, card)
    resp = _disposal(client, card, "damage",
                     ["技术鉴定单", "报损说明", "资产卡片"])
    order = resp.json()
    _login(client, "insp")
    resp = client.post(f"/api/asset/disposals/{order['id']}/appraise",
                       json={"conclusion": "建议报废", "detail": "示例鉴定"})
    assert resp.status_code == 201, resp.text
    _login(client, "am")
    resp = client.get(f"/api/asset/disposals/{order['id']}")
    assert resp.json()["status"] == "待审批"


# ── #56 分级处置审批 ──────────────────────────────
def test_disposal_graded_approval_and_separation(env, users):
    client, db = env
    order, card = _approved_disposal(client, users, value=6000)
    assert order["status"] == "审批通过"
    # 审批金额取原值:实例金额应为 6000。
    _login(client, "am")
    resp = client.get(f"/api/asset/approval-instances/{order['approval_instance_id']}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["amount"] == 6000


def test_disposal_low_value_skips_director_node(env, users):
    client, db = env
    # 金额 3000 < 5000,分管领导节点跳过,两级审批即通过。
    card2 = _create_card(client, original_value=3000)
    _to_pending(client, card2)
    resp = _disposal(client, card2, "scrap",
                     ["技术鉴定单", "资产卡片", "购置凭证"])
    order2 = resp.json()
    _login(client, "insp")
    client.post(f"/api/asset/disposals/{order2['id']}/appraise",
                json={"conclusion": "建议处置"})
    _login(client, "am")
    resp = client.post(f"/api/asset/disposals/{order2['id']}/submit-approval")
    inst_id = resp.json()["approval_instance_id"]
    _login(client, "da")
    assert client.post(f"/api/asset/approval-instances/{inst_id}/act",
                       json={"action": "approve"}).status_code == 200
    _login(client, "adm")
    assert client.post(f"/api/asset/approval-instances/{inst_id}/act",
                       json={"action": "approve"}).status_code == 200
    _login(client, "am")
    resp = client.get(f"/api/asset/disposals/{order2['id']}")
    assert resp.json()["status"] == "审批通过"


# ── #57/#99 申报材料包只对已选择生效 ──────────────────────────────
def test_package_requires_manual_selection(env, users):
    client, db = env
    order, card = _approved_disposal(client, users, value=6000)
    _login(client, "am")
    resp = client.post(f"/api/asset/disposals/{order['id']}/package")
    assert resp.status_code == 400
    assert "未手动选择" in resp.text
    resp = client.post(f"/api/asset/disposals/{order['id']}/select-official")
    assert resp.status_code == 200, resp.text
    assert resp.json()["selected_for_official"] is True
    resp = client.post(f"/api/asset/disposals/{order['id']}/package")
    assert resp.status_code == 201, resp.text
    assert resp.json()["package_no"].startswith("SB-")
    resp = client.get(f"/api/asset/disposals/{order['id']}/package/export")
    assert resp.status_code == 200, resp.text
    assert "application/vnd.openxmlformats" in resp.headers["content-type"]


# ── #58 未回填批复不得核销;核销后编号封存与历史可查 ──────────────────────────────
def test_retire_blocked_without_official_reply(env, users):
    client, db = env
    order, card = _approved_disposal(client, users, value=6000)
    _login(client, "am")
    # 处置单核销确认:未回填批复拦截。
    resp = client.post(f"/api/asset/disposals/{order['id']}/retire-confirm")
    assert resp.status_code == 400
    assert "未回填官方批复" in resp.text
    # 通用 retire 端点同样拦截(doc_no=处置单号)。
    resp = client.post(
        f"/api/asset/assets/{card['id']}/retire?doc_no={order['doc_no']}")
    assert resp.status_code == 400
    assert "未回填官方批复" in resp.text


def test_retire_after_reply_and_recovery(env, users):
    client, db = env
    order, card = _approved_disposal(client, users, value=6000)
    _login(client, "am")
    client.post(f"/api/asset/disposals/{order['id']}/select-official")
    client.post(f"/api/asset/disposals/{order['id']}/package")
    resp = client.post(f"/api/asset/disposals/{order['id']}/official-reply",
                       json={"reply_no": "示例批复-2026-001"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "已批复"
    resp = client.post(f"/api/asset/disposals/{order['id']}/retire-confirm")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "已核销"
    # 编号封存:卡片已核销、is_retired,历史仍可查到。
    resp = client.get(f"/api/asset/assets/{card['id']}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "已核销"
    assert resp.json()["is_retired"] is True
    # 在库台账不再出现该资产。
    resp = client.get("/api/asset/assets?status=在库")
    assert resp.status_code == 200, resp.text
    codes = [row["asset_code"] for row in resp.json()["items"]]
    assert card["asset_code"] not in codes
    # 回收交接单已生成骨架,补填后置已交接。
    resp = client.get(f"/api/asset/disposals/{order['id']}/recovery")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "待交接"
    assert resp.json()["recovery_no"].startswith("HS-")
    resp = client.post(
        f"/api/asset/disposals/{order['id']}/recovery",
        json={"recovery_org": "示例回收单位", "residual_income": 120,
              "voucher_no": "PZ-示例-残值-001",
              "photo_urls": ["https://example.invalid/handover.jpg"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "已交接"
    assert resp.json()["voucher_no"] == "PZ-示例-残值-001"
