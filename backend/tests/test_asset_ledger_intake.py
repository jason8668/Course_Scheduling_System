"""台账/入库验收测试(学校资产管理系统一期第 2 批)。

自建测试 app(不改共用 conftest):auth + asset_foundation + asset_ledger
+ asset_intake 四个路由,SQLite 记忆体库,种子经 seed_asset_foundation 写入。
覆盖:#8 组合查询与排序、#9 导出含审计、#12 附件归档、#13 批量维护逐条、
#14 闲置识别阈值、#19~#24 六类入库入口与取得方式、#25 验收不通过不建卡、
#26 批量建卡、#27 待入账清单与未回填标记、#28 标签码生成与补打。
"""

import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import asset_foundation, asset_intake, asset_ledger, auth
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
    application.include_router(asset_ledger.router, prefix="/api/asset")
    application.include_router(asset_intake.router, prefix="/api/asset")
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


def _book(client, asset_id, voucher="PZ-示例-001"):
    _login(client, "fin")
    resp = client.post(f"/api/asset/assets/{asset_id}/book",
                       json={"voucher_no": voucher})
    assert resp.status_code == 200, resp.text
    _login(client, "am")
    return resp.json()


def _acceptance(client, intake_type="self_purchase", **overrides):
    body = {"intake_type": intake_type, "acceptors": ["示例验收人"]}
    body.update(overrides)
    resp = client.post("/api/asset/acceptances", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _confirm(client, acceptance_id, result="通过"):
    resp = client.post(f"/api/asset/acceptances/{acceptance_id}/confirm",
                       json={"result": result})
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── #8 组合查询 ──────────────────────────────
def test_search_multi_dimension_sort_and_pagination(env, users):
    client, db = env
    _login(client, "am")
    _create_card(client, name="示例电脑", category="A0201",
                 attributes={"serial_no": "SN-1"},
                 manage_dept="教务处", original_value=5000,
                 acquired_date="2025-03-10T00:00:00Z", funding_source="fiscal")
    _create_card(client, name="示例桌椅", category="A0501",
                 manage_dept="总务处", original_value=800,
                 acquired_date="2026-03-10T00:00:00Z", funding_source="self_raised")
    _create_card(client, name="示例投影", category="A0202",
                 manage_dept="教务处", original_value=3000,
                 acquired_date="2026-01-05T00:00:00Z", funding_source="fiscal")
    # 部门 + 资金来源组合
    resp = client.get("/api/asset/ledger/search?manage_dept=教务处&funding_source=fiscal")
    assert resp.status_code == 200
    assert resp.json()["total"] == 2
    # 价值区间 + 排序(原值升序)
    resp = client.get("/api/asset/ledger/search?min_value=1000&max_value=4000"
                      "&sort_by=original_value&sort_dir=asc")
    assert [r["original_value"] for r in resp.json()["items"]] == [3000]
    # 购置年份
    resp = client.get("/api/asset/ledger/search?acquired_year=2025")
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["name"] == "示例电脑"
    # 分页
    resp = client.get("/api/asset/ledger/search?limit=2&offset=0")
    assert resp.json()["total"] == 3 and len(resp.json()["items"]) == 2
    resp = client.get("/api/asset/ledger/search?limit=2&offset=2")
    assert len(resp.json()["items"]) == 1
    # 非法排序字段拒绝
    resp = client.get("/api/asset/ledger/search?sort_by=ext")
    assert resp.status_code == 400
    # 非法状态拒绝
    resp = client.get("/api/asset/ledger/search?status=不存在")
    assert resp.status_code == 400


# ── #9 台账导出 ──────────────────────────────
def test_export_xlsx_default_columns_and_audit(env, users):
    client, db = env
    _login(client, "am")
    card = _create_card(client, original_value=2500,
                        ext={"remark": "演示内部备注"})
    resp = client.get("/api/asset/ledger/export")
    assert resp.status_code == 200
    assert "spreadsheetml" in resp.headers["content-type"]
    wb = load_workbook(io.BytesIO(resp.content))
    ws = wb.active
    headers = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
    assert "资产编号" in headers and "资产名称" in headers
    assert "扩展区备注" not in headers  # 默认不导出扩展区
    assert any(str(c.value) == card["asset_code"] for row in ws.iter_rows(min_row=2)
               for c in row)
    row = db.query(AuditLog).filter_by(action="asset_ledger_export").first()
    assert row is not None and "1 件" in row.detail
    # include_ext=true 才追加扩展区列
    resp = client.get("/api/asset/ledger/export?include_ext=true")
    wb = load_workbook(io.BytesIO(resp.content))
    headers = [c.value for c in next(wb.active.iter_rows(min_row=1, max_row=1))]
    assert "扩展区备注" in headers


# ── #12 附件归档 ──────────────────────────────
def test_attachment_crud_and_soft_delete(env, users):
    client, db = env
    _login(client, "am")
    card = _create_card(client)
    resp = client.post(f"/api/asset/assets/{card['id']}/attachments", json={
        "file_type": "发票", "file_name": "示例发票.pdf",
        "file_path": "attachments/示例发票.pdf", "file_size": 1024})
    assert resp.status_code == 201, resp.text
    att_id = resp.json()["id"]
    # 非法类型拒绝
    resp = client.post(f"/api/asset/assets/{card['id']}/attachments", json={
        "file_type": "视频", "file_name": "x.mp4", "file_path": "attachments/x.mp4"})
    assert resp.status_code == 400
    resp = client.get(f"/api/asset/assets/{card['id']}/attachments")
    assert [a["file_name"] for a in resp.json()] == ["示例发票.pdf"]
    # 删除留痕:列表不再出现,审计有记录
    resp = client.delete(f"/api/asset/attachments/{att_id}")
    assert resp.status_code == 200
    resp = client.get(f"/api/asset/assets/{card['id']}/attachments")
    assert resp.json() == []
    assert db.query(AuditLog).filter_by(
        action="asset_attachment_delete", target_id=att_id).first() is not None
    resp = client.delete(f"/api/asset/attachments/{att_id}")
    assert resp.status_code == 404


# ── #13 批量维护逐条 ──────────────────────────────
def test_bulk_update_per_item_results(env, users):
    client, db = env
    _login(client, "am")
    a = _create_card(client, name="示例甲")
    b = _create_card(client, name="示例乙")
    # b 先核销:批量改时逐条失败,不整体回滚
    client.post(f"/api/asset/assets/{b['id']}/transition", json={
        "to_status": "待处置", "doc_type": "处置", "doc_no": "CZ-示例-101"})
    client.post(f"/api/asset/assets/{b['id']}/retire?doc_no=CZ-示例-101")
    resp = client.post("/api/asset/assets/bulk-update", json={
        "asset_ids": [a["id"], b["id"], 99999],
        "custodian_name": "示例保管人", "manage_dept": "教务处"})
    assert resp.status_code == 200
    assert len(resp.json()["succeeded"]) == 1
    assert len(resp.json()["failed"]) == 2
    assert "已核销" in resp.json()["failed"][0]["reason"]
    assert "不存在" in resp.json()["failed"][1]["reason"]
    resp = client.get(f"/api/asset/assets/{a['id']}")
    assert resp.json()["custodian_name"] == "示例保管人"
    assert resp.json()["manage_dept"] == "教务处"
    # atomic=true 时任一失败整批回滚
    c = _create_card(client, name="示例丙")
    resp = client.post("/api/asset/assets/bulk-update", json={
        "asset_ids": [c["id"], 99999], "custodian_name": "应回滚", "atomic": True})
    assert resp.json()["succeeded"] == []
    resp = client.get(f"/api/asset/assets/{c['id']}")
    assert resp.json()["custodian_name"] is None


# ── #14 闲置识别 ──────────────────────────────
def test_idle_refresh_rules(env, users):
    client, db = env
    _login(client, "am")
    # 无领用人 → 闲置(规则 A)
    idle_a = _create_card(client, name="示例无领用人")
    # 有保管人且近期购置 → 不闲置
    busy = _create_card(client, name="示例在用", custodian_name="示例保管人",
                        acquired_date="2026-11-01T00:00:00Z")
    # 有保管人但购置于 2025 年初 → 超 180 天闲置(规则 B)
    idle_b = _create_card(client, name="示例长期未用", custodian_name="示例保管人",
                          acquired_date="2025-01-10T00:00:00Z")
    resp = client.post("/api/asset/idle/refresh", json={})
    assert resp.status_code == 200
    assert resp.json()["threshold_days"] == 180
    assert set(resp.json()["idle_ids"]) == {idle_a["id"], idle_b["id"]}
    resp = client.get("/api/asset/idle")
    reasons = {r["asset_code"]: r["idle_reason"] for r in resp.json()}
    assert "无领用人" in reasons[idle_a["asset_code"]]
    assert "长期未使用超过180天" in reasons[idle_b["asset_code"]]
    assert busy["asset_code"] not in reasons
    # 阈值可临时覆盖:366 天后长期未用那件不再闲置(但无领用人那件仍闲置)
    resp = client.post("/api/asset/idle/refresh", json={"threshold_days": 1000})
    assert idle_b["id"] not in resp.json()["idle_ids"]
    assert idle_a["id"] in resp.json()["idle_ids"]


def test_idle_over_config_std(env, users):
    client, db = env
    _login(client, "adm")
    resp = client.put("/api/asset/params/asset.idle.over_config_std",
                      json={"value": "A0203:1"})
    assert resp.status_code == 200
    _login(client, "am")
    # 同一分类+部门 2 件,上限 1 件 → 新卡记超配置闲置
    _create_card(client, name="示例甲", manage_dept="教务处",
                 custodian_name="示例保管人", acquired_date="2026-11-01T00:00:00Z")
    second = _create_card(client, name="示例乙", manage_dept="教务处",
                          custodian_name="示例保管人",
                          acquired_date="2026-11-02T00:00:00Z")
    resp = client.post("/api/asset/idle/refresh", json={})
    resp = client.get("/api/asset/idle")
    reasons = {r["asset_code"]: r["idle_reason"] for r in resp.json()}
    assert "超配置标准" in reasons[second["asset_code"]]


# ── #19~#24 六类入库入口 ──────────────────────────────
@pytest.mark.parametrize("intake_type,acquire_method,source_doc", [
    ("gov_purchase", "purchase", {"contract_no": "示例合同-1", "order_no": "示例订单-1"}),
    ("self_purchase", "purchase", {"contract_no": "示例合同-2"}),
    ("donation", "donation", {"donor": "示例捐赠方", "value_basis": "示例评估报告"}),
    ("transfer_in", "transfer_in", {"transfer_no": "示例调拨单-1"}),
    ("self_built", "self_built", {"completion_doc": "示例竣工决算"}),
    ("inventory_surplus", "inventory_surplus", {"inventory_no": "示例盘点单-1"}),
])
def test_six_intake_types(env, users, intake_type, acquire_method, source_doc):
    client, db = env
    _login(client, "am")
    acc = _acceptance(client, intake_type=intake_type, source_doc=source_doc)
    assert acc["status"] == "待验收"
    _confirm(client, acc["id"])
    resp = client.post(f"/api/asset/acceptances/{acc['id']}/create-cards", json={
        "items": [{"name": f"示例-{intake_type}", "category_code": "A0203",
                   "original_value": 1000}]})
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["succeeded"]) == 1
    card_id = resp.json()["succeeded"][0]["asset_id"]
    resp = client.get(f"/api/asset/assets/{card_id}")
    assert resp.json()["acquire_method"] == acquire_method
    assert resp.json()["sync_status"] == "未同步"  # 建卡强制未同步
    assert resp.json()["is_booked"] is False  # 未回填凭证号
    assert resp.json()["acceptance_id"] == acc["id"]
    assert resp.json()["batch_no"] == resp.json()["batch_no"] and resp.json()["batch_no"]


