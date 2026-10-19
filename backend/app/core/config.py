"""应用程序设置。所有设置值由环境变数提供(见专案根目录 .env)。"""

import logging
import secrets
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# 已知不安全的 SECRET_KEY 值(程序码默认 + .env.example 范例)。启动时若仍是这些,
# 代表部署者没设置——用随机金钥取代并警告,避免以公开金钥签署 session。
_INSECURE_SECRETS = {
    "dev-insecure-change-me",
    "please-change-this-to-a-random-secret",
    "",
}


def _is_real_domain(site_address: str) -> bool:
    """SITE_ADDRESS 是否为真实网域(而非内网 HTTP 的默认 :80/空)。"""
    s = site_address.strip()
    return bool(s) and s != ":80" and not s.startswith(":")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 基本
    app_name: str = "排课与调代课系统"
    school_name: str = "示范学校"
    debug: bool = False
    # 学校所在时区,用于「今日/本周」等领域判定(见 architecture.md D6)
    tz: str = "Asia/Taipei"
    # 排程器心跳间隔(秒);周期任务骨架用,M5-2 每日备份亦挂此排程器
    scheduler_heartbeat_seconds: int = 3600
    # 备份(M5-2):存放目录(api 与 worker 共挂的 volume)、保留份数、每日自动备份时刻
    backup_dir: str = "/backups"
    backup_keep: int = 30
    backup_hour: int = 2  # 每日自动备份的小时(学校时区)

    # 资料库与伫列
    database_url: str = "postgresql+psycopg://scheduler:scheduler@postgres:5432/scheduler"
    redis_url: str = "redis://redis:6379/0"

    # 首次启动建立的管理员
    admin_username: str = "admin"
    admin_password: str = "changeme"

    # 认证与 session
    # 用于签署 session cookie;正式部署务必于 .env 设置随机值
    secret_key: str = "dev-insecure-change-me"
    session_max_age_seconds: int = 60 * 60 * 8  # 登录有效时间,默认 8 小时
    # 站台位址(与 Caddy 共用同一 .env 变数):设为网域即代表走 HTTPS
    site_address: str = ""
    # cookie Secure 旗标。默认 False(内网 HTTP);SITE_ADDRESS 为网域时自动 True(见 _harden)
    cookie_secure: bool = False
    # 登录失败锁定
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    # 新密码最短长度
    min_password_length: int = 8
    # 导入教师并建立帐号时的默认密码(首次登录强制更改)
    default_import_password: str = "changeme"

    # CORS(开发模式前端 dev server 来源)
    cors_origins: list[str] = ["http://localhost", "http://localhost:5173"]

    # 互动式 API 文件(/api/docs 与 openapi.json)。默认关闭:端点本身都有权限守著,
    # 公开它不是漏洞,但会把整套内部 API 摊在网路上给人看——尤其 VPS + 公开网域部署。
    # 开发用 compose 会显式打开(M6-5)。
    api_docs_enabled: bool = False

    # 系统版本:建置映像时由 CI 以 build-arg 注入(如 v1.2.3);自行从原始码建置未带时为 dev
    app_version: str = "dev"
    # 新版本提醒:管理员在「系统管理」看到有新版时的提示。最多一天向 GitHub 查一次公开的
    # Release 信息,不送出任何学校资料;不想让主机连外可设 false(v1.2.3)。
    update_check_enabled: bool = True
    update_check_url: str = (
        "https://api.github.com/repos/begin0808/Course_Scheduling_System/releases/latest"
    )

    @model_validator(mode="after")
    def _harden(self) -> "Settings":
        # A:SECRET_KEY 仍为默认/范例值 → 换随机金钥,避免以公开金钥签署 session
        if self.secret_key in _INSECURE_SECRETS:
            self.secret_key = secrets.token_hex(32)
            logger.warning(
                "未设置 SECRET_KEY,已改用随机金钥(重启会使所有登录失效);"
                "请于 .env 设置固定的 SECRET_KEY(例:openssl rand -hex 32)。"
            )
        # B:设了网域(走 HTTPS)但未显式指定 COOKIE_SECURE → 自动开启 Secure 旗标
        if "cookie_secure" not in self.model_fields_set and _is_real_domain(self.site_address):
            self.cookie_secure = True
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
