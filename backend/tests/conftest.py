"""测试共用设置。

以 SQLite 记忆体资料库建立独立测试环境,并组出一个含 auth 路由与
两个受保护测试路由(_protected、_scheduler)的 app,用来验证 RBAC 依赖。
"""

from collections.abc import Iterable
from contextlib import contextmanager

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import (
    assignments,
    audit,
    auth,
    backups,
    basedata,
    calendar,
    demo,
    exports,
    imports,
    leaves,
    notifications,
    semesters,
    solver,
    substitution_log,
    substitution_stats,
    substitutions,
    system,
    teaching_hours,
    timetables,
    user_grades,
    wizard,
)
from app.api import (
    settings as settings_api,
)
from app.core.auth import get_active_user, require_roles
from app.core.db import Base, get_db
from app.models.user import Role, User
from app.services.users import create_user


@pytest.fixture
def db():
    """干净的测试资料库 session(不经 API)。给 fixtures builder 与服务层测试用。"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture
def env():
    """回传 (client, db) — client 打 API,db 供测试准备资料。共用同一 SQLite 连线。"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    application = FastAPI()
    application.include_router(auth.router, prefix="/api/auth")
    application.include_router(semesters.router, prefix="/api")
    application.include_router(basedata.router, prefix="/api")
    application.include_router(assignments.router, prefix="/api")
    application.include_router(timetables.router, prefix="/api")
    application.include_router(solver.router, prefix="/api")
    application.include_router(exports.router, prefix="/api")
    application.include_router(audit.router, prefix="/api")
    application.include_router(imports.router, prefix="/api")
    application.include_router(wizard.router, prefix="/api")
    application.include_router(leaves.router, prefix="/api")
    application.include_router(substitutions.router, prefix="/api")
    application.include_router(substitution_log.router, prefix="/api")
    application.include_router(substitution_stats.router, prefix="/api")
    application.include_router(teaching_hours.router, prefix="/api")
    application.include_router(user_grades.router, prefix="/api")
    application.include_router(notifications.router, prefix="/api")
    application.include_router(settings_api.router, prefix="/api")
    application.include_router(backups.router, prefix="/api")
    application.include_router(demo.router, prefix="/api")
    application.include_router(system.router, prefix="/api")
    application.include_router(calendar.router, prefix="/api")

    @application.get("/api/_protected")
    def _protected(user: User = Depends(get_active_user)) -> dict:
        return {"user": user.username}

    @application.get("/api/_scheduler")
    def _scheduler(user: User = Depends(require_roles(Role.scheduler))) -> dict:
        return {"user": user.username}

    application.dependency_overrides[get_db] = override_get_db

    setup_db = TestSession()
    client = TestClient(application)
    try:
        yield client, setup_db
    finally:
        setup_db.close()
        Base.metadata.drop_all(engine)


def make_user(
    db: Session,
    username: str,
    password: str = "password123",
    roles: Iterable[Role] = (),
    must_change_password: bool = False,
) -> User:
    user = create_user(
        db,
        username=username,
        password=password,
        roles=list(roles),
        must_change_password=must_change_password,
    )
    db.commit()
    return user


def grant_grades(db: Session, user: User, grades: Iterable[int] = range(1, 13)) -> None:
    """测试用:代表管理员已给该帐号分配年级(默认 1–12 全配 = 旧测试里“什么都能排的主任”)。

    权限拦截本身只由 test_grade_scopes.py 验证;其他测试的组长帐号一律先配齐,
    否则按新规则(未配年级 = 无排课权限)连搭建资料都会被挡。
    """
    from app.models.user import UserGradeScope

    for g in grades:
        db.add(UserGradeScope(user_id=user.id, grade=g))
    db.commit()


@contextmanager
def as_admin(client, db, back_to="s", password="password123"):
    """整校操作(发布/改名/删课表)须由不受限帐号执行:切到管理员,做完切回原组长。

    管理员帐号按需建立(各测试的 fixture 只建了组长,未必建了 adm)。
    """
    from app.models.user import Role, User

    if not db.query(User).filter_by(username="adm").first():
        make_user(db, "adm", password, roles=[Role.admin])
    client.post("/api/auth/login", json={"username": "adm", "password": password})
    try:
        yield
    finally:
        if back_to:
            client.post("/api/auth/login", json={"username": back_to, "password": password})
