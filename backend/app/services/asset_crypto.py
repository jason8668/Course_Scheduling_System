"""资产字段级加密(#84)。

资产原值/净值、入账凭证号落库密文,Python 侧仍是 float/str:

- 算法:Fernet(AES-128-CBC + HMAC-SHA256,带时间戳与随机 IV)。
  每次加密结果都不同,密文是 urlsafe base64 字符串,可直接存 Text 列。
- 密钥:只从环境变数 ``ASSET_FIELD_KEY`` 读(Fernet key,base64 urlsafe
  32 字节);其次读 settings.asset_field_key(同样只由 .env 注入)。
  密钥绝不写进仓库、绝不写进代码默认值、不自动生成、不落盘。
  无密钥或密钥非法时加密/解密操作明确报错,绝不静默存明文。
- 数值:统一先化成 Decimal 并 quantize 到 2 位小数(ROUND_HALF_UP)再
  加密成字符串;解密回 Decimal/float,2 位小数语义无损。
  注意 float 本身是二进制近似,比较时以 round(x, 2) 或 Decimal 为准。

用法::

    # 生成密钥(部署时做一次,写进服务器 .env):
    # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # ASSET_FIELD_KEY=<上面输出的一行>

模型侧的加密列类型 :class:`EncryptedField` 也在这里定义,供
``app.models.asset_card.AssetCard`` 使用;审计日志(log_asset_action)
的 before/after 不动,改价走 API 时审计里仍是明文前后值。
"""

from __future__ import annotations

import os
from decimal import ROUND_HALF_UP, Decimal

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

__all__ = [
    "AssetFieldCryptoError",
    "EncryptedField",
    "decrypt_decimal",
    "decrypt_number",
    "decrypt_text",
    "encrypt_number",
    "encrypt_text",
    "get_fernet",
]

_CENT = Decimal("0.01")

# Fernet 实例按密钥字符串缓存:同一密钥重复建 Fernet 没有意义;换密钥
# (轮换)时按新字符串建新实例,旧缓存条目不影响新密钥。
_FERNET_CACHE: dict[str, Fernet] = {}


class AssetFieldCryptoError(RuntimeError):
    """字段加解密失败:无密钥、密钥非法、密文损坏或密钥不匹配。"""


def get_fernet(key: str | None = None) -> Fernet:
    """取 Fernet 实例。优先显式传入的 key,其次环境变数,最后 settings。

    环境变数优先于 settings,是因为 settings 在进程启动时就读好了;
    测试/轮换时改环境变数能立即生效,而 settings 仍是启动时的旧值。
    """
    raw = key if key is not None else os.environ.get("ASSET_FIELD_KEY", "")
    if not raw:
        # settings.asset_field_key 同样只由 .env 注入,代码里默认是 ""。
        try:
            from app.core.config import settings

            raw = settings.asset_field_key or ""
        except Exception:  # pragma: no cover - settings 导入失败时当无密钥处理
            raw = ""
    if not raw:
        raise AssetFieldCryptoError(
            "未设置 ASSET_FIELD_KEY:资产加密字段无法加解密。"
            "请在服务器 .env 设置 ASSET_FIELD_KEY=Fernet key"
            "(生成: python -c \"from cryptography.fernet import "
            "Fernet; print(Fernet.generate_key().decode())\")。"
            "不设密钥时不存明文,操作直接报错。"
        )
    cached = _FERNET_CACHE.get(raw)
    if cached is not None:
        return cached
    try:
        fernet = Fernet(raw.encode("ascii"))
    except Exception as exc:
        raise AssetFieldCryptoError(
            "ASSET_FIELD_KEY 不是合法的 Fernet key:须为 base64 urlsafe "
            "编码的 32 字节密钥(Fernet.generate_key() 的输出)。"
        ) from exc
    _FERNET_CACHE[raw] = fernet
    return fernet


def encrypt_text(value: str | None, *, key: str | None = None) -> str | None:
    """明文 str -> 密文 str;None 原样返回(None 不加密、不存密文)。"""
    if value is None:
        return None
    return get_fernet(key).encrypt(str(value).encode("utf-8")).decode("ascii")


def decrypt_text(value: str | None, *, key: str | None = None) -> str | None:
    """密文 str -> 明文 str;None 原样返回。密文损坏/密钥不对时明确报错。"""
    if value is None:
        return None
    try:
        return get_fernet(key).decrypt(str(value).encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise AssetFieldCryptoError(
            "资产加密字段解密失败:密文损坏、密钥不匹配,或该值是迁移前"
            "残留的明文。请检查 ASSET_FIELD_KEY 是否与加密时一致。"
        ) from exc


def _to_decimal(value: Decimal | float | int | str) -> Decimal:
    """数值 -> 2 位小数 Decimal。float 先经 str() 转,避开二进制近似
    (如 Decimal(0.1) 会是 0.1000000000000000055511...;Decimal(str(0.1))
    才是 0.1)。"""
    if isinstance(value, Decimal):
        dec = value
    elif isinstance(value, bool):  # bool 是 int 子类,先拦掉
        raise AssetFieldCryptoError(f"资产金额不能是布尔值:{value!r}")
    elif isinstance(value, (int, float, str)):
        dec = Decimal(str(value))
    else:
        raise AssetFieldCryptoError(f"资产金额类型不支持:{type(value).__name__}")
    return dec.quantize(_CENT, rounding=ROUND_HALF_UP)


def encrypt_number(
    value: Decimal | float | int | str | None, *, key: str | None = None
) -> str | None:
    """金额 -> 密文 str;None 原样返回。落库前统一成 2 位小数语义。"""
    if value is None:
        return None
    return encrypt_text(str(_to_decimal(value)), key=key)


def decrypt_decimal(value: str | None, *, key: str | None = None) -> Decimal | None:
    """密文 str -> Decimal(2 位小数);None 原样返回。"""
    if value is None:
        return None
    return _to_decimal(decrypt_text(value, key=key))


def decrypt_number(value: str | None, *, key: str | None = None) -> float | None:
    """密文 str -> float;None 原样返回。模型 Python 侧的金额类型是 float。"""
    dec = decrypt_decimal(value, key=key)
    return None if dec is None else float(dec)


class EncryptedField(TypeDecorator):
    """字段级加密列类型。

    落库是 Fernet 密文字符串(列类型 Text),Python 侧仍是原类型:
    kind="text" 对应 str(凭证号),kind="number" 对应 float(原值/净值)。
    因为 Python 侧类型不变,API、schema、导出代码都不用改。
    无密钥时 bind/result 处理都会抛 AssetFieldCryptoError,绝不静默
    读写明文。

    注意:密文不可做 SQL 层聚合/排序/比较(密文每次加密都不同,且是
    文本)。需要汇总金额的地方必须在 Python 侧解密后算,不要对加密
    列写 func.sum / ORDER BY(见 asset_sync.unsynced_stats 的待办)。
    """

    impl = Text
    cache_ok = True

    def __init__(self, kind: str = "text", *args, **kwargs) -> None:
        if kind not in ("text", "number"):
            raise ValueError(f"EncryptedField kind 只支持 'text'/'number',收到 {kind!r}")
        super().__init__(*args, **kwargs)
        self.kind = kind

    def process_bind_param(self, value, dialect):  # type: ignore[no-untyped-def]
        if value is None:
            return None
        if self.kind == "number":
            return encrypt_number(value)
        return encrypt_text(value)

    def process_result_value(self, value, dialect):  # type: ignore[no-untyped-def]
        if value is None:
            return None
        if self.kind == "number":
            return decrypt_number(value)
        return decrypt_text(value)
