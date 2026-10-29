"""定时任务排程骨架(M5-0;M6-2 起改挂 ops 伫列)。

RQ worker 以 `with_scheduler=True` 启动,内建排程器会在到期时把排定的任务丢回伫列。
周期任务用「执行时把下一次排进去」的自我续期模式表达——不必额外的 rq-scheduler 套件或
独立容器。定时任务(每日备份、心跳)都是维运任务,故一律排进 **ops** 伫列,由 ops worker
兼任排程器;排课那条伫列被占住数分钟时,备份照跑。

心跳任务只证明排程器存活(写一行 log 并排下一次)。以固定 job_id 续期,重启不会堆叠。
"""

import logging
from datetime import datetime, timedelta

from rq.registry import ScheduledJobRegistry

from app.core import clock
from app.core.config import settings
from app.workers.queue import default_queue, ops_queue

logger = logging.getLogger(__name__)

HEARTBEAT_JOB_ID = "scheduler-heartbeat"
DAILY_BACKUP_JOB_ID = "daily-backup"
CLASS_REMINDER_JOB_ID = "class-reminder"
CLASS_REMINDER_INTERVAL = timedelta(minutes=5)
HOLIDAY_SYNC_JOB_ID = "holiday-sync"
HOLIDAY_SYNC_INTERVAL = timedelta(days=1)


def _interval() -> timedelta:
    return timedelta(seconds=settings.scheduler_heartbeat_seconds)


def _schedule_next() -> None:
    # 固定 job_id:同时只会有一笔待执行的心跳,重复排入会覆盖而非堆叠
    ops_queue.enqueue_in(_interval(), heartbeat, job_id=HEARTBEAT_JOB_ID)


def heartbeat() -> None:
    """排程器存活心跳;执行时把下一次排进去(自我续期)。

    顺带自愈每日备份链:若 daily-backup 因某次失败而未再排入(见 backup_job),
    这里补排回去——备份系统最忌讳的是静默断裂,心跳每小时兜底一次。
    """
    try:
        logger.info("排程器心跳 OK,下次 %s 后", _interval())
        _ensure_daily_backup_scheduled()
        _ensure_class_reminder_scheduled()
        _ensure_holiday_sync_scheduled()
    finally:
        _schedule_next()  # 无论本次是否出错,下一次心跳一定排入


def _ensure_daily_backup_scheduled() -> None:
    try:
        registry = ScheduledJobRegistry(queue=ops_queue)
        if DAILY_BACKUP_JOB_ID not in set(registry.get_job_ids()):
            schedule_daily_backup()
            logger.warning("侦测到每日备份未排入,已补排,下次 %s", _next_backup_time())
    except Exception:  # noqa: BLE001 - 自愈失败不该让心跳挂掉
        logger.warning("检查/补排每日备份失败(Redis 不可用?)")


def _drop_legacy_default_schedules() -> None:
    """清掉旧版排在 **default** 伫列上的定时任务(M6-2 之前的版本)。

    升级后排程器改看 ops 伫列。若不清,旧的 daily-backup / heartbeat 会永远留在
    default 的 ScheduledJobRegistry 里——排课 worker 不跑排程器,没人会把它们捞出来,
    每日备份就此静默断裂(备份系统最不能忍的失败模式)。以固定 job_id 精准移除。
    """
    try:
        registry = ScheduledJobRegistry(queue=default_queue)
        for job_id in (HEARTBEAT_JOB_ID, DAILY_BACKUP_JOB_ID):
            if job_id in set(registry.get_job_ids()):
                registry.remove(job_id, delete_job=True)
                logger.info("已移除旧版排在 default 伫列的定时任务:%s", job_id)
    except Exception:  # noqa: BLE001 - 清理失败不该让 worker 起不来
        logger.warning("清理旧版 default 伫列定时任务失败(Redis 不可用?)")


