"""系统版本与新版本提醒(v1.2.3)。"""

from dataclasses import asdict

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import get_active_user, require_roles
from app.core.db import get_db
from app.models.user import Role, User
from app.services import update_check, upgrade_notice

router = APIRouter(tags=["system"])

admin_only = require_roles(Role.admin)


class VersionOut(BaseModel):
    version: str


class UpdateStatusOut(BaseModel):
    enabled: bool
    current: str
    latest: str = ""
    latest_url: str = ""
    published_at: str = ""
    checked_at: str = ""
    update_available: bool = False
    error: str = ""


@router.get("/system/version", response_model=VersionOut)
def get_version(_: User = Depends(get_active_user)):
    """目前执行的系统版本(建置映像时注入)。登录者皆可看,回报问题时用得到。"""
    return VersionOut(version=update_check.current_version())


class UpgradeNoticeOut(BaseModel):
    """资料表结构升级后的一次性提示(v1.3.0)。"""

    version: str = ""
    at: str = ""
    backup: str = ""   # 升级前自动备份的档名
    error: str = ""    # 自动备份失败的原因(系统仍照常升级)


@router.get("/system/upgrade-notice", response_model=UpgradeNoticeOut | None)
def get_upgrade_notice(db: Session = Depends(get_db), _: User = Depends(admin_only)):
    """最近一次结构升级的提示;按过「知道了」或从未升级过时为 null。"""
    data = upgrade_notice.get(db)
    if data is None:
        return None
    return UpgradeNoticeOut(**{k: str(data.get(k, "")) for k in UpgradeNoticeOut.model_fields})


@router.post("/system/upgrade-notice/dismiss", status_code=204)
def dismiss_upgrade_notice(db: Session = Depends(get_db), _: User = Depends(admin_only)) -> None:
    upgrade_notice.dismiss(db)
    db.commit()


@router.get("/system/update", response_model=UpdateStatusOut)
def get_update_status(
    refresh: bool = Query(default=False, description="立即重新查询(至少间隔一分钟)"),
    db: Session = Depends(get_db),
    _: User = Depends(admin_only),
):
    """目前版本与 GitHub 上的最新正式版。最多一天连外查一次;只提醒,不会自动升级。"""
    result = update_check.status(db, refresh=refresh)
    db.commit()
    return UpdateStatusOut(**asdict(result))