def test_acceptance_invalid_type_rejected(env, users):
    client, db = env
    _login(client, "am")
    resp = client.post("/api/asset/acceptances", json={"intake_type": "未知入口"})
    assert resp.status_code == 400


# ── #25 验收不通过不建卡 ──────────────────────────────
def test_failed_acceptance_cannot_create_cards(env, users):
    client, db = env
    _login(client, "am")
    acc = _acceptance(client, intake_type="donation")
    _confirm(client, acc["id"], result="不通过")
    resp = client.post(f"/api/asset/acceptances/{acc['id']}/create-cards", json={
        "items": [{"name": "示例捐赠", "category_code": "A0203"}]})
    assert resp.status_code == 400
    assert "验收不通过" in resp.json()["detail"] or "验收通过后才可建卡" in resp.json()["detail"]
    # 未确认的验收单同样不可建卡
    acc2 = _acceptance(client, intake_type="self_purchase")
    resp = client.post(f"/api/asset/acceptances/{acc2['id']}/create-cards", json={
        "items": [{"name": "示例", "category_code": "A0203"}]})
    assert resp.status_code == 400


# ── #26 批量建卡 ──────────────────────────────
def test_bulk_create_cards(env, users):
    client, db = env
    _login(client, "am")
    acc = _acceptance(client, intake_type="gov_purchase")
    _confirm(client, acc["id"])
    resp = client.post(f"/api/asset/acceptances/{acc['id']}/bulk-create", json={
        "template": {"name": "示例课桌椅", "category_code": "A0501",
                     "original_value": 500},
        "quantity": 3})
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["succeeded"]) == 3
    assert resp.json()["failed"] == []
    codes = [s["asset_code"] for s in resp.json()["succeeded"]]
    assert len(set(codes)) == 3  # 每件独立编号
    batch_no = resp.json()["batch_no"]
    resp = client.get(f"/api/asset/ledger/search?batch_no={batch_no}")
    assert resp.json()["total"] == 3
    assert sorted(r["name"] for r in resp.json()["items"]) == [
        "示例课桌椅-01", "示例课桌椅-02", "示例课桌椅-03"]


