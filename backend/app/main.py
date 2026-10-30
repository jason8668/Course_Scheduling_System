"""FastAPI 应用程序进入点。"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    assignments,
    audit,
    auth,
    backups,
    basedata,
    calendar,
    demo,
    duty,
    exports,
    health,
    imports,
    leaves,
    notifications,
    semesters,
    solver,
    special_days,
    substitution_log,
    substitution_stats,
    substitutions,
    teacher_swaps,
    teachers,
    teaching_hours,
    system,
    timetables,
    user_grades,
    wizard,
)
from app.api import (
    settings as settings_api,
)
from app.core.config import settings
from app.services.users import ensure_admin

logger = logging.getLogger(__name__)


# 启动时 worker-ops 可能还在起(compose 是平行启动的),故给它一段宽限期再判定。
OPS_CHECK_RETRIES = 6
OPS_CHECK_INTERVAL = 2.0


async def _warn_if_no_ops_worker() -> None:
    """背景检查 ops 伫列有没有 worker 在守,没有就在启动 log 讲清楚。

    升级只换映像、没更新 docker-compose.yml 的话,worker-ops 根本不存在;此时导出/备份
    会失败(那还算吵),而每日自动备份是**静默**停摆的——没人会发现,直到需要那份备份的
    那一天。不阻塞启动,也不在冷启动的头几秒就误报。
    """
    try:
        from app.workers.queue import OPS_WORKER_MISSING, ops_worker_available

        for _ in range(OPS_CHECK_RETRIES):
            await asyncio.sleep(OPS_CHECK_INTERVAL)
            if await asyncio.to_thread(ops_worker_available):
                return
        logger.warning(OPS_WORKER_MISSING)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - Redis 尚未就绪等情况不该影响 api 运作
        pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 启动时:若系统尚无任何用户,依 .env 建立初始管理员
    ensure_admin()
    check = asyncio.create_task(_warn_if_no_ops_worker())
    yield
    check.cancel()


app = FastAPI(
    title=settings.app_name,
    description="开源免费的排课与调代课系统 API",
    version=settings.app_version,
    # 正式部署默认关闭(见 settings.api_docs_enabled);None = 该路由不存在,回 404
    docs_url="/api/docs" if settings.api_docs_enabled else None,
    openapi_url="/api/openapi.json" if settings.api_docs_enabled else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 所有 API 挂在 /api 前缀之下(Caddy 依此前缀分流)
app.include_router(health.router, prefix="/api")
app.include_router(system.router, prefix="/api")
app.include_router(auth.router, prefix="/api/auth")
app.include_router(semesters.router, prefix="/api")
app.include_router(basedata.router, prefix="/api")
app.include_router(assignments.router, prefix="/api")
app.include_router(timetables.router, prefix="/api")
app.include_router(solver.router, prefix="/api")
app.include_router(exports.router, prefix="/api")
app.include_router(leaves.router, prefix="/api")
app.include_router(substitutions.router, prefix="/api")
app.include_router(substitution_log.router, prefix="/api")
app.include_router(substitution_stats.router, prefix="/api")
app.include_router(teaching_hours.router, prefix="/api")
app.include_router(user_grades.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")
app.include_router(teachers.router, prefix="/api")
app.include_router(settings_api.router, prefix="/api")
app.include_router(backups.router, prefix="/api")
app.include_router(audit.router, prefix="/api")
app.include_router(imports.router, prefix="/api")
app.include_router(wizard.router, prefix="/api")
app.include_router(demo.router, prefix="/api")
app.include_router(calendar.router, prefix="/api")
app.include_router(special_days.router, prefix="/api")
app.include_router(duty.router, prefix="/api")
app.include_router(teacher_swaps.router, prefix="/api")
