"""月度课时确认背景任务(RQ,ops 伫列)。

每月最后一天 17:00 跑一次(与假日同步同款自我续期模式:续期放 finally,
本次失败也不断链)。未配置企业应用时系统通知照常建,个人钉钉不发——
管理员填好配置后下一次运行即开始推送,无需重启 worker。
"""

import logging

logger = logging.getLogger(__name__)


def monthly_hours_job() -> dict:
    """RQ 进入点:给本学期每位任课老师建一条月度课时确认通知并个人钉钉推出去,
    回传计数与跳过/失败名单。"""
    from app.core.db import SessionLocal
    from app.services.monthly_hours import run_monthly_hours

    db = SessionLocal()
    try:
        result = run_monthly_hours(db)
        logger.info("月度课时确认完成:%s", result)
        return result
    finally:
        from app.workers.scheduler import schedule_monthly_hours

        schedule_monthly_hours()
        db.close()
