"""#83:备份含附件包(附件目录 tar.gz 与 .dump 同名同进退)。

pg_dump/pg_restore 以假 subprocess 替代(SQLite 环境无 pg 工具);
真实 pg_dump/pg_restore 恢复演练在真 Postgres 16 上另做。
"""

import subprocess
import tarfile

import pytest

from app.core.config import settings
from app.services import backup as bk

PGDMP = b"PGDMP" + b"\x00" * 100  # 假的 custom 格式档头


@pytest.fixture
def backup_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "backup_dir", str(tmp_path))
    return tmp_path


@pytest.fixture
def attach_dir(tmp_path, monkeypatch):
    """附件目录:直接替换 backup 模块的 _attachment_dir(配置项尚未落地时
    用 getattr 兜底,测试不依赖 Settings 是否已有该字段)。"""
    d = tmp_path / "attachments"
    d.mkdir()
    monkeypatch.setattr(bk, "_attachment_dir", lambda: str(d))
    return d


def _fake_pg_dump():
    def fake_run(cmd, **kwargs):
        path = cmd[cmd.index("-f") + 1]
        with open(path, "wb") as f:
            f.write(PGDMP)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    return fake_run


def _fake_pg_restore():
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    return fake_run


def _touch(dir_, name: str, content: bytes = PGDMP):
    (dir_ / name).write_bytes(content)


def _make_tar(path, members: dict[str, bytes]):
    import io

    with tarfile.open(path, "w:gz") as tf:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))


# ── create_backup 打包附件 ──────────────────────────────────
def test_create_backup_packs_attachments(backup_dir, attach_dir, monkeypatch):
    (attach_dir / "sub").mkdir()
    (attach_dir / "sub" / "invoice.pdf").write_bytes(b"PDF-1")
    (attach_dir / "photo.jpg").write_bytes(b"JPG-2")
    monkeypatch.setattr(bk.subprocess, "run", _fake_pg_dump())

    info = bk.create_backup("manual")

    tar = backup_dir / bk.attachment_tar_name(info.name)
    assert tar.exists()
    assert info.has_attachments is True
    assert info.attachment_size_bytes == tar.stat().st_size
    with tarfile.open(tar) as tf:
        assert sorted(tf.getnames()) == ["photo.jpg", "sub/invoice.pdf"]
        assert tf.extractfile("sub/invoice.pdf").read() == b"PDF-1"


def test_attachment_tar_name():
    assert bk.attachment_tar_name("backup_20260101_010101_manual.dump") == (
        "backup_20260101_010101_manual.tar.gz"
    )
    with pytest.raises(bk.BackupError):
        bk.attachment_tar_name("backup_20260101_010101_manual.tar.gz")


def test_create_backup_without_attachment_dir_succeeds(
    backup_dir, tmp_path, monkeypatch, caplog
):
    monkeypatch.setattr(bk, "_attachment_dir", lambda: str(tmp_path / "no-such-dir"))
    monkeypatch.setattr(bk.subprocess, "run", _fake_pg_dump())

    with caplog.at_level("INFO", logger="app.services.backup"):
        info = bk.create_backup("manual")

    assert (backup_dir / info.name).exists()
    assert not (backup_dir / bk.attachment_tar_name(info.name)).exists()
    assert info.has_attachments is False
    assert "跳过" in caplog.text


def test_create_backup_empty_attachment_dir_succeeds(
    backup_dir, attach_dir, monkeypatch, caplog
):
    monkeypatch.setattr(bk.subprocess, "run", _fake_pg_dump())

    with caplog.at_level("INFO", logger="app.services.backup"):
        info = bk.create_backup("manual")

    assert (backup_dir / info.name).exists()
    assert not (backup_dir / bk.attachment_tar_name(info.name)).exists()
    assert "目录为空" in caplog.text


def test_attachment_dir_default_when_setting_missing():
    """附件目录读 Settings.asset_attachment_dir(#12 新加配置项);
    配置项尚未出现时用默认路径,不报错。"""
    import app.services.backup as bk_mod

    expected = getattr(settings, "asset_attachment_dir", None) or "/data/asset-attachments"
    assert bk_mod._attachment_dir() == expected


