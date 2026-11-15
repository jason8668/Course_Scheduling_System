"""第 5 批后端测试:对接与同步(M13 #91~#104/#106)与财务衔接(M15 #116)。

自建测试 app:auth + asset_foundation + asset_intake + asset_circulation
+ asset_sync_select + asset_sync,SQLite 记忆体库,种子经
seed_asset_foundation 写入(含 sync.separation_of_duties=true 默认分岗)。
"""

import io
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import pytest

from app.api import (
    asset_circulation,
    asset_foundation,
    asset_intake,
    asset_sync,
    asset_sync_select,
    auth,
)
from app.core.db import Base, get_db
from app.models.asset_card import AssetCard
from app.models.asset_ledger import AssetSyncSelection
from app.models.asset_circulation import AssetReminder
from app.models.user import Role
from app.services.asset_seed import seed_asset_foundation
from app.services.asset_sync_adapter import get_adapter
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


@pytest.fixture
def users(env):
    client, db = env
    made = {}
    for username, roles in [
        ("adm", [Role.admin]),
        ("am", [Role.asset_admin]),
        ("am2", [Role.asset_admin]),
        ("da", [Role.asset_dept_admin]),
        ("dir", [Role.director]),
        ("fin", [Role.asset_finance]),
        ("aud", [Role.asset_auditor]),
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
    body = {"name": "示例资产", "category_code": "A0203"}
    body.update(overrides)
    resp = client.post("/api/asset/assets", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _booked_card(client, **overrides):
    """建卡 + 财务回填凭证号(可勾选状态);默认带齐同步必填字段。"""
    body = {
        "original_value": 3000, "acquire_method": "purchase",
        "funding_source": "fiscal", "acquired_date": "2026-01-05T00:00:00Z",
    }
    body.update(overrides)
    _login(client, "am")
    card = _create_card(client, **body)
    _login(client, "fin")
    resp = client.post(f"/api/asset/assets/{card['id']}/book",
                       json={"voucher_no": f"PZ-示例-{card['id']}"})
    assert resp.status_code == 200, resp.text
    _login(client, "am")
    return resp.json()


def _select(client, card_ids, username="am"):
    _login(client, username)
    resp = client.post("/api/asset/sync/select", json={"asset_ids": card_ids})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _pool(client):
    resp = client.get("/api/asset/sync/pool")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _rows_from_xlsx(content: bytes):
    wb = load_workbook(io.BytesIO(content))
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    return rows


# ── #91 同步前校验 ──────────────────────────────
def test_validate_blocks_missing_fields_and_attributes(env, users):
    client, db = env
    good = _booked_card(client)
    no_date = _booked_card(client, acquired_date=None)
    # A0201 要求特性字段 serial_no:建卡时带上,随后在库里清空以模拟缺项。
    no_serial = _booked_card(
        client, category_code="A0201", attributes={"serial_no": "SN-示例-1"})
    row = db.get(AssetCard, no_serial["id"])
    row.attributes = {}
    db.commit()
    _select(client, [good["id"], no_date["id"], no_serial["id"]])
    _login(client, "am")
    resp = client.get("/api/asset/sync/validate")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["passed"] == [good["id"]]
    assert data["total"] == 3
    blocked = {b["asset_id"]: b for b in data["blocked"]}
    assert "acquired_date" in blocked[no_date["id"]]["missing"]
    assert "attributes.serial_no" in blocked[no_serial["id"]]["missing"]


def test_validate_missing_mapping_goes_to_blocklist(env, users):
    client, db = env
    card = _booked_card(client)
    _select(client, [card["id"]])
    # 停用 acquire_method 的映射:缺映射须进拦截清单并提示。
    _login(client, "adm")
    resp = client.get("/api/asset/field-mappings")
    mapping = next(m for m in resp.json() if m["local_field"] == "acquire_method")
    resp = client.patch(f"/api/asset/field-mappings/{mapping['id']}",
                        json={"is_active": False})
    assert resp.status_code == 200, resp.text
    _login(client, "am")
    resp = client.get("/api/asset/sync/validate")
    blocked = {b["asset_id"]: b for b in resp.json()["blocked"]}
    assert card["id"] in blocked
    assert "acquire_method" in blocked[card["id"]]["missing"]
    assert any("缺少官方映射" in r for r in blocked[card["id"]]["reasons"])


# ── #92/#94 生成批次 + 二次确认 + 分岗 ──────────────────────────────
def test_batch_requires_confirm_and_separation(env, users):
    client, db = env
    good = _booked_card(client)
    bad = _booked_card(client, acquired_date=None)
    _select(client, [good["id"], bad["id"]])  # 勾选人 am
    _login(client, "am2")
    resp = client.post("/api/asset/sync/batches", json={"confirm": False})
    assert resp.status_code == 400
    assert "二次确认" in resp.text
    # 勾选人 am 自己执行 → 分岗拦截。
    _login(client, "am")
    resp = client.post("/api/asset/sync/batches", json={"confirm": True})
    assert resp.status_code == 400
    assert "分岗" in resp.text
    # 另一位资产管理员 am2 执行 → 成功;拦截资产留在待同步池。
    _login(client, "am2")
    resp = client.post("/api/asset/sync/batches", json={"confirm": True})
    assert resp.status_code == 201, resp.text
    batch = resp.json()
    assert batch["batch_no"].startswith("TB")
    assert batch["total_count"] == 1
    assert batch["blocked_count"] == 1
    assert batch["total_value"] == 3000
    pool = _pool(client)
    assert pool["total"] == 1
    assert pool["items"][0]["asset_id"] == bad["id"]


# ── #93 仅导出已勾选资产且扩展区不出现 ──────────────────────────────
def test_export_only_selected_and_no_extension_fields(env, users):
    client, db = env
    good = _booked_card(client, ext={"room_package": "示例资产包",
                                     "photo_url": "https://example.invalid/x.jpg"})
    other = _booked_card(client, name="示例未勾选资产")
    _select(client, [good["id"]])
    _login(client, "am2")
    batch = client.post("/api/asset/sync/batches",
                        json={"confirm": True}).json()
    resp = client.get(f"/api/asset/sync/batches/{batch['id']}/export")
    assert resp.status_code == 200, resp.text
    rows = _rows_from_xlsx(resp.content)
    headers = [str(h) for h in rows[0]]
    assert "资产编号" in headers and "资产名称" in headers
    assert not any("扩展" in h or "资产包" in h or "IP" in h for h in headers)
    body_text = " ".join(str(c) for row in rows[1:] for c in row if c is not None)
    assert good["asset_code"] in body_text
    assert other["asset_code"] not in body_text
    assert "示例资产包" not in body_text
    assert len(rows) == 2  # 表头 + 1 件


def test_push_still_refused(env, users):
    client, db = env
    with pytest.raises(NotImplementedError):
        get_adapter().push(db, [])


def test_boundary_page_states_template_exchange(env, users):
    client, db = env
    _login(client, "am")
    resp = client.get("/api/asset/sync/boundary")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["live_api"] is False
    assert "模板交换" in data["execution_note"]
    assert "实时接口未开放" in data["execution_note"]
    assert data["template_version"] == "当期模板"


# ── #96 编号回填逐条冲突回告与双号索引 ──────────────────────────────
def _synced_batch(client, db, card, official_code, executor="am2"):
    _select(client, [card["id"]])
    _login(client, executor)
    batch = client.post("/api/asset/sync/batches",
                        json={"confirm": True}).json()
    resp = client.post(
        f"/api/asset/sync/batches/{batch['id']}/backfill",
        json={"items": [{"asset_id": card["id"], "official_code": official_code}]},
    )
    assert resp.status_code == 200, resp.text
    return batch, resp.json()


def test_backfill_conflicts_reported_per_item(env, users):
    client, db = env
    first = _booked_card(client)
    batch1, results1 = _synced_batch(client, db, first, "GF-示例-001")
    assert results1[0]["ok"] is True
    _login(client, "am")
    resp = client.get(f"/api/asset/assets/{first['id']}")
    assert resp.json()["official_code"] == "GF-示例-001"
    assert resp.json()["sync_status"] == "已同步"
    # 第二件用同一官方编号回填 → 冲突逐条回告,不回填。
    second = _booked_card(client)
    _select(client, [second["id"]])
    _login(client, "am2")
    batch2 = client.post("/api/asset/sync/batches",
                         json={"confirm": True}).json()
    resp = client.post(
        f"/api/asset/sync/batches/{batch2['id']}/backfill",
        json={"items": [{"asset_id": second["id"], "official_code": "GF-示例-001"}]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()[0]["ok"] is False
    assert "已被资产" in resp.json()[0]["reason"]
    _login(client, "am")
    resp = client.get(f"/api/asset/assets/{second['id']}")
    assert resp.json()["official_code"] is None
    assert resp.json()["sync_status"] == "待同步"
    # 换不冲突的编号回填成功;未同步资产不在批次中不回填。
    _login(client, "am2")
    resp = client.post(
        f"/api/asset/sync/batches/{batch2['id']}/backfill",
        json={"items": [{"asset_id": second["id"], "official_code": "GF-示例-002"}]},
    )
    assert resp.json()[0]["ok"] is True
    unsynced = _booked_card(client)
    resp = client.post(
        f"/api/asset/sync/batches/{batch2['id']}/backfill",
        json={"items": [{"asset_id": unsynced["id"], "official_code": "GF-示例-003"}]},
    )
    assert resp.json()[0]["ok"] is False
    assert "不在本同步批次" in resp.json()[0]["reason"]


# ── #97 同步失败退回待同步池再勾选 ──────────────────────────────
def test_confirm_failure_returns_to_pool_and_reselect(env, users):
    client, db = env
    card = _booked_card(client)
    _select(client, [card["id"]])
    _login(client, "am2")
    batch = client.post("/api/asset/sync/batches",
                        json={"confirm": True}).json()
    resp = client.post(
        f"/api/asset/sync/batches/{batch['id']}/confirm",
        json={"results": [{"asset_id": card["id"], "ok": False,
                           "reason": "官方导入失败:分类代码不符"}]},
    )
    assert resp.status_code == 200, resp.text
    _login(client, "am")
    resp = client.get(f"/api/asset/assets/{card['id']}")
    assert resp.json()["sync_status"] == "同步失败"
    result = _select(client, [card["id"]])
    assert len(result["succeeded"]) == 1
    pool = _pool(client)
    assert pool["total"] == 1
    assert pool["items"][0]["sync_status"] == "待同步"


# ── #98 变更再同步清 pending_sync_change 标记 ──────────────────────────────
def test_resync_clears_pending_change_flag(env, users):
    client, db = env
    card = _booked_card(client)
    _select(client, [card["id"]])
    _login(client, "am2")
    batch = client.post("/api/asset/sync/batches",
                        json={"confirm": True}).json()
    # 模拟调拨后打上的待同步变更标记。
    row = db.get(AssetCard, card["id"])
    row.pending_sync_change = True
    row.pending_sync_change_reason = "示例调拨变更"
    db.commit()
    _login(client, "am")
    resp = client.get("/api/asset/sync/pending-changes")
    assert resp.status_code == 200, resp.text
    assert any(p["asset_id"] == card["id"] for p in resp.json())
    # 回填成功后标记清掉。
    _login(client, "am2")
    resp = client.post(
        f"/api/asset/sync/batches/{batch['id']}/backfill",
        json={"items": [{"asset_id": card["id"], "official_code": "GF-示例-010"}]},
    )
    assert resp.json()[0]["ok"] is True
    db.refresh(row)
    assert row.pending_sync_change is False
    assert row.pending_sync_change_reason is None
    _login(client, "am")
    resp = client.get("/api/asset/sync/pending-changes")
    assert resp.json() == []
    # 同步日志里有清除记录。
    resp = client.get("/api/asset/sync/logs?action=待同步变更清除")
    assert resp.status_code == 200, resp.text
    assert any(log["asset_id"] == card["id"] for log in resp.json())


# ── #100 未同步资产三类出口自动排除与单独统计 ──────────────────────────────
def test_unsynced_excluded_and_stats(env, users):
    client, db = env
    synced = _booked_card(client)
    _synced_batch(client, db, synced, "GF-示例-020")
    unsynced = _booked_card(client, category_code="A0203")
    _login(client, "am")
    resp = client.get("/api/asset/sync/unsynced-stats")
    assert resp.status_code == 200, resp.text
    stats = {s["category_code"]: s for s in resp.json()}
    assert stats["A0203"]["count"] == 1
    assert stats["A0203"]["total_value"] == 3000
    # 导出只含批次内资产,未同步资产不在其中(见 #93 测试);对账清单上报口径
    # 只计已同步(synced_count),未同步只在校内口径出现。
    _login(client, "fin")
    resp = client.get("/api/asset/finance/reconciliation?month=2026-11")
    assert resp.status_code == 200, resp.text
    cat = next(c for c in resp.json()["categories"]
               if c["category_code"] == "A0203")
    assert cat["synced_count"] == 1
    assert cat["all_count"] == 2


# ── #102 同步日志不可删与查询 ──────────────────────────────
def test_sync_logs_queryable_and_not_deletable(env, users):
    client, db = env
    card = _booked_card(client)
    _select(client, [card["id"]])
    _login(client, "am2")
    batch = client.post("/api/asset/sync/batches",
                        json={"confirm": True}).json()
    _login(client, "aud")
    resp = client.get(f"/api/asset/sync/logs?batch_no={batch['batch_no']}")
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) >= 1
    assert all(log["batch_no"] == batch["batch_no"] for log in resp.json())
    # 无删除接口。
    resp = client.delete(f"/api/asset/sync/logs/{resp.json()[0]['id']}")
    assert resp.status_code in (404, 405)


# ── #103 待同步积压提醒只提醒不执行 ──────────────────────────────
def test_backlog_scan_only_reminds(env, users):
    client, db = env
    card = _booked_card(client)
    result = _select(client, [card["id"]])
    batch_no = result["batch_no"]
    # 把勾选时间改到 20 天前(超过默认 14 天阈值)。
    sel = db.query(AssetSyncSelection).filter_by(
        asset_id=card["id"], status="active").first()
    sel.selected_at = datetime.now(UTC) - timedelta(days=20)
    db.commit()
    _login(client, "am")
    resp = client.post("/api/asset/sync/scan-backlog")
    assert resp.status_code == 200, resp.text
    assert batch_no in resp.json()["reminded_batches"]
    assert resp.json()["asset_count"] == 1
    # 只提醒:资产仍在待同步池,未被执行同步。
    pool = _pool(client)
    assert pool["total"] == 1
    reminder = db.query(AssetReminder).filter_by(kind="同步待处理").first()
    assert reminder is not None
    assert batch_no in reminder.title


# ── #116 财务衔接:月度对账清单差异定位 ──────────────────────────────
def test_finance_reconciliation_differences(env, users):
    client, db = env
    mismatch = _booked_card(
        client, original_value=10000, accumulated_depreciation=1000,
        net_value=8000)  # 应为 9000,差 1000
    _login(client, "fin")
    resp = client.get("/api/asset/finance/reconciliation?month=2026-11")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "不做财务核算" in data["note"]
    diff = next(d for d in data["differences"]
                if d["asset_id"] == mismatch["id"])
    assert diff["reason"] == "净值与原值-累计折旧不符"
    assert diff["expected_net_value"] == 9000
    assert diff["voucher_no"] == f"PZ-示例-{mismatch['id']}"
    cat = next(c for c in data["categories"]
               if c["category_code"] == "A0203")
    assert cat["all_original_value"] == 10000
    assert cat["all_accumulated_depreciation"] == 1000
    resp = client.get("/api/asset/finance/reconciliation/export?month=2026-11")
    assert resp.status_code == 200, resp.text
    wb = load_workbook(io.BytesIO(resp.content))
    assert "差异清单" in wb.sheetnames
    # 财务岗可看,普通教师不可看。
    _login(client, "tea")
    resp = client.get("/api/asset/finance/reconciliation?month=2026-11")
    assert resp.status_code == 403
