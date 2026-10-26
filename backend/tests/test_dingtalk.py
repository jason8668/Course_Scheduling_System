"""钉钉群机器人:设置读写、加签、通知广播、测试发送。

不连真实钉钉:monkeypatch notifications.send_dingtalk 拦截发送。
"""

import pytest

from app.models.user import Role
from app.services import notifications as notif
from app.services import settings as app_settings
from tests.conftest import make_user
from tests.dates import SEM_END, SEM_START

PW = "password123"
HOOK = "https://oapi.dingtalk.com/robot/send?access_token=abc123"


@pytest.fixture
def admin(env):
    client, db = env
    make_user(db, "admin1", PW, roles=[Role.admin])
    client.post("/api/auth/login", json={"username": "admin1", "password": PW})
    return client, db


def test_dingtalk_settings_roundtrip(admin):
    client, db = admin
    r = client.get("/api/settings/dingtalk")
    assert r.status_code == 200
    assert r.json() == {"webhook": "", "configured": False, "has_secret": False}

    r = client.put("/api/settings/dingtalk", json={"webhook": HOOK, "secret": "SECxyz"})
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is True and body["has_secret"] is True
    assert "SECxyz" not in r.text  # 密钥不明文回传

    # 密钥留空 = 不变更
    r = client.put("/api/settings/dingtalk", json={"webhook": HOOK, "secret": ""})
    assert r.json()["has_secret"] is True
    cfg = app_settings.dingtalk_config(db)
    assert cfg.webhook == HOOK and cfg.secret == "SECxyz"

    # 清空 webhook = 停用
    r = client.put("/api/settings/dingtalk", json={"webhook": "", "secret": ""})
    assert r.json()["configured"] is False


def test_dingtalk_signing():
    url = notif.dingtalk_signed_url(HOOK, "")
    assert url == HOOK  # 无密钥不加签
    url = notif.dingtalk_signed_url(HOOK, "SECxyz")
    assert "timestamp=" in url and "sign=" in url and url.startswith(HOOK + "&")


def test_notification_broadcasts_to_dingtalk(admin, monkeypatch):
    client, db = admin
    sent: list[tuple[str, str, str, str]] = []
    monkeypatch.setattr(
        notif, "send_dingtalk",
        lambda webhook, secret, title, text: sent.append((webhook, secret, title, text)),
    )
    app_settings.save_dingtalk(db, webhook=HOOK, secret="SECxyz")
    db.commit()

    client.post("/api/semesters", json={
        "academic_year": 2026, "term": 1, "template_key": "junior_high",
        "start_date": SEM_START.isoformat(), "end_date": SEM_END.isoformat(),
    })
    sid = client.get("/api/semesters").json()[0]["id"]
    teacher = client.post(f"/api/teachers?semester_id={sid}", json={"name": "王小明"}).json()

    sent.clear()
    # 直接走服务层验证广播:调课/代课类型 notify + commit 后应 POST 一次
    from app.models.notification import NotificationType
    notif.notify(db, semester_id=sid, teacher_id=teacher["id"],
                 type=NotificationType.substitution_assigned, title="代课通知", body="内容摘要")
    db.commit()
    assert len(sent) == 1
    webhook, secret, title, text = sent[0]
    assert webhook == HOOK and secret == "SECxyz"
    assert "代课通知" in title and "内容摘要" in text


def test_leave_does_not_broadcast_to_dingtalk(admin, monkeypatch):
    client, db = admin
    sent: list = []
    monkeypatch.setattr(
        notif, "send_dingtalk",
        lambda *a, **k: sent.append(a),
    )
    app_settings.save_dingtalk(db, webhook=HOOK, secret="SECxyz")
    db.commit()

    client.post("/api/semesters", json={
        "academic_year": 2026, "term": 1, "template_key": "junior_high",
        "start_date": SEM_START.isoformat(), "end_date": SEM_END.isoformat(),
    })
    sid = client.get("/api/semesters").json()[0]["id"]
    teacher = client.post(f"/api/teachers?semester_id={sid}", json={"name": "王小明"}).json()

    # 请假登记与销假:站内通知照常写,但一律不进钉钉群
    from app.models.notification import NotificationType
    notif.notify(db, semester_id=sid, teacher_id=teacher["id"],
                 type=NotificationType.leave_registered, title="请假已登记", body="")
    notif.notify(db, semester_id=sid, teacher_id=teacher["id"],
                 type=NotificationType.leave_cancelled, title="销假完成", body="")
    db.commit()
    assert sent == []


def test_no_webhook_no_broadcast(admin, monkeypatch):
    client, db = admin
    calls: list = []
    monkeypatch.setattr(notif, "send_dingtalk", lambda *a, **k: calls.append(a))
    sid = client.post("/api/semesters", json={
        "academic_year": 2026, "term": 1, "template_key": "junior_high",
        "start_date": SEM_START.isoformat(), "end_date": SEM_END.isoformat(),
    }).json()["id"]
    from app.models.notification import NotificationType
    notif.notify(db, semester_id=sid, teacher_id=None,
                 type=NotificationType.substitution_assigned, title="无广播", body="")
    db.commit()
    assert calls == []


def test_dingtalk_test_endpoint(admin, monkeypatch):
    client, db = admin
    # 未设置 → 400
    r = client.post("/api/settings/dingtalk/test", json={})
    assert r.status_code == 400

    sent: list = []
    monkeypatch.setattr(
        "app.services.notifications.send_dingtalk",
        lambda webhook, secret, title, text: sent.append((webhook, title)),
    )
    r = client.post("/api/settings/dingtalk/test", json={"webhook": HOOK, "secret": ""})
    assert r.status_code == 200 and r.json()["sent"] is True
    assert sent and sent[0][0] == HOOK
