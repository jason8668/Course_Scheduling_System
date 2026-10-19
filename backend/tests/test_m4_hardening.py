"""M4 里程碑复审(Fable 5)修正的回归测试:条件 A / B / C。

A. 「已完成」为读取时推导:销假不得抹除已上过的课(课时照算)、已上过的处置不得再变更。
B. availability 的 swap 补课判定只挡「该笔调课的补课方」,不误伤全校。
C. 推荐引擎的本月代课公平计数排除已销假的幽灵代课。
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.core import clock
from app.models.leave import AffectedPeriod, AffectedStatus
from app.models.user import Role
from app.services.availability import Availability, Interval
from tests.conftest import make_user
from tests.dates import SEM_END, SEM_START, WED, WED2  # 日期一律由执行当日推算,不硬编
from tests.test_substitutions import _find_entry, _World

PW = "password123"
# 假造的「现在」:两个周三都已过(用于验证 is_past_slot 的完整性关口)
AFTER = datetime.combine(
    WED2 + timedelta(days=1), time(23, 0), tzinfo=ZoneInfo("Asia/Taipei")
)


@pytest.fixture
def w(env):
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    sid = client.post("/api/semesters", json={
        "academic_year": 115, "term": 1, "template_key": "junior_high",
        "start_date": SEM_START.isoformat(), "end_date": SEM_END.isoformat(),
    }).json()["id"]
    return _World(client, db, sid)


def _stats(w):
    """查基准周那个月的月结(受影响节次都落在那里)。"""
    return w.client.get(
        f"/api/substitution-stats{w.q}&year={WED.year}&month={WED.month}").json()


# ── 条件 A:已完成推导 ───────────────────────────────────────
def test_cancelling_leave_keeps_already_taught_period(w, monkeypatch):
    """代课上完后才销假:那节不转取消、课时照算。"""
    w.teacher("王师", ["国文"])
    w.teacher("陈师", ["国文"])
    w.place("王师", "国文", "701", 0)
    w.publish()
    leave = w.client.post(f"/api/leaves{w.q}", json={
        "teacher_id": w.teachers["王师"], "leave_type": "sick",
        "start_date": WED.isoformat(), "end_date": WED.isoformat()}).json()
    ap_id = leave["affected_periods"][0]["id"]
    w.assign(ap_id, type="substitute", handler_teacher_id=w.teachers["陈师"])
    assert _stats(w)["summaries"], "指派后应计入"

    # 时间快转到两节课都上完之后才销假
    monkeypatch.setattr(clock, "school_now", lambda: AFTER)
    w.client.post(f"/api/leaves/{leave['id']}/cancel")

    w.db.expire_all()
    ap = w.db.get(AffectedPeriod, ap_id)
    assert ap.status == AffectedStatus.resolved.value, "已上过的课不该被销假转为取消"
    chen = next(s for s in _stats(w)["summaries"] if s["teacher_name"] == "陈师")
    assert chen["billable_count"] == 1, "已上过的代课课时照算"


def test_future_period_still_cancelled_on_leave_cancel(w):
    """对照组:未上过的课,销假照常转取消(真实今天 < WED)。"""
    w.teacher("王师", ["国文"])
    w.teacher("陈师", ["国文"])
    w.place("王师", "国文", "701", 0)
    w.publish()
    leave = w.client.post(f"/api/leaves{w.q}", json={
        "teacher_id": w.teachers["王师"], "leave_type": "sick",
        "start_date": WED.isoformat(), "end_date": WED.isoformat()}).json()
    ap_id = leave["affected_periods"][0]["id"]
    w.assign(ap_id, type="substitute", handler_teacher_id=w.teachers["陈师"])
    w.client.post(f"/api/leaves/{leave['id']}/cancel")
    w.db.expire_all()
    assert w.db.get(AffectedPeriod, ap_id).status == AffectedStatus.cancelled.value


def test_cannot_assign_or_clear_past_period(w, monkeypatch):
    w.teacher("王师", ["国文"])
    w.teacher("陈师", ["国文"])
    w.place("王师", "国文", "701", 0)
    w.publish()
    ap_id = w.leave("王师")[0]["id"]
    w.assign(ap_id, type="substitute", handler_teacher_id=w.teachers["陈师"])  # 现在(未来日)可指派

    monkeypatch.setattr(clock, "school_now", lambda: AFTER)  # 课上过了
    code, body = w.assign(ap_id, type="merge", handler_teacher_id=w.teachers["陈师"])
    assert code == 409 and "已结束" in body["detail"]
    r = w.client.delete(f"/api/affected-periods/{ap_id}/substitution")
    assert r.status_code == 409 and "已结束" in r.json()["detail"]


def test_past_resolved_shows_completed(w, monkeypatch):
    w.teacher("王师", ["国文"])
    w.teacher("陈师", ["国文"])
    w.place("王师", "国文", "701", 0)
    w.publish()
    ap_id = w.leave("王师")[0]["id"]
    w.assign(ap_id, type="substitute", handler_teacher_id=w.teachers["陈师"])

    monkeypatch.setattr(clock, "school_now", lambda: AFTER)
    leaves = w.client.get(f"/api/leaves{w.q}").json()
    ap = next(p for lv in leaves for p in lv["affected_periods"] if p["id"] == ap_id)
    assert ap["status"] == "completed", "已上过的已指派节次显示为已完成"


# ── 条件 B:swap 补课只挡补课方 ─────────────────────────────
def test_swap_makeup_blocks_only_the_makeup_teacher(w):
    """甲乙成立调课后,只有补课方(甲)在补课时段被判已占用,第三人不受影响。"""
    w.teacher("王师", ["国文"])   # 甲:请假、日后补课
    w.teacher("陈师", ["数学"])   # 乙:代课、放掉一节由甲补
    w.teacher("林师", ["体育"])   # 丙:完全无关的第三人
    w.place("王师", "国文", "701", 0)             # 甲 周三第一节(被请假)
    w.place("陈师", "数学", "702", 1)             # 乙 周三第二节(swap 目标,甲于 WED2 补)
    w.publish()
    affected_id = w.leave("王师")[0]["id"]
    entry_id = _find_entry(w, "陈师", period_idx=1)
    code, body = w.assign(
        affected_id, type="swap", handler_teacher_id=w.teachers["陈师"],
        swap_entry_id=entry_id, swap_date=WED2.isoformat())
    assert code == 200, body

    av = Availability(w.db, w.sid)
    makeup_slot = Interval(3, w.wed[1]["period_no"], None, None)  # WED2 周三第二节
    # 甲(王师)承诺在 WED2 第二节补课 → 已占用
    c_wang = av.conflict_for(w.teachers["王师"], WED2, makeup_slot)
    assert c_wang is not None and c_wang.kind == "already_covering"
    # 丙(林师)与这笔调课无关 → 不该被误判占用
    assert av.conflict_for(w.teachers["林师"], WED2, makeup_slot) is None


# ── 条件 D:重新发布课表提醒未来的调代课依旧课表 ───────────
def test_republish_flags_stale_future_affected(w):
    w.teacher("王师", ["国文"])
    w.place("王师", "国文", "701", 0)
    w.publish()
    # 依已发布课表登记一张未来假单 → 受影响节次以此版课表展开
    w.leave("王师")

    # 重新发布另一版课表:回应应提醒有未来的调代课依旧课表安排
    tt2 = w.client.post(f"/api/timetables{w.q}", json={"name": "草稿B"}).json()["id"]
    r = w.client.post(f"/api/timetables/{tt2}/publish?force=true")
    assert r.status_code == 200
    assert r.json()["stale_affected"] >= 1


def test_first_publish_has_no_stale(w):
    w.teacher("王师", ["国文"])
    w.place("王师", "国文", "701", 0)
    r = w.client.post(f"/api/timetables/{w.tt}/publish?force=true")
    assert r.status_code == 200
    assert r.json()["stale_affected"] == 0


# ── 条件 C:公平计数排除幽灵代课 ───────────────────────────
def test_monthly_fair_count_excludes_cancelled(w):
    """林师代的那节被销假后,推荐别节时他的『本月已代』应回到 0。"""
    w.teacher("王师", ["国文"])
    w.teacher("陈师", ["国文"])
    w.teacher("林师", ["国文"])
    w.place("王师", "国文", "701", 0)   # 王师 周三第一节
    w.place("陈师", "国文", "702", 1)   # 陈师 周三第二节(供另一张假单)
    w.publish()

    leave1 = w.client.post(f"/api/leaves{w.q}", json={
        "teacher_id": w.teachers["王师"], "leave_type": "sick",
        "start_date": WED.isoformat(), "end_date": WED.isoformat()}).json()
    w.assign(leave1["affected_periods"][0]["id"],
             type="substitute", handler_teacher_id=w.teachers["林师"])
    w.client.post(f"/api/leaves/{leave1['id']}/cancel")  # 销假 → 那节取消(未来日)

    # 陈师 WED2 第二节请假,替它找代课
    leave2 = w.client.post(f"/api/leaves{w.q}", json={
        "teacher_id": w.teachers["陈师"], "leave_type": "sick",
        "start_date": WED2.isoformat(), "end_date": WED2.isoformat()}).json()
    rec = w.recommend(leave2["affected_periods"][0]["id"])
    lin = next(c for c in rec["candidates"] if c["teacher_name"] == "林师")
    assert lin["sub_periods_this_month"] == 0, "已销假的代课不计入公平计数"
    assert "本月已代 0 节" in lin["reasons"]
