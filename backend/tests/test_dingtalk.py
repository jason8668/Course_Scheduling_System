"""个人钉钉:设置读写、通知一对一推送。

群机器人已于 2026-11-06 停用:群里不再发任何消息,群 Webhook 配置保留未删,
但不再有任何代码路径往群里发消息(本文件断言 send_dingtalk 已不存在、
群测试接口已下线)。请假、调代课、课表发布、月度课时确认等通知,全部一对一
发给相关老师本人的个人钉钉(企业内部应用工作通知)。

不连真实钉钉:monkeypatch notifications.DingTalkAppClient 拦截发送。
"""

import pytest

from app.models.basedata import Teacher
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


def _fake_client_factory(sent, lookups):
    """拦截企业应用:按手机号查 userid 只认一支测试号,其余回 None。"""
    class FakeClient:
        def __init__(self, app_key, app_secret, agent_id):
            self.app_key = app_key

        def get_userid(self, mobile):
            lookups.append(mobile)
            return {"13800000000": "U-chen"}.get(mobile)

        def send_work_notification(self, userid, title, text):
            sent.append((userid, title, text))

    return FakeClient


@pytest.fixture
def app_configured(admin, monkeypatch):
    """配好企业应用三件套 + 拦截发送;回传 (sent, lookups)。"""
    _client, db = admin
    sent: list = []
    lookups: list = []
    monkeypatch.setattr(
        notif, "DingTalkAppClient", _fake_client_factory(sent, lookups))
    app_settings.save_dingtalk_app(
        db, app_key="KEY", app_secret="SEC", agent_id="123", lead_minutes=15)
    db.commit()
    return sent, lookups


def _semester_and_teacher(admin):
    client, db = admin
    client.post("/api/semesters", json={
        "academic_year": 2026, "term": 1, "template_key": "junior_high",
        "start_date": SEM_START.isoformat(), "end_date": SEM_END.isoformat(),
    })
    sid = client.get("/api/semesters").json()[0]["id"]
    teacher = client.post(f"/api/teachers?semester_id={sid}", json={"name": "王小明"}).json()
    return sid, teacher["id"]


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

    # 清空 webhook = 停用(配置保留,只是没东西可发)
    r = client.put("/api/settings/dingtalk", json={"webhook": "", "secret": ""})
    assert r.json()["configured"] is False


def test_no_group_send_path_left(admin):
    """群发送已彻底停用:群发送函数不存在、通道里没有群、群测试接口已下线。"""
    client, _db = admin
    assert not hasattr(notif, "send_dingtalk")
    assert not hasattr(notif, "dingtalk_signed_url")
    assert "dingtalk" not in [c.key for c in notif.CHANNELS]
    assert "personal_dingtalk" in [c.key for c in notif.CHANNELS]
    r = client.post("/api/settings/dingtalk/test", json={})
    assert r.status_code == 404


def test_notification_goes_to_personal_dingtalk(admin, app_configured):
    sent, _lookups = app_configured
    client, db = admin
    sid, teacher_id = _semester_and_teacher(admin)
    teacher = db.get(Teacher, teacher_id)
    teacher.dingtalk_userid = "U-wang"
    db.commit()

    # 直接走服务层验证一对一推送:调课/代课类型 notify + commit 后应推一次
    from app.models.notification import NotificationType
    notif.notify(db, semester_id=sid, teacher_id=teacher_id,
                 type=NotificationType.substitution_assigned, title="代课通知", body="内容摘要")
    db.commit()
    assert len(sent) == 1
    userid, title, text = sent[0]
    assert userid == "U-wang"
    assert "代课通知" in title and "内容摘要" in text
    # 措辞原样推送,不再贴“相关教师:”标
    assert "相关教师:" not in text


def test_personal_message_keeps_user_wording(admin, app_configured):
    sent, _lookups = app_configured
    client, db = admin
    sid, teacher_id = _semester_and_teacher(admin)
    teacher = db.get(Teacher, teacher_id)
    teacher.dingtalk_userid = "U-wang"
    db.commit()

    # 个人钉钉正文原样推送:第一句说清谁代谁的课,正文里没有第二人称“您”
    from app.models.notification import NotificationType
    notif.notify(db, semester_id=sid, teacher_id=teacher_id,
                 type=NotificationType.substitution_assigned,
                 title="代课通知",
                 body="10月30日 第1节,七年级1班《数学》,王小明老师调课,由李小红老师代课。")
    db.commit()
    assert len(sent) == 1
    assert "由李小红老师代课" in sent[0][2]
    assert "相关教师:" not in sent[0][2]
    assert "您" not in sent[0][2]


def test_leave_goes_to_personal_dingtalk(admin, app_configured):
    """新规则:请假登记与销假也发给相关老师本人的个人钉钉,不再只留站内。"""
    sent, _lookups = app_configured
    client, db = admin
    sid, teacher_id = _semester_and_teacher(admin)
    teacher = db.get(Teacher, teacher_id)
    teacher.dingtalk_userid = "U-wang"
    db.commit()

    from app.models.notification import NotificationType
    notif.notify(db, semester_id=sid, teacher_id=teacher_id,
                 type=NotificationType.leave_registered, title="请假已登记", body="")
    notif.notify(db, semester_id=sid, teacher_id=teacher_id,
                 type=NotificationType.leave_cancelled, title="销假完成", body="")
    db.commit()
    assert len(sent) == 2
    assert {s[0] for s in sent} == {"U-wang"}


def test_teacher_without_userid_resolved_by_mobile(admin, app_configured):
    """老师没缓存 userid 但有手机号:寄出阶段按手机号查一次,查到就发。"""
    sent, lookups = app_configured
    client, db = admin
    sid, teacher_id = _semester_and_teacher(admin)
    teacher = db.get(Teacher, teacher_id)
    teacher.phone = "13800000000"
    db.commit()

    from app.models.notification import NotificationType
    notif.notify(db, semester_id=sid, teacher_id=teacher_id,
                 type=NotificationType.substitution_assigned, title="代课通知", body="")
    db.commit()
    assert lookups == ["13800000000"]
    assert len(sent) == 1 and sent[0][0] == "U-chen"


def test_teacher_without_any_contact_skipped(admin, app_configured):
    """既无 userid 又无手机号:个人钉钉跳过,但站内通知照常写。"""
    sent, _lookups = app_configured
    client, db = admin
    sid, teacher_id = _semester_and_teacher(admin)

    from app.models.notification import Notification, NotificationType
    notif.notify(db, semester_id=sid, teacher_id=teacher_id,
                 type=NotificationType.substitution_assigned, title="代课通知", body="")
    db.commit()
    assert sent == []
    assert db.query(Notification).filter_by(teacher_id=teacher_id).count() == 1


def test_no_app_config_no_personal_push(admin, monkeypatch):
    """未配企业应用:个人钉钉不发,站内通知照常。"""
    client, db = admin
    sent: list = []
    monkeypatch.setattr(
        notif, "DingTalkAppClient", _fake_client_factory(sent, []))
    sid, teacher_id = _semester_and_teacher(admin)
    teacher = db.get(Teacher, teacher_id)
    teacher.dingtalk_userid = "U-wang"
    db.commit()

    from app.models.notification import Notification, NotificationType
    notif.notify(db, semester_id=sid, teacher_id=teacher_id,
                 type=NotificationType.substitution_assigned, title="代课通知", body="")
    db.commit()
    assert sent == []
    assert db.query(Notification).filter_by(teacher_id=teacher_id).count() == 1
