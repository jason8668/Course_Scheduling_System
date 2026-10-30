"""行政值日提醒:前一天一次 + 当天早上提前半小时一次。

时间口径(Jason 2026-10-30 09:21 定):
- 前一天提醒:前一天下午 17:00 之后首次运行即发(5 分钟任务,防重复日志兜底)。
- 当天早上:以学期默认节次表当天周几的第一节开始时间为值日起点,
  提前 30 分钟提醒;与上课提醒同款窗口(起点前 30 分钟内首次运行即发,
  即 30~25 分钟前,5 分钟任务精度)。没有节次表时起点默认 08:00(即 07:30 提醒)。

值日提醒不看教师的上课提醒开关:值日是必须到校的行政事务,不是一节课,
关掉上课提醒不应连值日提醒一起关掉(若 Jason 要改,再接开关)。
"""

import logging
from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.models.duty import DutyReminderLog
from app.models.semester import Semester
from app.models.timetable import Timetable, TimetableStatus
from app.services import duty as duty_service
from app.services import settings as app_settings
from app.services.dingtalk_app import DingTalkAppClient
from app.services.period_tables import semester_default_table

logger = logging.getLogger(__name__)

DAY_BEFORE_HOUR = 17
MORNING_LEAD_MINUTES = 30
DEFAULT_FIRST_PERIOD = time(8, 0)


def _first_period_start(db: Session, semester_id: int, weekday: int):
    table = semester_default_table(db, semester_id)
    if table is None:
        return DEFAULT_FIRST_PERIOD
    regular = [p for p in table.periods if p.weekday == weekday and p.type == "regular"]
    if not regular:
        regular = [p for p in table.periods if p.type == "regular"]
    if not regular:
        return DEFAULT_FIRST_PERIOD
    starts = [p.start_time for p in regular if p.start_time is not None]
    return min(starts) if starts else DEFAULT_FIRST_PERIOD


def run_duty_reminders(
    db: Session,
    *,
    now: datetime | None = None,
    client: DingTalkAppClient | None = None,
) -> dict:
    """扫已发布课表所在的学期,发值日提醒。回传计数。"""
    cfg = app_settings.dingtalk_app_config(db)
    if not cfg.configured:
        return {"sent": 0, "skipped": 0, "reason": "not_configured"}
    client = client or DingTalkAppClient(cfg.app_key, cfg.app_secret, cfg.agent_id)

    now_wall = (now or clock.school_now()).replace(tzinfo=None)
    today = now_wall.date()
    sent = skipped = 0

    # 值日提醒只针对有已发布课表的学期(与上课提醒同一口径:未发布不提醒)
    timetables = db.scalars(
        select(Timetable).where(Timetable.status == TimetableStatus.published.value)
    ).all()
    for tt in timetables:
        sem: Semester | None = db.get(Semester, tt.semester_id)
        if sem is None:
            continue
        # 今天的值日(当天早上提醒) + 明天的值日(前一天提醒)
        checks = [(today, "morning"), (today + timedelta(days=1), "day_before")]
        for duty_date, kind in checks:
            if sem.start_date and sem.end_date and not (
                sem.start_date <= duty_date <= sem.end_date
            ):
                continue
            teacher = duty_service.duty_teacher(db, tt.semester_id, duty_date)
            if teacher is None:
                continue
            # 时间窗口判定
            if kind == "day_before":
                # 前一天 17:00 之后才发(17:00 前不发,避免提前一天以上就提醒)
                if now_wall.hour < DAY_BEFORE_HOUR:
                    continue
            else:
                first = _first_period_start(db, tt.semester_id, duty_date.isoweekday())
                starts_at = datetime.combine(duty_date, first)
                delta = starts_at - now_wall
                # 提前 30 分钟提醒:与上课提醒同款窗口(起点前 30 分钟内首次运行即发)
                if not (timedelta(0) <= delta <= timedelta(minutes=MORNING_LEAD_MINUTES)):
                    continue
            already = db.scalar(
                select(DutyReminderLog).where(
                    DutyReminderLog.semester_id == tt.semester_id,
                    DutyReminderLog.duty_date == duty_date,
                    DutyReminderLog.teacher_id == teacher.id,
                    DutyReminderLog.kind == kind,
                )
            )
            if already is not None:
                continue
            userid = teacher.dingtalk_userid
            if not userid and teacher.phone:
                userid = client.get_userid(teacher.phone)
                if userid:
                    teacher.dingtalk_userid = userid
                    db.commit()
            if not userid:
                logger.warning("值日提醒跳过:%s 无钉钉 userid", teacher.name)
                skipped += 1
                continue
            when = "明天" if kind == "day_before" else "今天"
            title = "行政值日提醒"
            body = (
                f"### 行政值日提醒\n\n{teacher.name}老师,您{when}是全校行政值日, "
                f"请到校处理全校事务。值日不算课时,当天课程照常上。"
            )
            try:
                client.send_work_notification(userid, title, body)
            except Exception as exc:  # noqa: BLE001 - 单个老师失败不影响其他人
                logger.warning("值日提醒发送失败(%s):%s", teacher.name, exc)
                skipped += 1
                continue
            db.add(DutyReminderLog(
                semester_id=tt.semester_id, duty_date=duty_date,
                teacher_id=teacher.id, kind=kind,
            ))
            db.commit()
            sent += 1
    return {"sent": sent, "skipped": skipped}