def test_bulk_create_partial_failure_reported(env, users):
    client, db = env
    _login(client, "am")
    acc = _acceptance(client, intake_type="self_purchase")
    _confirm(client, acc["id"])
    # 第一件缺序列号(A0201 模板必填)失败,第二件成功,不整体回滚
    resp = client.post(f"/api/asset/acceptances/{acc['id']}/create-cards", json={
        "items": [
            {"name": "示例电脑缺序列号", "category_code": "A0201"},
            {"name": "示例办公设备", "category_code": "A0203"},
        ]})
    assert len(resp.json()["succeeded"]) == 1
    assert len(resp.json()["failed"]) == 1
    assert "序列号" in resp.json()["failed"][0]["reason"]


# ── #27 待入账清单 ──────────────────────────────
def test_booking_pending_and_confirm(env, users):
    client, db = env
    _login(client, "am")
    card = _create_card(client, original_value=2000)
    resp = client.get("/api/asset/booking-pending")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["total_value"] == 2000
    # 财务回填凭证号 → 正式状态
    booked = _book(client, card["id"], voucher="PZ-示例-2026-001")
    assert booked["is_booked"] is True
    assert booked["voucher_no"] == "PZ-示例-2026-001"
    resp = client.get("/api/asset/booking-pending")
    assert resp.json()["total"] == 0
    # 重复回填拦截
    _login(client, "fin")
    resp = client.post(f"/api/asset/assets/{card['id']}/book",
                       json={"voucher_no": "PZ-重复"})
    assert resp.status_code == 400
    # 教师无权回填
    _login(client, "tea")
    resp = client.post(f"/api/asset/assets/{card['id']}/book",
                       json={"voucher_no": "PZ-越权"})
    assert resp.status_code == 403


