"""M4-2:代课推荐、指派处置、调课验证。

**推荐引擎是这张卡的星角**,测试也集中在它:排序规则(同科目 > 当天在校 > 本月代课少)
与硬性过滤(那个特定日期真的能来的人)。

硬性过滤正是 Fable 5 提醒的「周格 vs 特定日期」落差——李师周三第二节空堂,
不代表 11/11 他能代(他自己可能也请假、或已被指派代别班)。这里逐一造出那些情境。
"""

from datetime import date, timedelta

import pytest

from app.models.leave import AffectedPeriod, AffectedStatus
from app.models.user import Role, UserGradeScope
from tests.conftest import make_user
from tests.dates import SEM_END, SEM_START, THU, WED, WED2  # 日期一律由执行当日推算,不硬编

PW = "password123"


@pytest.fixture
def env2(env):
    """已发布课表的初中。回传 helper 物件,测试逐步叠教师/配课/请假。"""
    client, db = env
    s = make_user(db, "s", PW, roles=[Role.director])
    # 本批语意:未配年级的组长没有任何排课权限;本 helper 用 7 年级,同年级推荐测试另用 8 年级,都先配给 s
    db.add(UserGradeScope(user_id=s.id, grade=7))
    db.add(UserGradeScope(user_id=s.id, grade=8))
    db.commit()
    make_user(db, "adm", PW, roles=[Role.admin])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    sid = client.post("/api/semesters", json={
        "academic_year": 2026, "term": 1, "template_key": "junior_high",
        "start_date": SEM_START.isoformat(), "end_date": SEM_END.isoformat(),
    }).json()["id"]
    return _World(client, db, sid)


class _World:
    def __init__(self, client, db, sid):
        self.client, self.db, self.sid = client, db, sid
        self.q = f"?semester_id={sid}"
        self.subjects: dict[str, int] = {
            s["name"]: s["id"]
            for s in client.get(f"/api/subjects{self.q}").json()
        }
        self.teachers: dict[str, int] = {}
        self.classes: dict[str, int] = {}
        self.tt = client.post(f"/api/timetables{self.q}", json={"name": "草稿A"}).json()["id"]
        self._published = False
        # 周三节次
        c = self.klass("900")  # 占位班,取节次表
        self.wed = [p for p in client.get(f"/api/class-units/{c}/period-table").json()["periods"]
                    if p["weekday"] == 3 and p["type"] == "regular"]

    def subject(self, name: str) -> int:
        if name not in self.subjects:
            self.subjects[name] = self.client.post(
                f"/api/subjects{self.q}", json={"name": name}).json()["id"]
        return self.subjects[name]

    def teacher(self, name: str, subjects: list[str] | None = None) -> int:
        tid = self.client.post(f"/api/teachers{self.q}", json={
            "name": name, "base_periods": 20,
            "subject_ids": [self.subject(s) for s in (subjects or [])],
        }).json()["id"]
        self.teachers[name] = tid
        return tid

    def klass(self, name: str) -> int:
        if name not in self.classes:
            self.classes[name] = self.client.post(f"/api/class-units{self.q}", json={
                "grade": 7, "name": name, "track": "junior_high"}).json()["id"]
        return self.classes[name]

    def place(self, teacher: str, subject: str, klass: str, period_idx: int, weekday: int = 3):
        """把 teacher 的 subject 课排到 (weekday, 第 period_idx 个一般课节次)、上 klass 班。"""
        slots = [p for p in self.client.get(
            f"/api/class-units/{self.klass(klass)}/period-table").json()["periods"]
            if p["weekday"] == weekday and p["type"] == "regular"]
        a = self.client.post(f"/api/assignments{self.q}", json={
            "class_id": self.klass(klass), "subject_id": self.subject(subject),
            "periods_per_week": 1, "teachers": [{"teacher_id": self.teachers[teacher]}],
            "block_rules": [],
        }).json()
        r = self.client.post(f"/api/timetables/{self.tt}/entries", json={
            "course_assignment_id": a["id"], "weekday": weekday,
            "period_no": slots[period_idx]["period_no"], "span": 1})
        assert r.status_code == 201, r.json()
        return a["id"], slots[period_idx]["period_no"]

    def publish(self):
        # 发布是整校操作,有年级限制的组长做不了,改由管理员发布再切回组长。
        # 管理员帐号按需建立:各测试的 fixture 只建了组长,未必建了 adm。
        from app.models.user import User
        from tests.conftest import make_user

        if not self.db.query(User).filter_by(username="adm").first():
            make_user(self.db, "adm", PW, roles=[Role.admin])
        self.client.post("/api/auth/login", json={"username": "adm", "password": PW})
        r = self.client.post(f"/api/timetables/{self.tt}/publish?force=true")
        self.client.post("/api/auth/login", json={"username": "s", "password": PW})
        assert r.status_code == 200, r.json()
        self._published = True

    def leave(self, teacher: str, when: date = WED, leave_type: str = "sick") -> list[dict]:
        r = self.client.post(f"/api/leaves{self.q}", json={
            "teacher_id": self.teachers[teacher], "leave_type": leave_type,
            "start_date": when.isoformat(), "end_date": when.isoformat()})
        assert r.status_code == 201, r.json()
        return r.json()["affected_periods"]

    def recommend(self, affected_id: int) -> dict:
        return self.client.get(
            f"/api/affected-periods/{affected_id}/recommendations").json()

    def assign(self, affected_id: int, **body) -> "tuple[int, dict]":
        r = self.client.put(f"/api/affected-periods/{affected_id}/substitution", json=body)
        return r.status_code, r.json()


