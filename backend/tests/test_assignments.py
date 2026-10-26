"""配课(M2-1)测试:单班/跑班/协同/连堂三种结构 + 五项验收标准。"""

import io

import pytest
from openpyxl import Workbook

from app.api.imports import XLSX_MIME
from app.models.user import Role
from tests.conftest import grant_grades, make_user

PW = "password123"


@pytest.fixture
def env2(env):
    """已登录教学组长 + 初中范本学期(含默认节次表与科目)。回传 (client, sid)。"""
    client, db = env
    grant_grades(db, make_user(db, "s", PW, roles=[Role.director]))
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    sem = client.post(
        "/api/semesters", json={"academic_year": 2026, "term": 1, "template_key": "junior_high"}
    ).json()
    return client, sem["id"]


def _subject(client, sid, name):
    return client.post(f"/api/subjects?semester_id={sid}", json={"name": name}).json()


def _teacher(client, sid, name, base=0):
    return client.post(
        f"/api/teachers?semester_id={sid}", json={"name": name, "base_periods": base}
    ).json()


def _class(client, sid, grade, name, track="junior_high", period_table_id=None):
    body = {"grade": grade, "name": name, "track": track}
    if period_table_id:
        body["period_table_id"] = period_table_id
    return client.post(f"/api/class-units?semester_id={sid}", json=body).json()


def _create_assignment(client, sid, **body):
    return client.post(f"/api/assignments?semester_id={sid}", json=body)


# ── 验收① 单班 + 跑班群组 ──────────────
def test_single_assignment(env2):
    """301 班 × 国文 × 王师 × 每周 5 节。"""
    client, sid = env2
    c = _class(client, sid, 3, "301")
    s = _subject(client, sid, "国文")
    t = _teacher(client, sid, "王师", 20)
    r = _create_assignment(
        client, sid, class_id=c["id"], subject_id=s["id"], periods_per_week=5,
        teachers=[{"teacher_id": t["id"]}],
    )
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["scheduling_unit"]["unit_type"] == "single"
    assert a["scheduling_unit"]["classes"][0]["id"] == c["id"]
    assert a["periods_per_week"] == 5
    assert a["teachers"][0]["is_lead"] is True


def test_group_five_courses(env2):
    """高二多元选修跑班群组(3 班),群组内建 5 笔配课。"""
    client, sid = env2
    cids = [_class(client, sid, 2, f"20{i}", track="senior_high")["id"] for i in (1, 2, 3)]
    g = client.post(
        f"/api/scheduling-units?semester_id={sid}",
        json={"name": "高二多元选修", "class_ids": cids},
    )
    assert g.status_code == 201, g.text
    gid = g.json()["id"]
    assert len(g.json()["classes"]) == 3
    for i in range(5):
        s = _subject(client, sid, f"选修{i}")
        t = _teacher(client, sid, f"选修师{i}")
        r = _create_assignment(
            client, sid, scheduling_unit_id=gid, subject_id=s["id"], periods_per_week=2,
            teachers=[{"teacher_id": t["id"]}],
        )
        assert r.status_code == 201, r.text
    items = client.get(f"/api/assignments?semester_id={sid}").json()
    group_items = [a for a in items if a["scheduling_unit"]["id"] == gid]
    assert len(group_items) == 5


# ── 验收② 协同 + 连堂 ─────────────────
def test_coteaching_with_block(env2):
    """机械科实习 × 2 位协同教师 × 每周 6 节含 3 连堂×2。"""
    client, sid = env2
    c = _class(client, sid, 1, "机械一", track="vocational")
    s = _subject(client, sid, "机械实习")
    t1 = _teacher(client, sid, "师甲")
    t2 = _teacher(client, sid, "师乙")
    r = _create_assignment(
        client, sid, class_id=c["id"], subject_id=s["id"], periods_per_week=6,
        teachers=[
            {"teacher_id": t1["id"], "is_lead": True},
            {"teacher_id": t2["id"], "is_lead": False},
        ],
        block_rules=[{"block_size": 3, "count_per_week": 2}],
    )
    assert r.status_code == 201, r.text
    a = r.json()
    assert len(a["teachers"]) == 2
    assert {t["name"] for t in a["teachers"]} == {"师甲", "师乙"}
    assert a["block_rules"][0]["block_size"] == 3
    assert a["block_rules"][0]["count_per_week"] == 2


