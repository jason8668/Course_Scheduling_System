"""M6-3:部分排课三合一。

(a) 完全排不下的课列入未排清单并注明原因,不再让整个部分排课失败
(b) 未排清单随草稿持久化(先前只活在 Redis 24h;force 发布后原因就永远遗失)
(c) 跑班群组掉一个时段只算一节,不再乘上成员班级数
"""

from app.models.timetable import Timetable
from app.workers.progress import JobStatus
from tests.solver.test_auto_schedule import _start, sched  # noqa: F401 - 沿用 fixture


def _blocked_course(client, sid):
    """一门「完全无处可排」的课:教师整周都不可排。

    这是协同教学/兼课教师的真实情境——两位教师的不可排时段刚好盖满整周。旧行为是
    `_make_lesson_vars` 直接 raise,连「其他课照排」都做不到,部分排课整锅失败。
    """
    c = client.post(f"/api/class-units?semester_id={sid}",
                    json={"grade": 3, "name": "301", "track": "junior_high"}).json()
    s = client.post(f"/api/subjects?semester_id={sid}", json={"name": "美术"}).json()
    t = client.post(f"/api/teachers?semester_id={sid}",
                    json={"name": "封锁师", "base_periods": 20}).json()
    # 整周每一格都设为「不可排」(H4 硬约束)→ 这门课完全没有候选时段
    table = client.get(f"/api/class-units/{c['id']}/period-table").json()
    rules = [{"weekday": p["weekday"], "period_no": p["period_no"],
              "rule_type": "unavailable"} for p in table["periods"]]
    r = client.put(f"/api/teachers/{t['id']}/time-rules", json=rules)
    assert r.status_code == 200, r.text
    client.post(f"/api/assignments?semester_id={sid}", json={
        "class_id": c["id"], "subject_id": s["id"], "periods_per_week": 2,
        "teachers": [{"teacher_id": t["id"]}], "block_rules": [],
    })
    return c, s


def _normal_course(client, sid, cls):
    s = client.post(f"/api/subjects?semester_id={sid}", json={"name": "语文"}).json()
    t = client.post(f"/api/teachers?semester_id={sid}",
                    json={"name": "王师", "base_periods": 20}).json()
    client.post(f"/api/assignments?semester_id={sid}", json={
        "class_id": cls["id"], "subject_id": s["id"], "periods_per_week": 4,
        "teachers": [{"teacher_id": t["id"]}], "block_rules": [],
    })


# ── (a) 完全排不下的课不再炸掉整锅 ───────────────────────────
def test_a_completely_blocked_course_is_listed_not_fatal(sched):  # noqa: F811
    """部分排课的承诺是「排不下的列清单、其他照排」——完全被挡死的课不能让它整个失败。"""
    client, db, sid, tid, _store, _calls = sched
    cls, _ = _blocked_course(client, sid)
    _normal_course(client, sid, cls)

    r = _start(client, tid, max_seconds=30, allow_partial=True)
    assert r.status_code == 202
    body = client.get(f"/api/solver/jobs/{r.json()['job_id']}").json()

    assert body["status"] == JobStatus.finished.value, body.get("error")
    blocked = next(u for u in body["unscheduled"] if u["subject_name"] == "美术")
    assert blocked["periods"] == 2
    assert "找不到任何可排的" in blocked["reason"], "排不下要说得出为什么"

    # 其他课照排(这正是部分排课存在的意义)
    result = db.get(Timetable, body["result_timetable_id"])
    assert len(result.entries) == 4


def test_a_blocked_course_still_fails_loudly_in_normal_mode(sched):  # noqa: F811
    """一般模式维持原行为:完全排不下就要当场挡下,不能默默少排。

    这份资料连 pre-flight 都过不了(教师整周不可排 → 供给为零),根本轮不到 solver。
    「部分排课不再炸锅」只放宽部分排课那条路,一般模式的把关一格都没松。
    (solver 层「非部分排课仍 raise SolverInputError」的不变式由
     test_conflict_explainer.py 的「找不到任何可排」守著。)
    """
    client, _db, sid, tid, _store, _calls = sched
    cls, _ = _blocked_course(client, sid)
    _normal_course(client, sid, cls)

    r = _start(client, tid, max_seconds=30)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["issues"], "挡下来要说得出是哪一项不对"


