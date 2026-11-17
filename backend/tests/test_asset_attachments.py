"""附件直传测试(#12 补半成品)。

覆盖:上传成功落盘且建行(相对路径 + 审计)、非法类型 400、超大 400、
资产不存在 404、软删除后文件仍在但列表不可见、路径穿越被净化、重名加后缀。
自建测试 app(不改共用 conftest):auth + asset_foundation + asset_ledger,
SQLite 记忆体库,附件目录用 tmp_path 覆盖 settings.asset_attachment_dir。
"""

import io
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import asset_foundation, asset_ledger, auth
from app.core.config import settings
from app.core.db import Base, get_db
from app.models.asset_ledger import AssetAttachment
from app.models.audit import AuditLog
from app.models.user import Role
from app.services.asset_seed import seed_asset_foundation
from app.services.users import create_user

PW = "pw-123456"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "asset_attachment_dir", str(tmp_path / "attachments"))
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
    application.dependency_overrides[get_db] = override_get_db

    setup_db = TestSession()
    seed_asset_foundation(setup_db)
    setup_db.commit()
    client = TestClient(application)
    try:
        yield client, setup_db, tmp_path / "attachments"
    finally:
        setup_db.close()
        Base.metadata.drop_all(engine)


@pytest.fixture
def users(env):
    client, db, _ = env
    for username, roles in [
        ("adm", [Role.admin]),
        ("am", [Role.asset_admin]),
    ]:
        create_user(db, username=username, password=PW, roles=list(roles),
                    must_change_password=False)
    db.commit()


def _login(client, username):
    resp = client.post("/api/auth/login", json={"username": username, "password": PW})
    assert resp.status_code == 200, resp.text