# ── 验收①:第一名必为空堂 + 同科;已满档者靠后 ──────────────
def test_recommendation_ranks_same_subject_first(env2):
    w = env2
    w.teacher("王师", ["国文"])
    w.teacher("陈师", ["国文"])   # 同科,当天没课
    w.teacher("林师", ["数学"])   # 非本科
    # 王师周三第一节上 701 国文;陈师与林师该节空堂
    a_id, _ = w.place("王师", "国文", "701", 0)
    w.publish()
    affected = w.leave("王师")

    rec = w.recommend(affected[0]["id"])
    names = [c["teacher_name"] for c in rec["candidates"]]
    assert names[0] == "陈师", names   # 同科优先
    top = rec["candidates"][0]
    assert top["same_subject"] is True
    assert "同科目教师" in top["reasons"]


def test_recommendation_ranks_same_grade_before_cross_grade(env2):
    """同科时,同年级优先于跨年级;跨年级仍在候选里(特殊情况可跨年级指派)。"""
    w = env2
    w.teacher("王师", ["国文"])
    w.teacher("陈师", ["国文"])   # 同科同年级(7 年级)
    w.teacher("林师", ["国文"])   # 同科跨年级(8 年级)
    c801 = w.client.post(f"/api/class-units{w.q}", json={
        "grade": 8, "name": "801", "track": "junior_high"}).json()["id"]
    w.classes["801"] = c801
    w.place("王师", "国文", "701", 0)   # 王师周三第一节 701(7 年级)国文
    w.place("陈师", "国文", "702", 2)   # 陈师 7 年级另一班,第一节空堂
    w.place("林师", "国文", "801", 2)   # 林师 8 年级,第一节空堂
    w.publish()
    affected = w.leave("王师")

    rec = w.recommend(affected[0]["id"])
    names = [c["teacher_name"] for c in rec["candidates"]]
    assert names.index("陈师") < names.index("林师"), names
    chen = next(c for c in rec["candidates"] if c["teacher_name"] == "陈师")
    lin = next(c for c in rec["candidates"] if c["teacher_name"] == "林师")
    assert chen["same_grade"] is True and "同年级教师" in chen["reasons"]
    assert lin["same_grade"] is False and "跨年级教师" in lin["reasons"]


def test_at_school_that_day_beats_a_teacher_not_coming_in(env2):
    """同为非本科,当天已在校者优先(免多跑一趟)。"""
    w = env2
    w.teacher("王师", ["国文"])
    w.teacher("陈师", ["体育"])  # 非本科,当天周三另有课 → 已在校
    w.teacher("林师", ["体育"])  # 非本科,周三完全没课
    w.place("王师", "国文", "701", 0)  # 王师周三第一节(被请假)
    w.place("陈师", "体育", "702", 2)  # 陈师周三第三节有课 → 当天在校,但第一节空
    w.publish()
    affected = w.leave("王师")

    rec = w.recommend(affected[0]["id"])
    names = [c["teacher_name"] for c in rec["candidates"]]
    assert names.index("陈师") < names.index("林师"), names
    chen = next(c for c in rec["candidates"] if c["teacher_name"] == "陈师")
    assert chen["at_school_that_day"] is True
    assert "当天已在校" in chen["reasons"]


def test_fewer_monthly_sub_periods_ranks_higher(env2):
    """同科同条件时,本月代课少者优先(公平)。"""
    w = env2
    w.teacher("王师", ["国文"])
    w.teacher("陈师", ["国文"])
    w.teacher("林师", ["国文"])
    w.place("王师", "国文", "701", 0)
    # 林师本月已代一节(11/18):先帮另一个请假的老师代
    w.teacher("周师", ["国文"])
    w.place("周师", "国文", "702", 0, weekday=3)
    w.publish()

    other = w.client.post(f"/api/leaves{w.q}", json={
        "teacher_id": w.teachers["周师"], "leave_type": "sick",
        "start_date": WED2.isoformat(), "end_date": WED2.isoformat()}).json()
    code, _ = w.assign(other["affected_periods"][0]["id"],
                       type="substitute", handler_teacher_id=w.teachers["林师"])
    assert code == 200

    affected = w.leave("王师")  # 11/11
    rec = w.recommend(affected[0]["id"])
    names = [c["teacher_name"] for c in rec["candidates"] if c["teacher_name"] in ("陈师", "林师")]
    assert names[0] == "陈师", names  # 陈师本月 0 节,林师 1 节
    lin = next(c for c in rec["candidates"] if c["teacher_name"] == "林师")
    assert lin["sub_periods_this_month"] == 1
    assert "本月已代 1 节" in lin["reasons"]


