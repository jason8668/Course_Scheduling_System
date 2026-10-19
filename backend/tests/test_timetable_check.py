"""课表检查(v1.2.18,用户回报 #40、#41)。

手动排入每一步都有检查,所以这里的违规一律是「排好之后,规则或资料又改了」造成的:
事后设不可排时段、改配课的教师、调低每日上限、改少每周节数。
"""

import pytest

from app.models.timetable import ScheduleEntry, Timetable
from app.services import timetable_check
from app.services.solver_data import load_problem
from app.solver.model_builder import SolveOptions, solve
from app.solver.problem import SolverConfig
from tests.fixtures import build_elementary_small, build_junior_high_mid, build_vocational_high
from tests.test_publish import env3  # noqa: F401  (env3 是 fixture)
from tests.test_timetables import _assign, _class, _place, _subject, _teacher


# ── 不误报:自动排课排出来的课表,检查结果必须是零 ──────────────
@pytest.mark.parametrize("key", ["elementary_small", "junior_high_mid", "vocational_high"])
def test_auto_scheduled_fixtures_have_no_issues(key, db):
    """升级后各校按「发布」不该突然跳出一堆警告。

    三套范例学校(小学、初中、技高:含连堂、跑班群组、实习工场、协同教学)自动排课后
    写进课表,检查结果必须是空的——检查器与排课引擎对「合规」的定义要一致。
    """
    build = {
        "elementary_small": build_elementary_small,
        "junior_high_mid": build_junior_high_mid,
        "vocational_high": build_vocational_high,
    }[key]
    fx = build(db)
    result = solve(
        load_problem(db, fx.semester_id),
        SolveOptions(max_seconds=120.0, workers=4, random_seed=1),
        config=SolverConfig.hard_only(),
    )
    assert result.solved
    tt = Timetable(semester_id=fx.semester_id, name="自排结果")
    db.add(tt)
    db.flush()
    db.add_all(
        ScheduleEntry(
            timetable_id=tt.id, course_assignment_id=e.assignment_id, weekday=e.weekday,
            period_no=e.period_no, span=e.span, room_id=e.room_id,
        )
        for e in result.entries
    )
    db.flush()

    issues = timetable_check.check(db, tt)
    assert issues == [], [i.message for i in issues[:5]]


def _course(client, sid, cname, sname, tname, periods=1):
    c = _class(client, sid, 3, cname)
    s = _subject(client, sid, sname)
    t = _teacher(client, sid, tname)
    a = _assign(client, sid, class_id=c["id"], subject_id=s["id"],
                teacher_ids=[t["id"]], periods=periods)
    return a, c, s, t


def _check(client, tid):
    r = client.get(f"/api/timetables/{tid}/check")
    assert r.status_code == 200, r.text
    return r.json()


def _unavailable(client, teacher_id, *cells, extra=()):
    rules = [{"weekday": w, "period_no": p, "rule_type": "unavailable"} for w, p in cells]
    rules += list(extra)
    r = client.put(f"/api/teachers/{teacher_id}/time-rules", json=rules)
    assert r.status_code == 200, r.text


# ── 检查课表 ──────────────────────────
def test_clean_complete_timetable_passes_and_publishes(env3):  # noqa: F811
    client, sid, tid, _ = env3
    a, *_ = _course(client, sid, "301", "国文", "王师")
    assert _place(client, tid, a["id"], 1, 1).status_code == 201

    r = _check(client, tid)
    assert r["ok"] is True and r["issues"] == [] and r["completeness"]["complete"] is True
    assert client.post(f"/api/timetables/{tid}/publish").status_code == 200


def test_incomplete_timetable_is_not_reported_as_a_violation(env3):  # noqa: F811
    """还没排完是完整性检查的事,不能又在违规清单里讲一次。"""
    client, sid, tid, _ = env3
    a, *_ = _course(client, sid, "301", "国文", "王师", periods=3)
    assert _place(client, tid, a["id"], 1, 1).status_code == 201

    r = _check(client, tid)
    assert r["ok"] is False
    assert r["issues"] == []
    assert r["completeness"]["remaining"] == 2


