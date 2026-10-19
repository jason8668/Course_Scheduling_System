"""备份/还原背景任务(worker;pg_dump/pg_restore 只在 worker 映像,M5-2)。"""

import logging

from app.services import backup as backup_service

logger = logging.getLogger(__name__)


def _as_dict(info: backup_service.BackupInfo) -> dict:
    return {
        "name": info.name,
        "size_bytes": info.size_bytes,
        "created_at": info.created_at.isoformat(),
        "reason": info.reason,
    }


def create_backup_job(reason: str = "manual") -> dict:
    info = backup_service.create_backup(reason)
    logger.info("已建立备份 %s(%d bytes)", info.name, info.size_bytes)
    return _as_dict(info)


def restore_job(name: str) -> list[str]:
    """还原指定备份;完成后强制全员重新登录。回传可忽略的警告摘要。"""
    warnings = backup_service.restore_backup(name)
    from app.core.session_epoch import force_logout_all
    force_logout_all()
    logger.info("已从 %s 还原,并要求全员重新登录", name)
    return warnings


def daily_backup_job() -> dict:
    """每日自动备份;执行后把下一次排进去(自我续期,见 scheduler)。

    续期一定要发生,否则一次备份失败(磁碟满、DB 暂时不可达)就会让整条每日备份链
    永久静默断裂。故先在 finally 把下一次排进去,再让本次的错误照常往上抛(RQ 记失败)。
    """
    from app.workers.scheduler import schedule_daily_backup
    try:
        info = backup_service.create_backup("auto")
        logger.info("每日自动备份完成 %s", info.name)
        return _as_dict(info)
    finally:
        schedule_daily_backup()