# ── 硬性过滤:周格 vs 特定日期(Fable 5 的落差)──────────────
def test_a_teacher_busy_that_period_is_filtered_out(env2):
    """周格层:陈师该节有自己的课 → 不可代。"""
    w = env2
    w.teacher("王师", ["国文"])
    w.teacher("陈师", ["国文"])
    w.place("王师", "国文", "701", 0)  # 王师周三第一节
    w.place("陈师", "国文", "702", 0)  # 陈师同一节也有课
    w.publish()
    affected = w.leave("王师")

    names = [c["teacher_name"] for c in w.recommend(affected[0]["id"])["candidates"]]
    assert "陈师" not in names


def test_a_teacher_on_leave_that_day_is_filtered_out(env2):
    """日期层:陈师该节空堂,但『那一天』他自己也请假 → 不可代。"""
    w = env2
    w.teacher("王师", ["国文"])
    w.teacher("陈师", ["国文"])
    w.place("王师", "国文", "701", 0)   # 王师周三第一节(被请假)
    w.place("陈师", "国文", "703", 2)   # 陈师周三第三节有课;第一节空堂
    w.publish()
    w.leave("陈师")                     # 陈师也请整天假(含第一节)
    affected = w.leave("王师")

    names = [c["teacher_name"] for c in w.recommend(affected[0]["id"])["candidates"]]
    assert "陈师" not in names, "当天请假的人不该出现在可代清单"


def test_a_teacher_already_covering_that_slot_is_filtered_out(env2):
    """日期层:陈师该节空堂、当天没请假,但已被指派代别班 → 不可代。"""
    w = env2
    w.teacher("王师", ["国文"])
    w.teacher("周师", ["国文"])
    w.teacher("陈师", ["国文"])
    w.place("王师", "国文", "701", 0)  # 王师周三第一节
    w.place("周师", "国文", "702", 0)  # 周师同一节也有课(也会被请假)
    w.publish()

    a_wang = w.leave("王师")[0]["id"]
    a_zhou = w.leave("周师")[0]["id"]
    # 陈师先被指派去代周师那一节(周三第一节)
    code, _ = w.assign(a_zhou, type="substitute", handler_teacher_id=w.teachers["陈师"])
    assert code == 200

    names = [c["teacher_name"] for c in w.recommend(a_wang)["candidates"]]
    assert "陈师" not in names, "同一时段已被指派代课的人不该再被推荐"


def test_the_absent_teacher_is_never_a_candidate(env2):
    w = env2
    w.teacher("王师", ["国文"])
    w.place("王师", "国文", "701", 0)
    w.publish()
    affected = w.leave("王师")
    names = [c["teacher_name"] for c in w.recommend(affected[0]["id"])["candidates"]]
    assert "王师" not in names


# ── 验收③:全校无人可代 → 提示并班/自习 ────────────────────
def test_no_available_teacher_hints_merge_or_self_study(env2):
    w = env2
    w.teacher("王师", ["国文"])
    w.teacher("陈师", ["国文"])
    w.place("王师", "国文", "701", 0)  # 王师周三第一节
    w.place("陈师", "国文", "702", 0)  # 唯一其他教师同一节也有课
    w.publish()
    affected = w.leave("王师")

    rec = w.recommend(affected[0]["id"])
    assert rec["candidates"] == []
    assert "并班" in rec["no_candidate_hint"] and "自习" in rec["no_candidate_hint"]


# ── 指派处置 ─────────────────────────────────────────────────
def test_assigning_a_substitute_marks_resolved_and_notifies(env2):
    w = env2
    w.teacher("王师", ["国文"])
    w.teacher("陈师", ["国文"])
    w.place("王师", "国文", "701", 0)
    w.publish()
    affected_id = w.leave("王师")[0]["id"]

    code, body = w.assign(affected_id, type="substitute", handler_teacher_id=w.teachers["陈师"])
    assert code == 200
    assert body["type_label"] == "代课"
    assert body["handler_name"] == "陈师"
    assert body["counts_toward_hours"] is True

    ap = w.db.get(AffectedPeriod, affected_id)
    assert ap.status == AffectedStatus.resolved.value
    assert ap.handler_teacher_id == w.teachers["陈师"]

    # 陈师收到代课通知
    notes = w.client.get(
        f"/api/notifications{w.q}&teacher_id={w.teachers['陈师']}").json()
    assert notes and notes[0]["type"] == "substitution_assigned"


def test_self_study_and_merge_hours_policy(env2):
    """自习不计课时且无处理教师;并班计不计由默认(不计)。"""
    w = env2
    w.teacher("王师", ["国文"])
    w.teacher("陈师", ["国文"])
    w.place("王师", "国文", "701", 0)
    w.publish()
    ids = [p["id"] for p in w.leave("王师")]

    _, self_study = w.assign(ids[0], type="self_study")
    assert self_study["handler_name"] is None
    assert self_study["counts_toward_hours"] is False


def test_cannot_assign_absent_teacher_to_cover_self(env2):
    w = env2
    w.teacher("王师", ["国文"])
    w.place("王师", "国文", "701", 0)
    w.publish()
    affected_id = w.leave("王师")[0]["id"]
    code, body = w.assign(affected_id, type="substitute", handler_teacher_id=w.teachers["王师"])
    assert code == 409
    assert "代自己" in body["detail"]


