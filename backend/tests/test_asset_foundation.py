"""资产地基批测试(学校资产管理系统一期第 1 批)。

自建测试 app(不改共用 conftest):auth + asset_foundation 两个路由,
SQLite 记忆体库,种子数据经 seed_asset_foundation 写入。
覆盖:分类字典种子、编码生成+校验位、状态机非法转移拦截、同步状态
默认未同步、审批流流转+岗位分离拦截、权限越权 403、审计留痕、映射配置 CRUD。
"""

from datetime import UTC

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import asset_foundation, auth
from app.core.db import Base, get_db
from app.models.asset_approval import ApprovalInstance
from app.models.asset_category import AssetCategory, AssetCategoryFinanceMap
from app.models.asset_config import AssetCodeRule, AssetDictionary, AssetParam
from app.models.asset_sync import AssetFieldMapping
from app.models.audit import AuditLog
from app.models.user import Role
from app.services import asset_foundation as asset_svc
from app.services.asset_seed import seed_asset_foundation
from app.services.asset_sync_adapter import TemplateExportAdapter
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
        "admin": _make_user(db, "adm", [Role.admin]),
        "asset_admin": _make_user(db, "am", [Role.asset_admin]),
        "dept_admin": _make_user(db, "da", [Role.asset_dept_admin]),
        "dept_admin2": _make_user(db, "da2", [Role.asset_dept_admin]),
        "director": _make_user(db, "dir", [Role.director]),
        "finance": _make_user(db, "fin", [Role.asset_finance]),
        "auditor": _make_user(db, "aud", [Role.asset_auditor]),
        "teacher": _make_user(db, "tea", [Role.teacher]),
        "applicant": _make_user(db, "app", [Role.asset_dept_admin]),
    }
    return made


