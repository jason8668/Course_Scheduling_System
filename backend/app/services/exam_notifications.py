"""考务通知服务(KW-57~59/61):考试日程、监考提醒、录分截止催录、到期扫。

发送口径:
- 钉钉只发个人工作通知,绝不发群消息(与清单备注一致)。
- 同步直发:不用 notifications 服务的 after_commit 寄件匣,那条路
  commit 后才异步发、调用时拿不到成功/失败,无法记 sent/failed 计数;
  本批直接调 DingTalkAppClient 同步发,失败当场记失败。
- 未配置企业应用、或收件人既无钉钉 userid 又无手机号时,不记失败,
  改记站内通知、状态成功(站内记录本身即送达,与现有通知哲学一致)。
- 教师提醒提前量复用 Teacher.reminder_lead_minutes(教师在「我的」页自设);
  读不到个人设置时默认考前 30 分钟(任务口径,不用学校全局 15 分钟默认值)。
- 手动触发不去重(教务点一次发一次);到期扫同一提醒 24 小时内不重复发,
  以 ExamNotificationLog(成功记录)去重。
- 教师提醒开关 reminder_enabled 本批不作过滤:开关是上课提醒的开关,
  清单没说它管考务通知,手动触发的教务通知不应被它静默吞掉;是否要管,
  待学校确认(见汇报)。
"""

import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings as app_config
from app.models.assignment import (
    AssignmentTeacher,
    CourseAssignment,
    SchedulingUnitMember,
)
from app.models.basedata import ClassUnit, Room, Subject, Teacher
from app.models.exam import Exam, ExamParticipant, ExamSubject
from app.models.exam_invigilation import ExamInvigilation
from app.models.exam_notifications import (
    ExamNotificationLog,
    ExamNotificationSetting,
)
from app.models.exam_scores import ExamMarkingAssignment, ExamScore, ExamScoreSetting
from app.models.user import Role, User
from app.services import settings as app_settings
from app.services.dingtalk_app import DingTalkAppClient

logger = logging.getLogger(__name__)

#: 监考提醒默认提前量(分钟):读不到教师个人设置时用它。
DEFAULT_INVIGILATION_LEAD_MINUTES = 30
#: 到期扫去重窗口。
DEDUP_WINDOW = timedelta(hours=24)
#: 录分截止提醒的两个时间点。
SCORE_DEADLINE_FIRST_HOURS = 24
SCORE_DEADLINE_SECOND_HOURS = 2

TITLES = {
    "考试日程": "考试日程通知",
    "监考提醒": "监考提醒",
    "录分截止": "录分截止提醒",
    "成绩发布": "成绩已可查询",
}



def _now() -> datetime:
    return datetime.now(timezone.utc)


def _tz() -> ZoneInfo:
    return ZoneInfo(app_config.tz)


