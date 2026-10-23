"""资料库连线与 SQLAlchemy 基础设置(SQLAlchemy 2.0 风格)。"""

import logging
from collections.abc import Generator

from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

logger = logging.getLogger(__name__)

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

# 统一约束/索引命名惯例,确保跨资料库(PostgreSQL/SQLite)迁移可靠、可预测
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """所有 ORM model 的基底。各 model 定义于 app/models/。"""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def get_db() -> Generator:
    """FastAPI 依赖注入用的资料库 session。

    收尾的 `close()` 刻意吞掉例外:yield 依赖是在**回应送出后**才收尾,此时再掷出例外
    只会变成一段没有请求可归属的 ASGI traceback,而用户早已拿到(正确的)回应。
    唯一会走到这里的情境是连线在请求期间被中止——资料库刚被还原(pg_restore --clean
    会砍掉所有连线)、或 DBA 手动踢人。真正的失败会在查询当下就报错,不会被这里盖掉。
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        try:
            db.close()
        except Exception:  # noqa: BLE001
            logger.warning("关闭资料库 session 时连线已中止(多半是刚还原过资料库)")
