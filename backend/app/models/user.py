"""帐号与角色 model。

一个 User 可有多个角色(RBAC);admin 为超级用户,通过所有角色检查。
teacher 角色的帐号日后(M1)以 nullable 的 teacher_id 绑定教师主档。
"""

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Role(enum.StrEnum):
    """系统角色。值即为资料库与 API 使用的字串。"""

    admin = "admin"          # 系统管理员(超级用户)
    director = "director"    # 教务主任
    scheduler = "scheduler"  # 停用:三种角色只剩管理员/主任/教师,不再分配;枚举保留只为兼容旧数据
    teacher = "teacher"      # 教师


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    display_name: Mapped[str] = mapped_column(String(64), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # 首次登录或被重设密码后为 True,强制用户改密码后才能使用其他功能
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    # 认证来源:local(本地帐密)或未来的 oidc(教育云端帐号)
    auth_provider: Mapped[str] = mapped_column(String(20), default="local")
    # 登录失败锁定机制
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    roles: Mapped[list["UserRole"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def role_names(self) -> set[str]:
        return {r.role for r in self.roles}


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role", name="uq_user_role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))

    user: Mapped["User"] = relationship(back_populates="roles")


class UserGradeScope(Base):
    """帐号—年级对应(按年级排课的权限分离)。

    管理员给帐号配年级后,该帐号的排课写操作只允许在这些年级内:
    配课、手动排课格位、自动排课范围、班级资料、调课处置均按此拦截。
    年级主任本身就是老师:未配年级的主任没有任何排课权限,只能当任课老师用;
    主任、管理员始终不受限。
    年级是全校统一的数字(7/8/9),不绑定学期——年级主任换学期仍管同一年级。
    """

    __tablename__ = "user_grade_scopes"
    __table_args__ = (
        UniqueConstraint("user_id", "grade", name="uq_user_grade_scope"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    grade: Mapped[int] = mapped_column(Integer)
