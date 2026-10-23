"""系统版本与新版本提醒(v1.2.3)。

**为什么要做。** 系统是各校自己架设的,新版发布后学校不会知道——只能靠作者一间间通知,
或学校自己去 GitHub 看。管理员登录「系统管理」就能看到「有新版本 vX.Y.Z」,并直接连到
更新内容与升级步骤。

**只提醒,不自动升级。** 升级要学校自己决定、先备份,这里不碰容器也不拉映像。

**对外连线的界线:**
- 只送出一个读取 GitHub 公开 Release 信息的 GET,不带任何学校资料。
- 结果快取在资料库(`app_settings`),最多一天查一次;失败(例如校内主机不能连外)也快取,
  不会每次开页面都卡著等逾时。
- `.env` 设 `UPDATE_CHECK_ENABLED=false` 即完全不连外。

版本号由建置映像时的 `APP_VERSION` 注入(CI 在打版本标签时带入,如 `v1.2.3`);
自行从原始码建置而没带时为 `dev`,此时照样显示最新版,但不判断「是否较新」。
"""

import json
import logging
import re
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services import settings as app_settings

logger = logging.getLogger(__name__)

CACHE_KEY = "update_check"
CHECK_INTERVAL = timedelta(hours=24)
# 「立即检查」的最短间隔:避免连点把 GitHub 未登录 API 的额度(每小时 60 次)用光
MIN_FORCE_INTERVAL = timedelta(seconds=60)
TIMEOUT_SECONDS = 5

_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def parse_version(tag: str) -> tuple[int, int, int] | None:
    """「v1.2.3」→ (1, 2, 3)。预发布(v1.3.0-rc1)、dev、main-xxxx 等一律视为无法比较。"""
    m = _VERSION_RE.match(tag.strip())
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def current_version() -> str:
    return get_settings().app_version.strip() or "dev"


@dataclass(frozen=True, slots=True)
class UpdateStatus:
    enabled: bool
    current: str
    latest: str = ""
    latest_url: str = ""
    published_at: str = ""
    checked_at: str = ""
    update_available: bool = False
    error: str = ""  # 最近一次查询失败的原因(给人看的);成功时为空


def _now() -> datetime:
    return datetime.now(UTC)


def _fetch_latest(url: str) -> dict:
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"Course-Scheduling-System/{current_version()}",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:  # noqa: S310 - 固定 https URL
        data = json.load(resp)
    return {
        "latest": str(data.get("tag_name") or ""),
        "latest_url": str(data.get("html_url") or ""),
        "published_at": str(data.get("published_at") or ""),
    }


def _load_cache(db: Session) -> dict:
    raw = app_settings.get(db, CACHE_KEY)
    try:
        cache = json.loads(raw) if raw else {}
    except ValueError:
        cache = {}
    return cache if isinstance(cache, dict) else {}


def _checked_at(cache: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(cache["checked_at"])
    except (KeyError, TypeError, ValueError):
        return None


def status(db: Session, *, refresh: bool = False) -> UpdateStatus:
    """目前版本与最新版本。快取过期(或 `refresh` 且距上次超过一分钟)才真的连外查询。

    呼叫端负责 commit(查询结果写入快取)。
    """
    settings = get_settings()
    current = current_version()
    if not settings.update_check_enabled:
        return UpdateStatus(enabled=False, current=current)

    cache = _load_cache(db)
    last = _checked_at(cache)
    now = _now()
    stale = last is None or now - last >= CHECK_INTERVAL
    forced = refresh and (last is None or now - last >= MIN_FORCE_INTERVAL)
    if stale or forced:
        fresh: dict = {"checked_at": now.isoformat()}
        try:
            fresh.update(_fetch_latest(settings.update_check_url))
            fresh["error"] = ""
        except Exception as exc:  # noqa: BLE001 - 连不上外网是常态,不能让系统管理页坏掉
            logger.info("检查新版本失败:%s", exc)
            # 保留上次成功查到的版本,只更新失败原因与时间
            fresh.update({k: cache.get(k, "") for k in ("latest", "latest_url", "published_at")})
            fresh["error"] = "无法连线到 GitHub 查询最新版本(学校主机可能无法连外)"
        cache = fresh
        app_settings.set_value(db, CACHE_KEY, json.dumps(cache, ensure_ascii=False))
        db.flush()  # 同一个 session 内再读快取要读得到(否则会重复连外)

    latest = str(cache.get("latest", ""))
    cur_v, latest_v = parse_version(current), parse_version(latest)
    return UpdateStatus(
        enabled=True,
        current=current,
        latest=latest,
        latest_url=str(cache.get("latest_url", "")),
        published_at=str(cache.get("published_at", "")),
        checked_at=str(cache.get("checked_at", "")),
        update_available=bool(cur_v and latest_v and latest_v > cur_v),
        error=str(cache.get("error", "")),
    )
