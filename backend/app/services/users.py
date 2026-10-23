"""用户相关服务:建立帐号、首次启动建立管理员。"""

import logging
from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models.user import Role, User, UserRole

logger = logging.getLogger("app.users")


def create_user(
    db: Session,
    username: str,
    password: str,
    roles: Iterable[Role],
    display_name: str = "",
    must_change_password: bool = True,
) -> User:
    """建立帐号并指派角色。呼叫端负责 commit。"""
    user = User(
        username=username,
        password_hash=hash_password(password),
        display_name=display_name or username,
        must_change_password=must_change_password,
        roles=[UserRole(role=r.value) for r in roles],
    )
    db.add(user)
    db.flush()
    return user


def ensure_admin() -> None:
    """系统首次启动(尚无任何用户)时,依 .env 建立管理员帐号。

    以「是否已有任何用户」判断,避免重复建立;默认要求首次登录改密码。
    """
    with SessionLocal() as db:
        user_count = db.scalar(select(func.count()).select_from(User))
        if user_count and user_count > 0:
            return
        create_user(
            db,
            username=settings.admin_username,
            password=settings.admin_password,
            roles=[Role.admin],
            display_name="系统管理员",
            must_change_password=True,
        )
        db.commit()
        logger.info("已建立初始管理员帐号:%s(首次登录需改密码)", settings.admin_username)
