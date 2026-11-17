"""资产 7 类扫描定时任务(RQ, ops 伫列; #83 定时 worker 挂载)。

每日 08:00(学校时区)跑一次,见 workers/scheduler.py 的 ASSET_SCAN_JOB_ID。
7 类扫描各自 try/except 隔离:一类抛错只记该类失败并 rollback,不中断其他类;
每类成功后立即 commit,避免后一类失败把前一类的提醒/状态变更一起滚掉。

自我续期模式与每日备份同款:续期放 finally,本次失败也不断链。
"""

import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.services import asset_circulation as circ_svc
from app.services import asset_inventory as inv_svc
from app.services import asset_sync_exec as sync_svc
from app.workers.scheduler import schedule_asset_scan

logger = logging.getLogger(__name__)


def _scan_fns() -> tuple[tuple[str, Callable], ...]:
    """7 类扫描(每次现取函数对象,便于测试 monkeypatch 替换其中一类)。"""
    return (
        ("borrow_overdue", circ_svc.scan_borrow_overdue),
        ("handover_warnings", circ_svc.scan_handover_warnings),
        ("warranty", circ_svc.scan_warranty),
        ("reservation_release", circ_svc.scan_reservation_release),
        ("approval_overdue", circ_svc.scan_approval_overdue_reminders),
        ("inventory_due", inv_svc.scan_inventory_due),
        ("sync_backlog", sync_svc.scan_sync_backlog),
    )


def run_asset_scans(db: Session) -> dict[str, dict]:
    """跑全部 7 类扫描,每类独立成败。回传 {扫描名: {ok, result|error}}。"""
    results: dict[str, dict] = {}
    for name, fn in _scan_fns():
        try:
            result = fn(db)
            db.commit()
            results[name] = {"ok": True, "result": result}
            logger.info("资产扫描 %s 完成:%s", name, result)
        except Exception as exc:  # noqa: BLE001 - 单类失败只记日志,不中断其他类
            db.rollback()
            results[name] = {"ok": False, "error": str(exc)}
            logger.warning("资产扫描 %s 失败(不中断其他扫描):%s", name, exc, exc_info=True)
    return results


def asset_scan_job(db: Session | None = None) -> dict[str, dict]:
    """RQ 进入点:跑全部 7 类资产扫描;执行后把下一次排进去(自我续期)。

    db 仅供测试注入;正式运行时为 None,内部开 SessionLocal。
    """
    from app.core.db import SessionLocal

    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        assert db is not None
        results = run_asset_scans(db)
        logger.info(
            "资产每日扫描完成:%s",
            {k: v["ok"] for k, v in results.items()},
        )
        return results
    finally:
        schedule_asset_scan()
        if own_session:
            db.close()