# ── 轮替:附件包与 .dump 同进退 ─────────────────────────────
def test_prune_removes_tar_with_dump(backup_dir):
    for i in range(1, 4):
        stem = f"backup_2026010{i}_010101_auto"
        _touch(backup_dir, f"{stem}.dump")
        _make_tar(backup_dir / f"{stem}.tar.gz", {"f.txt": b"x"})
    removed = bk.prune(keep=1)
    remaining_dumps = sorted(b.name for b in bk.list_backups())
    remaining_tars = sorted(p.name for p in backup_dir.iterdir() if p.suffix == ".gz")
    assert remaining_dumps == ["backup_20260103_010101_auto.dump"]
    assert remaining_tars == ["backup_20260103_010101_auto.tar.gz"]
    assert "backup_20260101_010101_auto.tar.gz" in removed
    assert "backup_20260102_010101_auto.tar.gz" in removed


def test_prune_removes_orphan_tar_but_keeps_preupgrade(backup_dir):
    _make_tar(backup_dir / "backup_20260101_010101_auto.tar.gz", {"f.txt": b"x"})
    _make_tar(backup_dir / "backup_20260101_010101_preupgrade.tar.gz", {"f.txt": b"x"})
    _touch(backup_dir, "backup_20260102_010101_auto.dump")
    removed = bk.prune(keep=30)
    assert "backup_20260101_010101_auto.tar.gz" in removed
    assert (backup_dir / "backup_20260101_010101_preupgrade.tar.gz").exists()


# ── 还原:附件解回 ──────────────────────────────────────────
def _restore_setup(backup_dir, monkeypatch):
    monkeypatch.setattr(bk, "_terminate_other_connections", lambda p: None)
    monkeypatch.setattr(bk.subprocess, "run", _fake_pg_restore())


def test_restore_restores_attachments(backup_dir, attach_dir, monkeypatch):
    _restore_setup(backup_dir, monkeypatch)
    name = "backup_20260101_010101_manual.dump"
    _touch(backup_dir, name)
    _make_tar(
        backup_dir / bk.attachment_tar_name(name),
        {"new.txt": b"new-content", "sub/keep.txt": b"keep"},
    )
    (attach_dir / "old.txt").write_bytes(b"old-content")

    warnings = bk.restore_backup(name)

    assert warnings == []
    assert (attach_dir / "new.txt").read_bytes() == b"new-content"
    assert (attach_dir / "sub" / "keep.txt").read_bytes() == b"keep"
    # 旧附件目录被整体移走备份,而非直接覆盖丢档
    backups = [p for p in attach_dir.parent.iterdir()
               if p.name.startswith("attachments.pre-restore-")]
    assert len(backups) == 1
    assert (backups[0] / "old.txt").read_bytes() == b"old-content"


def test_restore_without_tar_succeeds(backup_dir, attach_dir, monkeypatch):
    _restore_setup(backup_dir, monkeypatch)
    name = "backup_20260101_010101_manual.dump"
    _touch(backup_dir, name)
    (attach_dir / "old.txt").write_bytes(b"old-content")

    assert bk.restore_backup(name) == []
    # 无附件包:现有附件目录原样不动
    assert (attach_dir / "old.txt").read_bytes() == b"old-content"


def test_restore_rejects_tar_with_path_traversal(backup_dir, attach_dir, monkeypatch):
    _restore_setup(backup_dir, monkeypatch)
    name = "backup_20260101_010101_manual.dump"
    _touch(backup_dir, name)
    _make_tar(backup_dir / bk.attachment_tar_name(name), {"../evil.txt": b"evil"})
    (attach_dir / "old.txt").write_bytes(b"old-content")

    with pytest.raises(bk.BackupError):
        bk.restore_backup(name)

    # 恶意成员未落地,现有附件目录完好
    assert not (backup_dir.parent / "evil.txt").exists()
    assert (attach_dir / "old.txt").read_bytes() == b"old-content"


# ── 非法档名拒绝 ────────────────────────────────────────────
def test_restore_rejects_non_dump_names(backup_dir):
    with pytest.raises(bk.BackupError):
        bk.restore_backup("../../etc/passwd")
    with pytest.raises(bk.BackupError):
        bk.restore_backup("backup_20260101_010101_manual.tar.gz")
    with pytest.raises(bk.BackupError):
        bk.restore_backup("backup_20260101_010101_manual.dump/extra")