def test_unavailable_rule_added_after_placement_is_reported(env3):  # noqa: F811
    """#41:课排好之后才把那一节设成不可排。"""
    client, sid, tid, _ = env3
    a, _c, _s, t = _course(client, sid, "301", "国文", "王师")
    assert _place(client, tid, a["id"], 3, 2).status_code == 201
    _unavailable(client, t["id"], (3, 2))

    r = _check(client, tid)
    assert r["ok"] is False
    assert [i["code"] for i in r["issues"]] == ["H4"]
    assert r["issues"][0]["label"] == "教师不可排时段"
    assert r["issues"][0]["message"] == "教师王师 周三第二节 为不可排时段,却排了「301 国文」"


def test_teacher_clash_after_reassigning_teacher_names_both_classes(env3):  # noqa: F811
    """配课改了老师(不检查课表)→ 同一位老师同一节两堂;讯息要看得出是哪两班。"""
    client, sid, tid, _ = env3
    a1, c1, s1, t1 = _course(client, sid, "301", "国文", "王师")
    a2, c2, s2, _t2 = _course(client, sid, "302", "数学", "李师")
    assert _place(client, tid, a1["id"], 1, 1).status_code == 201
    assert _place(client, tid, a2["id"], 1, 1).status_code == 201
    r = client.patch(f"/api/assignments/{a2['id']}", json={
        "class_id": c2["id"], "subject_id": s2["id"], "periods_per_week": 1,
        "teachers": [{"teacher_id": t1["id"], "is_lead": True}], "block_rules": []})
    assert r.status_code == 200, r.text

    issues = _check(client, tid)["issues"]
    assert [i["code"] for i in issues] == ["H2"]
    msg = issues[0]["message"]
    assert "王师" in msg and "周一第一节" in msg
    assert "301 国文" in msg and "302 数学" in msg


def test_daily_cap_lowered_after_placement_is_reported(env3):  # noqa: F811
    client, sid, tid, _ = env3
    a, *_ = _course(client, sid, "301", "国文", "王师", periods=2)
    assert _place(client, tid, a["id"], 1, 1).status_code == 201
    assert _place(client, tid, a["id"], 1, 2).status_code == 201
    assert _check(client, tid)["ok"] is True

    cfg = client.get(f"/api/solver/config?semester_id={sid}").json()
    cfg["daily_subject_cap"] = 1
    assert client.put(f"/api/solver/config?semester_id={sid}", json=cfg).status_code == 200

    issues = _check(client, tid)["issues"]
    assert [i["code"] for i in issues] == ["H10"]
    assert "301" in issues[0]["message"] and "国文" in issues[0]["message"]
    assert "每日上限 1 节" in issues[0]["message"]


def test_more_periods_placed_than_the_assignment_now_allows(env3):  # noqa: F811
    """配课的每周节数事后改少 → 课表上多出来的节数要讲,而且讲人话。"""
    client, sid, tid, _ = env3
    a, c, s, t = _course(client, sid, "301", "国文", "王师", periods=2)
    assert _place(client, tid, a["id"], 1, 1).status_code == 201
    assert _place(client, tid, a["id"], 2, 1).status_code == 201
    r = client.patch(f"/api/assignments/{a['id']}", json={
        "class_id": c["id"], "subject_id": s["id"], "periods_per_week": 1,
        "teachers": [{"teacher_id": t["id"], "is_lead": True}], "block_rules": []})
    assert r.status_code == 200, r.text

    issues = _check(client, tid)["issues"]
    assert [i["code"] for i in issues] == ["H8"]
    assert issues[0]["message"] == "301「国文」排了 2 节,超过配课的每周 1 节"


def test_room_type_without_a_room_is_not_a_violation(env3):  # noqa: F811
    """手动排课不会替「需要某类型场地」的课挑教室——那是还没指定,不是冲突。"""
    client, sid, tid, _ = env3
    c = _class(client, sid, 3, "301")
    s = _subject(client, sid, "理化")
    t = _teacher(client, sid, "王师")
    r = client.post(f"/api/assignments?semester_id={sid}", json={
        "class_id": c["id"], "subject_id": s["id"], "periods_per_week": 1,
        "teachers": [{"teacher_id": t["id"], "is_lead": True}], "block_rules": [],
        "required_room_type": "special"})
    assert r.status_code == 201, r.text
    assert _place(client, tid, r.json()["id"], 1, 1).status_code == 201

    assert _check(client, tid)["ok"] is True


