"""提醒诊断:只读,按链一步步定位“为什么没收到提醒”。

用 special_days 的 _base:已发布周一第 1 节,王小明教 1 班数学。
"""

from app.models.user import Role
from app.services import reminder_diagnosis as diag
from app.services import settings as app_settings
from tests.dates import MON
from tests.test_special_days import _base, _login


def _configure(db):
    app_settings.save_dingtalk_app(db, "k", "s", "123", 15)
    db.commit()


def test_diagnose_all_ok_when_slot_and_binding_present(db):
    ctx = _base(db)
    _configure(db)
    ctx["t1"].dingtalk_userid = "u-wang"
    db.commit()
    d = diag.diagnose(db, ctx["sem"], ctx["t1"], MON, 1)
    by_key = {s.key: s for s in d.steps}
    assert by_key["app_configured"].status == "ok"
    assert by_key["timetable_published"].status == "ok"
    assert by_key["slot_exists"].status == "ok"
    assert "数学" in by_key["slot_exists"].detail
    assert by_key["phone"].status == "ok"
    assert by_key["dingtalk_userid"].status == "ok"
    assert by_key["window"].status == "ok"
    assert "08:00" in by_key["window"].detail
    # 测试环境 Redis 不在、也无发送记录,故提醒任务与发送记录两步是 warn 而非 ok;
    # 关键是没有任何 fail 步,结论应是“没有硬性断点”。
    assert all(s.status != "fail" for s in d.steps)
    assert "没有硬性断点" in d.conclusion


def test_diagnose_points_at_missing_phone_and_unbound(db):
    ctx = _base(db)
    _configure(db)
    # 王小明有手机号但未绑定:诊断会真查通讯录——未配置的 FakeClient 不适用,
    # 这里直接把手机号清空,断点应落在手机号一步,结论含该步。
    ctx["t1"].phone = ""
    db.commit()
    d = diag.diagnose(db, ctx["sem"], ctx["t1"], MON, 1)
    by_key = {s.key: s for s in d.steps}
    assert by_key["phone"].status == "fail"
    assert "手机号" in d.conclusion


def test_diagnose_no_slot_on_wrong_period(db):
    ctx = _base(db)
    _configure(db)
    ctx["t1"].dingtalk_userid = "u-wang"
    db.commit()
    d = diag.diagnose(db, ctx["sem"], ctx["t1"], MON, 5)
    by_key = {s.key: s for s in d.steps}
    assert by_key["slot_exists"].status == "fail"


def test_api_diagnose_and_test_send(monkeypatch, env):
    client, db = env
    ctx = _base(db)
    _configure(db)
    _login(client, db, roles=(Role.admin,), username="a")
    from tests.test_class_reminders import FakeClient

    # 诊断查通讯录只读:用假客户端,避免测试真连钉钉
    # (诊断服务在模块顶层 import 了客户端,故按它的模块名打补丁)
    monkeypatch.setattr(
        "app.services.reminder_diagnosis.DingTalkAppClient", lambda *a, **k: FakeClient({}))
    resp = client.get(
        "/api/settings/dingtalk-app/diagnose",
        params={"semester_id": ctx["sem"].id, "teacher_id": ctx["t1"].id,
                "on": str(MON), "period_no": 1},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["teacher_name"] == "王小明"
    assert any(s["key"] == "slot_exists" for s in body["steps"])

    # 测试发送:钉钉客户端换成 FakeClient(只记录,不真发)
    fake = FakeClient({"13800000000": "u-wang"})
    monkeypatch.setattr(
        "app.services.dingtalk_app.DingTalkAppClient", lambda *a, **k: fake)
    resp = client.post(
        "/api/settings/dingtalk-app/test-send",
        json={"teacher_id": ctx["t1"].id},
    )
    assert resp.status_code == 200, resp.text
    assert fake.sent and fake.sent[0][0] == "u-wang"
    assert fake.sent[0][1] == "测试提醒"

    # 通讯录里找不到人:400 且说清原因
    resp = client.post(
        "/api/settings/dingtalk-app/test-send",
        json={"teacher_id": ctx["t2"].id},
    )
    assert resp.status_code == 400
    assert "通讯录" in resp.json()["detail"]
