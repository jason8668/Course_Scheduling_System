"""个人上课提醒:上课前 N 分钟把工作通知推到老师个人钉钉。

只看已发布课表(同学期至多一份 published);节次开始时间取班级节次表
(有指定用班级的,否则学期默认表),与学校时区的墙钟时间对照(D6:领域时间
皆为无时区墙钟,故 now 也先去时区再比)。单双周的课只在对应周提醒。

防重复:同一格位、同一天、同一位老师只发一次,class_reminder_logs
唯一约束兜底(任务重跑、worker 重复执行都不会发两次)。

未配置企业应用时静默不做(与群机器人通道同款语义);单个老师失败
(没手机号、查不到 userid、发送失败)只记日志并跳过,不影响其他老师。
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.week_parity import runs_in_week, week_number
from app.models.basedata import Teacher
from app.models.semester import Semester
from app.models.timetable import ClassReminderLog, ScheduleEntry, Timetable, TimetableStatus
from app.services import settings as app_settings
from app.services.dingtalk_app import DingTalkAppClient
from app.services.period_tables import resolve_period_table, semester_default_table

logger = logging.getLogger(__name__)


def _period_start(db: Session, entry: ScheduleEntry, semester_id: int):
    """该格位在班级节次表里的开始时间;找不到或没填时间回 None(无法提醒则跳过)。"""
    members = entry.assignment.scheduling_unit.members
    table = None
    if members:
        table = resolve_period_table(db, members[0].class_unit)
    if table is None:
        table = semester_default_table(db, semester_id)
    if table is None:
        return None
    cell = next(
        (p for p in table.periods if p.weekday == entry.weekday and p.period_no == entry.period_no),
        None,
    )
    if cell is None:
        cell = next((p for p in table.periods if p.period_no == entry.period_no), None)
    return cell.start_time if cell is not None else None


def _message(teacher_name: str, start_text: str, classes: list[str], subject: str, room: str | None) -> str:
    where = f"在{room}" if room else ""
    return (
        f"### 上课提醒\n\n{teacher_name}老师,您 {start_text} {where}有 "
        f"{'、'.join(classes)}的《{subject}》。"
    )


def run_class_reminders(
    db: Session,
    *,
    now: datetime | None = None,
    client: DingTalkAppClient | None = None,
) -> dict:
    """扫一遍已发布课表,把 15 分钟(设置可调)内要上的课推给老师。回传计数。"""
    cfg = app_settings.dingtalk_app_config(db)
    if not cfg.configured:
        return {"sent": 0, "skipped": 0, "reason": "not_configured"}
    client = client or DingTalkAppClient(cfg.app_key, cfg.app_secret, cfg.agent_id)

    now_wall = (now or clock.school_now()).replace(tzinfo=None)
    today = now_wall.date()
    weekday = today.isoweekday()  # 1=周一,与节次表/格位 weekday 口径一致
    lead = timedelta(minutes=cfg.lead_minutes)

    sent = skipped = 0
    timetables = db.scalars(
        select(Timetable).where(Timetable.status == TimetableStatus.published.value)
    ).all()
    for tt in timetables:
        sem: Semester | None = db.get(Semester, tt.semester_id)
        if sem is not None and sem.start_date and sem.end_date:
            if not (sem.start_date <= today <= sem.end_date):
                continue
        wn = week_number(sem.start_date if sem is not None else None, today)
        week = None if wn is None else ("odd" if wn % 2 == 1 else "even")
        entries = db.scalars(
            select(ScheduleEntry).where(
                ScheduleEntry.timetable_id == tt.id, ScheduleEntry.weekday == weekday
            )
        ).all()
        for entry in entries:
            assignment = entry.assignment
            if not runs_in_week(assignment.week_parity, week):
                continue
            start_time = _period_start(db, entry, tt.semester_id)
            if start_time is None:
                skipped += 1
                continue
            starts_at = datetime.combine(today, start_time)
            delta = starts_at - now_wall
            if delta < timedelta(0) or delta > lead:
                continue
            members = assignment.scheduling_unit.members
            classes = [m.class_unit.name for m in members]
            room_obj = entry.room if entry.room is not None else assignment.room
            room = room_obj.name if room_obj is not None else None
            start_text = start_time.strftime("%H:%M")
            for link in assignment.teachers:
                teacher: Teacher | None = link.teacher
                if teacher is None:
                    continue
                already = db.scalar(
                    select(ClassReminderLog).where(
                        ClassReminderLog.entry_id == entry.id,
                        ClassReminderLog.class_date == today,
                        ClassReminderLog.teacher_id == teacher.id,
                    )
                )
                if already is not None:
                    continue
                userid = teacher.dingtalk_userid
                if not userid and teacher.phone:
                    userid = client.get_userid(teacher.phone)
                    if userid:
                        teacher.dingtalk_userid = userid
                        db.commit()  # 解析结果先落盘,发送失败也不必重查
                if not userid:
                    logger.warning(
                        "上课提醒跳过:%s 无钉钉 userid(未填手机号或不在企业通讯录)",
                        teacher.name,
                    )
                    skipped += 1
                    continue
                try:
                    client.send_work_notification(
                        userid,
                        "上课提醒",
                        _message(teacher.name, start_text, classes, assignment.subject.name, room),
                    )
                except Exception as exc:  # noqa: BLE001 - 单个老师失败不影响其他人
                    logger.warning("上课提醒发送失败(%s):%s", teacher.name, exc)
                    skipped += 1
                    continue
                db.add(
                    ClassReminderLog(
                        entry_id=entry.id, class_date=today, teacher_id=teacher.id
                    )
                )
                db.commit()
                sent += 1
    return {"sent": sent, "skipped": skipped}