def _to_wall(value: datetime) -> datetime:
    """把时刻换算成学校时区墙钟(考试日期/时间都是墙钟)。

    SQLite 会把 DateTime(timezone=True) 回读成无时区时间,按 UTC
    视作有时区再换算(与 exam_publish._as_aware 同一口径)。
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(_tz()).replace(tzinfo=None)


def _fmt_date(d) -> str:
    return f"{d.month}月{d.day}日"


def _fmt_time(t: time) -> str:
    return t.strftime("%H:%M")


# ── 钉钉直发(可 mock 的缝) ──────────────────────────────
def send_personal_dingtalk(
    db: Session, *, userid: str | None, mobile: str | None, title: str, text: str,
) -> tuple[bool, str | None]:
    """同步发一则个人钉钉工作通知。回 (是否成功, 失败原因)。

    测试 mock 这一只函数即可,不碰真实钉钉;未配置企业应用回失败,
    由 _deliver 决定是否改走站内(本函数本身不改渠道)。
    """
    cfg = app_settings.dingtalk_app_config(db)
    if not cfg.configured:
        return False, "钉钉企业应用未配置"
    client = DingTalkAppClient(cfg.app_key, cfg.app_secret, cfg.agent_id)
    if not userid and mobile:
        userid = client.get_userid(mobile)
    if not userid:
        return False, "该收件人不在钉钉企业通讯录里"
    client.send_work_notification(userid, title, text)
    return True, None


def _deliver(
    db: Session, *, teacher: Teacher | None = None, mobile: str | None = None,
    title: str, text: str,
) -> tuple[str, bool, str | None]:
    """发一次通知,回 (渠道, 是否成功, 失败原因)。

    未配置企业应用、或收件人无钉钉身份(userid 与手机号都没有)时
    改记站内、算成功;钉钉已配置且有身份但发送失败时记钉钉、失败。
    """
    cfg = app_settings.dingtalk_app_config(db)
    userid = teacher.dingtalk_userid if teacher is not None else None
    phone = mobile or (teacher.phone if teacher is not None else None)
    if not cfg.configured or (not userid and not phone):
        return "站内", True, None
    try:
        ok, err = send_personal_dingtalk(
            db, userid=userid, mobile=phone, title=title, text=text
        )
    except Exception as exc:  # noqa: BLE001 - 单个收件人失败不影响其他人
        logger.warning("考务钉钉发送失败:%s", exc)
        return "钉钉", False, str(exc)
    if ok:
        return "钉钉", True, None
    return "钉钉", False, err or "钉钉发送失败"


def _record(
    db: Session, exam: Exam, notification_type: str, recipient_user_id: int | None,
    recipient_name: str, channel: str, ok: bool, message: str, error: str | None,
    related_type: str | None, related_id: int | None,
) -> ExamNotificationLog:
    log = ExamNotificationLog(
        exam_id=exam.id, notification_type=notification_type,
        recipient_user_id=recipient_user_id, recipient_name=recipient_name,
        channel=channel, status="成功" if ok else "失败",
        message=message, error=(error or "")[:512] if error else None,
        related_type=related_type, related_id=related_id,
        sent_at=_now() if ok else None,
    )
    db.add(log)
    db.flush()
    return log


def _send_one(
    db: Session, exam: Exam, notification_type: str,
    recipient_user_id: int | None, recipient_name: str,
    teacher: Teacher | None, mobile: str | None,
    title: str, text: str, related_type: str | None, related_id: int | None,
) -> bool:
    channel, ok, error = _deliver(db, teacher=teacher, mobile=mobile, title=title, text=text)
    _record(
        db, exam, notification_type, recipient_user_id, recipient_name,
        channel, ok, text, error, related_type, related_id,
    )
    return ok


def _count(results: list[bool]) -> tuple[int, int]:
    sent = sum(1 for ok in results if ok)
    return sent, len(results) - sent


# ── 开关 ────────────────────────────────────────────────
def get_settings(db: Session, exam: Exam) -> ExamNotificationSetting | None:
    return db.scalar(
        select(ExamNotificationSetting).where(
            ExamNotificationSetting.exam_id == exam.id
        )
    )


def settings_out(exam: Exam, row: ExamNotificationSetting | None) -> dict:
    if row is None:
        return {
            "exam_id": exam.id,
            "schedule_notify_enabled": True,
            "invigilation_remind_enabled": True,
            "score_deadline_remind_enabled": True,
        }
    return {
        "exam_id": exam.id,
        "schedule_notify_enabled": row.schedule_notify_enabled,
        "invigilation_remind_enabled": row.invigilation_remind_enabled,
        "score_deadline_remind_enabled": row.score_deadline_remind_enabled,
    }


def _settings_or_default(db: Session, exam: Exam) -> dict:
    return settings_out(exam, get_settings(db, exam))


def upsert_settings(
    db: Session, exam: Exam, schedule_notify_enabled: bool,
    invigilation_remind_enabled: bool, score_deadline_remind_enabled: bool,
) -> ExamNotificationSetting:
    row = get_settings(db, exam)
    if row is None:
        row = ExamNotificationSetting(exam_id=exam.id)
        db.add(row)
    row.schedule_notify_enabled = schedule_notify_enabled
    row.invigilation_remind_enabled = invigilation_remind_enabled
    row.score_deadline_remind_enabled = score_deadline_remind_enabled
    db.flush()
    return row


def _require_enabled(db: Session, exam: Exam, key: str, label: str) -> None:
    if not _settings_or_default(db, exam)[key]:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"本次考试已关闭{label},请先在通知设置里开启"
        )


# ── 共用查询 ────────────────────────────────────────────
def _participants(db: Session, exam: Exam) -> list[ExamParticipant]:
    return list(db.scalars(
        select(ExamParticipant).where(ExamParticipant.exam_id == exam.id)
    ).all())


def _class_map(db: Session, class_ids: set[int]) -> dict[int, ClassUnit]:
    if not class_ids:
        return {}
    rows = db.scalars(select(ClassUnit).where(ClassUnit.id.in_(class_ids))).all()
    return {c.id: c for c in rows}


def _subject_map(db: Session, subject_ids: set[int]) -> dict[int, Subject]:
    if not subject_ids:
        return {}
    rows = db.scalars(select(Subject).where(Subject.id.in_(subject_ids))).all()
    return {s.id: s for s in rows}


def _teaching_map(db: Session, semester_id: int) -> dict[tuple[int, int], set[int]]:
    """(班级 id, 科目 id) -> 任教教师 id 集合。"""
    rows = db.execute(
        select(
            SchedulingUnitMember.class_unit_id,
            CourseAssignment.subject_id,
            AssignmentTeacher.teacher_id,
        )
        .join(
            CourseAssignment,
            CourseAssignment.scheduling_unit_id
            == SchedulingUnitMember.scheduling_unit_id,
        )
        .join(
            AssignmentTeacher,
            AssignmentTeacher.course_assignment_id == CourseAssignment.id,
        )
        .where(CourseAssignment.semester_id == semester_id)
    ).all()
    out: dict[tuple[int, int], set[int]] = {}
    for class_id, subject_id, teacher_id in rows:
        out.setdefault((class_id, subject_id), set()).add(teacher_id)
    return out


def _teacher_map(db: Session, teacher_ids: set[int]) -> dict[int, Teacher]:
    if not teacher_ids:
        return {}
    rows = db.scalars(select(Teacher).where(Teacher.id.in_(teacher_ids))).all()
    return {t.id: t for t in rows}


def _lead_minutes(teacher: Teacher) -> int:
    """监考提醒提前量:教师自设优先,读不到默认 30 分钟。"""
    if teacher.reminder_lead_minutes is not None:
        return teacher.reminder_lead_minutes
    return DEFAULT_INVIGILATION_LEAD_MINUTES


# ── KW-57 考试日程通知 ────────────────────────────────
def _schedule_recipients(db: Session, exam: Exam) -> list[Teacher]:
    """班主任 + 参试班级的任课教师(按教师 id 去重、排序)。"""
    participants = _participants(db, exam)
    class_ids = {p.class_unit_id for p in participants}
    classes = _class_map(db, class_ids)
    teacher_ids: set[int] = set()
    for cls in classes.values():
        if cls.homeroom_teacher_id is not None:
            teacher_ids.add(cls.homeroom_teacher_id)
    teaching = _teaching_map(db, exam.semester_id)
    for (class_id, _subject_id), tids in teaching.items():
        if class_id in class_ids:
            teacher_ids.update(tids)
    teachers = _teacher_map(db, teacher_ids)
    return [teachers[tid] for tid in sorted(teachers)]


def _schedule_text(db: Session, exam: Exam) -> tuple[str, str]:
    rows = db.scalars(
        select(ExamSubject).where(ExamSubject.exam_id == exam.id)
        .order_by(ExamSubject.exam_date, ExamSubject.start_time)
    ).all()
    subjects = _subject_map(db, {r.subject_id for r in rows})
    lines = [
        f"{subjects.get(r.subject_id).name if subjects.get(r.subject_id) else ''}"
        f" {_fmt_date(r.exam_date)} {_fmt_time(r.start_time)}-{_fmt_time(r.end_time)}"
        for r in rows
    ]
    title = f"【{exam.name}】考试日程通知"
    body = f"{exam.name}考试日程如下:\n" + ("\n".join(lines) if lines else "暂无科目安排")
    return title, f"### {title}\n\n{body}"


def notify_schedule(db: Session, exam: Exam) -> tuple[int, int]:
    _require_enabled(db, exam, "schedule_notify_enabled", "考试日程通知")
    title, text = _schedule_text(db, exam)
    results = [
        _send_one(
            db, exam, "考试日程", t.user_id, t.name, t, None,
            title, text, "exam", exam.id,
        )
        for t in _schedule_recipients(db, exam)
    ]
    db.flush()
    return _count(results)


# ── KW-58 监考提醒 ────────────────────────────────────
def _invigilation_rows(db: Session, exam: Exam) -> list[ExamInvigilation]:
    return list(db.scalars(
        select(ExamInvigilation).where(ExamInvigilation.exam_id == exam.id)
        .order_by(ExamInvigilation.id)
    ).all())


def _invigilation_line(
    db: Session, exam: Exam, row: ExamInvigilation,
    subjects: dict[int, Subject], rooms: dict[int, Room],
) -> str:
    subject = db.scalar(
        select(ExamSubject).where(
            ExamSubject.exam_id == exam.id,
            ExamSubject.subject_id == row.subject_id,
        )
    )
    subject_name = subjects.get(row.subject_id).name if subjects.get(row.subject_id) else ""
    room_name = rooms.get(row.room_id).name if rooms.get(row.room_id) else ""
    if subject is None:
        return f"{subject_name} 考场:{room_name}" if room_name else subject_name
    return (
        f"{subject_name} {_fmt_date(subject.exam_date)}"
        f" {_fmt_time(subject.start_time)}-{_fmt_time(subject.end_time)}"
        f" 考场:{room_name}"
    )


def _invigilation_text(
    db: Session, exam: Exam, rows: list[ExamInvigilation], when: str,
) -> str:
    subjects = _subject_map(db, {r.subject_id for r in rows})
    room_ids = {r.room_id for r in rows}
    rooms = (
        {r.id: r for r in db.scalars(select(Room).where(Room.id.in_(room_ids))).all()}
        if room_ids else {}
    )
    lines = [_invigilation_line(db, exam, r, subjects, rooms) for r in rows]
    return (
        f"### 监考提醒\n\n{exam.name}{when},您的监考安排如下:\n"
        + "\n".join(lines)
        + "\n请按时到场监考。"
    )


def notify_invigilation(db: Session, exam: Exam) -> tuple[int, int]:
    _require_enabled(db, exam, "invigilation_remind_enabled", "监考提醒")
    rows = _invigilation_rows(db, exam)
    by_teacher: dict[int, list[ExamInvigilation]] = {}
    for row in rows:
        by_teacher.setdefault(row.teacher_id, []).append(row)
    teachers = _teacher_map(db, set(by_teacher))
    results = []
    for teacher_id in sorted(by_teacher):
        teacher = teachers.get(teacher_id)
        if teacher is None:
            continue
        text = _invigilation_text(db, exam, by_teacher[teacher_id], "")
        results.append(_send_one(
            db, exam, "监考提醒", teacher.user_id, teacher.name, teacher, None,
            TITLES["监考提醒"], text, "invigilation", teacher.id,
        ))
    db.flush()
    return _count(results)


# ── KW-59 录分截止提醒 ────────────────────────────────
def _score_deadline(db: Session, exam: Exam) -> datetime | None:
    row = db.scalar(
        select(ExamScoreSetting).where(ExamScoreSetting.exam_id == exam.id)
    )
    return row.score_deadline if row is not None else None


def _incomplete_score_teachers(
    db: Session, exam: Exam,
) -> dict[int, dict]:
    """未录完/未提交的教师 -> {"teacher": Teacher, "items": {(科目名, 班级名)}}。

    未录完 = 该科目该学生没有成绩行,或成绩行 submitted 为 False。
    归属:有阅卷分工时归分工教师,否则归任教该班级该科目的教师;
    两处都找不到时无人可催,跳过。
    """
    subjects = db.scalars(
        select(ExamSubject).where(ExamSubject.exam_id == exam.id)
    ).all()
    if not subjects:
        return {}
    subject_names = _subject_map(db, {s.subject_id for s in subjects})
    participants = _participants(db, exam)
    classes = _class_map(db, {p.class_unit_id for p in participants})
    scores = {
        (r.subject_id, r.student_id): r
        for r in db.scalars(
            select(ExamScore).where(ExamScore.exam_id == exam.id)
        ).all()
    }
    marking: dict[int, set[int]] = {}
    for row in db.scalars(
        select(ExamMarkingAssignment).where(
            ExamMarkingAssignment.exam_id == exam.id
        )
    ).all():
        marking.setdefault(row.subject_id, set()).add(row.teacher_id)
    teaching = _teaching_map(db, exam.semester_id)
    out: dict[int, dict] = {}
    teacher_ids: set[int] = set()
    pending: list[tuple[int, str, str]] = []
    for subj in subjects:
        subject_name = (
            subject_names.get(subj.subject_id).name
            if subject_names.get(subj.subject_id) else ""
        )
        for p in participants:
            row = scores.get((subj.subject_id, p.student_id))
            if row is not None and row.submitted:
                continue
            class_name = classes.get(p.class_unit_id).name if classes.get(p.class_unit_id) else ""
            tids = marking.get(subj.subject_id) or teaching.get(
                (p.class_unit_id, subj.subject_id), set()
            )
            for tid in tids:
                pending.append((tid, subject_name, class_name))
                teacher_ids.add(tid)
    teachers = _teacher_map(db, teacher_ids)
    for tid, subject_name, class_name in pending:
        teacher = teachers.get(tid)
        if teacher is None:
            continue
        entry = out.setdefault(tid, {"teacher": teacher, "items": set()})
        entry["items"].add((subject_name, class_name))
    return out


def _score_deadline_text(db: Session, exam: Exam, items: set, deadline: datetime) -> str:
    deadline_wall = _to_wall(deadline)
    lines = sorted(f"{s}({c})" if c else s for s, c in items)
    return (
        "### 录分截止提醒\n\n"
        f"{exam.name}录分截止时间为"
        f"{deadline_wall.strftime('%Y-%m-%d %H:%M')},"
        "以下科目/班级还有未提交的成绩,请尽快录入并提交:\n"
        + "\n".join(lines)
    )


def notify_score_deadline(db: Session, exam: Exam) -> tuple[int, int]:
    _require_enabled(db, exam, "score_deadline_remind_enabled", "录分截止提醒")
    deadline = _score_deadline(db, exam)
    if deadline is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "本次考试未设置录分截止时间,无法发送催录提醒"
        )
    incomplete = _incomplete_score_teachers(db, exam)
    results = []
    for teacher_id in sorted(incomplete):
        entry = incomplete[teacher_id]
        teacher = entry["teacher"]
        text = _score_deadline_text(db, exam, entry["items"], deadline)
        results.append(_send_one(
            db, exam, "录分截止", teacher.user_id, teacher.name, teacher, None,
            TITLES["录分截止"], text, "score_deadline", teacher.id,
        ))
    db.flush()
    return _count(results)


# ── 到期扫(供定时任务调用) ──────────────────────────
def _recent_success(
    db: Session, exam_id: int, notification_type: str, related_type: str,
    related_id: int | None, recipient_user_id: int | None,
    recipient_name: str, since: datetime,
) -> bool:
    stmt = select(ExamNotificationLog).where(
        ExamNotificationLog.exam_id == exam_id,
        ExamNotificationLog.notification_type == notification_type,
        ExamNotificationLog.related_type == related_type,
        ExamNotificationLog.related_id == related_id,
        ExamNotificationLog.status == "成功",
        ExamNotificationLog.created_at >= since,
    )
    if recipient_user_id is not None:
        stmt = stmt.where(
            ExamNotificationLog.recipient_user_id == recipient_user_id
        )
    else:
        stmt = stmt.where(ExamNotificationLog.recipient_name == recipient_name)
    return db.scalar(stmt) is not None


def remind_due(db: Session, *, now: datetime | None = None) -> tuple[int, int]:
    """到期扫:考前一天与当天开考前到点的监考提醒、截止前 24 小时与
    2 小时到点的录分催提醒。同一提醒 24 小时内不重复发。"""
    now_aware = now if now is not None else _now()
    if now_aware.tzinfo is None:
        now_aware = now_aware.replace(tzinfo=timezone.utc)
    now_wall = _to_wall(now_aware)
    since = now_aware - DEDUP_WINDOW
    results: list[bool] = []
    exams = db.scalars(select(Exam)).all()
    for exam in exams:
        cfg = _settings_or_default(db, exam)
        if cfg["invigilation_remind_enabled"]:
            results.extend(_remind_invigilation_due(db, exam, now_wall, since))
        if cfg["score_deadline_remind_enabled"]:
            results.extend(_remind_score_deadline_due(db, exam, now_wall, since))
    db.flush()
    return _count(results)


def _remind_invigilation_due(
    db: Session, exam: Exam, now_wall: datetime, since: datetime,
) -> list[bool]:
    rows = _invigilation_rows(db, exam)
    if not rows:
        return []
    teachers = _teacher_map(db, {r.teacher_id for r in rows})
    results: list[bool] = []
    for row in rows:
        teacher = teachers.get(row.teacher_id)
        if teacher is None:
            continue
        subject = db.scalar(
            select(ExamSubject).where(
                ExamSubject.exam_id == exam.id,
                ExamSubject.subject_id == row.subject_id,
            )
        )
        if subject is None:
            continue
        start = datetime.combine(subject.exam_date, subject.start_time)
        kind: str | None = None
        when = ""
        if now_wall.date() == subject.exam_date - timedelta(days=1):
            kind, when = "invigilation_day_before", "明天"
        elif now_wall.date() == subject.exam_date:
            lead = _lead_minutes(teacher)
            delta = start - now_wall
            if timedelta(0) <= delta <= timedelta(minutes=lead):
                kind, when = "invigilation_day_of", "今天"
        if kind is None:
            continue
        if _recent_success(
            db, exam.id, "监考提醒", kind, row.id,
            teacher.user_id, teacher.name, since,
        ):
            continue
        text = _invigilation_text(db, exam, [row], when)
        results.append(_send_one(
            db, exam, "监考提醒", teacher.user_id, teacher.name, teacher, None,
            TITLES["监考提醒"], text, kind, row.id,
        ))
    return results


def _remind_score_deadline_due(
    db: Session, exam: Exam, now_wall: datetime, since: datetime,
) -> list[bool]:
    deadline = _score_deadline(db, exam)
    if deadline is None:
        return []
    deadline_wall = _to_wall(deadline)
    if deadline_wall - timedelta(hours=SCORE_DEADLINE_FIRST_HOURS) <= now_wall < deadline_wall - timedelta(hours=SCORE_DEADLINE_SECOND_HOURS):
        kind = "score_deadline_24h"
    elif deadline_wall - timedelta(hours=SCORE_DEADLINE_SECOND_HOURS) <= now_wall < deadline_wall:
        kind = "score_deadline_2h"
    else:
        return []
    incomplete = _incomplete_score_teachers(db, exam)
    results: list[bool] = []
    for teacher_id in sorted(incomplete):
        entry = incomplete[teacher_id]
        teacher = entry["teacher"]
        if _recent_success(
            db, exam.id, "录分截止", kind, teacher.id,
            teacher.user_id, teacher.name, since,
        ):
            continue
        text = _score_deadline_text(db, exam, entry["items"], deadline)
        results.append(_send_one(
            db, exam, "录分截止", teacher.user_id, teacher.name, teacher, None,
            TITLES["录分截止"], text, kind, teacher.id,
        ))
    return results


# ── KW-61 记录查询与重发 ────────────────────────────
def list_logs(
    db: Session, user: User, exam: Exam,
    type_filter: str | None, status_filter: str | None, q: str | None,
) -> tuple[list[ExamNotificationLog], int]:
    stmt = select(ExamNotificationLog).where(
        ExamNotificationLog.exam_id == exam.id
    )
    if type_filter is not None:
        if type_filter not in ("考试日程", "监考提醒", "录分截止", "成绩发布"):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "通知类型只能是考试日程、监考提醒、录分截止或成绩发布",
            )
        stmt = stmt.where(ExamNotificationLog.notification_type == type_filter)
    if status_filter is not None:
        if status_filter not in ("成功", "失败", "待发送"):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "通知状态只能是成功、失败或待发送"
            )
        stmt = stmt.where(ExamNotificationLog.status == status_filter)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            (ExamNotificationLog.recipient_name.ilike(like))
            | (ExamNotificationLog.message.ilike(like))
        )
    rows = list(db.scalars(stmt.order_by(ExamNotificationLog.id.desc())).all())
    if Role.admin.value not in user.role_names and Role.director.value not in user.role_names:
        rows = [r for r in rows if r.recipient_user_id == user.id]
    return rows, len(rows)


def log_out(row: ExamNotificationLog) -> dict:
    return {
        "id": row.id,
        "exam_id": row.exam_id,
        "notification_type": row.notification_type,
        "recipient_name": row.recipient_name,
        "channel": row.channel,
        "status": row.status,
        "message": row.message,
        "error": row.error,
        "sent_at": row.sent_at,
        "created_at": row.created_at,
    }


def resend_log(db: Session, exam: Exam, log_id: int) -> ExamNotificationLog:
    """失败重发:只允许重发失败记录,成功记录 409。原行就地更新状态,
    不另起一行,健康页只看最新状态。"""
    log = db.get(ExamNotificationLog, log_id)
    if log is None or log.exam_id != exam.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到通知记录")
    if log.status != "失败":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "只有发送失败的通知可以重发"
        )
    title = TITLES.get(log.notification_type, log.notification_type)
    teacher: Teacher | None = None
    mobile: str | None = None
    if log.recipient_user_id is not None:
        user = db.get(User, log.recipient_user_id)
        if user is not None:
            teacher = db.scalar(
                select(Teacher).where(
                    Teacher.user_id == user.id,
                    Teacher.semester_id == exam.semester_id,
                ).order_by(Teacher.id)
            )
    if teacher is None and log.recipient_user_id is None:
        teacher = db.scalar(
            select(Teacher).where(
                Teacher.semester_id == exam.semester_id,
                Teacher.name == log.recipient_name,
            ).order_by(Teacher.id)
        )
    channel, ok, error = _deliver(
        db, teacher=teacher, mobile=mobile, title=title, text=log.message
    )
    log.channel = channel
    log.status = "成功" if ok else "失败"
    log.error = (error or "")[:512] if error else None
    if ok:
        log.sent_at = _now()
    db.flush()
    return log