def test_assigning_a_busy_teacher_is_rejected_with_reason(env2):
    w = env2
    w.teacher("王师", ["国文"])
    w.teacher("陈师", ["国文"])
    w.place("王师", "国文", "701", 0)
    w.place("陈师", "国文", "702", 0)  # 陈师同一节有课
    w.publish()
    affected_id = w.leave("王师")[0]["id"]
    code, body = w.assign(affected_id, type="substitute", handler_teacher_id=w.teachers["陈师"])
    assert code == 409
    assert "有自己的课" in body["detail"]


def test_clearing_a_substitution_returns_to_pending(env2):
    w = env2
    w.teacher("王师", ["国文"])
    w.teacher("陈师", ["国文"])
    w.place("王师", "国文", "701", 0)
    w.publish()
    affected_id = w.leave("王师")[0]["id"]
    w.assign(affected_id, type="substitute", handler_teacher_id=w.teachers["陈师"])

    r = w.client.delete(f"/api/affected-periods/{affected_id}/substitution")
    assert r.status_code == 200
    assert r.json()["status"] == AffectedStatus.pending.value
    assert w.db.get(AffectedPeriod, affected_id).handler_teacher_id is None
    # 陈师收到取消通知
    types = [n["type"] for n in w.client.get(
        f"/api/notifications{w.q}&teacher_id={w.teachers['陈师']}").json()]
    assert "substitution_cancelled" in types


# ── 验收②:调课(swap)验证 ─────────────────────────────────
def test_swap_succeeds_when_both_sides_are_free(env2):
    """乙代甲周三第一节;甲于下周三补乙原本周三第二节的课。两边都空 → 成立。"""
    w = env2
    w.teacher("王师", ["国文"])
    w.teacher("陈师", ["数学"])
    w.place("王师", "国文", "701", 0)              # 甲:周三第一节(被请假)
    _, swap_entry = _entry(w, "陈师", "数学", "702", 1)  # 乙:周三第二节
    w.publish()
    affected_id = w.leave("王师")[0]["id"]

    entry_id = _find_entry(w, "陈师")
    code, body = w.assign(
        affected_id, type="swap", handler_teacher_id=w.teachers["陈师"],
        swap_entry_id=entry_id, swap_date=WED2.isoformat())  # 下周三补
    assert code == 200, body
    assert body["type_label"] == "调课"
    assert body["swap_subject_name"] == "数学"
    assert body["swap_date"] == WED2.isoformat()


def test_swap_rejected_when_partner_busy_at_absent_slot(env2):
    """乙在甲请假那节本来就有课 → 无法来代,拒绝并指名。"""
    w = env2
    w.teacher("王师", ["国文"])
    w.teacher("陈师", ["数学"])
    w.place("王师", "国文", "701", 0)   # 甲周三第一节
    w.place("陈师", "数学", "702", 0)   # 乙周三第一节也有课
    _entry(w, "陈师", "数学", "703", 1)  # 乙另有周三第二节(用来当 swap 目标)
    w.publish()
    affected_id = w.leave("王师")[0]["id"]

    entry_id = _find_entry(w, "陈师", period_idx=1)
    code, body = w.assign(
        affected_id, type="swap", handler_teacher_id=w.teachers["陈师"],
        swap_entry_id=entry_id, swap_date=WED2.isoformat())
    assert code == 409
    assert "陈师" in body["detail"] and "有自己的课" in body["detail"]


def test_swap_rejected_when_absent_teacher_busy_at_makeup_slot(env2):
    """甲在补课那节本来就有别的课 → 补不了,拒绝并指名。"""
    w = env2
    w.teacher("王师", ["国文"])
    w.teacher("陈师", ["数学"])
    w.place("王师", "国文", "701", 0)   # 甲周三第一节(被请假)
    w.place("王师", "国文", "705", 1)   # 甲周三第二节另有课(补课会撞)
    _entry(w, "陈师", "数学", "702", 1)  # 乙周三第二节 → swap 目标
    w.publish()
    affected_id = [p for p in w.leave("王师") if p["period_name"] == w.wed[0]["name"]][0]["id"]

    entry_id = _find_entry(w, "陈师", period_idx=1)
    code, body = w.assign(
        affected_id, type="swap", handler_teacher_id=w.teachers["陈师"],
        swap_entry_id=entry_id, swap_date=WED2.isoformat())
    assert code == 409
    assert "王师" in body["detail"]


# ── v1.2.1:可对调节次清单(调课前端的资料来源)──────────────
def _swap_world(w):
    """王师周三第一节 701 国文请假。
    陈师也教 701(周四第二节数学),另有 702 周三第二节自然;林师只教 703。
    """
    w.teacher("王师", ["国文"])
    w.teacher("陈师", ["数学", "自然"])
    w.teacher("林师", ["英文"])
    w.place("王师", "国文", "701", 0)
    w.place("陈师", "数学", "701", 1, weekday=4)
    w.place("陈师", "自然", "702", 1)
    w.place("林师", "英文", "703", 2)
    w.publish()
    return w.leave("王师")[0]["id"]