# ── 验收③ 教师超课时 ─────────────────
def test_teacher_over_hours(env2):
    """王师配 22 节、基本课时 20 → delta +2。"""
    client, sid = env2
    t = _teacher(client, sid, "王师", 20)
    c = _class(client, sid, 3, "301")
    s = _subject(client, sid, "国文")
    _create_assignment(
        client, sid, class_id=c["id"], subject_id=s["id"], periods_per_week=22,
        teachers=[{"teacher_id": t["id"]}],
    )
    loads = client.get(f"/api/assignments/teacher-load?semester_id={sid}").json()
    wang = next(x for x in loads if x["teacher_id"] == t["id"])
    assert wang["assigned"] == 22
    assert wang["target"] == 20
    assert wang["delta"] == 2


def test_teacher_target_subtracts_admin_reduction(env2):
    """应授 = 基本课时 - 行政减课。"""
    client, sid = env2
    tr = client.post(
        f"/api/teachers?semester_id={sid}",
        json={"name": "组长", "base_periods": 20, "admin_reduction": 4},
    ).json()
    loads = client.get(f"/api/assignments/teacher-load?semester_id={sid}").json()
    row = next(x for x in loads if x["teacher_id"] == tr["id"])
    assert row["target"] == 16
    assert row["assigned"] == 0
    assert row["delta"] == -16


# ── 验收④ 班级配课超出可排节次 ────────
def test_class_over_capacity(env2):
    client, sid = env2
    c = _class(client, sid, 3, "305")
    s = _subject(client, sid, "国文")
    t = _teacher(client, sid, "师")
    # 先读该班可排节次数(capacity)
    cl = client.get(f"/api/assignments/class-load?semester_id={sid}").json()
    cap = next(x for x in cl if x["class_id"] == c["id"])["capacity"]
    assert cap > 0
    over = min(cap + 1, 40)
    _create_assignment(
        client, sid, class_id=c["id"], subject_id=s["id"], periods_per_week=over,
        teachers=[{"teacher_id": t["id"]}],
    )
    cl2 = client.get(f"/api/assignments/class-load?semester_id={sid}").json()
    row = next(x for x in cl2 if x["class_id"] == c["id"])
    assert row["assigned"] == over
    assert row["over_capacity"] is True


def test_class_load_counts_group_once(env2):
    """跑班群组的多门课同时段开课(H7),班级被占用的是最长的一笔,不是全部相加。

    3 门 3 节的选修同时开,班级只被占掉 3 节;若相加成 9 节,60 班规模的学校
    会满页误报「超出可排节数」。
    """
    client, sid = env2
    classes = [_class(client, sid, 2, f"20{i}") for i in (1, 2)]
    gr = client.post(
        f"/api/scheduling-units?semester_id={sid}",
        json={"name": "高二多元选修", "class_ids": [c["id"] for c in classes]},
    )
    assert gr.status_code == 201, gr.text
    group = gr.json()
    for name in ("选修甲", "选修乙", "选修丙"):
        s = _subject(client, sid, name)
        t = _teacher(client, sid, f"{name}师")
        r = _create_assignment(
            client, sid, scheduling_unit_id=group["id"], subject_id=s["id"],
            periods_per_week=3, teachers=[{"teacher_id": t["id"]}],
        )
        assert r.status_code == 201, r.text

    cl = client.get(f"/api/assignments/class-load?semester_id={sid}").json()
    for c in classes:
        row = next(x for x in cl if x["class_id"] == c["id"])
        assert row["assigned"] == 3, "跑班群组应计 3 节(同时段),而非 3 门 × 3 节 = 9"
        assert row["over_capacity"] is False


