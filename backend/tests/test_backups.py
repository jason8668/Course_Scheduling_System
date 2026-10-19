"""M5-2:备份/还原的纯逻辑与 RBAC。实际 pg_dump/pg_restore(需 PostgreSQL 与
pg 工具)由 docker 整合测试涵盖;这里测档头验证、轮替、清单、权限、非法上传拒绝。
"""

import pytest

from app.core.config import settings
from app.models.user import Role
from app.services import backup as bk
from tests.conftest import make_user

PW = "password123"
PGDMP = b"PGDMP" + b"\x00" * 100  # 假的 custom 格式档头


@pytest.fixture
def backup_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "backup_dir", str(tmp_path))
    return tmp_path


def _touch(dir_, name: str, content: bytes = PGDMP):
    (dir_ / name).write_bytes(content)


# ── 档头验证(验收②)───────────────────────────────────────
def test_is_valid_dump(backup_dir):
    _touch(backup_dir, "good.dump", PGDMP)
    _touch(backup_dir, "bad.dump", b"not a dump")
    assert bk.is_valid_dump(str(backup_dir / "good.dump")) is True
    assert bk.is_valid_dump(str(backup_dir / "bad.dump")) is False


def test_save_uploaded_rejects_non_dump(backup_dir):
    with pytest.raises(bk.BackupError):
        bk.save_uploaded("x.dump", b"garbage bytes")
    # 拒绝的档案不落地
    assert list(backup_dir.iterdir()) == []


def test_save_uploaded_accepts_valid(backup_dir):
    name = bk.save_uploaded("x.dump", PGDMP)
    assert name.endswith("_upload.dump")
    assert (backup_dir / name).exists()


# ── 清单 / 轮替(验收③)───────────────────────────────────
def test_list_backups_newest_first(backup_dir):
    _touch(backup_dir, "backup_20260101_010101_manual.dump")
    _touch(backup_dir, "backup_20260301_010101_auto.dump")
    _touch(backup_dir, "notabackup.txt")
    names = [b.name for b in bk.list_backups()]
    assert names == [
        "backup_20260301_010101_auto.dump",
        "backup_20260101_010101_manual.dump",
    ]  # 非备份档被忽略


def test_prune_keeps_newest(backup_dir):
    for i in range(1, 6):
        _touch(backup_dir, f"backup_2026010{i}_010101_auto.dump")
    removed = bk.prune(keep=2)
    remaining = sorted(b.name for b in bk.list_backups())
    assert len(remaining) == 2
    assert remaining == [
        "backup_20260104_010101_auto.dump",
        "backup_20260105_010101_auto.dump",
    ]
    assert len(removed) == 3


def test_path_traversal_rejected(backup_dir):
    with pytest.raises(bk.BackupError):
        bk.restore_backup("../../etc/passwd")


# ── RBAC:仅管理员 ─────────────────────────────────────────
def _login(client, db, username, roles):
    make_user(db, username, PW, roles=roles)
    client.post("/api/auth/login", json={"username": username, "password": PW})


def test_list_backups_admin_only(env, backup_dir):
    client, db = env
    _login(client, db, "sch", [Role.scheduler])
    assert client.get("/api/backups").status_code == 403
    client.post("/api/auth/logout")
    _login(client, db, "adm", [Role.admin])
    r = client.get("/api/backups")
    assert r.status_code == 200
    assert r.json() == []


def test_restore_upload_rejects_garbage_before_touching_db(env, backup_dir):
    client, db = env
    _login(client, db, "adm", [Role.admin])
    r = client.post(
        "/api/backups/restore-upload",
        files={"file": ("evil.dump", b"rm -rf /", "application/octet-stream")},
    )
    assert r.status_code == 400
    assert "格式不符" in r.json()["detail"]
    assert list(backup_dir.iterdir()) == []  # 系统无损:没有档案落地


def test_scheduler_cannot_restore(env, backup_dir):
    client, db = env
    _login(client, db, "sch", [Role.scheduler])
    assert client.post("/api/backups/some.dump/restore").status_code == 403


# ── 还原不得留著一条会被 pg_restore 砍掉的 session(M6-6 实测发现)────────
def test_restore_closes_the_request_session_before_touching_the_database(
    env, backup_dir, monkeypatch
):
    """pg_restore --clean 会中止资料库上的所有连线,包含本请求验证身分时开的那条。

    yield 依赖是在**回应送出后**才收尾,届时 db.close() 会对一条已死的连线送 ROLLBACK,
    在 log 喷出 AdminShutdown traceback——回应与资料都是对的,但刚按下「还原」的人看到
    那段红字只会以为还原失败了。故还原派工前必须先把这条 session 关掉。
    """
    from app.api import backups as backups_api
    from app.core.db import get_db

    client, db = env
    _touch(backup_dir, "backup_20260101_010101_manual.dump")
    _login(client, db, "adm", [Role.admin])

    # 拦下请求用的 session,记下它是否被关闭
    original = client.app.dependency_overrides[get_db]
    closed: dict[str, bool] = {}

    def spy_get_db():
        gen = original()
        session = next(gen)
        real_close = session.close

        def close():
            closed["yes"] = True
            real_close()

        session.close = close  # type: ignore[method-assign]
        try:
            yield session
        finally:
            next(gen, None)

    client.app.dependency_overrides[get_db] = spy_get_db

    seen: dict[str, bool] = {}

    def fake_restore(name):
        # 这一刻 pg_restore 正要砍掉所有连线:请求的 session 必须已经关了
        seen["closed_before_restore"] = closed.get("yes", False)
        return []

    monkeypatch.setattr(backups_api.job_queue, "solver_busy", lambda: False)
    monkeypatch.setattr(
        backups_api.job_queue, "run_backup",
        lambda reason: {"name": f"backup_20260102_010101_{reason}.dump"},
    )
    monkeypatch.setattr(backups_api.job_queue, "run_restore", fake_restore)

    try:
        r = client.post("/api/backups/backup_20260101_010101_manual.dump/restore")
    finally:
        client.app.dependency_overrides[get_db] = original

    assert r.status_code == 200
    assert r.json()["restored_from"] == "backup_20260101_010101_manual.dump"
    assert seen["closed_before_restore"] is True


def test_get_db_teardown_never_raises(monkeypatch, caplog):
    """收尾关 session 失败不该变成一段没有请求可归属的 ASGI traceback——
    用户早就拿到(正确的)回应了。真正的失败会在查询当下就报错,不会被这里盖掉。"""
    from app.core import db as db_mod

    class _DeadSession:
        def close(self):
            raise RuntimeError("terminating connection due to administrator command")

    monkeypatch.setattr(db_mod, "SessionLocal", lambda: _DeadSession())

    gen = db_mod.get_db()
    next(gen)
    with caplog.at_level("WARNING"), pytest.raises(StopIteration):
        next(gen)  # 触发 finally:不得掷出
    assert "还原" in caplog.text
