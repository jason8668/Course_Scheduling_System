"""认证与授权的 FastAPI 依赖。

三个层级:
- get_current_user:仅需登录(供 /me、改密码、登出使用,允许 must_change_password 者)
- get_active_user:已登录且已完成必要改密(功能性 API 应依赖此)
- require_roles(*roles):在 get_active_user 之上再检查角色;admin 为超级用户通过所有检查
"""

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.security import password_fingerprint, read_session_token, session_issued_at
from app.core.session_epoch import min_issued_at
from app.models.user import Role, User

COOKIE_NAME = "session"


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    payload = read_session_token(token, settings.session_max_age_seconds)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期,请重新登录"
        )
    user = db.get(User, payload["uid"])
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="帐号无效")
    # 密码指纹不符表示密码已变更,旧 session 一律失效
    if payload.get("pv") != password_fingerprint(user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效,请重新登录"
        )
    # 全域强制重新登录(如资料库还原后):签发时间早于门槛的 session 失效
    epoch = min_issued_at()
    if epoch > 0:
        issued = session_issued_at(token, settings.session_max_age_seconds)
        if issued is not None and issued < epoch:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="系统已还原或重设,请重新登录",
            )
    return user


def get_active_user(user: User = Depends(get_current_user)) -> User:
    """已登录且无待处理的强制改密。功能性 API 应依赖此。"""
    if user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="请先变更密码",
            headers={"X-Reason": "must_change_password"},
        )
    return user


def require_roles(*roles: Role) -> Callable[..., User]:
    """回传一个检查角色的依赖。admin 一律通过。"""
    allowed = {r.value for r in roles}

    def checker(user: User = Depends(get_active_user)) -> User:
        names = user.role_names
        if Role.admin.value in names or allowed & names:
            return user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")

    return checker