def _options(w, affected_id, teacher=None):
    q = f"?teacher_id={w.teachers[teacher]}" if teacher else ""
    r = w.client.get(f"/api/affected-periods/{affected_id}/swap-options{q}")
    assert r.status_code == 200, r.json()
    return r.json()


def _notif_titles(w, teacher):
    return [n["title"] for n in w.client.get(
        f"/api/notifications{w.q}&teacher_id={w.teachers[teacher]}").json()]


def test_swap_options_list_same_class_teachers_this_and_next_week(env2):
    """默认只找也教这个班的老师;同班的节次排前面;甲请假当天的节次不列。"""
    from datetime import timedelta

    w = env2
    affected_id = _swap_world(w)
    body = _options(w, affected_id)

    assert [p["teacher_name"] for p in body["partners"]] == ["陈师"]  # 林师不教 701
    chen = body["partners"][0]
    assert chen["teaches_same_class"] is True and chen["blocked_reason"] == ""
    got = [(o["date"], o["class_names"], o["same_class"]) for o in chen["options"]]
    assert got == [
        (THU.isoformat(), "701", True),                        # 本周四,同班互调
        ((THU + timedelta(days=7)).isoformat(), "701", True),  # 下周四
        (WED2.isoformat(), "702", False),                      # 周三当天王师请假 → 只剩下周三
    ]


def test_swap_option_from_list_is_accepted_and_both_teachers_notified(env2):
    """清单上的组合送出去一定成立;乙收到代课、甲收到补课通知,撤回后两人都收到取消。"""
    w = env2
    affected_id = _swap_world(w)
    opt = _options(w, affected_id)["partners"][0]["options"][0]

    code, body = w.assign(affected_id, type="swap", handler_teacher_id=w.teachers["陈师"],
                          swap_entry_id=opt["entry_id"], swap_date=opt["date"])
    assert code == 200, body
    assert body["swap_class_names"] == "701" and body["counts_toward_hours"] is False
    assert any(t.startswith("调课通知") for t in _notif_titles(w, "陈师"))
    assert any(t.startswith("调课补课通知") for t in _notif_titles(w, "王师"))

    assert w.client.delete(f"/api/affected-periods/{affected_id}/substitution").status_code == 200
    assert "原订调课已取消" in _notif_titles(w, "王师")
    assert "原订调课已取消" in _notif_titles(w, "陈师")


def test_swap_search_range_can_widen_to_four_weeks(env2):
    """默认两周;组长可放宽到四周(本周与隔三周对调),超过四周拒绝。"""
    from datetime import timedelta

    w = env2
    affected_id = _swap_world(w)
    thursdays = lambda body: [o["date"] for o in body["partners"][0]["options"]  # noqa: E731
                              if o["class_names"] == "701"]

    two = _options(w, affected_id)
    assert two["date_to"] == (WED + timedelta(days=11)).isoformat()  # 下周日
    assert len(thursdays(two)) == 2

    r = w.client.get(f"/api/affected-periods/{affected_id}/swap-options?weeks=4")
    four = r.json()
    assert four["date_to"] == (WED + timedelta(days=25)).isoformat()  # 隔三周的周日
    assert thursdays(four)[-1] == (THU + timedelta(days=21)).isoformat()
    assert len(thursdays(four)) == 4

    assert w.client.get(
        f"/api/affected-periods/{affected_id}/swap-options?weeks=5").status_code == 422


def test_swap_options_for_a_named_teacher_outside_the_class(env2):
    """组长指定一位不教这班的老师,照样列出他换得成的节次。"""
    w = env2
    affected_id = _swap_world(w)
    body = _options(w, affected_id, teacher="林师")
    lin = body["partners"][0]
    assert lin["teacher_name"] == "林师" and lin["teaches_same_class"] is False
    assert [o["date"] for o in lin["options"]] == [WED2.isoformat()]


def test_swap_partner_on_leave_at_absent_slot_is_blocked(env2):
    """乙在甲请假那节自己也请假:清单说明原因,送出也被拒绝(原本只验「有没有课」)。"""
    w = env2
    affected_id = _swap_world(w)
    w.leave("陈师")  # 陈师周三也请假

    chen = _options(w, affected_id)["partners"][0]
    assert chen["options"] == [] and "请假" in chen["blocked_reason"]

    entry_id = _find_entry(w, "陈师", period_idx=1, weekday=3)
    code, body = w.assign(affected_id, type="swap", handler_teacher_id=w.teachers["陈师"],
                          swap_entry_id=entry_id, swap_date=WED2.isoformat())
    assert code == 409 and "陈师" in body["detail"]


def test_swap_slot_where_partner_is_on_leave_is_not_offered(env2):
    """乙在补课那天自己请假:那节课本身要另外安排,不能拿来对调。"""
    w = env2
    affected_id = _swap_world(w)
    w.leave("陈师", when=WED2)

    dates = [o["date"] for o in _options(w, affected_id)["partners"][0]["options"]]
    assert WED2.isoformat() not in dates

    entry_id = _find_entry(w, "陈师", period_idx=1, weekday=3)
    code, body = w.assign(affected_id, type="swap", handler_teacher_id=w.teachers["陈师"],
                          swap_entry_id=entry_id, swap_date=WED2.isoformat())
    assert code == 409 and "也请假" in body["detail"]


