"""教师「我的」页后端:个人上课提醒自配置(只给教师本人用)。

解析复用 teachers.current_teacher;未绑定教师档案时 GET 回默认值
(与 notifications/mine 回空清单同一惯例:不报错,让页面显示提示),
PUT 则 404。手机号变了要清空已缓存的 dingtalk_userid,
保存时立刻按新手机号匹配一次钉钉(Jason 2026-10-30 定):
绑上当场显示已绑定,查不到也不让保存失败(仍回未绑定,提醒时再跳过)。
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.core.auth import get_active_user
from app.core.db import get_db
from app.models.user import User
from app.schemas.teacher_home import ReminderPreferenceIn, ReminderPreferenceOut
from app.services import settings as app_settings
from app.services.teachers import current_teacher

router = APIRouter(tags=["teachers"])


def _out(db: Session, teacher, *, bound: bool) -> ReminderPreferenceOut:
    cfg = app_settings.dingtalk_app_config(db)
    return ReminderPreferenceOut(
        bound=bound,
        reminder_enabled=True if teacher is None else bool(teacher.reminder_enabled),
        reminder_lead_minutes=None if teacher is None else teacher.reminder_lead_minutes,
        global_lead_minutes=cfg.lead_minutes,
        phone=None if teacher is None else teacher.phone,
        dingtalk_bound=bool(teacher and teacher.dingtalk_userid),
    )


@router.get("/teachers/me/reminder-preference", response_model=ReminderPreferenceOut)
def get_reminder_preference(
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """本人提醒自配置;未绑定教师档案回默认值 + bound=False。"""
    me = current_teacher(db, user, semester_id)
    return _out(db, me, bound=me is not None)


@router.put("/teachers/me/reminder-preference", response_model=ReminderPreferenceOut)
def put_reminder_preference(
    body: ReminderPreferenceIn,
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """保存本人提醒自配置;未绑定教师档案 404。"""
    me = current_teacher(db, user, semester_id)
    if me is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未绑定教师档案")
    me.reminder_enabled = body.reminder_enabled
    if "reminder_lead_minutes" in body.model_fields_set:
        me.reminder_lead_minutes = body.reminder_lead_minutes
    if "phone" in body.model_fields_set:
        new_phone = (body.phone or "").strip() or None
        if new_phone != me.phone:
            me.phone = new_phone
            me.dingtalk_userid = None  # 号码变了,先清空,下面保存时立刻重新匹配
    db.commit()
    db.refresh(me)
    # 保存时立刻匹配一次:手机号已填、尚未缓存 userid、且钉钉应用已配置时,
    # 当场按手机号查企业通讯录,查到就缓存,页面马上显示已绑定,不用等到下一节课。
    # 查不到(不在通讯录)或钉钉调用失败,都不让保存失败,仍回未绑定。
    if me.phone and not me.dingtalk_userid:
        cfg = app_settings.dingtalk_app_config(db)
        if cfg.configured:
            try:
                from app.services.dingtalk_app import DingTalkAppClient

                client = DingTalkAppClient(cfg.app_key, cfg.app_secret, cfg.agent_id)
                userid = client.get_userid(me.phone)
                if userid:
                    me.dingtalk_userid = userid
                    db.commit()
                    db.refresh(me)
            except Exception as exc:  # noqa: BLE001 - 匹配失败只记日志,保存本身已成功
                logger.warning("保存提醒设置时钉钉匹配失败(%s):%s", me.name, exc)
    return _out(db, me, bound=True)
