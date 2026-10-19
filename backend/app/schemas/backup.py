"""备份与还原 schema(M5-2)。"""

from datetime import datetime

from pydantic import BaseModel

_REASON_CN = {
    "manual": "手动",
    "auto": "每日自动",
    "presafe": "还原前保护",
    "preupgrade": "升级前自动备份",
    "upload": "上传",
}


class BackupOut(BaseModel):
    name: str
    size_bytes: int
    created_at: datetime
    reason: str
    reason_label: str = ""

    @classmethod
    def of(cls, name: str, size_bytes: int, created_at: datetime, reason: str) -> "BackupOut":
        return cls(
            name=name, size_bytes=size_bytes, created_at=created_at,
            reason=reason, reason_label=_REASON_CN.get(reason, reason),
        )


class RestoreResult(BaseModel):
    restored_from: str
    presafe_backup: str  # 还原前自动建立的现状备份(可反悔)
    warnings: list[str] = []  # pg_restore 可忽略的警告(如跨版本 GUC),显示给管理员