def test_swap_slot_already_taken_by_another_swap_is_not_offered(env2):
    """乙的同一节课不能换给两个人补。"""
    w = env2
    w.teacher("王师", ["国文"])
    w.teacher("陈师", ["数学"])
    w.place("王师", "国文", "701", 0)
    w.place("王师", "历史", "701", 2)
    w.place("陈师", "数学", "701", 1, weekday=4)
    w.publish()
    first, second = [p["id"] for p in w.leave("王师")]

    opt = _options(w, first)["partners"][0]["options"][0]
    code, _ = w.assign(first, type="swap", handler_teacher_id=w.teachers["陈师"],
                       swap_entry_id=opt["entry_id"], swap_date=opt["date"])
    assert code == 200

    remaining = [o["date"] for o in _options(w, second)["partners"][0]["options"]]
    assert opt["date"] not in remaining
    code, body = w.assign(second, type="swap", handler_teacher_id=w.teachers["陈师"],
                          swap_entry_id=opt["entry_id"], swap_date=opt["date"])
    assert code == 409 and "已经和别的老师调课" in body["detail"]


def test_board_on_makeup_day_lists_the_swapped_period(env2):
    """补课那天的看板也要列出被换来的那一节:原任陈师、改由王师上,并指回请假那节。"""
    w = env2
    affected_id = _swap_world(w)
    opt = _options(w, affected_id)["partners"][0]["options"][0]  # 本周四第二节 701 数学
    code, _ = w.assign(affected_id, type="swap", handler_teacher_id=w.teachers["陈师"],
                       swap_entry_id=opt["entry_id"], swap_date=opt["date"])
    assert code == 200

    board = w.client.get(f"/api/daily-board{w.q}&on={opt['date']}").json()
    assert len(board["entries"]) == 1
    row = board["entries"][0]
    assert row["row_kind"] == "swap_makeup"
    assert (row["class_names"], row["subject_name"]) == ("701", "数学")
    assert row["absent_teacher_name"] == "陈师" and row["handler_name"] == "王师"
    assert row["leave_type_label"] == "调课补课"
    assert row["swap_date"] == WED.isoformat() and row["swap_subject_name"] == "国文"

    # 请假那天仍是原本那一列;撤回调课后补课日的列跟著消失
    wed = w.client.get(f"/api/daily-board{w.q}&on={WED.isoformat()}").json()["entries"]
    assert [e["row_kind"] for e in wed] == ["leave"]
    w.client.delete(f"/api/affected-periods/{affected_id}/substitution")
    assert w.client.get(f"/api/daily-board{w.q}&on={opt['date']}").json()["entries"] == []


# ── v1.2.2:调课通知单(教师调课单、班级调课单)────────────────
def _slips(w, *affected_ids):
    q = "&".join(f"affected_period_ids={i}" for i in affected_ids)
    return w.client.get(f"/api/swap-slips{w.q}&{q}")


def _swap_first(w, affected_id, pick):
    opt = next(o for o in _options(w, affected_id)["partners"][0]["options"] if pick(o))
    code, body = w.assign(affected_id, type="swap", handler_teacher_id=w.teachers["陈师"],
                          swap_entry_id=opt["entry_id"], swap_date=opt["date"],
                          swap_period_no=opt["period_no"])
    assert code == 200, body
    return opt


def _cells(slip):
    return [(c["date"], c["ordinal"], c["subject_name"], c["actor"], c["code"])
            for week in slip["weeks"] for c in week["cells"]]


def test_swap_slips_same_class_follow_the_paper_form(env2):
    """同班互调:两张教师单(先对调的老师)+ 一张班级单;科目跟著老师走,代码指向对调的另一节。"""
    w = env2
    affected_id = _swap_world(w)  # 王师周三第 1 节 701 国文 ⇄ 陈师周四第 2 节 701 数学
    _swap_first(w, affected_id, lambda o: o["date"] == THU.isoformat())
    wang = [p["id"] for p in w.client.get(f"/api/leaves{w.q}").json()[0]["affected_periods"]]
    listed = w.client.get(f"/api/leaves{w.q}").json()[0]["affected_periods"][0]
    assert listed["sub_type"] == "swap"
    assert listed["swap_date"] == THU.isoformat() and listed["swap_period_name"]

    r = _slips(w, *wang)
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["title"].endswith("2026-2027学年第一学期")
    kinds = [(s["kind"], s["teacher_name"], s["class_names"]) for s in body["slips"]]
    assert kinds == [("teacher", "陈师", "701"), ("teacher", "王师", "701"), ("class", "", "701")]

    chen, wang_slip, klass = body["slips"]
    thu, wed = THU.strftime("%m-%d"), WED.strftime("%m-%d")
    assert _cells(chen) == [(WED.isoformat(), 1, "数学", "陈师", f"调{thu}_42")]
    assert _cells(wang_slip) == [(THU.isoformat(), 2, "国文", "王师", f"调{wed}_31")]
    assert len(_cells(klass)) == 2
    assert (chen["date_from"], chen["date_to"]) == (WED.isoformat(), WED.isoformat())
    assert (klass["date_from"], klass["date_to"]) == (WED.isoformat(), THU.isoformat())

    week = klass["weeks"][0]
    assert week["monday"] == (WED - timedelta(days=2)).isoformat() and len(week["days"]) == 5
    assert [r["ordinal"] for r in klass["rows"]][:2] == [1, 2]
    assert any(r["afternoon_starts"] for r in klass["rows"])  # 午休后画粗线


