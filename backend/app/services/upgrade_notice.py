"""升级提示(v1.3.0):资料表结构升级后,提醒系统管理员一次。

`app.scripts.migrate` 在升级结构后写入;系统管理页的「系统版本」卡片读取并显示,
按「知道了」后清除。内容是升级前自动备份的档名(或备份失败的原因),
让没看过升级说明的学校(例如使用 latest 映像)也知道有这份备份、要退回时怎么做。
"""

import json

from sqlalchemy.orm import Session

from app.services import settings as settings_service

KEY = "upgrade_notice"


def get(db: Session) -> dict | None:
    raw = settings_service.get(db, KEY)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def save(db: Session, notice: dict) -> None:
    settings_service.set_value(db, KEY, json.dumps(notice, ensure_ascii=False))


def dismiss(db: Session) -> None:
    settings_service.set_value(db, KEY, "")