# ── 验收⑤ 跑班群组节次表须一致 ────────
def test_group_requires_same_period_table(env2):
    client, sid = env2
    pt2 = client.post(
        f"/api/semesters/{sid}/period-tables",
        json={"name": "高中部节次表", "template_key": "senior_high"},
    ).json()
    ca = _class(client, sid, 2, "甲")  # 用学期默认表
    cb = _class(client, sid, 2, "乙", period_table_id=pt2["id"])  # 用另一套表
    r = client.post(
        f"/api/scheduling-units?semester_id={sid}",
        json={"name": "跨表群组", "class_ids": [ca["id"], cb["id"]]},
    )
    assert r.status_code == 409


def test_group_same_table_ok(env2):
    client, sid = env2
    ca = _class(client, sid, 2, "甲")
    cb = _class(client, sid, 2, "乙")
    r = client.post(
        f"/api/scheduling-units?semester_id={sid}",
        json={"name": "同表群组", "class_ids": [ca["id"], cb["id"]]},
    )
    assert r.status_code == 201


# ── 验证与级联 ────────────────────────
def test_block_total_exceeds_rejected(env2):
    client, sid = env2
    c = _class(client, sid, 1, "甲")
    s = _subject(client, sid, "数学")
    t = _teacher(client, sid, "师")
    r = _create_assignment(
        client, sid, class_id=c["id"], subject_id=s["id"], periods_per_week=4,
        teachers=[{"teacher_id": t["id"]}],
        block_rules=[{"block_size": 3, "count_per_week": 2}],  # 6 > 4
    )
    assert r.status_code == 422


def test_target_xor_required(env2):
    client, sid = env2
    c = _class(client, sid, 1, "甲")
    s = _subject(client, sid, "数学")
    t = _teacher(client, sid, "师")
    both = _create_assignment(
        client, sid, class_id=c["id"], scheduling_unit_id=1, subject_id=s["id"],
        periods_per_week=1, teachers=[{"teacher_id": t["id"]}],
    )
    assert both.status_code == 422
    neither = _create_assignment(
        client, sid, subject_id=s["id"], periods_per_week=1,
        teachers=[{"teacher_id": t["id"]}],
    )
    assert neither.status_code == 422


def test_delete_group_cascades_assignments(env2):
    client, sid = env2
    cids = [_class(client, sid, 2, f"2{i}", track="senior_high")["id"] for i in (1, 2)]
    g = client.post(
        f"/api/scheduling-units?semester_id={sid}",
        json={"name": "群组X", "class_ids": cids},
    ).json()
    s = _subject(client, sid, "选修")
    t = _teacher(client, sid, "师")
    _create_assignment(
        client, sid, scheduling_unit_id=g["id"], subject_id=s["id"], periods_per_week=2,
        teachers=[{"teacher_id": t["id"]}],
    )
    assert client.delete(f"/api/scheduling-units/{g['id']}").status_code == 204
    assert client.get(f"/api/assignments?semester_id={sid}").json() == []


def test_single_unit_reused_across_assignments(env2):
    """同班多科配课共用同一 single 排课单位。"""
    client, sid = env2
    c = _class(client, sid, 3, "301")
    t = _teacher(client, sid, "师")
    ids = set()
    for name in ("国文", "数学"):
        s = _subject(client, sid, name)
        a = _create_assignment(
            client, sid, class_id=c["id"], subject_id=s["id"], periods_per_week=3,
            teachers=[{"teacher_id": t["id"]}],
        ).json()
        ids.add(a["scheduling_unit"]["id"])
    assert len(ids) == 1


