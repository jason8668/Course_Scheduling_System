"""部门字典测试(学校资产管理系统一期补半成品 #76)。

自建测试 app(不改共用 conftest):auth + asset_departments 两个路由,
SQLite 记忆体库。覆盖:字典 CRUD、资产卡回填(建字典时按名补外键 +
reconcile 全量对齐)、引用中部门不可删、待认领列表与认领、改名同步
资产卡字符串、非管理员写操作 403。

迁移 0044 本身的数据迁移(建表 + distinct 回填)在真 Postgres 16 上
另行验证(见任务汇报),此处只验与迁移同语义的回填逻辑。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import asset_departments, auth
from app.core.db import Base, get_db
from app.models.asset_card import AssetCard
from app.models.asset_category import AssetCategory
from app.models.asset_department import AssetDepartment
from app.models.user import Role
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
    application.include_router(asset_departments.router, prefix="/api/asset")
    application.dependency_overrides[get_db] = override_get_db

    setup_db = TestSession()
    setup_db.add(AssetCategory(code="A0203", name="通用设备", level=3,
                               is_reportable=True, origin="seed"))
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
    made = {
        "admin": _make_user(db, "adm", [Role.admin]),
        "asset_admin": _make_user(db, "am", [Role.asset_admin]),
        "teacher": _make_user(db, "tea", [Role.teacher]),
    }
    return made


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


def _make_card(db, asset_code, manage_dept=None, use_dept=None):
    card = AssetCard(
        asset_code=asset_code, label_code=f"{asset_code}X",
        name=f"资产{asset_code}", category_code="A0203",
        manage_dept=manage_dept, use_dept=use_dept,
    )
    db.add(card)
    db.commit()
    return card


def _create_dept(client, name, **overrides):
    body = {"name": name}
    body.update(overrides)
    resp = client.post("/api/asset/departments", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── 字典 CRUD ──────────────────────────────
def test_create_and_list_departments(env, users):
    client, db = env
    _login(client, "adm")
    row = _create_dept(client, "教务处", code="JW01")
    assert row["name"] == "教务处"
    assert row["code"] == "JW01"
    assert row["is_active"] is True
    assert row["asset_count"] == 0
    resp = client.get("/api/asset/departments")
    assert resp.status_code == 200, resp.text
    assert [r["name"] for r in resp.json()] == ["教务处"]


def test_create_duplicate_name_or_code_rejected(env, users):
    client, db = env
    _login(client, "am")
    _create_dept(client, "教务处", code="JW01")
    resp = client.post("/api/asset/departments", json={"name": "教务处"})
    assert resp.status_code == 400
    resp = client.post("/api/asset/departments", json={"name": "总务处", "code": "JW01"})
    assert resp.status_code == 400


def test_create_forbidden_for_non_admin(env, users):
    client, db = env
    _login(client, "tea")
    resp = client.post("/api/asset/departments", json={"name": "教务处"})
    assert resp.status_code == 403


def test_patch_rename_and_deactivate(env, users):
    client, db = env
    _login(client, "adm")
    row = _create_dept(client, "教务处")
    resp = client.patch(f"/api/asset/departments/{row['id']}",
                        json={"is_active": False})
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_active"] is False
    resp = client.get("/api/asset/departments?is_active=true")
    assert resp.json() == []
    resp = client.get("/api/asset/departments")
    assert [r["name"] for r in resp.json()] == ["教务处"]


def test_patch_rename_syncs_card_strings(env, users):
    """改名不断口径:资产卡上等于旧名的字符串同步改成新名。"""
    client, db = env
    _make_card(db, "ZC0001", manage_dept="教务处", use_dept="教务处")
    _login(client, "adm")
    row = _create_dept(client, "教务处")
    resp = client.patch(f"/api/asset/departments/{row['id']}",
                        json={"name": "教务部"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "教务部"
    card = db.query(AssetCard).filter_by(asset_code="ZC0001").one()
    assert card.manage_dept == "教务部"
    assert card.use_dept == "教务部"


def test_patch_self_parent_rejected(env, users):
    client, db = env
    _login(client, "adm")
    row = _create_dept(client, "教务处")
    resp = client.patch(f"/api/asset/departments/{row['id']}",
                        json={"parent_id": row["id"]})
    assert resp.status_code == 400


# ── 资产卡回填 ──────────────────────────────
def test_create_department_backfills_matching_cards(env, users):
    """建字典时按名补外键:字符串等于新字典名的卡,外键指向该行。"""
    client, db = env
    card_a = _make_card(db, "ZC0001", manage_dept="教务处")
    card_b = _make_card(db, "ZC0002", use_dept="教务处")
    _make_card(db, "ZC0003", manage_dept="总务处")
    _login(client, "adm")
    row = _create_dept(client, "教务处")
    assert row["manage_count"] == 1
    assert row["use_count"] == 1
    assert row["asset_count"] == 2
    db.refresh(card_a)
    db.refresh(card_b)
    assert card_a.manage_dept_id == row["id"]
    assert card_b.use_dept_id == row["id"]
    card_c = db.query(AssetCard).filter_by(asset_code="ZC0003").one()
    assert card_c.manage_dept_id is None


def test_reconcile_backfills_later_cards(env, users):
    """入库建卡只传字符串时,外键为空;reconcile 全量对齐补上。"""
    client, db = env
    _login(client, "adm")
    row = _create_dept(client, "教务处")
    card = _make_card(db, "ZC0001", manage_dept="教务处", use_dept="教务处")
    assert card.manage_dept_id is None
    resp = client.post("/api/asset/departments/reconcile")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"updated_manage": 1, "updated_use": 1}
    db.refresh(card)
    assert card.manage_dept_id == row["id"]
    assert card.use_dept_id == row["id"]
    # 第二遍幂等:无新增回填。
    resp = client.post("/api/asset/departments/reconcile")
    assert resp.json() == {"updated_manage": 0, "updated_use": 0}


# ── 引用中不可删 ──────────────────────────────
def test_delete_blocked_when_referenced(env, users):
    client, db = env
    _make_card(db, "ZC0001", manage_dept="教务处")
    _make_card(db, "ZC0002", use_dept="教务处")
    _login(client, "adm")
    row = _create_dept(client, "教务处")
    resp = client.delete(f"/api/asset/departments/{row['id']}")
    assert resp.status_code == 400
    assert "2" in resp.json()["detail"]


def test_delete_blocked_by_string_only_reference(env, users):
    """只剩字符串引用(外键为空)时同样不可删,防止删字典丢口径。"""
    client, db = env
    _make_card(db, "ZC0001", manage_dept="教务处")
    _login(client, "adm")
    row = _create_dept(client, "教务处")
    card = db.query(AssetCard).filter_by(asset_code="ZC0001").one()
    card.manage_dept_id = None
    db.commit()
    resp = client.delete(f"/api/asset/departments/{row['id']}")
    assert resp.status_code == 400


def test_delete_ok_when_unreferenced(env, users):
    client, db = env
    _login(client, "adm")
    row = _create_dept(client, "教务处")
    resp = client.delete(f"/api/asset/departments/{row['id']}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"] == row["id"]
    assert db.get(AssetDepartment, row["id"]) is None


def test_delete_blocked_when_has_children(env, users):
    client, db = env
    _login(client, "adm")
    parent = _create_dept(client, "教务处")
    _create_dept(client, "教务科", parent_id=parent["id"])
    resp = client.delete(f"/api/asset/departments/{parent['id']}")
    assert resp.status_code == 400


# ── 待认领与认领 ──────────────────────────────
def test_unclaimed_lists_only_unknown_names(env, users):
    client, db = env
    _make_card(db, "ZC0001", manage_dept="教务处")
    _make_card(db, "ZC0002", manage_dept="教务", use_dept="教务")
    _make_card(db, "ZC0003", use_dept="总务处")
    _login(client, "adm")
    _create_dept(client, "教务处")
    resp = client.get("/api/asset/departments/unclaimed")
    assert resp.status_code == 200, resp.text
    rows = {r["name"]: r for r in resp.json()}
    assert "教务处" not in rows
    assert rows["教务"]["manage_count"] == 1
    assert rows["教务"]["use_count"] == 1
    assert rows["教务"]["total_count"] == 2
    assert rows["总务处"]["use_count"] == 1


def test_claim_merges_raw_name_into_department(env, users):
    """认领“教务”并入“教务处”:外键补上,字符串统一成字典名。"""
    client, db = env
    card = _make_card(db, "ZC0001", manage_dept="教务", use_dept="教务")
    _login(client, "adm")
    row = _create_dept(client, "教务处")
    resp = client.post(f"/api/asset/departments/{row['id']}/claim",
                       json={"name": "教务", "field": "both"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated_manage"] == 1
    assert resp.json()["updated_use"] == 1
    db.refresh(card)
    assert card.manage_dept_id == row["id"]
    assert card.use_dept_id == row["id"]
    assert card.manage_dept == "教务处"
    assert card.use_dept == "教务处"
    resp = client.get("/api/asset/departments/unclaimed")
    assert resp.json() == []


def test_claim_already_dictionary_name_rejected(env, users):
    client, db = env
    _login(client, "adm")
    row = _create_dept(client, "教务处")
    resp = client.post(f"/api/asset/departments/{row['id']}/claim",
                       json={"name": "教务处"})
    assert resp.status_code == 400
