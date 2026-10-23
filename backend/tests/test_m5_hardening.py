"""M5 里程碑复审(Fable 5,2026-07-11)修正的回归测试。

涵盖条件 A(逾时取消 + 排课中禁止还原)、B(排程自我续期/自愈)、
E(pg_restore stderr 白名单分类)、F(强制登出后尽力落盘)。
"""

import pytest

from app.models.user import Role
from app.services import backup as bk
from tests.conftest import make_user
from tests.test_backups import PGDMP, backup_dir  # noqa: F401 - 沿用 backup_dir fixture

PW = "password123"


# ── E:pg_restore stderr 白名单分类 ──────────────────────────
def test_classify_restore_stderr_tolerates_cross_version_guc():
    stderr = (
        "pg_restore: while PROCESSING TOC:\n"
        "pg_restore: error: could not execute query: ERROR:  "
        'unrecognized configuration parameter "transaction_timeout"\n'
        "pg_restore: warning: errors ignored on restore: 1\n"
    )
    warnings = bk._classify_restore_stderr(stderr)
    assert len(warnings) == 2  # GUC 错误(可忽略)+ 摘要行,皆收为警告、不掷例外


def test_classify_restore_stderr_raises_on_real_data_error():
    stderr = (
        "pg_restore: error: could not execute query: ERROR:  "
        'duplicate key value violates unique constraint "users_pkey"\n'
        "pg_restore: warning: errors ignored on restore: 1\n"
    )
    with pytest.raises(bk.BackupError, match="非预期错误"):
        bk._classify_restore_stderr(stderr)


def test_classify_restore_stderr_empty_is_clean():
    assert bk._classify_restore_stderr("") == []


# ── F:force_logout_all 设 key 后尽力 bgsave ─────────────────
def test_force_logout_triggers_bgsave(monkeypatch):
    from app.core import session_epoch as se

    calls: list[str] = []

    class FakeRedis:
        def set(self, k, v):
            calls.append("set")

        def bgsave(self):
            calls.append("bgsave")

    monkeypatch.setattr(se, "_redis", FakeRedis())
    se.force_logout_all()
    assert calls == ["set", "bgsave"]


def test_force_logout_bgsave_failure_swallowed(monkeypatch):
    from app.core import session_epoch as se

    class FakeRedis:
        def set(self, k, v):
            pass

        def bgsave(self):
            raise RuntimeError("bgsave 失败")

    monkeypatch.setattr(se, "_redis", FakeRedis())
    se.force_logout_all()  # 不应抛出


# ── B:每日备份链一次失败仍续期 ─────────────────────────────
def test_daily_backup_reschedules_even_on_failure(monkeypatch):
    from app.workers import backup_job as bj
    from app.workers import scheduler as sched

    scheduled: list[int] = []
    monkeypatch.setattr(sched, "schedule_daily_backup", lambda: scheduled.append(1))

    def boom(reason):
        raise RuntimeError("磁碟已满")

    monkeypatch.setattr(bj.backup_service, "create_backup", boom)
    with pytest.raises(RuntimeError):
        bj.daily_backup_job()
    assert scheduled == [1]  # 即使备份失败,下一次仍被排入(链不断)


def test_heartbeat_schedules_next_and_selfheals(monkeypatch):
    from app.workers import scheduler as sched

    rec = {"next": 0, "heal": 0}
    monkeypatch.setattr(sched, "_schedule_next", lambda: rec.__setitem__("next", rec["next"] + 1))
    monkeypatch.setattr(sched, "_ensure_daily_backup_scheduled",
                        lambda: rec.__setitem__("heal", rec["heal"] + 1))
    sched.heartbeat()
    assert rec == {"next": 1, "heal": 1}