# ── Excel 导入 ────────────────────────
def _xlsx(rows, ncols=7):
    wb = Workbook()
    ws = wb.active
    for _ in range(3):
        ws.append(["表头"] * ncols)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_import_assignments(env2):
    client, sid = env2
    _class(client, sid, 3, "301")
    _subject(client, sid, "国文")
    _teacher(client, sid, "王师")
    _teacher(client, sid, "李协")
    rows = [["301", "国文", "王师、李协", 6, 3, 2, ""]]
    r = client.post(
        f"/api/import/assignments?semester_id={sid}",
        files={"file": ("a.xlsx", _xlsx(rows), XLSX_MIME)},
    )
    assert r.json() == {"imported": 1, "updated": 0, "errors": []}
    items = client.get(f"/api/assignments?semester_id={sid}").json()
    assert len(items) == 1
    a = items[0]
    assert len(a["teachers"]) == 2
    assert a["teachers"][0]["is_lead"] is True  # 王师为主教
    assert a["block_rules"][0]["block_size"] == 3


def test_import_assignments_unknown_class_zero_write(env2):
    client, sid = env2
    _subject(client, sid, "国文")
    _teacher(client, sid, "王师")
    rows = [["不存在班", "国文", "王师", 5, "", "", ""]]
    body = client.post(
        f"/api/import/assignments?semester_id={sid}",
        files={"file": ("a.xlsx", _xlsx(rows), XLSX_MIME)},
    ).json()
    assert body["imported"] == 0
    assert any("班级" in e for e in body["errors"])
    assert client.get(f"/api/assignments?semester_id={sid}").json() == []


# ── 超课时上限(Phase 1)────────────────────────────────
# 上限的语意是「应授 + N」而非固定节数:应授本身因身分而异
# (台南市:国文专任 16、兼任导师 11、兼任主任 6),固定值对谁都不合适。


def _set_limit(client, db, n):
    """上限是校务政策,端点限管理员;测试里暂时切换身分再切回教学组长。"""
    make_user(db, "adm", PW, roles=[Role.admin])
    client.post("/api/auth/login", json={"username": "adm", "password": PW})
    r = client.put("/api/settings/scheduling", json={"max_overtime": n})
    assert r.status_code == 200
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    return r


def test_overtime_limit_defaults_to_8(env2):
    client, sid = env2
    _teacher(client, sid, "王师", base=11)
    loads = client.get(f"/api/assignments/teacher-load?semester_id={sid}").json()
    assert loads[0]["max_overtime"] == 8
    assert loads[0]["over_limit"] is False


def test_assignment_within_limit_is_accepted(env2):
    """国文导师应授 11,配到 19 节(刚好 +8)应该过——上限是「可以到」不是「不能到」。"""
    client, sid = env2
    _class(client, sid, 1, "101")
    subj = _subject(client, sid, "国文")
    t = _teacher(client, sid, "王师", base=11)
    r = _create_assignment(
        client, sid, class_id=_class(client, sid, 1, "102")["id"],
        subject_id=subj["id"], periods_per_week=19,
        teachers=[{"teacher_id": t["id"], "is_lead": True}],
    )
    assert r.status_code == 201
    load = client.get(f"/api/assignments/teacher-load?semester_id={sid}").json()[0]
    assert load["assigned"] == 19 and load["delta"] == 8
    assert load["over_limit"] is False


def test_assignment_over_limit_is_rejected_and_not_written(env2):
    client, sid = env2
    cu = _class(client, sid, 1, "101")
    subj = _subject(client, sid, "国文")
    t = _teacher(client, sid, "王师", base=11)
    r = _create_assignment(
        client, sid, class_id=cu["id"], subject_id=subj["id"], periods_per_week=20,
        teachers=[{"teacher_id": t["id"], "is_lead": True}],
    )
    assert r.status_code == 409
    assert "王师" in r.json()["detail"] and "上限 8 节" in r.json()["detail"]
    # 被挡下时不可留下半笔资料
    assert client.get(f"/api/assignments?semester_id={sid}").json() == []


def test_overtime_limit_accumulates_across_assignments(env2):
    """单笔都不超标,但加起来超标——检核看的是教师的总量,不是单笔。"""
    client, sid = env2
    subj = _subject(client, sid, "国文")
    t = _teacher(client, sid, "王师", base=11)
    # 11+10=21(+10)才超标;19 节(+8)是允许的上界
    for name, periods, expected in [("101", 10, 201), ("102", 10, 409)]:
        cu = _class(client, sid, 1, name)
        r = _create_assignment(
            client, sid, class_id=cu["id"], subject_id=subj["id"],
            periods_per_week=periods,
            teachers=[{"teacher_id": t["id"], "is_lead": True}],
        )
        assert r.status_code == expected