def _next_backup_time() -> datetime:
    """学校时区的下一个 backup_hour 时刻(unaware,供 enqueue_at)。"""
    now = clock.school_now().replace(tzinfo=None)
    target = now.replace(hour=settings.backup_hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def schedule_daily_backup() -> None:
    from app.workers.backup_job import daily_backup_job
    ops_queue.enqueue_at(_next_backup_time(), daily_backup_job, job_id=DAILY_BACKUP_JOB_ID)


def schedule_class_reminder() -> None:
    """把下一次上课提醒排入(5 分钟后);固定 job_id,重复排入会覆盖而非堆叠。"""
    from app.workers.class_reminder_job import class_reminder_job
    ops_queue.enqueue_in(CLASS_REMINDER_INTERVAL, class_reminder_job, job_id=CLASS_REMINDER_JOB_ID)


def _ensure_class_reminder_scheduled() -> None:
    """心跳兜底:提醒链若断了(某次续期失败),在这里补排回去。

    提醒是 15 分钟提前量,链断超过 15 分钟就会漏提醒;心跳每小时检查一次,
    正常情况下链自我续期,本函数只是不断链的保险。
    """
    try:
        registry = ScheduledJobRegistry(queue=ops_queue)
        if CLASS_REMINDER_JOB_ID not in set(registry.get_job_ids()):
            schedule_class_reminder()
            logger.warning("侦测到上课提醒未排入,已补排,下次 %s 后", CLASS_REMINDER_INTERVAL)
    except Exception:  # noqa: BLE001 - 自愈失败不该让心跳挂掉
        logger.warning("检查/补排上课提醒失败(Redis 不可用?)")


def schedule_holiday_sync() -> None:
    """把下一次假日同步排入(24 小时后);固定 job_id,重复排入会覆盖而非堆叠。"""
    from app.workers.holiday_sync_job import holiday_sync_job
    ops_queue.enqueue_in(HOLIDAY_SYNC_INTERVAL, holiday_sync_job, job_id=HOLIDAY_SYNC_JOB_ID)


def _ensure_holiday_sync_scheduled() -> None:
    """心跳兜底:假日同步链若断了,在这里补排回去(假日公布时间不定,断链会漏更新)。"""
    try:
        registry = ScheduledJobRegistry(queue=ops_queue)
        if HOLIDAY_SYNC_JOB_ID not in set(registry.get_job_ids()):
            schedule_holiday_sync()
            logger.warning("侦测到假日同步未排入,已补排,下次 %s 后", HOLIDAY_SYNC_INTERVAL)
    except Exception:  # noqa: BLE001 - 自愈失败不该让心跳挂掉
        logger.warning("检查/补排假日同步失败(Redis 不可用?)")


def ensure_scheduled() -> None:
    """ops worker 启动时呼叫:确保心跳、备份、提醒与假日同步已排入(已存在则略过)。"""
    _drop_legacy_default_schedules()
    try:
        registry = ScheduledJobRegistry(queue=ops_queue)
        pending = set(registry.get_job_ids())
        if HEARTBEAT_JOB_ID not in pending:
            _schedule_next()
            logger.info("已排入排程器心跳,间隔 %s", _interval())
        if DAILY_BACKUP_JOB_ID not in pending:
            schedule_daily_backup()
            logger.info("已排入每日自动备份,下次 %s", _next_backup_time())
        if CLASS_REMINDER_JOB_ID not in pending:
            schedule_class_reminder()
            logger.info("已排入上课提醒,间隔 %s", CLASS_REMINDER_INTERVAL)
        if HOLIDAY_SYNC_JOB_ID not in pending:
            schedule_holiday_sync()
            logger.info("已排入假日同步,间隔 %s", HOLIDAY_SYNC_INTERVAL)
    except Exception:  # noqa: BLE001 - Redis 不可用不该让 worker 起不来
        logger.warning("排入定时任务失败(Redis 不可用?);背景任务仍可运作")