def test_ensure_daily_backup_reschedules_when_missing(monkeypatch):
    from app.workers import scheduler as sched

    class FakeReg:
        def __init__(self, queue):
            pass

        def get_job_ids(self):
            return []  # daily-backup 不在排程中 → 应补排

    scheduled: list[int] = []
    monkeypatch.setattr(sched, "ScheduledJobRegistry", FakeReg)
    monkeypatch.setattr(sched, "schedule_daily_backup", lambda: scheduled.append(1))
    sched._ensure_daily_backup_scheduled()
    assert scheduled == [1]


def test_ensure_daily_backup_noop_when_present(monkeypatch):
    from app.workers import scheduler as sched

    class FakeReg:
        def __init__(self, queue):
            pass

        def get_job_ids(self):
            return [sched.DAILY_BACKUP_JOB_ID]

    scheduled: list[int] = []
    monkeypatch.setattr(sched, "ScheduledJobRegistry", FakeReg)
    monkeypatch.setattr(sched, "schedule_daily_backup", lambda: scheduled.append(1))
    sched._ensure_daily_backup_scheduled()
    assert scheduled == []  # 已在排程中 → 不重复排


# ── A:阻塞式派工逾时取消 + 排课中禁止还原 ──────────────────
class _FakeJob:
    def __init__(self):
        self.cancelled = False

    def latest_result(self):
        return None  # 模拟逾时(worker 被排课占住)

    def cancel(self):
        self.cancelled = True


def test_run_blocking_cancels_job_on_timeout(monkeypatch):
    from app.workers import queue as q

    job = _FakeJob()
    # 备份/还原/导出自 M6-2 起走 ops 伫列
    monkeypatch.setattr(q.ops_queue, "enqueue", lambda *a, **k: job)
    with pytest.raises(q.BackupJobError):
        q._run_blocking(lambda: None, timeout=1)
    assert job.cancelled is True  # 逾时的任务被取消,不会晚点才偷跑


def test_render_export_cancels_job_on_timeout(monkeypatch):
    from app.workers import queue as q

    job = _FakeJob()
    monkeypatch.setattr(q.ops_queue, "enqueue", lambda *a, **k: job)
    with pytest.raises(q.RenderError):
        q.render_export("<html></html>", "pdf", timeout=1)
    assert job.cancelled is True


class _OkResult:
    """最小可用的 RQ Result 替身(render_export 只碰 type 与 return_value)。"""

    class Type:
        SUCCESSFUL = 1

    type = Type.SUCCESSFUL
    return_value = b"PNG-BYTES"


class _SlowJob:
    """第二次轮询才有结果:模拟 worker 仍在渲染(redis-py 8 之后 XREAD 阻塞读
    等不到结果写入,_wait_result 必须靠轮询在逾时前拿到;CI 首跑抓到的实虫)。"""

    def __init__(self):
        self.cancelled = False
        self._polls = 0

    def latest_result(self):
        self._polls += 1
        return _OkResult() if self._polls >= 2 else None

    def cancel(self):
        self.cancelled = True


def test_render_export_returns_result_arriving_mid_wait(monkeypatch):
    from app.workers import queue as q

    job = _SlowJob()
    monkeypatch.setattr(q, "RESULT_POLL_INTERVAL", 0.01)
    monkeypatch.setattr(q.ops_queue, "enqueue", lambda *a, **k: job)
    assert q.render_export("<html></html>", "png", timeout=5) == b"PNG-BYTES"
    assert job.cancelled is False  # 拿到结果就不取消
    assert job._polls >= 2  # 确认走的是轮询路径


def test_restore_rejected_while_solver_busy(env, backup_dir, monkeypatch):  # noqa: F811
    client, db = env
    from app.workers import queue as job_queue

    make_user(db, "adm", PW, roles=[Role.admin])
    client.post("/api/auth/login", json={"username": "adm", "password": PW})
    (backup_dir / "backup_20260101_010101_manual.dump").write_bytes(PGDMP)

    monkeypatch.setattr(job_queue, "solver_busy", lambda: True)
    r = client.post("/api/backups/backup_20260101_010101_manual.dump/restore")
    assert r.status_code == 409
    assert "排课进行中" in r.json()["detail"]