def test_admin_reduction_lowers_the_ceiling(env2):
    """兼任主任应授 6(18−12),上限即 6+8=14 节。"""
    client, sid = env2
    cu = _class(client, sid, 1, "101")
    subj = _subject(client, sid, "国文")
    t = client.post(
        f"/api/teachers?semester_id={sid}",
        json={"name": "陈主任", "base_periods": 18, "admin_reduction": 12},
    ).json()
    ok = _create_assignment(
        client, sid, class_id=cu["id"], subject_id=subj["id"], periods_per_week=14,
        teachers=[{"teacher_id": t["id"], "is_lead": True}],
    )
    assert ok.status_code == 201
    over = _create_assignment(
        client, sid, class_id=_class(client, sid, 1, "102")["id"],
        subject_id=subj["id"], periods_per_week=1,
        teachers=[{"teacher_id": t["id"], "is_lead": True}],
    )
    assert over.status_code == 409


def test_limit_zero_disables_the_check(env, env2):
    client, db = env
    _, sid = env2
    _set_limit(client, db, 0)
    cu = _class(client, sid, 1, "101")
    subj = _subject(client, sid, "国文")
    t = _teacher(client, sid, "王师", base=11)
    r = _create_assignment(
        client, sid, class_id=cu["id"], subject_id=subj["id"], periods_per_week=30,
        teachers=[{"teacher_id": t["id"], "is_lead": True}],
    )
    assert r.status_code == 201
    assert client.get(
        f"/api/assignments/teacher-load?semester_id={sid}"
    ).json()[0]["over_limit"] is False


def test_configured_limit_is_honoured(env, env2):
    client, db = env
    _, sid = env2
    _set_limit(client, db, 2)
    cu = _class(client, sid, 1, "101")
    subj = _subject(client, sid, "国文")
    t = _teacher(client, sid, "王师", base=11)
    r = _create_assignment(
        client, sid, class_id=cu["id"], subject_id=subj["id"], periods_per_week=14,
        teachers=[{"teacher_id": t["id"], "is_lead": True}],
    )
    assert r.status_code == 409 and "上限 2 节" in r.json()["detail"]


def test_teacher_without_base_periods_is_not_capped(env2):
    """没填基本课时(默认 0)的教师不受管制。

    很多学校不维护基钟栏位。若把「应授 0」当真,这些学校一升级就会发现
    所有超过 8 节的配课全被挡下——等于系统坏掉。
    """
    client, sid = env2
    cu = _class(client, sid, 1, "101")
    subj = _subject(client, sid, "国文")
    t = _teacher(client, sid, "王师")  # base_periods 未填 → 0
    r = _create_assignment(
        client, sid, class_id=cu["id"], subject_id=subj["id"], periods_per_week=30,
        teachers=[{"teacher_id": t["id"], "is_lead": True}],
    )
    assert r.status_code == 201
    load = client.get(f"/api/assignments/teacher-load?semester_id={sid}").json()[0]
    assert load["delta"] == 30 and load["over_limit"] is False


def test_import_over_limit_writes_nothing(env2):
    """导入是一次几百笔的操作,超标时整批不进,不可留下一半。"""
    client, sid = env2
    _class(client, sid, 1, "101")
    _subject(client, sid, "国文")
    _teacher(client, sid, "王师", base=11)
    body = client.post(
        f"/api/import/assignments?semester_id={sid}",
        files={"file": ("a.xlsx", _xlsx([["101", "国文", "王师", 20, "", "", ""]]), XLSX_MIME)},
    ).json()
    assert body["imported"] == 0
    assert any("上限 8 节" in e for e in body["errors"])
    assert client.get(f"/api/assignments?semester_id={sid}").json() == []
