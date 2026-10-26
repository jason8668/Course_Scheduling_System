"""帐号—年级管理(按年级排课的权限分离)。三种角色:管理员、年级主任、普通老师。

只有管理员能看全帐号、改年级;普通帐号只能看自己的年级(自动排课页的默认范围用它)。
年级是全校统一的数字,不绑定学期。
任命方式:管理员在这里给老师帐号配年级,配了即授予该年级的主任权限(自动带上
主任身份);不配年级就没有排课权限,只能当任课老师用。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import get_active_user, require_roles
from app.core.db import get_db
from app.models.user import Role, User, UserRole
from app.services import grade_scopes

router = APIRouter(tags=["users"])

admin_only = require_roles(Role.admin)


class GradeScopesIn(BaseModel):
    grades: list[int] = Field(default=[], description="该帐号可操作的年级;空 = 无排课权限")


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    roles: list[str]
    grades: list[int]


@router.get("/users", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db), _: User = Depends(admin_only),
):
    """管理员:全帐号一览(帐号、角色、已配年级)。"""
    users = db.query(User).order_by(User.id).all()
    return [
        UserOut(
            id=u.id, username=u.username, display_name=u.display_name,
            roles=sorted(u.role_names), grades=grade_scopes.user_grades(db, u.id),
        )
        for u in users
    ]


@router.get("/users/me/grade-scopes", response_model=list[int] | None)
def my_grade_scopes(
    db: Session = Depends(get_db), user: User = Depends(get_active_user),
):
    """自己的年级范围;null = 不受限(仅管理员),空 = 未被分配年级(无排课权限)。"""
    allowed = grade_scopes.allowed_grades(db, user)
    return sorted(allowed) if allowed is not None else None


@router.put("/users/{user_id}/grade-scopes", response_model=list[int])
def set_grades(
    user_id: int, body: GradeScopesIn,
    db: Session = Depends(get_db), _: User = Depends(admin_only),
):
    """管理员:替换某帐号的年级(整批覆盖;空 = 无排课权限)。

    任命:配了年级即授予主任权限——目标不是管理员且还没有主任身份时,自动带上
    主任身份;年级清空后身份保留,但无年级即无排课权限。
    """
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到帐号")
    out = grade_scopes.set_user_grades(db, user_id, body.grades)
    if out and Role.admin.value not in target.role_names \
            and Role.director.value not in target.role_names:
        # 经关系追加(而非只设外键),同 session 内立即可见,避免 expire_on_commit=False 时读到旧角色
        target.roles.append(UserRole(role=Role.director.value))
    db.commit()
    return out
