"""健康检查端点。供 Docker healthcheck 与部署验证使用。"""

from fastapi import APIRouter
from sqlalchemy import text

from app.core.db import engine

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict:
    """存活检查:程序有回应即为 ok。"""
    return {"status": "ok"}


@router.get("/health/ready")
def readiness() -> dict:
    """就绪检查:确认资料库可连线。"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": db_ok}