def _create_card(client, category="A0203", **overrides):
    body = {"name": "示例资产", "category_code": category}
    body.update(overrides)
    resp = client.post("/api/asset/assets", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── #16 分类字典种子 ──────────────────────────────
def test_seed_categories_top_level(env):
    client, db = env
    rows = db.query(AssetCategory).filter_by(level=1).order_by(AssetCategory.code).all()
    assert [(r.code, r.name) for r in rows] == [
        ("A01", "房屋和构筑物"),
        ("A02", "设备"),
        ("A03", "文物和陈列品"),
        ("A04", "图书和档案"),
        ("A05", "家具和用具"),
        ("A06", "特种动植物"),
    ]
    # 四级字典:各级都有种子,总数 28
    assert db.query(AssetCategory).count() == 28
    assert db.query(AssetCategory).filter_by(level=4).count() == 2
    # 上报分类全部锁定来源可追溯
    assert db.query(AssetCategory).filter_by(origin="gbt14885").count() == 6


def test_seed_finance_map_and_dictionaries_and_params(env):
    client, db = env
    maps = db.query(AssetCategoryFinanceMap).filter_by(category_code="A02").all()
    assert {m.finance_subject_name for m in maps} == {"通用设备", "专用设备"}
    assert db.query(AssetDictionary).filter_by(dict_type="acquire_method").count() == 5
    assert db.query(AssetDictionary).filter_by(dict_type="disposal_type").count() == 7
    param = db.query(AssetParam).filter_by(key="fixed_asset.min_value").first()
    assert param is not None and param.value == "1000"
    assert db.query(AssetParam).filter_by(key="fixed_asset.min_years").first().value == "1"
    rule = db.query(AssetCodeRule).filter_by(is_active=True).first()
    assert rule is not None and rule.prefix == "ZC" and rule.sequence_width == 4
    assert db.query(AssetFieldMapping).filter_by(is_required=True).count() >= 7


def test_list_categories_api(env, users):
    client, db = env
    _login(client, "tea")
    resp = client.get("/api/asset/categories?level=1")
    assert resp.status_code == 200
    assert [r["code"] for r in resp.json()] == ["A01", "A02", "A03", "A04", "A05", "A06"]
    resp = client.get("/api/asset/categories?parent_code=A02")
    assert {r["code"] for r in resp.json()} == {
        "A0201", "A0202", "A0203", "A0204", "A0205"}


def test_reportable_category_cannot_be_created_or_renamed(env, users):
    client, db = env
    _login(client, "adm")
    # 上报分类不得自行新增
    resp = client.post("/api/asset/categories", json={
        "code": "A07", "name": "自创分类", "level": 1, "is_reportable": True})
    assert resp.status_code == 400
    # 校内标签可以新增(is_reportable=False)
    resp = client.post("/api/asset/categories", json={
        "code": "X01", "name": "校内标签示例", "level": 2, "parent_code": "A02"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["is_reportable"] is False
    # PATCH 不接受代码/名称,只改启用与排序;上报分类名称保持不变
    resp = client.patch("/api/asset/categories/A01",
                        json={"name": "改名尝试", "is_active": False})
    assert resp.status_code == 200
    assert resp.json()["name"] == "房屋和构筑物"
    assert resp.json()["is_active"] is False


# ── #17 编码生成 + 校验位 ──────────────────────────────
def test_check_digit_roundtrip():
    code = "ZC2026A020001"
    label = asset_svc.make_label_code(code)
    assert len(label) == len(code) + 1
    assert asset_svc.verify_label_code(label) is True
    assert asset_svc.verify_label_code(label[:-1] + "X") is False
    assert asset_svc.compute_check_digit(code) == asset_svc.compute_check_digit(code)


def test_generate_asset_code_sequence(env, users):

    client, db = env
    _login(client, "am")
    first = _create_card(client, category="A0203",
                         acquired_date="2026-03-10T00:00:00Z")
    assert first["asset_code"] == "ZC2026A02030001"
    second = _create_card(client, category="A0203")
    assert second["asset_code"] == "ZC2026A02030002"
    # 不同分类流水独立
    other = _create_card(client, category="A0501")
    assert other["asset_code"].startswith("ZC2026A0501")
    assert other["asset_code"].endswith("0001")


def test_code_rule_preview_requires_category(env, users):
    client, db = env
    _login(client, "am")
    resp = client.get("/api/asset/code-rules/preview?category_code=A0203")
    assert resp.status_code == 200
    assert resp.json()["asset_code"].startswith("ZC")
    assert asset_svc.verify_label_code(resp.json()["label_code"])


# ── #10/#11/#85 建卡:四区、标签码、默认未同步 ──────────────────────────────
def test_create_card_defaults_unsynced_and_label(env, users):
    client, db = env
    _login(client, "am")
    card = _create_card(
        client, category="A0203", original_value=2500, funding_source="fiscal",
        acquire_method="purchase", voucher_no="示例凭证-001",
        manage_dept="总务处", use_dept="教务处", custodian_name="示例保管人",
        campus="示例校区", building="示例楼", room_name="示例房间",
        attributes={"precision_grade": "一级"},
        ext={"remark": "演示备注", "bogus_field": "应被过滤"},
    )
    assert card["sync_status"] == "未同步"
    assert card["status"] == "在库"
    assert card["official_code"] is None
    assert card["label_code"] == asset_svc.make_label_code(card["asset_code"])
    assert asset_svc.verify_label_code(card["label_code"])
    # 扩展区只留白名单键,上报字段不混入
    assert card["ext"] == {"remark": "演示备注"}
    # 审计留痕
    row = db.query(AuditLog).filter_by(
        action="asset_card_create", target_id=card["id"]).first()
    assert row is not None


def test_attribute_template_validation(env, users):
    client, db = env
    _login(client, "am")
    # A0101 房屋须填面积与权证号
    resp = client.post("/api/asset/assets", json={
        "name": "示例房屋", "category_code": "A0101"})
    assert resp.status_code == 400
    assert "面积" in resp.json()["detail"]
    card = _create_card(client, category="A0101",
                        attributes={"area_sqm": 120, "certificate_no": "示例权证-1"})
    assert card["category_code"] == "A0101"
    # A0204 车辆须填车牌与行驶证
    resp = client.post("/api/asset/assets", json={
        "name": "示例车辆", "category_code": "A0204",
        "attributes": {"plate_no": "示例车牌"}})
    assert resp.status_code == 400
    # 叶级分类继承父级模板:A02010101 继承 A0201 的序列号要求
    resp = client.post("/api/asset/assets", json={
        "name": "示例一体机", "category_code": "A02010101"})
    assert resp.status_code == 400
    card = _create_card(client, category="A02010101",
                        attributes={"serial_no": "SN-示例-001"})
    assert card["asset_code"].startswith("ZC")


def test_create_card_unknown_category_rejected(env, users):
    client, db = env
    _login(client, "am")
    resp = client.post("/api/asset/assets", json={
        "name": "示例", "category_code": "A99"})
    assert resp.status_code == 400


# ── #15 状态机 ──────────────────────────────
def test_illegal_transition_blocked(env, users):
    client, db = env
    _login(client, "am")
    card = _create_card(client)
    # 在库 → 已核销 非法(须先经待处置)
    resp = client.post(f"/api/asset/assets/{card['id']}/transition", json={
        "to_status": "已核销", "doc_type": "处置", "doc_no": "CZ-示例-001"})
    assert resp.status_code == 400
    assert "非法状态转移" in resp.json()["detail"]
    # 在库 → 在用 合法,须带单据
    resp = client.post(f"/api/asset/assets/{card['id']}/transition", json={
        "to_status": "在用", "doc_type": "领用", "doc_no": "LY-示例-001"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "在用"
    # 已核销为终态:待处置 → 已核销后不可再转
    client.post(f"/api/asset/assets/{card['id']}/transition", json={
        "to_status": "待处置", "doc_type": "处置", "doc_no": "CZ-示例-002"})
    resp = client.post(f"/api/asset/assets/{card['id']}/retire?doc_no=CZ-示例-002")
    assert resp.status_code == 200
    assert resp.json()["status"] == "已核销"
    assert resp.json()["is_retired"] is True
    resp = client.post(f"/api/asset/assets/{card['id']}/transition", json={
        "to_status": "在库", "doc_type": "领用", "doc_no": "LY-示例-002"})
    assert resp.status_code == 400


def test_no_direct_status_endpoint(env, users):
    client, db = env
    _login(client, "am")
    card = _create_card(client)
    # PATCH 即使带 status 也改不了状态( schema 不接受该字段)
    resp = client.patch(f"/api/asset/assets/{card['id']}",
                        json={"status": "已核销", "name": "改名示例"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "在库"
    assert resp.json()["name"] == "改名示例"


def test_retire_requires_doc_no(env, users):
    client, db = env
    _login(client, "am")
    card = _create_card(client)
    client.post(f"/api/asset/assets/{card['id']}/transition", json={
        "to_status": "待处置", "doc_type": "处置", "doc_no": "CZ-示例-003"})
    resp = client.post(f"/api/asset/assets/{card['id']}/retire")
    assert resp.status_code == 400


def test_retired_code_cannot_be_reused(env, users):
    client, db = env
    _login(client, "am")
    card = _create_card(client, asset_code="ZC2026A02039999")
    client.post(f"/api/asset/assets/{card['id']}/transition", json={
        "to_status": "待处置", "doc_type": "处置", "doc_no": "CZ-示例-004"})
    client.post(f"/api/asset/assets/{card['id']}/retire?doc_no=CZ-示例-004")
    resp = client.post("/api/asset/assets", json={
        "name": "复用尝试", "category_code": "A0203",
        "asset_code": "ZC2026A02039999"})
    assert resp.status_code == 400
    assert "封存" in resp.json()["detail"]


# ── #85/#86 同步状态 ──────────────────────────────
def test_sync_status_filter(env, users):
    client, db = env
    _login(client, "am")
    card = _create_card(client)
    resp = client.get("/api/asset/assets?sync_status=未同步")
    assert resp.status_code == 200
    assert any(r["id"] == card["id"] for r in resp.json()["items"])
    resp = client.get("/api/asset/assets?sync_status=已同步")
    assert not any(r["id"] == card["id"] for r in resp.json()["items"])
    resp = client.get("/api/asset/assets?sync_status=不存在的状态")
    assert resp.status_code == 400


def test_dual_code_lookup(env, users):
    client, db = env
    _login(client, "am")
    card = _create_card(client)
    # 官方编号回填后双号可查
    resp = client.patch(f"/api/asset/assets/{card['id']}",
                        json={"official_code": "官方-示例-2026-001"})
    assert resp.status_code == 200
    for code in (card["asset_code"], "官方-示例-2026-001"):
        resp = client.get(f"/api/asset/assets/by-code/{code}")
        assert resp.status_code == 200, resp.text
        assert resp.json()["id"] == card["id"]


def test_label_verify_endpoint(env, users):
    client, db = env
    _login(client, "am")
    card = _create_card(client)
    resp = client.get(f"/api/asset/assets/{card['id']}/label")
    assert resp.status_code == 200
    assert resp.json()["valid"] is True


# ── #78/#82 权限越权 403 + 审计 ──────────────────────────────
def test_create_asset_forbidden_for_teacher_and_logged(env, users):
    client, db = env
    _login(client, "tea")
    resp = client.post("/api/asset/assets", json={
        "name": "示例", "category_code": "A0203"})
    assert resp.status_code == 403
    row = db.query(AuditLog).filter_by(action="asset_access_denied").first()
    assert row is not None
    assert "tea" in row.username


def test_audit_read_only_for_auditor(env, users):
    client, db = env
    _login(client, "am")
    card = _create_card(client)
    _login(client, "aud")
    resp = client.get(f"/api/asset/audit?target_type=asset_card&target_id={card['id']}")
    assert resp.status_code == 200
    assert any(r["action"] == "asset_card_create" for r in resp.json())
    _login(client, "tea")
    resp = client.get("/api/asset/audit")
    assert resp.status_code == 403


def test_update_audit_before_after(env, users):
    client, db = env
    _login(client, "am")
    card = _create_card(client)
    client.patch(f"/api/asset/assets/{card['id']}",
                 json={"name": "改后名称", "original_value": 3000})
    row = db.query(AuditLog).filter_by(
        action="asset_card_update", target_id=card["id"]).first()
    assert row is not None
    assert "改前" in row.detail and "改后" in row.detail
    assert "示例资产" in row.detail and "改后名称" in row.detail


# ── #5/#79/#80 审批流 ──────────────────────────────
def _make_instance(client, doc_type="通用", doc_id=1, amount=None, doc_no="SP-示例-001"):
    body = {"doc_type": doc_type, "doc_id": doc_id, "doc_no": doc_no}
    if amount is not None:
        body["amount"] = amount
    resp = client.post("/api/asset/approval-instances", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_approval_flow_low_amount_skips_director_step(env, users):
    client, db = env
    _login(client, "app")  # 申请人(部门资产管理员)
    inst = _make_instance(client, amount=100)
    assert inst["status"] == "进行中"
    assert inst["current_step"] == 1
    assert len(inst["nodes"]) == 2  # 金额 100 < 5000,分管领导节点被跳过
    # 申请人自己审批 → 403 岗位分离
    resp = client.post(f"/api/asset/approval-instances/{inst['id']}/act",
                       json={"action": "approve"})
    assert resp.status_code == 403
    assert "不能为同一人" in resp.json()["detail"]
    # 角色不符的审批 → 403
    _login(client, "tea")
    resp = client.post(f"/api/asset/approval-instances/{inst['id']}/act",
                       json={"action": "approve"})
    assert resp.status_code == 403
    # 第 1 步:另一位部门管理员通过 → 进入第 2 步
    _login(client, "da")
    resp = client.post(f"/api/asset/approval-instances/{inst['id']}/act",
                       json={"action": "approve"})
    assert resp.status_code == 200
    assert resp.json()["current_step"] == 2
    # 第 2 步:资产管理员通过 → 全流程通过
    _login(client, "am")
    resp = client.post(f"/api/asset/approval-instances/{inst['id']}/act",
                       json={"action": "approve"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "已通过"
    # 已结束的流程不可再操作
    resp = client.post(f"/api/asset/approval-instances/{inst['id']}/act",
                       json={"action": "approve"})
    assert resp.status_code == 400


def test_approval_high_amount_requires_director(env, users):
    client, db = env
    _login(client, "app")
    inst = _make_instance(client, doc_id=2, amount=6000)
    assert len(inst["nodes"]) == 3
    _login(client, "da")
    client.post(f"/api/asset/approval-instances/{inst['id']}/act",
                json={"action": "approve"})
    _login(client, "am")
    client.post(f"/api/asset/approval-instances/{inst['id']}/act",
                json={"action": "approve"})
    resp = client.get(f"/api/asset/approval-instances/{inst['id']}")
    assert resp.json()["status"] == "进行中"
    assert resp.json()["current_step"] == 3
    _login(client, "dir")
    resp = client.post(f"/api/asset/approval-instances/{inst['id']}/act",
                       json={"action": "approve"})
    assert resp.json()["status"] == "已通过"


def test_approval_reject_and_transfer(env, users):
    client, db = env
    _login(client, "app")
    inst = _make_instance(client, doc_id=3, amount=100)
    _login(client, "da")
    # 转交给财务岗
    resp = client.post(f"/api/asset/approval-instances/{inst['id']}/transfer",
                       json={"to_role": "asset_finance", "comment": "转财务复核"})
    assert resp.status_code == 200
    assert resp.json()["nodes"][0]["role"] == "asset_finance"
    # 财务岗退回
    _login(client, "fin")
    resp = client.post(f"/api/asset/approval-instances/{inst['id']}/act",
                       json={"action": "reject", "comment": "材料不全"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "已退回"


def test_approval_all_mode_needs_two_approvers(env, users):
    client, db = env
    _login(client, "adm")
    resp = client.post("/api/asset/approval-flows", json={
        "doc_type": "处置", "name": "处置会签流",
        "nodes": [{"step": 1, "role": "asset_dept_admin", "mode": "all",
                   "required_approvals": 2}]})
    assert resp.status_code == 201, resp.text
    _login(client, "app")
    inst = _make_instance(client, doc_type="处置", doc_id=9, amount=100)
    assert len(inst["nodes"]) == 1
    # 同一人重复审批被拦截
    _login(client, "da")
    resp = client.post(f"/api/asset/approval-instances/{inst['id']}/act",
                       json={"action": "approve"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "进行中"
    resp = client.post(f"/api/asset/approval-instances/{inst['id']}/act",
                       json={"action": "approve"})
    assert resp.status_code == 400
    # 第二人通过后才算过
    _login(client, "da2")
    resp = client.post(f"/api/asset/approval-instances/{inst['id']}/act",
                       json={"action": "approve"})
    assert resp.json()["status"] == "已通过"


def test_approval_overdue_marking(env, users):
    from datetime import datetime, timedelta

    client, db = env
    _login(client, "app")
    inst = _make_instance(client, doc_id=4, amount=100)
    row = db.get(ApprovalInstance, inst["id"])
    row.deadline = datetime.now(UTC) - timedelta(hours=1)
    db.commit()
    _login(client, "adm")
    resp = client.post("/api/asset/approval-instances/mark-overdue")
    assert resp.status_code == 200
    assert inst["id"] in resp.json()["marked"]
    resp = client.get(f"/api/asset/approval-instances/{inst['id']}")
    assert resp.json()["is_overdue"] is True
    assert resp.json()["status"] == "进行中"  # 只标记,不自动流转


# ── #104 映射配置 CRUD ──────────────────────────────
def test_field_mapping_crud(env, users):
    client, db = env
    _login(client, "adm")
    resp = client.get("/api/asset/field-mappings")
    assert resp.status_code == 200
    assert any(m["local_field"] == "category_code" for m in resp.json())
    resp = client.post("/api/asset/field-mappings", json={
        "local_field": "room_name", "official_field": "存放地点",
        "transform_rule": "校区-楼栋-房间归集", "is_required": False})
    assert resp.status_code == 201, resp.text
    mapping_id = resp.json()["id"]
    # 重复映射被拦截
    resp = client.post("/api/asset/field-mappings", json={
        "local_field": "room_name", "official_field": "存放地点"})
    assert resp.status_code == 400
    resp = client.patch(f"/api/asset/field-mappings/{mapping_id}",
                        json={"is_required": True})
    assert resp.status_code == 200
    assert resp.json()["is_required"] is True
    # 非管理员不得改映射
    _login(client, "tea")
    resp = client.post("/api/asset/field-mappings", json={
        "local_field": "x", "official_field": "y"})
    assert resp.status_code == 403


# ── #81 字典与参数 ──────────────────────────────
def test_dictionary_and_param_api(env, users):
    client, db = env
    _login(client, "adm")
    resp = client.post("/api/asset/dictionaries", json={
        "dict_type": "funding_source", "code": "special", "label": "专项拨款"})
    assert resp.status_code == 201, resp.text
    resp = client.put("/api/asset/params/approval.timeout_hours",
                      json={"value": "48"})
    assert resp.status_code == 200
    assert resp.json()["value"] == "48"
    resp = client.get("/api/asset/params")
    assert any(p["key"] == "fixed_asset.min_value" for p in resp.json())


# ── #76 房间扩展(复用 rooms 表) ──────────────────────────────
def test_room_extension_requires_existing_room(env, users):
    from app.models.basedata import Room
    from app.models.semester import Semester

    client, db = env
    _login(client, "adm")
    resp = client.post("/api/asset/room-extensions", json={
        "room_id": 9999, "building": "示例楼"})
    assert resp.status_code == 404
    semester = Semester(academic_year=2026, term=1)
    db.add(semester)
    db.flush()
    room = Room(semester_id=semester.id, name="示例教室", room_type="normal")
    db.add(room)
    db.commit()
    resp = client.post("/api/asset/room-extensions", json={
        "room_id": room.id, "campus": "示例校区", "building": "示例楼",
        "asset_package": "示例实验室仪器包"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["asset_package"] == "示例实验室仪器包"


# ── #106 对接适配层占位:无真实官方接口调用 ──────────────────────────────
def test_sync_adapter_reports_no_live_api(env, users):
    client, db = env
    _login(client, "tea")
    resp = client.get("/api/asset/sync/adapter")
    assert resp.status_code == 200
    assert resp.json()["live_api"] is False
    assert resp.json()["adapter"] == "template_export"


def test_sync_adapter_push_refuses(env, users):
    client, db = env
    adapter = TemplateExportAdapter()
    with pytest.raises(NotImplementedError, match="未向单个学校开放实时 API"):
        adapter.push(db, [])
    # B5 已实现模板导出:空资产列表也能生成只有表头的模板文件(xlsx/PK 开头)。
    data = adapter.export_template(db, [])
    assert isinstance(data, bytes) and data[:2] == b"PK"


def test_seed_endpoint_idempotent(env, users):
    client, db = env
    _login(client, "adm")
    resp = client.post("/api/asset/admin/seed")
    assert resp.status_code == 200
    # 种子已存在,新增为 0
    assert resp.json()["seeded"]["categories"] == 0
