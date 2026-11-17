"""资产字段级加密(#84):原值/净值/入账凭证号落库改密文。

- 三列由 Numeric(14,2)/Numeric(14,2)/String(64) 改成 Text,落库值
  为 Fernet 密文(urlsafe base64 字符串);Python 侧模型仍是
  float/float/str(见 app.services.asset_crypto.EncryptedField),
  API、schema、导出代码不用改,审计日志 before/after 也不动。
- upgrade 先改列类型(旧明文值在 Postgres 下经 USING 转成文本、
  SQLite 下由 batch 重建表时转成文本),再逐行把现有明文值加密写回;
  downgrade 先逐行解密回写明文文本,再把列类型改回原类型。
- 密钥只从环境变数 ASSET_FIELD_KEY 读。无密钥或密钥非法时迁移
  明确失败(抛错、中断),绝不悄悄跳过、绝不存明文、绝不自动生成
  密钥落盘。部署前须先在服务器 .env 设好密钥再跑迁移。
- 幂等保护:已是 Fernet 密文的值(以 gAAAAA 开头)不再重复加密;
  downgrade 只解密密文值,明文值原样保留。upgrade/downgrade 各
  跑一次后值不变(测试见 tests/test_asset_field_encryption.py)。

回滚方案:alembic downgrade 0044_asset_department_dict(即本迁移
的 downgrade)。要求:同一把 ASSET_FIELD_KEY 必须还在(丢了密钥
就解不开密文,回滚前请先确认密钥在手);downgrade 会把三列解密
回写并改回 Numeric(14,2)/String(64)。密钥丢失时不要 downgrade,
先恢复密钥;若密钥已丢且必须回滚,三列只能以密文形式留在 Text 列,
需人工介入处理。

Revision ID: 0045_asset_field_encryption
Revises: 0044_asset_department_dict
"""

import os
from decimal import ROUND_HALF_UP, Decimal

import sqlalchemy as sa
from cryptography.fernet import Fernet, InvalidToken

from alembic import op

revision = "0045_asset_field_encryption"
down_revision = "0044_asset_department_dict"
branch_labels = None
depends_on = None

_COLUMNS = ("original_value", "net_value", "voucher_no")
_NUMBER_COLUMNS = ("original_value", "net_value")
_CENT = Decimal("0.01")


def _get_fernet() -> Fernet:
    """迁移内联的最小 Fernet 取法:只读环境变数,不 import app 模型
    (避免循环依赖),不读 settings(迁移应在任何应用配置之外可跑)。"""
    raw = os.environ.get("ASSET_FIELD_KEY", "")
    if not raw:
        raise RuntimeError(
            "迁移 0045_asset_field_encryption 需要 ASSET_FIELD_KEY:"
            "请先在环境变数设置 Fernet key 再跑 alembic upgrade。"
            "生成: python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"。"
            "无密钥时迁移明确失败,不会悄悄跳过加密。"
        )
    try:
        return Fernet(raw.encode("ascii"))
    except Exception as exc:
        raise RuntimeError(
            "ASSET_FIELD_KEY 不是合法的 Fernet key:须为 base64 urlsafe "
            "编码的 32 字节密钥(Fernet.generate_key() 的输出)。"
        ) from exc


def _is_ciphertext(value: object) -> bool:
    """Fernet token 一律是 urlsafe base64,以版本字节 0x80 开头,
    文本形式恒为 gAAAAA...。明文金额/凭证号不会是这个前缀。"""
    return isinstance(value, str) and value.startswith("gAAAAA")


def _encrypt_number(fernet: Fernet, value: object) -> str:
    dec = Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP)
    return fernet.encrypt(str(dec).encode("utf-8")).decode("ascii")


def _encrypt_text(fernet: Fernet, value: object) -> str:
    return fernet.encrypt(str(value).encode("utf-8")).decode("ascii")


def _decrypt(fernet: Fernet, value: str) -> str:
    try:
        return fernet.decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError(
            "迁移 0045 回滚/解密失败:某行密文损坏或 ASSET_FIELD_KEY "
            "与加密时不一致。请确认密钥无误后再跑,不要强行继续。"
        ) from exc


def _reflect_table(conn):  # type: ignore[no-untyped-def]
    meta = sa.MetaData()
    return sa.Table("asset_cards", meta, autoload_with=conn)


def upgrade() -> None:
    fernet = _get_fernet()  # 先验密钥:无密钥时在改任何列之前就失败
    # ── 1. 列类型改 Text ──
    with op.batch_alter_table("asset_cards") as batch_op:
        batch_op.alter_column(
            "original_value", type_=sa.Text(),
            existing_type=sa.Numeric(14, 2), existing_nullable=True,
            postgresql_using="original_value::text",
        )
        batch_op.alter_column(
            "net_value", type_=sa.Text(),
            existing_type=sa.Numeric(14, 2), existing_nullable=True,
            postgresql_using="net_value::text",
        )
        batch_op.alter_column(
            "voucher_no", type_=sa.Text(),
            existing_type=sa.String(64), existing_nullable=True,
            postgresql_using="voucher_no::text",
        )
    # ── 2. 现有明文值加密写回(NULL 不动;已是密文的不重复加密) ──
    conn = op.get_bind()
    table = _reflect_table(conn)
    rows = conn.execute(
        sa.select(
            table.c.id,
            table.c.original_value,
            table.c.net_value,
            table.c.voucher_no,
        )
    ).fetchall()
    for row in rows:
        values = {}
        for col in _COLUMNS:
            value = getattr(row, col)
            if value is None or _is_ciphertext(value):
                continue
            if col in _NUMBER_COLUMNS:
                values[col] = _encrypt_number(fernet, value)
            else:
                values[col] = _encrypt_text(fernet, value)
        if values:
            conn.execute(
                table.update().where(table.c.id == row.id).values(**values)
            )


def downgrade() -> None:
    fernet = _get_fernet()  # 先验密钥:无密钥/错密钥时在改列之前就失败
    # ── 1. 密文值解密回写明文文本(NULL 不动;明文原样保留) ──
    conn = op.get_bind()
    table = _reflect_table(conn)
    rows = conn.execute(
        sa.select(
            table.c.id,
            table.c.original_value,
            table.c.net_value,
            table.c.voucher_no,
        )
    ).fetchall()
    for row in rows:
        values = {}
        for col in _COLUMNS:
            value = getattr(row, col)
            if value is None or not _is_ciphertext(value):
                continue
            values[col] = _decrypt(fernet, value)
        if values:
            conn.execute(
                table.update().where(table.c.id == row.id).values(**values)
            )
    # ── 2. 列类型改回原类型(Postgres 须 USING 转回数值) ──
    with op.batch_alter_table("asset_cards") as batch_op:
        batch_op.alter_column(
            "original_value", type_=sa.Numeric(14, 2),
            existing_type=sa.Text(), existing_nullable=True,
            postgresql_using="original_value::numeric(14, 2)",
        )
        batch_op.alter_column(
            "net_value", type_=sa.Numeric(14, 2),
            existing_type=sa.Text(), existing_nullable=True,
            postgresql_using="net_value::numeric(14, 2)",
        )
        batch_op.alter_column(
            "voucher_no", type_=sa.String(64),
            existing_type=sa.Text(), existing_nullable=True,
            postgresql_using="voucher_no::text",
        )
