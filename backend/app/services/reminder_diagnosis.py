"""上课提醒诊断(只读,不发消息、不改资料)。

老师说“没收到提醒”时,过去只能翻 worker-ops 日志,失败原因看不见。
诊断按提醒链一步步查,每一步给 ok / warn / fail + 人话结论,管理员在
系统管理页输入老师、日期、节次就能定位到断在哪一环:
  企业应用配置 -> 提醒任务排入 -> 学期在范围内 -> 课表已发布
  -> 那天那节实际有课(实际课表口径,含特殊日/调课/请假/放假)
  -> 老师没关提醒(提前分钟) -> 有手机号 -> 钉钉通讯录能找到人
  -> 该节开始时间与提醒窗口 -> 是否已有发送记录

注意:诊断不重放发送。通讯录查询只读 getbymobile,不写回缓存;
窗口结论按该节的开始时间与提前分钟算,不按“现在”判(查过去的节也成立)。
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.basedata import Teacher
from app.models.semester import Semester
from app.models.special_day import SpecialDayReminderLog
from app.models.teacher_swap import TeacherSwapReminderLog
from app.models.timetable import ClassReminderLog, ScheduleEntry, Timetable, TimetableStatus
from app.services import actual_timetable as _actual
from app.services import settings as app_settings
from app.services.dingtalk_app import DingTalkAppClient
from app.services.period_tables import resolve_period_table, semester_default_table


@dataclass
class Step:
    key: str
    label: str
    status: str  # ok / warn / fail
    detail: str


@dataclass
class Diagnosis:
    teacher_id: int
    teacher_name: str
    date: date
    period_no: int
    steps: list[Step]
    conclusion: str


def _period_start(db: Session, semester_id: int, class_unit_id: int, weekday: int, period_no: int):
    from app.models.basedata import ClassUnit

    cls = db.get(ClassUnit, class_unit_id) if class_unit_id else None
    table = resolve_period_table(db, cls) if cls is not None else None
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


def diagnose(
    db: Session, semester: Semester, teacher: Teacher, on: date, period_no: int,
) -> Diagnosis:
    steps: list[Step] = []
    cfg = app_settings.dingtalk_app_config(db)
    steps.append(Step(
        "app_configured", "企业应用配置",
        "ok" if cfg.configured else "fail",
        "已配置" if cfg.configured else "未配置 appKey/appSecret/agentId,提醒根本不会发",
    ))
    job_scheduled = None
    try:
        from rq.registry import ScheduledJobRegistry

        from app.workers.queue import ops_queue
        from app.workers.scheduler import CLASS_REMINDER_JOB_ID

        job_scheduled = CLASS_REMINDER_JOB_ID in set(
            ScheduledJobRegistry(queue=ops_queue).get_job_ids()
        )
    except Exception:  # noqa: BLE001 - Redis 不可达时只报查不到,不挡诊断
        job_scheduled = None
    steps.append(Step(
        "job_scheduled", "提醒任务排入",
        "ok" if job_scheduled is True else "warn" if job_scheduled is None else "fail",
        "已排入,每 5 分钟扫一次" if job_scheduled is True
        else "排程状态查不到(Redis 不可达)" if job_scheduled is None
        else "未排入:任务没跑,所有提醒都不会发,请看 worker-ops 是否在跑",
    ))
    in_range = True
    if semester.start_date and on < semester.start_date:
        in_range = False
    if semester.end_date and on > semester.end_date:
        in_range = False
    steps.append(Step(
        "semester_range", "学期日期范围",
        "ok" if in_range else "fail",
        "在学期内" if in_range else "该日期不在学期起止日期内,提醒链直接跳过",
    ))
    tt = db.scalar(
        select(Timetable).where(
            Timetable.semester_id == semester.id,
            Timetable.status == TimetableStatus.published.value,
        ).order_by(Timetable.id.desc())
    )
    steps.append(Step(
        "timetable_published", "课表已发布",
        "ok" if tt is not None else "fail",
        f"已发布「{tt.name}」" if tt is not None else "没有已发布课表,提醒只看已发布课表",
    ))

    # 实际课表口径:那天那节这位老师到底有没有课、是什么来源
    actual_slot = None
    if tt is not None:
        days = _actual.compute(db, semester, on, on)
        if days:
            for s in days[0].slots:
                if s.period_no == period_no and teacher.id in s.teacher_ids:
                    actual_slot = s
                    break
    if actual_slot is None:
        # 区分“本来没课”与“有课但被取消/放假/调走”:看该班该节原课表或异动
        steps.append(Step(
            "slot_exists", "该节实际有课",
            "fail",
            "那天那节这位老师没有实际要上的课(本来没排,或被放假/取消/调课换走),"
            "没提醒是正常的;先到课表查询“某天实际课表”看那节的来源",
        ))
    elif actual_slot.origin in ("holiday", "cancelled"):
        steps.append(Step(
            "slot_exists", "该节实际有课",
            "fail",
            f"该节被取消:{actual_slot.note},提醒不发是正常的",
        ))
    elif actual_slot.origin == "pending":
        steps.append(Step(
            "slot_exists", "该节实际有课",
            "warn",
            f"该节实际有课,但{actual_slot.note}:原任请假未指派,提醒按实际授课老师算,原任不收提醒",
        ))
    else:
        steps.append(Step(
            "slot_exists", "该节实际有课",
            "ok",
            f"{actual_slot.class_name}《{actual_slot.subject}》,来源:{actual_slot.origin}"
            + (f",{actual_slot.note}" if actual_slot.note else ""),
        ))

    lead = (
        teacher.reminder_lead_minutes
        if teacher.reminder_lead_minutes is not None
        else cfg.lead_minutes
    )
    steps.append(Step(
        "reminder_enabled", "老师提醒开关与提前分钟",
        "fail" if teacher.reminder_enabled is False else "ok",
        "老师关了提醒,系统不会推" if teacher.reminder_enabled is False
        else f"已开启,提前 {lead} 分钟"
        + ("(老师自设)" if teacher.reminder_lead_minutes is not None else "(学校默认值)"),
    ))
    steps.append(Step(
        "phone", "手机号",
        "ok" if (teacher.phone or "").strip() else "fail",
        teacher.phone if (teacher.phone or "").strip()
        else "教师档案里没有手机号,钉钉按手机号找人,找不到就推不出去",
    ))
    userid = teacher.dingtalk_userid
    userid_source = "已绑定" if userid else ""
    if not userid and cfg.configured and (teacher.phone or "").strip():
        try:
            client = DingTalkAppClient(cfg.app_key, cfg.app_secret, cfg.agent_id)
            found = client.get_userid(teacher.phone)
            if found:
                userid = found
                userid_source = "通讯录里能找到(缓存为空,下次提醒时会自动绑定)"
            else:
                userid_source = "通讯录里找不到这个手机号"
        except Exception as exc:  # noqa: BLE001 - 诊断只报原因,不抛错
            userid_source = f"查通讯录失败:{exc}"
    steps.append(Step(
        "dingtalk_userid", "钉钉通讯录",
        "ok" if userid else "fail",
        userid_source or "未绑定且通讯录里找不到,请核对手机号是否在企业通讯录里",
    ))

    # 开始时间与窗口(按该节算,不按现在判)
    start = None
    if actual_slot is not None:
        start = _period_start(
            db, semester.id, actual_slot.class_unit_id, on.isoweekday(), period_no)
    steps.append(Step(
        "window", "开始时间与提醒窗口",
        "ok" if start is not None else "warn",
        f"该节 {start.strftime('%H:%M')} 开始,提醒窗口为开始前 {lead} 分钟内,任务每 5 分钟扫一次"
        if start is not None else "找不到该节的开始时间(节次表缺该节),提醒无法算窗口,会跳过",
    ))

    # 已发送记录(三张防重复表按老师+日期查,再按节次/班级对)
    sent = False
    if tt is not None:
        entry_ids = {
            e.id for e in db.scalars(
                select(ScheduleEntry).where(
                    ScheduleEntry.timetable_id == tt.id,
                    ScheduleEntry.period_no == period_no,
                )
            ).all()
        }
        if db.scalar(select(ClassReminderLog).where(
            ClassReminderLog.teacher_id == teacher.id,
            ClassReminderLog.class_date == on,
            ClassReminderLog.entry_id.in_(entry_ids),
        )) is not None:
            sent = True
        if not sent and db.scalar(select(SpecialDayReminderLog).where(
            SpecialDayReminderLog.teacher_id == teacher.id,
            SpecialDayReminderLog.class_date == on,
            SpecialDayReminderLog.period_no == period_no,
        )) is not None:
            sent = True
        if not sent and db.scalar(select(TeacherSwapReminderLog).where(
            TeacherSwapReminderLog.teacher_id == teacher.id,
            TeacherSwapReminderLog.class_date == on,
            TeacherSwapReminderLog.period_no == period_no,
        )) is not None:
            sent = True
    steps.append(Step(
        "already_sent", "是否已有发送记录",
        "ok" if sent else "warn",
        ("已有发送记录,同一节同一天不会重发;"
         "若老师说没收到,先看钉钉工作通知里有没有被折叠")
        if sent else ("没有发送记录:上面任一步 fail 都会导致没发;"
                      "若上面全 ok 且窗口已过,请看 worker-ops 日志"),
    ))

    fails = [s for s in steps if s.status == "fail"]
    warns = [s for s in steps if s.status == "warn"]
    if fails:
        conclusion = ("断在:" + "、".join(s.label for s in fails)
                      + "。先修这一步,再等下一个提醒窗口验证。")
    elif warns:
        conclusion = ("没有硬性断点,但有提醒项:" + "、".join(s.label for s in warns)
                      + "。窗口已过仍没收到时,请看 worker-ops 日志。")
    else:
        conclusion = ("链路全通:该节应该已发或会在窗口内发。"
                      "若老师仍说没收到,请核对钉钉工作通知是否被折叠/免打扰。")
    return Diagnosis(
        teacher_id=teacher.id, teacher_name=teacher.name,
        date=on, period_no=period_no, steps=steps, conclusion=conclusion,
    )
