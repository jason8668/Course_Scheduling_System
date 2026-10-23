"""api 容器启动时的资料库迁移:**要改资料表结构前,先自动备份一次**(v1.3.0)。

起因:v1.3.0 是第一个改动资料表结构的版本。使用 `IMAGE_TAG=latest` 的学校一拉新映像就会
升级,不会先看到「升级前请备份」的说明;结构升级后,旧版程序就认不得新结构。所以由系统自己
在升级前备份,学校什么都不用做,事后也能在「系统管理 → 资料备份与还原」找到这份备份还原。

规则(用户定案):
- 只在「资料库已经有资料、而且结构不是最新」时备份;全新安装与结构已是最新都不备份。
- 备份失败**照常升级**,并记下原因让系统管理员看到。拒绝启动会让用 latest 的学校整套
  系统停摆,而结构升级本身不修改既有资料(已在多个旧版的实际资料上验证)。
- 这份备份不参与每日备份的轮替(见 `services.backup.prune`),由组长自己决定何时删除。

用法(entrypoint.sh 呼叫):python -m app.scripts.migrate
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger("migrate")

PRE_UPGRADE = "preupgrade"  # 备份档名的 reason:backup_YYYYMMDD_HHMMSS_preupgrade.dump


@dataclass(frozen=True, slots=True)
class Outcome:
    upgraded: bool          # 这次有没有升级结构
    backup: str = ""        # 升级前备份的档名
    error: str = ""         # 备份失败的原因(仍照常升级)


def prepare_and_upgrade(
    current: str | None,
    head: str,
    backup: Callable[[], str],
    upgrade: Callable[[], None],
) -> Outcome:
    """决定要不要先备份,再升级结构。`backup` 回传备份档名,失败时掷例外。

    current 为 None = 资料库没有任何迁移纪录(全新安装):没有资料可备份。
    """
    if current is None or current == head:
        upgrade()  # 全新安装要建表;已是最新则什么也不做(与先前的 alembic upgrade head 相同)
        return Outcome(upgraded=current is None)
    name, error = "", ""
    try:
        name = backup()
        logger.warning("[migrate] 升级前已自动备份:%s", name)
    except Exception as exc:  # noqa: BLE001 - 备份失败不阻止升级(用户定案)
        error = str(exc)[:300] or exc.__class__.__name__
        logger.error("[migrate] 升级前自动备份失败,仍照常升级:%s", error)
    upgrade()
    return Outcome(upgraded=True, backup=name, error=error)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine

    from alembic import command
    from app.core.config import settings
    from app.services import backup as backup_service
    from app.services import update_check

    cfg = Config("alembic.ini")
    head = ScriptDirectory.from_config(cfg).get_current_head() or ""
    engine = create_engine(settings.database_url)
    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    engine.dispose()

    outcome = prepare_and_upgrade(
        current, head,
        backup=lambda: backup_service.create_backup(PRE_UPGRADE).name,
        upgrade=lambda: command.upgrade(cfg, "head"),
    )
    if not outcome.upgraded or current is None:
        return
    _record(current, head, update_check.current_version(), outcome)


def _record(from_rev: str, to_rev: str, version: str, outcome: Outcome) -> None:
    """记下这次升级,系统管理页据此提示一次(见 services.upgrade_notice)。"""
    from app.core.db import SessionLocal
    from app.services import upgrade_notice

    db = SessionLocal()
    try:
        upgrade_notice.save(db, {
            "version": version, "from_revision": from_rev, "to_revision": to_rev,
            "at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "backup": outcome.backup, "error": outcome.error,
        })
        db.commit()
    except Exception as exc:  # noqa: BLE001 - 提示写不进去不影响系统运作
        logger.error("[migrate] 无法记录升级提示:%s", json.dumps(str(exc), ensure_ascii=False))
    finally:
        db.close()


if __name__ == "__main__":
    main()
