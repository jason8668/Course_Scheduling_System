"""Excel 导入测试。对应 M1-3 验收标准。"""

import io

import pytest
from openpyxl import Workbook

from app.api.imports import XLSX_MIME
from app.models.user import Role
from tests.conftest import grant_grades, make_user

PW = "password123"


@pytest.fixture
def scheduler_env(env):
    client, db = env
    grant_grades(db, make_user(db, "s", PW, roles=[Role.director]))
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    sem = client.post("/api/semesters", json={"academic_year": 2026, "term": 1}).json()
    return client, sem["id"]


def make_xlsx(data_rows: list[list], ncols: int = 8) -> bytes:
    """建立含 3 列表头(栏名/说明/范例)+ 资料列的 xlsx。"""
    wb = Workbook()
    ws = wb.active
    ws.append(["栏名"] * ncols)
    ws.append(["说明"] * ncols)
    ws.append(["范例"] * ncols)
    for r in data_rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def upload(client, entity, sid, data_rows, ncols=8, create_accounts=False,
           update_existing=False):
    content = make_xlsx(data_rows, ncols)
    url = f"/api/import/{entity}?semester_id={sid}"
    if create_accounts:
        url += "&create_accounts=true"
    if update_existing:
        url += "&update_existing=true"
    return client.post(url, files={"file": ("t.xlsx", content, XLSX_MIME)})


def test_download_template(scheduler_env):
    client, _ = scheduler_env
    for entity in ("subjects", "teachers", "classes"):
        r = client.get(f"/api/import/templates/{entity}")
        assert r.status_code == 200
        assert r.headers["content-type"] == XLSX_MIME
        assert len(r.content) > 0


def test_import_subjects_ok(scheduler_env):
    client, sid = scheduler_env
    rows = [["数学", "数学领域", "普通教室", 1], ["物理", "自然", "专科教室", 2]]
    r = upload(client, "subjects", sid, rows, ncols=4)
    assert r.status_code == 200
    assert r.json() == {"imported": 2, "updated": 0, "errors": []}
    assert len(client.get(f"/api/subjects?semester_id={sid}").json()) == 2


def test_import_subjects_invalid_room_type_zero_write(scheduler_env):
    """验收②:错误回报列号,资料库零写入。"""
    client, sid = scheduler_env
    rows = [["数学", "", "普通教室", 1], ["体育", "", "操场外", 1]]  # 第 5 列场地类型无效
    r = upload(client, "subjects", sid, rows, ncols=4)
    body = r.json()
    assert body["imported"] == 0
    assert any("第 5 列" in e and "场地类型" in e for e in body["errors"])
    # 零写入:连合法的第 4 列也未写入
    assert client.get(f"/api/subjects?semester_id={sid}").json() == []


def test_import_teachers_with_accounts(scheduler_env):
    """验收①:导入教师、建立帐号、任教科目关联。"""
    client, sid = scheduler_env
    client.post(f"/api/subjects?semester_id={sid}", json={"name": "数学"})
    client.post(f"/api/subjects?semester_id={sid}", json={"name": "物理"})
    rows = [
        ["王小明", "1234", "数学、物理", 20, "教学组长", 4, "否", "wang001"],
        ["李小华", "5678", "数学", 18, "", "", "是", "lee001"],
    ]
    r = upload(client, "teachers", sid, rows, create_accounts=True)
    assert r.json()["imported"] == 2
    teachers = client.get(f"/api/teachers?semester_id={sid}").json()
    wang = next(t for t in teachers if t["name"] == "王小明")
    assert {s["name"] for s in wang["subjects"]} == {"数学", "物理"}
    # 帐号已建立,可用默认密码登录(首登需改密)
    client.post("/api/auth/logout")
    login = client.post("/api/auth/login", json={"username": "wang001", "password": "admin"})
    assert login.status_code == 200
    assert login.json()["must_change_password"] is True


def test_import_teachers_duplicate_name_id4(scheduler_env):
    client, sid = scheduler_env
    rows = [["王小明", "1234", "", "", "", "", "", ""], ["王小明", "1234", "", "", "", "", "", ""]]
    r = upload(client, "teachers", sid, rows)
    body = r.json()
    assert body["imported"] == 0
    assert any("重复" in e for e in body["errors"])
    assert client.get(f"/api/teachers?semester_id={sid}").json() == []


# ── 以导入批次更新既有教师(用户回报 #18)────────────────
# 栏序:姓名/末四码/任教科目/基本课时/行政职称/行政减课/外聘/登录帐号/Email/手机/LINE
def _teacher_row(name, id4, subj="", base="", title="", reduction="", external="", acc="",
                 email="", phone="", line=""):
    return [name, id4, subj, base, title, reduction, external, acc, email, phone, line]


def _seed_wang(client, sid):
    """系统里既有的王小明:教学组长、减课 4、课时 20、教数学。"""
    client.post(f"/api/subjects?semester_id={sid}", json={"name": "数学"})
    client.post(f"/api/subjects?semester_id={sid}", json={"name": "物理"})
    rows = [_teacher_row("王小明", "1234", "数学", 20, "教学组长", 4, "否", "", "w@a.edu.tw")]
    assert upload(client, "teachers", sid, rows, ncols=11).json()["imported"] == 1
    return next(t for t in client.get(f"/api/teachers?semester_id={sid}").json()
                if t["name"] == "王小明")