def test_swap_slips_cross_class_and_cross_week(env2):
    """跨班又跨周:两个班各一张,科目沿用那一节原本的课;每张单依周分开。"""
    w = env2
    affected_id = _swap_world(w)
    _swap_first(w, affected_id, lambda o: o["class_names"] == "702")  # 下周三 702 自然

    body = _slips(w, affected_id).json()
    kinds = [(s["kind"], s["class_names"]) for s in body["slips"]]
    assert kinds == [("teacher", "701"), ("teacher", "702"), ("class", "701"), ("class", "702")]
    chen, wang, c701, c702 = body["slips"]
    assert _cells(chen)[0][2:4] == ("国文", "陈师")   # 陈师去 701 上王师那节国文
    assert _cells(wang)[0][2:4] == ("自然", "王师")   # 王师去 702 上陈师那节自然
    assert _cells(c702)[0][0] == WED2.isoformat()
    assert [wk["monday"] for wk in c701["weeks"]] != [wk["monday"] for wk in c702["weeks"]]


def test_swap_slips_ignore_non_swap_periods(env2):
    """代课或未处置的节次不印;全都不是调课就回 404 并说明。"""
    w = env2
    affected_id = _swap_world(w)
    r = _slips(w, affected_id)
    assert r.status_code == 404 and "没有已成立的调课" in r.json()["detail"]
    assert w.client.get(f"/api/leaves{w.q}").json()[0]["affected_periods"][0]["sub_type"] is None


# ── v1.2.5:代课通知单(教师代课单、班级代课单)────────────────
def _sub_slips(w, *affected_ids):
    q = "&".join(f"affected_period_ids={i}" for i in affected_ids)
    return w.client.get(f"/api/substitute-slips{w.q}&{q}")


def _sub_world(w, leave_type: str = "sick") -> list[int]:
    """王师周三两节(701 国文、702 数学)请假,回传两个受影响节次。"""
    w.teacher("王师", ["国文"])
    w.teacher("陈师", ["国文"])
    w.teacher("林师", ["数学"])
    w.place("王师", "国文", "701", 0)
    w.place("王师", "数学", "702", 1)
    w.publish()
    return [p["id"] for p in w.leave("王师", leave_type=leave_type)]


def test_substitute_slips_follow_the_paper_form(env2):
    """每位代课老师一张、每个班一张;表头写请假教师、假别、计费方式,格子写班级[代]/老师[代]。"""
    w = env2
    first, second = _sub_world(w)
    assert w.assign(first, type="substitute", handler_teacher_id=w.teachers["陈师"])[0] == 200
    assert w.assign(second, type="substitute", handler_teacher_id=w.teachers["林师"])[0] == 200

    r = _sub_slips(w, first, second)
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["kind"] == "substitute"
    assert "学年" not in body["title"]  # 代课单纸本只有校名
    kinds = [(s["kind"], s["teacher_name"], s["class_names"]) for s in body["slips"]]
    assert kinds == [
        ("teacher", "陈师", "701"), ("teacher", "林师", "702"),
        ("class", "", "701"), ("class", "", "702"),
    ]

    chen, lin, c701, c702 = body["slips"]
    assert _cells(chen) == [(WED.isoformat(), 1, "国文", "701[代]", "")]
    assert _cells(lin) == [(WED.isoformat(), 2, "数学", "702[代]", "")]
    assert _cells(c701) == [(WED.isoformat(), 1, "国文", "陈师[代]", "")]
    assert _cells(c702) == [(WED.isoformat(), 2, "数学", "林师[代]", "")]

    for slip in body["slips"]:
        assert slip["absent_teacher_name"] == "王师"
        assert slip["leave_type_name"] == "病假"
        assert slip["funding_label"] == "计入课时"          # 代课默认计入课时
        # 日期是请假起讫,不是只有被代的那几天
        assert (slip["date_from"], slip["date_to"]) == (WED.isoformat(), WED.isoformat())
        assert [row["ordinal"] for row in slip["rows"]][:2] == [1, 2]
        assert any(row["afternoon_starts"] for row in slip["rows"])


def test_substitute_slips_personal_leave_defaults_to_self_funding(env2):
    """请人代课默认计入课时;界面指定的计费方式优先(自由文字仍存得进去)。"""
    w = env2
    first, second = _sub_world(w, leave_type="personal")
    assert w.assign(first, type="substitute", handler_teacher_id=w.teachers["陈师"])[0] == 200
    slip = _sub_slips(w, first).json()["slips"][0]
    assert slip["leave_type_name"] == "事假" and slip["funding_label"] == "计入课时"

    assert w.assign(second, type="substitute", handler_teacher_id=w.teachers["林师"],
                    funding_source="自行调课补课")[0] == 200
    sub = w.client.get(f"/api/affected-periods/{second}/substitution").json()
    assert sub["funding_source"] == "自行调课补课"


