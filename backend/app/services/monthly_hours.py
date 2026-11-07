"""月度课时确认:每月最后一天 17:00 给每位任课老师发一条系统通知 + 个人钉钉。

通知本身就是确认载体:老师在铃铛或统计中心「通知确认」点「确认收到」,
acknowledged_at 落盘,主任在统计中心看板看到确认状态。工作通知是单向的,
不设回复确认机制,消息里只写「请核对,有异议请联系教务」并指引他进系统确认。

任课老师 = 本学期累计教学课时 > 0 的老师(含本月 0 节但学期有课的)。
无钉钉 userid 的老师:系统通知照常建(铃铛里能确认),个人钉钉跳过并记入
回传的 skipped_no_dingtalk,供管理员查看。单个老师失败(算课时/写通知/
commit 出错)只记日志跳过,不拖垮整批。

防重复:同一学期、同一老师、同一标题(月份)的确认通知只建一条——任务
重跑、worker 重复执行都不会发两次(标题内含月份,同学期内月份不重复,
故不用 created_at 比日期,SQLite 与 Postgres 行为一致)。
"""

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.basedata import Teacher
from app.models.notification import Notification, NotificationType
from app.models.semester import Semester
from app.services import notifications as notif_service
from app.services import settings as app_settings
from app.services import teaching_hours as hours_service
from app.services.dingtalk_app import DingTalkAppClient
from app.services.substitution_log import school_today

logger = logging.getLogger(__name__)


def _semesters_overlapping_month(db: Session, month_start: date, today: date) -> list[Semester]:
    """本月有课的学期:学期区间与本月重叠(学期月中结束的,最后一个月也要发)。"""
    return list(db.scalars(
        select(Semester).where(
            Semester.start_date.isnot(None),
            Semester.end_date.isnot(None),
            Semester.start_date <= today,
            Semester.end_date >= month_start,
        )
    ).all())


def _already_sent(db: Session, semester_id: int, teacher_id: int, title: str) -> bool:
    return db.scalar(
        select(Notification.id).where(
            Notification.semester_id == semester_id,
            Notification.teacher_id == teacher_id,
            Notification.type == NotificationType.monthly_hours.value,
            Notification.title == title,
        )
    ) is not None


def run_monthly_hours(
    db: Session,
    *,
    today: date | None = None,
    client: DingTalkAppClient | None = None,
) -> dict:
    """跑一次月度课时确认。回传计数与跳过/失败名单(管理员在 worker 日志里看)。"""
    today = today or school_today()
    month_start = today.replace(day=1)
    sems = _semesters_overlapping_month(db, month_start, today)
    if not sems:
        return {
            "sent": 0, "skipped_no_dingtalk": [], "already_sent": 0, "failed": [],
            "reason": "no_semester",
        }
    app_cfg = app_settings.dingtalk_app_config(db)
    if client is None and app_cfg.configured:
        client = DingTalkAppClient(app_cfg.app_key, app_cfg.app_secret, app_cfg.agent_id)

    sent = already = 0
    skipped: list[str] = []
    failed: list[str] = []
    for sem in sems:
        sem_rows, _, _ = hours_service.compute(db, sem, sem.start_date, sem.end_date or today)
        month_rows, _, _ = hours_service.compute(db, sem, month_start, today)
        month_by_teacher = {r.teacher_id: r for r in month_rows}
        for row in sem_rows:
            if row.total <= 0:
                continue
            teacher = db.get(Teacher, row.teacher_id)
            if teacher is None:
                continue
            m = month_by_teacher.get(row.teacher_id)
            m_total = m.total if m else 0
            m_sub = m.substitute_total if m else 0
            title = f"{today.month}月课时确认"
            if _already_sent(db, sem.id, teacher.id, title):
                already += 1
                continue
            # 解析钉钉 userid(有手机号且未缓存时查一次,查到即回填,下次不再查)。
            # 未配企业应用时 client 为 None,不解析也不记跳过(全局原因,见
            # dingtalk_configured);系统通知照常建,老师仍能在铃铛里确认。
            if client is not None:
                has_dingtalk = bool(teacher.dingtalk_userid)
                if not has_dingtalk and teacher.phone:
                    userid = client.get_userid(teacher.phone)
                    if userid:
                        teacher.dingtalk_userid = userid
                        has_dingtalk = True
                if not has_dingtalk:
                    skipped.append(teacher.name)
            body = (
                f"{teacher.name}老师:{sem.label}{today.month}月教学课时 {m_total} 节"
                f"(其中代课 {m_sub} 节);本学期累计教学课时 {row.total} 节"
                f"(其中代课 {row.substitute_total} 节)。"
                "请核对,有异议请联系教务。请在系统里确认:"
                "打开铃铛或统计中心「通知确认」,点「确认收到」。"
            )
            try:
                # notify() 写系统通知;个人钉钉由通知通道在 commit 后同条推出去。
                notif_service.notify(
                    db, semester_id=sem.id, teacher_id=teacher.id,
                    type=NotificationType.monthly_hours, title=title, body=body,
                )
                db.commit()
                sent += 1
            except Exception as exc:  # noqa: BLE001 - 单个老师失败不拖垮整批
                db.rollback()
                logger.warning("月度课时确认失败(%s):%s", teacher.name, exc)
                failed.append(teacher.name)
    result = {
        "sent": sent, "skipped_no_dingtalk": skipped,
        "already_sent": already, "failed": failed,
        "dingtalk_configured": app_cfg.configured,
    }
    if skipped:
        logger.warning(
            "月度课时确认:以下老师无钉钉 userid,个人钉钉未发(系统通知已建):%s", skipped)
    return result