def _create_card(client, **overrides):
    body = {"name": "示例资产", "category_code": "A0203"}
    body.update(overrides)
    resp = client.post("/api/asset/assets", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _upload(client, asset_id, files, file_type="设备照片"):
    return client.post(
        f"/api/asset/assets/{asset_id}/attachments/upload",
        files=files, data={"file_type": file_type},
    )


def _jpg(name="photo.jpg", content=b"\xff\xd8\xff\xe0fake-jpeg"):
    return ("files", (name, io.BytesIO(content), "image/jpeg"))


# ── 上传成功 ──────────────────────────────
def test_upload_success_writes_disk_row_and_audit(env, users, tmp_path):
    client, db, att_dir = env
    _login(client, "am")
    card = _create_card(client)
    resp = _upload(client, card["id"], [
        _jpg("photo.jpg", b"JPEG-DATA-1"),
        ("files", ("invoice.pdf", io.BytesIO(b"%PDF-fake"), "application/pdf")),
    ])
    assert resp.status_code == 201, resp.text
    rows = resp.json()
    assert len(rows) == 2
    assert rows[0]["file_name"] == "photo.jpg"
    assert rows[0]["file_size"] == len(b"JPEG-DATA-1")
    # file_path 存相对路径,不含绝对目录
    assert rows[0]["file_path"] == f"{card['id']}/photo.jpg"
    assert not Path(rows[0]["file_path"]).is_absolute()
    assert (att_dir / str(card["id"]) / "photo.jpg").read_bytes() == b"JPEG-DATA-1"
    assert (att_dir / str(card["id"]) / "invoice.pdf").read_bytes() == b"%PDF-fake"
    # 数据库建行 + 列表可见 + 审计每件一条
    assert db.query(AssetAttachment).filter_by(
        asset_id=card["id"], is_deleted=False).count() == 2
    listed = client.get(f"/api/asset/assets/{card['id']}/attachments")
    assert listed.status_code == 200
    assert [r["file_name"] for r in listed.json()] == ["photo.jpg", "invoice.pdf"]
    audits = db.query(AuditLog).filter_by(
        action="asset_attachment_upload").all()
    assert len(audits) == 2
    assert all(a.target_type == "asset_attachment" for a in audits)


def test_upload_duplicate_names_get_suffix(env, users):
    client, db, att_dir = env
    _login(client, "am")
    card = _create_card(client)
    resp = _upload(client, card["id"], [_jpg("photo.jpg"), _jpg("photo.jpg")])
    assert resp.status_code == 201, resp.text
    names = [r["file_name"] for r in resp.json()]
    assert names == ["photo.jpg", "photo_1.jpg"]
    assert (att_dir / str(card["id"]) / "photo.jpg").exists()
    assert (att_dir / str(card["id"]) / "photo_1.jpg").exists()


def test_upload_path_traversal_sanitized(env, users, tmp_path):
    client, db, att_dir = env
    _login(client, "am")
    card = _create_card(client)
    resp = _upload(client, card["id"], [_jpg("../../evil.jpg")])
    assert resp.status_code == 201, resp.text
    assert resp.json()[0]["file_name"] == "evil.jpg"
    assert resp.json()[0]["file_path"] == f"{card['id']}/evil.jpg"
    assert not (tmp_path / "evil.jpg").exists()
    assert (att_dir / str(card["id"]) / "evil.jpg").exists()


# ── 400/404 ──────────────────────────────
def test_upload_illegal_type_400_and_nothing_written(env, users):
    client, db, att_dir = env
    _login(client, "am")
    card = _create_card(client)
    resp = _upload(client, card["id"], [
        ("files", ("bad.exe", io.BytesIO(b"MZ-fake"), "application/octet-stream")),
    ])
    assert resp.status_code == 400, resp.text
    assert "不支持的文件类型" in resp.json()["detail"]
    assert db.query(AssetAttachment).filter_by(asset_id=card["id"]).count() == 0
    assert not (att_dir / str(card["id"])).exists()


def test_upload_oversize_400(env, users, monkeypatch):
    monkeypatch.setattr(asset_ledger, "MAX_ATTACHMENT_SIZE", 10)
    client, db, att_dir = env
    _login(client, "am")
    card = _create_card(client)
    resp = _upload(client, card["id"], [_jpg("big.jpg", b"x" * 11)])
    assert resp.status_code == 400, resp.text
    assert "文件过大" in resp.json()["detail"]
    assert db.query(AssetAttachment).filter_by(asset_id=card["id"]).count() == 0


def test_upload_limit_is_20mb():
    assert asset_ledger.MAX_ATTACHMENT_SIZE == 20 * 1024 * 1024
    assert asset_ledger.ALLOWED_ATTACHMENT_EXTS == {
        ".jpg", ".jpeg", ".png", ".webp",
        ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    }


def test_upload_asset_missing_404(env, users):
    client, db, att_dir = env
    _login(client, "am")
    resp = _upload(client, 999999, [_jpg()])
    assert resp.status_code == 404, resp.text


def test_upload_bad_file_type_400(env, users):
    client, db, att_dir = env
    _login(client, "am")
    card = _create_card(client)
    resp = _upload(client, card["id"], [_jpg()], file_type="不存在的类型")
    assert resp.status_code == 400, resp.text


# ── 软删除后文件仍在但列表不可见 ──────────────────────────────
def test_soft_delete_keeps_file_but_hides_from_list(env, users):
    client, db, att_dir = env
    _login(client, "am")
    card = _create_card(client)
    resp = _upload(client, card["id"], [_jpg("photo.jpg", b"JPEG-DATA")])
    assert resp.status_code == 201, resp.text
    att_id = resp.json()[0]["id"]
    disk_path = att_dir / str(card["id"]) / "photo.jpg"
    assert disk_path.exists()
    deleted = client.delete(f"/api/asset/attachments/{att_id}")
    assert deleted.status_code == 200, deleted.text
    # 文件仍在磁盘上(只删索引留痕),列表不再可见
    assert disk_path.read_bytes() == b"JPEG-DATA"
    listed = client.get(f"/api/asset/assets/{card['id']}/attachments")
    assert listed.status_code == 200
    assert listed.json() == []
    row = db.query(AssetAttachment).filter_by(id=att_id).one()
    assert row.is_deleted is True
