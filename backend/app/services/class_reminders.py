"""个人上课提醒:上课前 N 分钟把工作通知推到老师个人钉钉。

只看已发布课表(同学期至多一份 published);节次开始时间取班级节次表
(有指定用班级的,否则学期默认表),与学校时区的墙钟时间对照(D6:领域时间
皆为无时区墙钟,故 now 也先去时区再比)。单双周的课只在对应周提醒。

防重复:同一格位、同一天、同一位老师只发一次,class_reminder_logs
唯一约束兜底(任务重跑、worker 重复执行都不会发两次)。

提醒窗口按教师自配置算:教师在「我的」页自设提前分钟则用自设值,
未设则用学校全局值;教师关了提醒则直接跳过(计 opted_out,不算失败)。

未配置企业应用时静默不做(与群机器人通道同款语义);单个老师失败
(没手机号、查不到 userid、发送失败)只记日志并跳过,不影响其他老师。
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.week_parity import runs_in_week, week_number
from app.models.basedata import ClassUnit, Teacher
from app.models.semester import Semester
from app.models.special_day import SpecialDayReminderLog
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


def _period_start_for_class(
    db: Session, cls: ClassUnit, weekday: int, period_no: int, semester_id: int
):
    """特殊日格位的开始时间:按该班的节次表取,找不到回 None。"""
    table = resolve_period_table(db, cls)
    if table is None:
        table = semester_default_table(db, semester_id)
    if table is None:
        return None
    cell = next(
        (p for p in table.periods if p.weekday == weekday and p.period_no == period_no),
        None,
    )
    if cell is None:
        cell = next((p for p in table.periods if p.period_no == period_no), None)
    return cell.start_time if cell is not None else None


def _try_send(db: Session, client, cfg, teacher: Teacher, starts_at: datetime,
              now_wall: datetime, classes: list[str], subject: str, room: str | None) -> str:
    """发一次提醒(不写日志,由调用方按自己的日志表落盘)。
    回: sent / opted_out / skipped / not_due。"""
    if teacher.reminder_enabled is False:
        return "opted_out"
    teacher_lead = (
        teacher.reminder_lead_minutes
        if teacher.reminder_lead_minutes is not None
        else cfg.lead_minutes
    )
    delta = starts_at - now_wall
    if delta < timedelta(0) or delta > timedelta(minutes=teacher_lead):
        return "not_due"
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
        return "skipped"
    try:
        client.send_work_notification(
            userid, "上课提醒",
            _message(teacher.name, starts_at.strftime("%H:%M"), classes, subject, room),
        )
    except Exception as exc:  # noqa: BLE001 - 单个老师失败不影响其他人
        logger.warning("上课提醒发送失败(%s):%s", teacher.name, exc)
        return "skipped"
    return "sent"


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
    """扫一遍已发布课表,把各教师提前量内要上的课推给老师。回传计数。"""
    cfg = app_settings.dingtalk_app_config(db)
    if not cfg.configured:
        return {"sent": 0, "skipped": 0, "reason": "not_configured"}
    client = client or DingTalkAppClient(cfg.app_key, cfg.app_secret, cfg.agent_id)

    now_wall = (now or clock.school_now()).replace(tzinfo=None)
    today = now_wall.date()
    weekday = today.isoweekday()  # 1=周一,与节次表/格位 weekday 口径一致

    sent = skipped = opted_out = 0
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
        # 特殊日覆盖(今天):主格位被替换/取消的班不再按主课表提醒,换好的课在后面单独提醒
        from app.services.special_days import (
            load_active_rules,
            load_holidays,
            overrides_for_date,
        )

        _classes_by_id = {
            c.id: c for c in db.scalars(
                select(ClassUnit).where(ClassUnit.semester_id == tt.semester_id)
            ).all()
        }
        _overrides = overrides_for_date(
            load_active_rules(db, tt.semester_id), _classes_by_id,
            load_holidays(db, tt.semester_id), today,
        )
        _base_covered: set[tuple[int, int]] = set()
        # 老师自主调课(今天生效的):主格位里原任教师不再为换出的班提醒,
        # 换课教师在后面单独提醒;补课节反过来。
        from app.services import teacher_swaps as _ts

        _swaps_today = [
            st for st in _ts.swap_teachings(db, tt.semester_id)
            if st.class_date == today
        ]
        _swap_by_class_period = {
            (st.class_unit_id, st.period_no): st for st in _swaps_today
        }
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
            members = assignment.scheduling_unit.members
            # 放假那天/那节不上课,提醒也不发(口径与课时统计一致)
            from app.services.holidays import is_holiday_on

            _grades = {
                m.class_unit.grade for m in members if m.class_unit is not None
            }
            _class_ids = {
                m.class_unit.id for m in members if m.class_unit is not None
            }
            _span = entry.span or 1
            if any(
                is_holiday_on(db, tt.semester_id, today, entry.period_no + i, _grades, _class_ids)
                for i in range(_span)
            ):
                skipped += 1
                continue
            # 特殊日:该班该节被替换/取消时,主课表老师不再为该班提醒;
            # 换成同一门配课时仍按主课表提醒,特殊日那遍跳过(防重复)。
            remaining = []
            for m in members:
                if m.class_unit is None:
                    continue
                ov = _overrides.get((m.class_unit.id, entry.period_no))
                if ov is not None and ov.course_assignment_id != assignment.id:
                    continue
                remaining.append(m)
                if ov is not None:
                    _base_covered.add((m.class_unit.id, entry.period_no))
            if not remaining:
                continue
            room_obj = entry.room if entry.room is not None else assignment.room
            room = room_obj.name if room_obj is not None else None
            for link in assignment.teachers:
                teacher: Teacher | None = link.teacher
                if teacher is None:
                    continue
                # 调课:原任教师不再为换出的班提醒(只提醒他还教的班);
                # 换课教师若本就是该配课的协同教师,主课表已提醒他,调课那遍跳过。
                teacher_members = []
                for m in remaining:
                    st = _swap_by_class_period.get((m.class_unit.id, entry.period_no))
                    if st is not None and st.assignment_id == assignment.id \
                            and st.original_teacher_id == teacher.id:
                        continue
                    teacher_members.append(m)
                if not teacher_members:
                    continue
                classes = [m.class_unit.name for m in teacher_members]
                already = db.scalar(
                    select(ClassReminderLog).where(
                        ClassReminderLog.entry_id == entry.id,
                        ClassReminderLog.class_date == today,
                        ClassReminderLog.teacher_id == teacher.id,
                    )
                )
                if already is not None:
                    continue
                result = _try_send(
                    db, client, cfg, teacher, starts_at, now_wall,
                    classes, assignment.subject.name, room,
                )
                if result == "sent":
                    db.add(
                        ClassReminderLog(
                            entry_id=entry.id, class_date=today, teacher_id=teacher.id
                        )
                    )
                    db.commit()
                    sent += 1
                elif result == "opted_out":
                    opted_out += 1
                elif result == "skipped":
                    skipped += 1
        # 特殊日换好的课:按换后的老师、科目、班级提醒(主课表已覆盖的同一门课跳过)
        from app.models.assignment import CourseAssignment as _CourseAssignment

        for (class_id, period_no), ov in sorted(_overrides.items()):
            if ov.course_assignment_id is None or (class_id, period_no) in _base_covered:
                continue
            cls = _classes_by_id.get(class_id)
            if cls is None:
                continue
            assignment = db.get(_CourseAssignment, ov.course_assignment_id)
            if assignment is None:
                continue
            start_time = _period_start_for_class(db, cls, weekday, period_no, tt.semester_id)
            if start_time is None:
                skipped += 1
                continue
            starts_at = datetime.combine(today, start_time)
            room_obj = assignment.room
            room = room_obj.name if room_obj is not None else None
            for link in assignment.teachers:
                teacher: Teacher | None = link.teacher
                if teacher is None:
                    continue
                already = db.scalar(
                    select(SpecialDayReminderLog).where(
                        SpecialDayReminderLog.rule_id == ov.rule_id,
                        SpecialDayReminderLog.class_unit_id == class_id,
                        SpecialDayReminderLog.period_no == period_no,
                        SpecialDayReminderLog.class_date == today,
                        SpecialDayReminderLog.teacher_id == teacher.id,
                    )
                )
                if already is not None:
                    continue
                result = _try_send(
                    db, client, cfg, teacher, starts_at, now_wall,
                    [cls.name], assignment.subject.name, room,
                )
                if result == "sent":
                    db.add(SpecialDayReminderLog(
                        rule_id=ov.rule_id, class_unit_id=class_id,
                        period_no=period_no, class_date=today, teacher_id=teacher.id,
                    ))
                    db.commit()
                    sent += 1
                elif result == "opted_out":
                    opted_out += 1
                elif result == "skipped":
                    skipped += 1
        # 老师自主调课换好的课:按换课教师提醒(补课节反过来)。
        # 放假那节不提醒;换课教师若本就是该配课教师,主课表已提醒,跳过。
        from app.models.teacher_swap import TeacherSwapReminderLog

        for st in _swaps_today:
            cls = _classes_by_id.get(st.class_unit_id)
            if cls is None:
                continue
            from app.services.holidays import is_holiday_on as _is_holiday_on

            if _is_holiday_on(
                db, tt.semester_id, today, st.period_no, {cls.grade}, {cls.id}
            ):
                continue
            assignment = db.get(_CourseAssignment, st.assignment_id)
            if assignment is None:
                continue
            if st.handler_teacher_id in [at.teacher_id for at in assignment.teachers]:
                continue
            teacher = db.get(Teacher, st.handler_teacher_id)
            if teacher is None:
                continue
            start_time = _period_start_for_class(
                db, cls, weekday, st.period_no, tt.semester_id)
            if start_time is None:
                skipped += 1
                continue
            starts_at = datetime.combine(today, start_time)
            room_obj = assignment.room
            room = room_obj.name if room_obj is not None else None
            already = db.scalar(
                select(TeacherSwapReminderLog).where(
                    TeacherSwapReminderLog.swap_id == st.swap_id,
                    TeacherSwapReminderLog.class_unit_id == cls.id,
                    TeacherSwapReminderLog.period_no == st.period_no,
                    TeacherSwapReminderLog.class_date == today,
                    TeacherSwapReminderLog.teacher_id == teacher.id,
                )
            )
            if already is not None:
                continue
            result = _try_send(
                db, client, cfg, teacher, starts_at, now_wall,
                [cls.name], assignment.subject.name, room,
            )
            if result == "sent":
                db.add(TeacherSwapReminderLog(
                    swap_id=st.swap_id, class_unit_id=cls.id,
                    period_no=st.period_no, class_date=today, teacher_id=teacher.id,
                ))
                db.commit()
                sent += 1
            elif result == "opted_out":
                opted_out += 1
            elif result == "skipped":
                skipped += 1
    return {"sent": sent, "skipped": skipped, "opted_out": opted_out}