def test_import_teachers_updates_existing_when_opted_in(scheduler_env):
    """新学年职务异动:同一份名册再导入一次,既有教师改为更新而不是报错。"""
    client, sid = scheduler_env
    before = _seed_wang(client, sid)

    rows = [
        # 王小明卸任组长、课时改 22、加教物理;空白的 Email 不应被洗掉
        _teacher_row("王小明", "1234", "数学、物理", 22, "无", 0, "", "", ""),
        _teacher_row("李小华", "5678", "数学", 18),  # 新人照旧新增
    ]
    body = upload(client, "teachers", sid, rows, ncols=11, update_existing=True).json()
    assert body == {"imported": 1, "updated": 1, "errors": []}

    teachers = client.get(f"/api/teachers?semester_id={sid}").json()
    assert len(teachers) == 2
    wang = next(t for t in teachers if t["name"] == "王小明")
    assert wang["id"] == before["id"]              # 是更新,不是新建一笔
    assert wang["admin_title"] in (None, "")        # 「无」= 卸任
    assert (wang["base_periods"], wang["admin_reduction"]) == (22, 0)
    assert {s["name"] for s in wang["subjects"]} == {"数学", "物理"}
    assert wang["email"] == "w@a.edu.tw"            # 空白栏位保留原值


def test_import_teachers_blank_cells_keep_existing_values(scheduler_env):
    """只想改行政职称时,其他栏位留空不该被清掉。"""
    client, sid = scheduler_env
    _seed_wang(client, sid)
    rows = [_teacher_row("王小明", "1234", "", "", "辅导主任")]
    assert upload(client, "teachers", sid, rows, ncols=11,
                  update_existing=True).json()["updated"] == 1
    wang = next(t for t in client.get(f"/api/teachers?semester_id={sid}").json()
                if t["name"] == "王小明")
    assert wang["admin_title"] == "辅导主任"
    assert (wang["base_periods"], wang["admin_reduction"]) == (20, 4)
    assert {s["name"] for s in wang["subjects"]} == {"数学"}
    assert wang["email"] == "w@a.edu.tw"


def test_import_teachers_without_opt_in_still_rejects_duplicates(scheduler_env):
    """没有勾选更新时维持原行为:既有教师视为重复、整批不写入。"""
    client, sid = scheduler_env
    _seed_wang(client, sid)
    rows = [_teacher_row("王小明", "1234", "", 22)]
    body = upload(client, "teachers", sid, rows, ncols=11).json()
    assert body["imported"] == 0 and body["updated"] == 0
    assert any("重复" in e for e in body["errors"])
    wang = next(t for t in client.get(f"/api/teachers?semester_id={sid}").json()
                if t["name"] == "王小明")
    assert wang["base_periods"] == 20  # 未被更动


def test_import_teachers_update_mode_still_rejects_duplicate_rows(scheduler_env):
    """同一个档案里出现两次同一位老师仍是错误(不知道该听哪一列)。"""
    client, sid = scheduler_env
    _seed_wang(client, sid)
    rows = [_teacher_row("王小明", "1234", "", 22), _teacher_row("王小明", "1234", "", 24)]
    body = upload(client, "teachers", sid, rows, ncols=11, update_existing=True).json()
    assert body["updated"] == 0
    assert any("重复" in e for e in body["errors"])


def test_import_teachers_update_does_not_touch_login_account(scheduler_env):
    """既有教师的登录帐号不在导入时建立(避免误建);新教师仍可建立。"""
    client, sid = scheduler_env
    _seed_wang(client, sid)
    rows = [
        _teacher_row("王小明", "1234", "", 22, "", "", "", "wang001"),
        _teacher_row("陈小美", "9999", "数学", 18, "", "", "", "chen001"),
    ]
    body = upload(client, "teachers", sid, rows, ncols=11,
                  create_accounts=True, update_existing=True).json()
    assert body == {"imported": 1, "updated": 1, "errors": []}
    teachers = client.get(f"/api/teachers?semester_id={sid}").json()
    wang = next(t for t in teachers if t["name"] == "王小明")
    chen = next(t for t in teachers if t["name"] == "陈小美")
    assert wang["user_id"] is None      # 既有教师不会被偷建帐号
    assert chen["user_id"] is not None  # 新教师照旧


def test_import_teachers_unknown_subject(scheduler_env):
    client, sid = scheduler_env
    rows = [["王小明", "", "不存在的科目", "", "", "", "", ""]]
    body = upload(client, "teachers", sid, rows).json()
    assert body["imported"] == 0
    assert any("科目" in e for e in body["errors"])


def test_import_classes_with_homeroom(scheduler_env):
    """验收③相关:班级导入,导师以姓名对应。"""
    client, sid = scheduler_env
    client.post(f"/api/teachers?semester_id={sid}", json={"name": "陈老师"})
    rows = [["1", "甲", "技术型高中", "机械科", "陈老师", 35]]
    r = upload(client, "classes", sid, rows, ncols=6)
    assert r.json()["imported"] == 1
    cu = client.get(f"/api/class-units?semester_id={sid}").json()[0]
    assert cu["department"] == "机械科"
    assert cu["homeroom_teacher"]["name"] == "陈老师"


def test_import_classes_unknown_homeroom(scheduler_env):
    client, sid = scheduler_env
    rows = [["1", "甲", "小学", "", "查无此人", ""]]
    body = upload(client, "classes", sid, rows, ncols=6).json()
    assert body["imported"] == 0
    assert any("班主任" in e for e in body["errors"])


def test_import_invalid_file_rejected(scheduler_env):
    client, sid = scheduler_env
    r = client.post(
        f"/api/import/subjects?semester_id={sid}",
        files={"file": ("bad.xlsx", b"not an excel file", XLSX_MIME)},
    )
    assert r.status_code == 400
