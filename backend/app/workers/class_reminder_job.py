"""上课提醒背景任务(RQ,ops 伫列)。

每 5 分钟自我续期(与每日备份同款模式:续期放 finally,本次失败也不断链)。
未配置企业应用时服务层静默返回,任务照常续期——管理员填好配置后下一次
运行即开始提醒,无需重启 worker。
"""

import logging

logger = logging.getLogger(__name__)


def class_reminder_job() -> dict:
    """RQ 进入点:扫已发布课表并推送 15 分钟内的上课提醒,回传计数。"""
    from app.core.db import SessionLocal
    from app.services.class_reminders import run_class_reminders

    db = SessionLocal()
    try:
        result = run_class_reminders(db)
        logger.info("上课提醒完成:%s", result)
        return result
    finally:
        from app.workers.scheduler import schedule_class_reminder

        schedule_class_reminder()
        db.close()
