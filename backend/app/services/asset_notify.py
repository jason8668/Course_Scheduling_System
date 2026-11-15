"""资产钉钉通知推送(学校资产管理系统一期 #7)。

复用系统现有钉钉企业应用客户端(services.dingtalk_students.get_client),
不另建钉钉客户端。收件人解析:User → Teacher(user_id 绑定) →
dingtalk_userid(已缓存)或 phone → get_userid 查钉钉 userid。

推送失败只记日志、不阻塞业务:任何一步异常都捕获并返回 False,
呼叫端继续走站内提醒(AssetReminder),业务流程不受影响。
未配置钉钉应用 / 用户无手机号 / 查不到 userid 时同样只记日志跳过。
"""

import logging

from sqlalchemy.orm import Session

from app.models.basedata import Teacher
from app.models.user import User

logger = logging.getLogger(__name__)


def resolve_dingtalk_userid(db: Session, user_id: int) -> str | None:
    """取某用户的钉钉 userid:缓存优先,否则按教师手机号查询。"""
    teacher = db.query(Teacher).filter_by(user_id=user_id).first()
    if teacher is None:
        return None
    if teacher.dingtalk_userid:
        return teacher.dingtalk_userid
    if not teacher.phone:
        return None
    try:
        from app.services import dingtalk_students

        client = dingtalk_students.get_client(db)
        userid = client.get_userid(teacher.phone)
    except Exception as exc:  # noqa: BLE001 - 推送辅助路径,失败只记日志
        logger.warning("钉钉解析 userid 失败(user_id=%s):%s", user_id, exc)
        return None
    if userid:
        teacher.dingtalk_userid = userid
        db.flush()
    return userid


def push_asset_notice(
    db: Session, user_ids: list[int], title: str, text: str
) -> dict[str, object]:
    """向若干用户推一则钉钉工作通知。返回 {sent, skipped, failed}。

    未配置 / 无收件人 / 发送失败均不抛错,只记日志。
    """
    sent, skipped, failed = 0, 0, 0
    if not user_ids:
        return {"sent": 0, "skipped": 0, "failed": 0}
    try:
        from app.services import dingtalk_students

        client = dingtalk_students.get_client(db)
    except Exception as exc:  # noqa: BLE001 - 未配置钉钉时只记日志
        logger.warning("钉钉推送跳过(未配置或取客户端失败):%s", exc)
        return {"sent": 0, "skipped": len(user_ids), "failed": 0}
    for user_id in user_ids:
        try:
            userid = resolve_dingtalk_userid(db, user_id)
            if not userid:
                skipped += 1
                continue
            client.send_work_notification(userid, title, text)
            sent += 1
        except Exception as exc:  # noqa: BLE001 - 单人失败不影响其他人
            failed += 1
            logger.warning("钉钉推送失败(user_id=%s):%s", user_id, exc)
    return {"sent": sent, "skipped": skipped, "failed": failed}


def push_to_role(db: Session, role: str, title: str, text: str) -> dict[str, object]:
    """向持有某角色的全部用户推送(审批待办用);失败不阻塞。"""
    from app.models.user import UserRole

    rows = db.query(UserRole).filter_by(role=role).all()
    user_ids = sorted({r.user_id for r in rows})
    if not user_ids:
        return {"sent": 0, "skipped": 0, "failed": 0}
    return push_asset_notice(db, user_ids, title, text)


def push_to_user(db: Session, user_id: int, title: str, text: str) -> dict[str, object]:
    return push_asset_notice(db, [user_id], title, text)