def test_substitute_slips_include_merge_with_its_own_mark(env2):
    """并班也印,格子标[并];自习、不处理、调课不印。"""
    w = env2
    first, second = _sub_world(w)
    assert w.assign(first, type="merge", handler_teacher_id=w.teachers["陈师"])[0] == 200
    assert w.assign(second, type="self_study")[0] == 200

    body = _sub_slips(w, first, second).json()
    assert [(s["kind"], s["class_names"]) for s in body["slips"]] == [
        ("teacher", "701"), ("class", "701")]
    assert _cells(body["slips"][0]) == [(WED.isoformat(), 1, "国文", "701[并]", "")]
    assert body["slips"][0]["funding_label"] == ""  # 并班不另计代课课时


def test_substitute_slips_without_any_substitute_is_404(env2):
    """全都不是代课/并班就回 404 并说明。"""
    w = env2
    first, _ = _sub_world(w)
    r = _sub_slips(w, first)
    assert r.status_code == 404 and "没有已指派的代课" in r.json()["detail"]


def test_funding_sources_are_listed_for_the_form(env2):
    options = env2.client.get("/api/substitution-funding-sources").json()
    assert options == ["计入课时", "不计入课时"]


def _place_block(w, teacher, subject, klass, weekday, period_idx):
    """排一堂两节连堂。"""
    slots = [p for p in w.client.get(
        f"/api/class-units/{w.klass(klass)}/period-table").json()["periods"]
        if p["weekday"] == weekday and p["type"] == "regular"]
    a = w.client.post(f"/api/assignments{w.q}", json={
        "class_id": w.klass(klass), "subject_id": w.subject(subject),
        "periods_per_week": 2, "teachers": [{"teacher_id": w.teachers[teacher]}],
        "block_rules": [{"block_size": 2, "count_per_week": 1}],
    }).json()
    r = w.client.post(f"/api/timetables/{w.tt}/entries", json={
        "course_assignment_id": a["id"], "weekday": weekday,
        "period_no": slots[period_idx]["period_no"], "span": 2})
    assert r.status_code == 201, r.json()
    return r.json()["id"], [s["period_no"] for s in slots[period_idx:period_idx + 2]]


def test_block_lesson_can_swap_a_single_period(env2):
    """乙的连堂可以只换其中一节;换掉的那节不再列出,另一节照样可换。"""
    w = env2
    w.teacher("王师", ["国文"])
    w.teacher("陈师", ["理化"])
    w.place("王师", "国文", "701", 0)
    w.place("王师", "历史", "701", 3)
    _, (first, second) = _place_block(w, "陈师", "理化", "701", 4, 1)  # 周四连堂
    w.publish()
    ap1, ap2 = [p["id"] for p in w.leave("王师")]

    opts = [o for o in _options(w, ap1)["partners"][0]["options"] if o["date"] == THU.isoformat()]
    assert [(o["period_no"], o["in_block"]) for o in opts] == [(first, True), (second, True)]

    code, body = w.assign(ap1, type="swap", handler_teacher_id=w.teachers["陈师"],
                          swap_entry_id=opts[1]["entry_id"], swap_date=THU.isoformat(),
                          swap_period_no=second)
    assert code == 200, body
    assert body["swap_period_name"] == opts[1]["period_name"]

    left = [o["period_no"] for o in _options(w, ap2)["partners"][0]["options"]
            if o["date"] == THU.isoformat()]
    assert left == [first]  # 第二节已换给第一笔调课,不能再换第二次

    code, body = w.assign(ap2, type="swap", handler_teacher_id=w.teachers["陈师"],
                          swap_entry_id=opts[0]["entry_id"], swap_date=THU.isoformat(),
                          swap_period_no=first + 5)
    assert code == 409 and "不在这堂课的时段内" in body["detail"]


def _entry(w, teacher, subject, klass, period_idx):
    return w.place(teacher, subject, klass, period_idx)


def _find_entry(w, teacher: str, period_idx: int | None = None, weekday: int | None = None) -> int:
    """取某教师某节的 schedule_entry id(供 swap 目标)。"""
    from app.models.assignment import AssignmentTeacher, CourseAssignment
    from app.models.timetable import ScheduleEntry
    q = (w.db.query(ScheduleEntry)
         .join(CourseAssignment, ScheduleEntry.course_assignment_id == CourseAssignment.id)
         .join(AssignmentTeacher,
               AssignmentTeacher.course_assignment_id == CourseAssignment.id)
         .filter(AssignmentTeacher.teacher_id == w.teachers[teacher],
                 ScheduleEntry.timetable_id == w.tt))
    if period_idx is not None:
        q = q.filter(ScheduleEntry.period_no == w.wed[period_idx]["period_no"])
    if weekday is not None:
        q = q.filter(ScheduleEntry.weekday == weekday)
    return q.first().id