# ── (b) 未排清单随草稿持久化 ─────────────────────────────────
def test_b_unscheduled_survives_redis_and_publish(sched):  # noqa: F811
    """Redis 清空(或 24h 过后)、草稿被 force 发布,原因都还在——存在 DB 里。"""
    client, db, sid, tid, store, _calls = sched
    cls, _ = _blocked_course(client, sid)
    _normal_course(client, sid, cls)

    job_id = _start(client, tid, max_seconds=30, allow_partial=True).json()["job_id"]
    result_id = client.get(f"/api/solver/jobs/{job_id}").json()["result_timetable_id"]

    store.clear() if hasattr(store, "clear") else None  # 模拟 Redis TTL 到期
    db.expire_all()

    stored = db.get(Timetable, result_id).unscheduled
    assert stored, "未排清单必须随草稿存进 DB,不能只活在 Redis"
    assert any("找不到任何可排的" in u["reason"] for u in stored)

    # force 发布后,版本页的完整性报告仍讲得出原因
    client.post(f"/api/timetables/{result_id}/publish?force=true")
    report = client.get(f"/api/timetables/{result_id}/completeness").json()
    art = next(u for u in report["unplaced"] if u["subject"] == "美术")
    assert art["remaining"] == 2
    assert "找不到任何可排的" in art["reason"]


def test_b_a_hand_made_draft_has_no_reason_and_that_is_fine(sched):  # noqa: F811
    """手动排的草稿没有 solver 纪录:未排清单照样从 DB 算得出来,只是没有原因。"""
    client, db, sid, tid, _store, _calls = sched
    cls = client.post(f"/api/class-units?semester_id={sid}",
                      json={"grade": 3, "name": "301", "track": "junior_high"}).json()
    _normal_course(client, sid, cls)

    report = client.get(f"/api/timetables/{tid}/completeness").json()
    assert report["complete"] is False
    assert report["unplaced"][0]["remaining"] == 4
    assert report["unplaced"][0]["reason"] == ""
    assert db.get(Timetable, tid).unscheduled is None


# ── (c) 跑班群组不灌水 ───────────────────────────────────────
def test_c_a_group_slot_counts_once_not_per_member_class(sched):  # noqa: F811
    """跑班群组同时段开课:掉一个时段就是掉一节课,不是掉「成员班级数」节。

    旧行为对群组内每笔成员配课各记一次,3 个班的跑班少排 1 节会报成「未排 3 节」。
    """
    client, _db, sid, tid, _store, _calls = sched
    classes = [
        client.post(f"/api/class-units?semester_id={sid}",
                    json={"grade": 3, "name": f"30{i}", "track": "junior_high"}).json()
        for i in (1, 2, 3)
    ]
    unit = client.post(f"/api/scheduling-units?semester_id={sid}", json={
        "name": "三年级选修", "class_ids": [c["id"] for c in classes],
    }).json()
    # 跑班 = 三个班的学生同时段拆进 2 门选修。每周 12 节,但 H10 每日同科上限 2 节
    # × 5 天 = 最多排 10 节 → 必然少排 2 个「时段」。
    # 旧行为对群组内每笔配课各记一次 → 同一件事被报成 4 节。
    for name in ("选修A", "选修B"):
        s = client.post(f"/api/subjects?semester_id={sid}", json={"name": name}).json()
        t = client.post(f"/api/teachers?semester_id={sid}",
                        json={"name": f"{name}师", "base_periods": 20}).json()
        r = client.post(f"/api/assignments?semester_id={sid}", json={
            "scheduling_unit_id": unit["id"], "subject_id": s["id"],
            "periods_per_week": 12,
            "teachers": [{"teacher_id": t["id"]}], "block_rules": [],
        })
        assert r.status_code == 201, r.text

    body = client.get(f"/api/solver/jobs/"
                      f"{_start(client, tid, max_seconds=30, allow_partial=True).json()['job_id']}"
                      ).json()
    assert body["status"] == JobStatus.finished.value, body.get("error")

    unscheduled = body["unscheduled"]
    assert len(unscheduled) == 1, "一个排课单位就是一笔,不是群组内每笔配课各一笔"
    item = unscheduled[0]
    assert item["periods"] == 2, f"少排 2 个时段 = 2 节,不是 2 门×2 = 4 节(得到 {item['periods']})"
    assert sorted(item["class_names"]) == ["301", "302", "303"]
    assert len(item["assignment_ids"]) == 2  # 群组内两门选修都留著,供前端定位
    assert item["subject_name"] == "选修A、选修B"  # 只印第一门会误导
