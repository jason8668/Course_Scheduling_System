"""建立 E2E 验收所需的前置状态(仅供开发机与 CI 使用,正式站不要执行)。

- 教学组长帐号 e2e_scheduler / e2etest1234(见 frontend/e2e/helpers.ts)
- 教师帐号 e2e_teacher / e2eteacher1234(供测试绑定「陈老师」)
- 系统管理员帐号 e2e_admin / e2eadmin1234(系统管理页的备份/SMTP 卡片只有 admin 看得到)
- **首次登录帐号** e2e_newuser / e2enewuser1234(`must_change_password=True`)
- **首次登录的纯教师帐号** e2e_newteacher / e2enewteacher1234(教师角色的强制改密流程,见 #10)
- 将设置精灵标记为已完成(否则路由守卫会把组长导回 /wizard,
  wizard.spec 会自行 reset 再走完整流程,不受影响)

幂等:已存在的帐号不重建、不改密码。**唯一例外是 e2e_newuser**——见下方说明。
用法(容器内):
    docker compose exec -T api python -m app.scripts.seed_e2e
"""

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models.user import Role, User
from app.models.wizard import SINGLETON_ID, WizardState
from app.services.users import create_user

_ACCOUNTS: list[tuple[str, str, Role, str]] = [
    ("e2e_scheduler", "e2etest1234", Role.director, "E2E 年级主任"),
    ("e2e_teacher", "e2eteacher1234", Role.teacher, "E2E 教师"),
    ("e2e_admin", "e2eadmin1234", Role.admin, "E2E 系统管理员"),
]

# 「首次登录强制改密」是每位新用户必经的第一个界面,而那一页**只有在强制状态下进得去**
# (路由守卫会把非强制状态的人导回仪表板)。测试跑完必然把这个状态消耗掉——它就是去改密码的——
# 所以这个帐号每次 seed 都强制重设回「首次登录」,否则第二次跑 e2e 会因为状态已被用掉而失败。
# 纯教师角色另外一个:教师可进的页面比组长少,改密码页曾因此被守卫互踢成无限跳转(#10)
NEW_USERS: list[tuple[str, str, Role, str]] = [
    ("e2e_newuser", "e2enewuser1234", Role.director, "E2E 首次登录用户"),
    ("e2e_newteacher", "e2enewteacher1234", Role.teacher, "E2E 首次登录教师"),
]


def _reset_first_login_accounts(db) -> None:
    for username, password, role, display in NEW_USERS:
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            create_user(
                db, username, password, [role],
                display_name=display, must_change_password=True,
            )
            print(f"已建立帐号:{username}(首次登录状态)")
            continue
        user.password_hash = hash_password(password)
        user.must_change_password = True
        print(f"已重设回首次登录状态:{username}")


def seed() -> None:
    with SessionLocal() as db:
        for username, password, role, display in _ACCOUNTS:
            if db.scalar(select(User).where(User.username == username)):
                print(f"帐号已存在,略过:{username}")
                continue
            create_user(
                db, username, password, [role],
                display_name=display, must_change_password=False,
            )
            print(f"已建立帐号:{username}({role.value})")

        _reset_first_login_accounts(db)

        state = db.get(WizardState, SINGLETON_ID)
        if state is None:
            state = WizardState(id=SINGLETON_ID, current_step=0, completed=True)
            db.add(state)
        else:
            state.completed = True
        db.commit()
        print("设置精灵已标记完成")


if __name__ == "__main__":
    seed()