def test_booking_pending_export(env, users):
    client, db = env
    _login(client, "am")
    _create_card(client, original_value=1500)
    _login(client, "fin")
    resp = client.get("/api/asset/booking-pending/export")
    assert resp.status_code == 200
    wb = load_workbook(io.BytesIO(resp.content))
    headers = [c.value for c in next(wb.active.iter_rows(min_row=1, max_row=1))]
    assert "资产编号" in headers
    assert db.query(AuditLog).filter_by(
        action="asset_booking_pending_export").first() is not None


# ── #28 标签 ──────────────────────────────
def test_labels_and_reprint(env, users):
    client, db = env
    _login(client, "am")
    card = _create_card(client, manage_dept="教务处")
    resp = client.get(f"/api/asset/ledger/labels?ids={card['id']}")
    assert resp.status_code == 200
    assert resp.json()[0]["label_code"] == card["label_code"]
    assert resp.json()[0]["valid"] is True
    assert resp.json()[0]["manage_dept"] == "教务处"
    # 批量打印记审计
    resp = client.post("/api/asset/ledger/labels/print",
                       json={"asset_ids": [card["id"]]})
    assert resp.status_code == 200
    assert db.query(AuditLog).filter_by(action="asset_label_print").first() is not None
    # 补打
    resp = client.post(f"/api/asset/assets/{card['id']}/label/reprint")
    assert resp.status_code == 200
    assert resp.json()["asset_code"] == card["asset_code"]


def test_label_qr_svg(env, users):
    """#28 复核补:标签码编成 QR(SVG)可取;不存在的资产 404。"""
    client, _db = env
    _login(client, "am")
    card = _create_card(client)
    resp = client.get(f"/api/asset/assets/{card['id']}/label/qr")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("image/svg+xml")
    assert resp.content.startswith(b"<?xml") or b"<svg" in resp.content
    assert client.get("/api/asset/assets/99999/label/qr").status_code == 404
