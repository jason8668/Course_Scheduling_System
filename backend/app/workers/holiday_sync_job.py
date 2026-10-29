"""公共假日 + 传统节日同步背景任务(RQ, ops 队列)。

每日任务自我续期(与上课提醒同款模式:续期放 finally,本次失败也不断链)。
单学期任务由学期创建/复制 API 入队,跑完不续期。
"""

import logging

logger = logging.getLogger(__name__)


def holiday_sync_job() -> list[dict]:
    """RQ 进入点:扫全部学期逐年同步,回传各学期各年的结果。"""
    from app.core.db import SessionLocal
    from app.services.holidays import sync_all_semesters

    db = SessionLocal()
    try:
        result = sync_all_semesters(db)
        logger.info("假日同步完成:%s", result)
        return result
    finally:
        from app.workers.scheduler import schedule_holiday_sync

        schedule_holiday_sync()
        db.close()


def holiday_sync_semester_job(semester_id: int) -> list[dict]:
    """RQ 进入点:只同步指定学期(学期创建/复制后入队的一次性任务)。"""
    from app.core.db import SessionLocal
    from app.models.semester import Semester
    from app.services.holidays import sync_semester

    db = SessionLocal()
    try:
        semester = db.get(Semester, semester_id)
        if semester is None:
            logger.warning("假日同步:学期 %s 不存在,跳过", semester_id)
            return []
        result = sync_semester(db, semester)
        logger.info("假日同步完成(学期 %s):%s", semester_id, result)
        return result
    finally:
        db.close()
