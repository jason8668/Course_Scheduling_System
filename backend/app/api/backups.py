"""资料库备份与还原(M5-2)。系统管理员专用。

清单/下载/上传由 api 直接读写共挂的备份 volume;实际 pg_dump/pg_restore 派到 worker。
还原一律**先自动备份现状**(可反悔),完成后强制全员重新登录。
"""

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.auth import require_roles
from app.core.db import get_db
from app.models.audit import AuditLog
from app.models.user import Role, User
from app.schemas.backup import BackupOut, RestoreResult
from app.services import backup as backup_service
from app.workers import queue as job_queue

logger = logging.getLogger(__name__)

router = APIRouter(tags=["backups"])

admin_only = require_roles(Role.admin)


def _out(info: backup_service.BackupInfo) -> BackupOut:
    return BackupOut.of(info.name, info.size_bytes, info.created_at, info.reason)


@router.get("/backups", response_model=list[BackupOut])
def list_backups(_: User = Depends(admin_only)):
    return [_out(i) for i in backup_service.list_backups()]


@router.post("/backups", response_model=BackupOut, status_code=status.HTTP_201_CREATED)
def create_backup(db: Session = Depends(get_db), user: User = Depends(admin_only)):
    """立即备份(pg_dump 于 worker)。"""
    try:
        data = job_queue.run_backup("manual")
    except job_queue.BackupJobError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"备份失败:{e}") from e
    db.add(AuditLog(
        user_id=user.id, username=user.username, action="create_backup",
        target_type="backup", target_id=None, detail=data["name"],
    ))
    db.commit()
    return BackupOut.of(**{k: data[k] for k in ("name", "size_bytes", "created_at", "reason")})


def _get_backup(name: str) -> backup_service.BackupInfo:
    info = next((i for i in backup_service.list_backups() if i.name == name), None)
    if info is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到备份")
    return info


@router.get("/backups/{name}/download")
def download_backup(name: str, _: User = Depends(admin_only)):
    info = _get_backup(name)
    from app.core.config import settings
    return FileResponse(
        path=f"{settings.backup_dir}/{info.name}",
        media_type="application/octet-stream", filename=info.name,
    )


@router.delete("/backups/{name}", status_code=status.HTTP_200_OK)
def delete_backup(name: str, db: Session = Depends(get_db), user: User = Depends(admin_only)):
    import os
    info = _get_backup(name)
    from app.core.config import settings
    try:
        os.remove(f"{settings.backup_dir}/{info.name}")
    except OSError as e:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "删除失败") from e
    db.add(AuditLog(
        user_id=user.id, username=user.username, action="delete_backup",
        target_type="backup", target_id=None, detail=info.name,
    ))
    db.commit()
    return {"deleted": info.name}


def _restore(db: Session, user: User, target_name: str) -> RestoreResult:
    """先备份现状,再还原;完成后强制全员重新登录。"""
    # 排课进行中不可还原:pg_restore --clean 覆盖整个资料库,而排课中的 worker 正要把
    # 结果写回同一个库;写回的草稿会落进一个刚被抹掉的世界(Fable 5 M5 复审 A)。
    if job_queue.solver_busy():
        raise HTTPException(status.HTTP_409_CONFLICT, "排课进行中,请待排课完成后再还原")

    # 还原前先关掉本请求的 session。pg_restore --clean 会中止资料库上的所有连线,包含
    # 验证身分时开的这条;而 FastAPI 的 yield 依赖是在**回应送出后**才收尾,届时
    # db.close() 会对一条已死的连线送出 ROLLBACK,在 log 喷出一段 AdminShutdown
    # traceback——回应与资料都是对的,但刚按下「还原」的主任看到那段红字,只会以为
    # 还原失败了。还原期间本来就用不到这条 session(稽核另开新连线写)。
    # 关闭前先把等下要用的栏位取成纯量,免得 user 成为 detached instance。
    actor_id, actor_name = user.id, user.username
    db.close()

    try:
        presafe = job_queue.run_backup("presafe")
        warnings = job_queue.run_restore(target_name)
    except job_queue.BackupJobError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"还原失败:{e}") from e
    # 还原已覆盖整个资料库并中止旧连线,且原本的资料已被取代;稽核要以**新连线**写进
    # **还原后**的资料库,否则不是连线已死就是纪录被覆盖掉。
    from app.core.db import SessionLocal, engine
    engine.dispose()
    audit_detail = f"还原自 {target_name};现状已备份为 {presafe['name']}"
    if warnings:
        audit_detail += f";可忽略警告 {len(warnings)} 则"
    try:
        with SessionLocal() as fresh:
            fresh.add(AuditLog(
                user_id=actor_id, username=actor_name, action="restore_backup",
                target_type="backup", target_id=None, detail=audit_detail[:500],
            ))
            fresh.commit()
    except Exception:  # noqa: BLE001 - 稽核补写失败不该推翻已完成的还原
        logger.warning("还原后补写稽核失败", exc_info=True)
    return RestoreResult(
        restored_from=target_name, presafe_backup=presafe["name"], warnings=warnings,
    )


@router.post("/backups/{name}/restore", response_model=RestoreResult)
def restore_backup(
    name: str, db: Session = Depends(get_db), user: User = Depends(admin_only)
):
    """从既有备份还原(还原前自动备份现状)。"""
    _get_backup(name)
    return _restore(db, user, name)


@router.post("/backups/restore-upload", response_model=RestoreResult)
async def restore_from_upload(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(admin_only),
):
    """上传备份档并还原。非法档案直接拒绝、不动资料库(验收②)。"""
    content = await file.read()
    try:
        name = backup_service.save_uploaded(file.filename or "upload", content)
    except backup_service.BackupError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return _restore(db, user, name)
