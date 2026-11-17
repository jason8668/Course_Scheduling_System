"""加密字段的 SQL 层操作修复测试(#84 跟进)。

覆盖:unsynced-stats 在真 Postgres 上的按分类汇总值正确;
台账按原值升/降序是数值顺序;原值区间筛选 + 排序下分页 total 不变;
按价值区间批量勾选只勾到区间内的卡。

必须在真 PostgreSQL 16 上跑,不要只在 SQLite 上测:SQLite 的
sum(text) 会静默算 0、密文比较也不会报错,测不出这类问题。
连接串由 DATABASE_URL 环境变数给(默认本机测试库
postgresql+psycopg://migtest:migtest@localhost:5432/course_sched_migtest);
密钥每测现场生成(Fernet.generate_key()),绝不写真实密钥进文件。
不改共用 conftest:自建测试 app + PG engine。
"""

import os

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import (
    asset_foundation,
    asset_intake,
    asset_ledger,
    asset_sync,
    asset_sync_select,
    auth,
)
from app.core.db import Base, get_db
from app.models.asset_card import AssetCard, SyncStatus
from app.models.user import Role
from app.services.asset_seed import seed_asset_foundation
from app.services.users import create_user

PG_URL = os.environ.get("DATABASE_URL") or (
    "postgresql+psycopg://migtest:migtest@localhost:5432/course_sched_migtest"
)
PW = "pw-123456"


@pytest.fixture(autouse=True)
def field_key(monkeypatch):
    """每测生成一把新密钥写进环境变数;库每测重建,密钥与密文不跨测。"""
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("ASSET_FIELD_KEY", key)
    return key


@pytest.fixture
def env(field_key):  # noqa: ARG001 - 依赖只为保证密钥先于建库/写卡就绪
    engine = create_engine(PG_URL)
    Base.metadata.drop_all(engine)
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
    application.include_router(asset_sync.router, prefix="/api/asset")
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
        engine.dispose()


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


# ── #100 未同步统计:Postgres 上 sum(text) 曾直接 500 ────────


def test_unsynced_stats_sums_decrypted_values_on_postgres(env, users):
    client, db = env
    _login(client, "am")
    _create_card(client, name="电脑A", category="A0201", original_value=1000.50,
                 attributes={"serial_no": "SN-A"})
    _create_card(client, name="电脑B", category="A0201", original_value=2000.25,
                 attributes={"serial_no": "SN-B"})
    _create_card(client, name="电脑C", category="A0201",
                 attributes={"serial_no": "SN-C"})  # 原值缺失,计 0 件但件数计入
    _create_card(client, name="桌椅A", category="A0501", original_value=300)
    synced = _create_card(client, name="电脑D", category="A0201",
                          original_value=9999, attributes={"serial_no": "SN-D"})
    # 已同步卡不计入未同步统计:直接改状态(不走同步流程)。
    row = db.get(AssetCard, synced["id"])
    row.sync_status = SyncStatus.synced.value
    db.commit()

    resp = client.get("/api/asset/sync/unsynced-stats")
    assert resp.status_code == 200, resp.text
    stats = {r["category_code"]: r for r in resp.json()}
    assert stats["A0201"]["count"] == 3
    assert stats["A0201"]["total_value"] == pytest.approx(3000.75)
    assert stats["A0501"]["count"] == 1
    assert stats["A0501"]["total_value"] == pytest.approx(300.0)


# ── #8 台账按原值排序:密文字符串顺序是随机的,必须是数值顺序 ──


def test_ledger_sort_by_original_value_is_numeric(env, users):
    client, db = env
    _login(client, "am")
    _create_card(client, name="贵", original_value=5000)
    _create_card(client, name="便宜", original_value=800)
    _create_card(client, name="中等", original_value=3000)
    _create_card(client, name="无价")  # 原值 None

    resp = client.get(
        "/api/asset/ledger/search?sort_by=original_value&sort_dir=asc&limit=10")
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 4
    assert [r["original_value"] for r in resp.json()["items"]] == [
        800, 3000, 5000, None]  # 升序,None 在最后(Postgres ASC 默认 NULLS LAST)

    resp = client.get(
        "/api/asset/ledger/search?sort_by=original_value&sort_dir=desc&limit=10")
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 4
    assert [r["original_value"] for r in resp.json()["items"]] == [
        None, 5000, 3000, 800]  # 降序,None 在最前(Postgres DESC 默认 NULLS FIRST)


# ── #8 原值筛选 + 排序 + 分页:total 是过滤后总数,切片是数值顺序 ─


def test_ledger_value_filter_and_pagination_total(env, users):
    client, db = env
    _login(client, "am")
    for name, value in [("V1", 500), ("V2", 1500), ("V3", 2500),
                        ("V4", 3500), ("V5", 5000)]:
        _create_card(client, name=name, original_value=value)

    base = ("sort_by=original_value&sort_dir=asc&limit=2")
    resp = client.get(
        f"/api/asset/ledger/search?min_value=1000&max_value=4000&{base}&offset=0")
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 3
    assert [r["original_value"] for r in resp.json()["items"]] == [1500, 2500]
    resp = client.get(
        f"/api/asset/ledger/search?min_value=1000&max_value=4000&{base}&offset=2")
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 3
    assert [r["original_value"] for r in resp.json()["items"]] == [3500]

    # 不筛选时 total 是全部件数,分页切片仍按数值顺序。
    resp = client.get(f"/api/asset/ledger/search?{base}&offset=2")
    assert resp.json()["total"] == 5
    assert [r["original_value"] for r in resp.json()["items"]] == [2500, 3500]
    resp = client.get(f"/api/asset/ledger/search?{base}&offset=4")
    assert resp.json()["total"] == 5
    assert [r["original_value"] for r in resp.json()["items"]] == [5000]


# ── #88 按价值区间批量勾选:只勾到区间内的卡 ────────────────


def test_select_by_filter_value_range(env, users):
    client, db = env
    _login(client, "am")
    low = _create_card(client, name="低值", original_value=800)
    mid = _create_card(client, name="中值", original_value=3000)
    high = _create_card(client, name="高值", original_value=5000)
    for card in (low, mid, high):
        _book(client, card["id"])

    resp = client.post("/api/asset/sync/select-by-filter",
                       json={"min_value": 1000, "max_value": 4000})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [r["asset_id"] for r in body["succeeded"]] == [mid["id"]]
    # 区间外的卡根本没进校验:既不在成功里,也不在失败里。
    seen = {r["asset_id"] for r in body["succeeded"] + body["failed"]}
    assert low["id"] not in seen and high["id"] not in seen