# ── 发布 ──────────────────────────────
def test_publish_blocked_by_violations_then_forced(env3):  # noqa: F811
    """#40:课务排满但有冲突 → 发布要先列出来,确认后才发布。"""
    client, sid, tid, _ = env3
    a, _c, _s, t = _course(client, sid, "301", "国文", "王师")
    assert _place(client, tid, a["id"], 3, 2).status_code == 201
    _unavailable(client, t["id"], (3, 2))

    r = client.post(f"/api/timetables/{tid}/publish")
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["message"] == "课表有冲突,确认后可强制发布"
    assert detail["completeness"]["complete"] is True
    assert [i["code"] for i in detail["issues"]] == ["H4"]

    r = client.post(f"/api/timetables/{tid}/publish?force=true")
    assert r.status_code == 200 and r.json()["status"] == "published"
    # 发布后仍可检查(已发布的课表也可能因为事后改规则而出现矛盾)
    assert [i["code"] for i in _check(client, tid)["issues"]] == ["H4"]


def test_publish_reports_violations_and_unplaced_together(env3):  # noqa: F811
    client, sid, tid, _ = env3
    a, _c, _s, t = _course(client, sid, "301", "国文", "王师", periods=2)
    assert _place(client, tid, a["id"], 3, 2).status_code == 201
    _unavailable(client, t["id"], (3, 2))

    detail = client.post(f"/api/timetables/{tid}/publish").json()["detail"]
    assert detail["message"] == "课表有冲突,且尚有课务未排完;确认后可强制发布"
    assert detail["completeness"]["remaining"] == 1
    assert len(detail["issues"]) == 1


# ── 储存不可排时段后的提示(#41)────────
def test_time_rule_conflicts_lists_lessons_in_draft_and_published(env3):  # noqa: F811
    client, sid, tid, _ = env3
    a, _c, _s, t = _course(client, sid, "301", "国文", "王师", periods=2)
    assert _place(client, tid, a["id"], 3, 2).status_code == 201
    assert _place(client, tid, a["id"], 4, 1).status_code == 201

    url = f"/api/teachers/{t['id']}/time-rules/conflicts"
    assert client.get(url).json() == []  # 还没有规则

    # 偏好时段不算;不可排但那节没课也不算
    _unavailable(client, t["id"], (3, 2), (5, 5),
                 extra=[{"weekday": 4, "period_no": 1, "rule_type": "prefer"}])
    hits = client.get(url).json()
    assert [(h["weekday"], h["period_no"]) for h in hits] == [(3, 2)]
    assert hits[0]["timetable_name"] == "草稿A" and hits[0]["timetable_status"] == "draft"
    assert hits[0]["text"] == "周三第二节 301 国文"

    # 复制一份并发布 → 两份都列,已发布的排前面
    copy = client.post(f"/api/timetables/{tid}/duplicate", json={"name": "正式版"}).json()
    assert client.post(f"/api/timetables/{copy['id']}/publish?force=true").status_code == 200
    hits = client.get(url).json()
    assert [(h["timetable_name"], h["timetable_status"]) for h in hits] == [
        ("正式版", "published"), ("草稿A", "draft")]

    # 再发布另一份 → 「正式版」转为封存,封存的不看
    other = client.post(f"/api/timetables?semester_id={sid}", json={"name": "空白版"}).json()
    assert client.post(f"/api/timetables/{other['id']}/publish?force=true").status_code == 200
    assert [h["timetable_name"] for h in client.get(url).json()] == ["草稿A"]


def test_time_rule_conflicts_covers_every_period_of_a_block(env3):  # noqa: F811
    """连堂只要其中一节落在不可排时段就要列,而且指的是那一节。"""
    client, sid, tid, _ = env3
    c = _class(client, sid, 3, "301")
    s = _subject(client, sid, "实习")
    t = _teacher(client, sid, "陈师")
    a = _assign(client, sid, class_id=c["id"], subject_id=s["id"], teacher_ids=[t["id"]],
                periods=3, blocks=[{"block_size": 3, "count_per_week": 1}])
    assert _place(client, tid, a["id"], 2, 1, span=3).status_code == 201
    _unavailable(client, t["id"], (2, 3))

    hits = client.get(f"/api/teachers/{t['id']}/time-rules/conflicts").json()
    assert [h["text"] for h in hits] == ["周二第三节 301 实习"]
