"""月度课时确认:每月最后一天 17:00 的通知 + 个人钉钉 + 排程时刻。

不连真实钉钉:monkeypatch monthly_hours 与 notifications 两个模块的
DingTalkAppClient(任务内解析用前者,通知通道寄出用后者)。
"""

from datetime import date, datetime

import pytest

from app.models.basedata import Teacher
from app.models.notification import Notification
from app.services import monthly_hours as mh_service
from app.services import settings as app_settings
from app.services import teaching_hours as hours_service
from app.services.substitution_log import school_today
from tests.test_teaching_hours import build_world


def _fake_client_factory(sent, lookups):
    class FakeClient:
        def __init__(self, app_key, app_secret, agent_id):
            pass

        def get_userid(self, mobile):
            lookups.append(mobile)
            return {"13800000000": "U-chen"}.get(mobile)

        def send_work_notification(self, userid, title, text):
            sent.append((userid, title, text))

    return FakeClient


@pytest.fixture
def world(db, monkeypatch):
    w = build_world(db)
    sent: list = []
    lookups: list = []
    fake = _fake_client_factory(sent, lookups)
    monkeypatch.setattr("app.services.monthly_hours.DingTalkAppClient", fake)
    monkeypatch.setattr("app.services.notifications.DingTalkAppClient", fake)
    app_settings.save_dingtalk_app(
        db, app_key="KEY", app_secret="SEC", agent_id="123", lead_minutes=15)
    db.commit()
    # 王师已有 userid;陈师只有手机号(任务内解析);林师什么都没有
    wang = db.get(Teacher, w["teachers"]["王师"].id)
    wang.dingtalk_userid = "U-wang"
    chen = db.get(Teacher, w["teachers"]["陈师"].id)
    chen.phone = "13800000000"
    db.commit()
    return {"w": w, "db": db, "sent": sent, "lookups": lookups}


def _totals(rows, name):
    r = next((x for x in rows if x.teacher_name == name), None)
    return (r.total, r.substitute_total) if r else (0, 0)


def test_run_sends_notification_and_personal_dingtalk(world):
    w, db = world["w"], world["db"]
    today = school_today()
    sem = w["sem"]
    month_rows, _, _ = hours_service.compute(db, sem, today.replace(day=1), today)
    sem_rows, _, _ = hours_service.compute(db, sem, sem.start_date, sem.end_date or today)

    result = mh_service.run_monthly_hours(db, today=today)
    assert result["sent"] == 3
    assert result["skipped_no_dingtalk"] == ["林师"]
    assert result["already_sent"] == 0 and result["failed"] == []

    # 个人钉钉:王师走缓存 userid,陈师走手机号解析;林师没有联系方式不发
    assert world["lookups"] == ["13800000000"]
    assert {u for u, _t, _x in world["sent"]} == {"U-wang", "U-chen"}
    # 解析到的 userid 已回填到教师档案
    assert db.get(Teacher, w["teachers"]["陈师"].id).dingtalk_userid == "U-chen"

    # 系统通知:每人一条(含无钉钉的林师——铃铛里能确认),正文写清本月与本学期课时
    notes = db.query(Notification).filter_by(type="monthly_hours").all()
    assert len(notes) == 3
    assert {n.title for n in notes} == {f"{today.month}月课时确认"}
    assert {n.teacher_id for n in notes} == {t.id for t in w["teachers"].values()}
    wang_note = next(n for n in notes if n.teacher_id == w["teachers"]["王师"].id)
    m_total, m_sub = _totals(month_rows, "王师")
    s_total, s_sub = _totals(sem_rows, "王师")
    assert f"教学课时 {m_total} 节(其中代课 {m_sub} 节)" in wang_note.body
    assert f"累计教学课时 {s_total} 节(其中代课 {s_sub} 节)" in wang_note.body
    assert "有异议请联系教务" in wang_note.body
    assert "确认收到" in wang_note.body


def test_run_is_idempotent(world):
    db = world["db"]
    today = school_today()
    first = mh_service.run_monthly_hours(db, today=today)
    assert first["sent"] == 3
    second = mh_service.run_monthly_hours(db, today=today)
    assert second["sent"] == 0 and second["already_sent"] == 3
    assert len(world["sent"]) == 2  # 个人钉钉也没有重发


def test_run_without_app_config_still_creates_notifications(db, monkeypatch):
    """未配企业应用:系统通知照常建(铃铛里能确认),个人钉钉不发。"""
    build_world(db)
    sent: list = []
    monkeypatch.setattr(
        "app.services.notifications.DingTalkAppClient", _fake_client_factory(sent, []))
    result = mh_service.run_monthly_hours(db, today=school_today())
    assert result["sent"] == 3
    assert result["dingtalk_configured"] is False
    assert sent == []


def test_no_semester_returns_reason(world):
    db = world["db"]
    result = mh_service.run_monthly_hours(db, today=date(2030, 1, 31))
    assert result["reason"] == "no_semester" and result["sent"] == 0


def test_next_monthly_hours_time(monkeypatch):
    from app.workers import scheduler

    def _at(year, month, day, hour):
        monkeypatch.setattr(
            "app.workers.scheduler.clock.school_now",
            lambda: datetime(year, month, day, hour, 0))
        return scheduler._next_monthly_hours_time()

    assert _at(2026, 11, 6, 10) == datetime(2026, 11, 30, 17, 0)
    assert _at(2026, 11, 30, 16) == datetime(2026, 11, 30, 17, 0)
    assert _at(2026, 11, 30, 17) == datetime(2026, 12, 31, 17, 0)
    assert _at(2026, 11, 30, 18) == datetime(2026, 12, 31, 17, 0)
    assert _at(2027, 2, 10, 9) == datetime(2027, 2, 28, 17, 0)
    assert _at(2026, 12, 31, 16) == datetime(2026, 12, 31, 17, 0)
