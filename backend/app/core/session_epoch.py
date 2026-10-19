"""全域「强制重新登录」时点(M5-2)。

session 是无服务器状态的签章 cookie,还原资料库不会使其失效(除非密码刚好被改回)。
还原后要「强制全员重新登录」,就把一个时点记在 **Redis**(还原只动 PostgreSQL,不碰 Redis):
凡是签发时间早于此时点的 session 一律失效。

Redis 不可用时 fail-open(不阻挡登录),并短暂快取结果,避免每次认证都打 Redis。
"""

import time

from redis import Redis

from app.core.config import settings

_KEY = "auth:min_session_iat"
_redis = Redis.from_url(
    settings.redis_url, socket_connect_timeout=0.5, socket_timeout=0.5
)

# 行程内快取:成功读取快取 5 秒;Redis 不可用时 30 秒内不再重试(不拖慢认证)
_cache: dict[str, float] = {"val": 0.0, "exp": 0.0}


def min_issued_at() -> float:
    now = time.time()
    if now < _cache["exp"]:
        return _cache["val"]
    try:
        raw = _redis.get(_KEY)
        val = float(raw) if raw else 0.0
        _cache["val"], _cache["exp"] = val, now + 5
        return val
    except Exception:  # noqa: BLE001 - Redis 不可用不该挡住登录
        _cache["val"], _cache["exp"] = 0.0, now + 30
        return 0.0


def force_logout_all() -> None:
    """把「最小有效签发时间」设为现在:所有既有 session 立即失效。"""
    try:
        _redis.set(_KEY, str(time.time()))
        _cache["exp"] = 0.0  # 使本行程快取失效,立即生效
    except Exception:  # noqa: BLE001
        return
    # 立即落盘:默认 RDB 快照条件下这个单一 key 可能一小时内都未持久化,
    # 若还原后 Redis 随即崩溃,epoch 遗失会让旧 cookie 复活。尽力而为,失败不挡。
    try:
        _redis.bgsave()
    except Exception:  # noqa: BLE001 - 落盘失败不影响强制登出本身
        pass
