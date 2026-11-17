"""资产字段级加密测试(#84)。

覆盖:纯函数加解密来回、数值 2 位小数精度无损、无密钥/非法密钥/
错密钥明确报错、模型落库是密文/读出是明文、迁移 0045 upgrade/
downgrade 各跑一次值不变(含重复跑 upgrade 的幂等保护)。

密钥一律现场生成(Fernet.generate_key()),绝不写真实密钥进文件。
SQLite 只验证逻辑;迁移在真 Postgres 16 上的验证见汇报(另跑)。
"""

import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.runtime.migration import MigrationContext
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.db import Base
from app.models.asset_card import AssetCard
from app.services.asset_crypto import (
    AssetFieldCryptoError,
    decrypt_decimal,
    decrypt_number,
    decrypt_text,
    encrypt_number,
    encrypt_text,
)

# 迁移目录没有 __init__.py,不能当包 import,按文件路径加载 0045。
_MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "alembic" / "versions" / "0045_asset_field_encryption.py"
)
_spec = importlib.util.spec_from_file_location(
    "migration_0045_asset_field_encryption", _MIGRATION_PATH
)
migration_0045 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration_0045)


# 迁移前的旧表结构(只含迁移碰到的列):建卡后跑 0045 的 upgrade/downgrade。
# 工厂函数:Column 对象只能属于一张 Table,每次建表都要新的。
def _old_table_columns():
    return [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("original_value", sa.Numeric(14, 2), nullable=True),
        sa.Column("net_value", sa.Numeric(14, 2), nullable=True),
        sa.Column("voucher_no", sa.String(64), nullable=True),
        sa.Column("name", sa.String(128), nullable=True),
    ]


@pytest.fixture(autouse=True)
def field_key(monkeypatch):
    """每测生成一把新密钥写进环境变数;密钥轮换/隔离靠它。"""
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("ASSET_FIELD_KEY", key)
    return key


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    yield eng
    eng.dispose()


def _run_migration(engine, fn) -> None:
    """不用整条 alembic 链,直接对给定连线跑某迁移的 upgrade/downgrade。
    迁移里用的 alembic.op 是 proxy,须由 Operations.context() 显式安装
    (只 MigrationContext.configure 是不够的)。"""
    from alembic.operations import Operations

    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction():
            with Operations.context(ctx):
                fn()


# ── 纯函数 ────────────────────────────────────────────────


def test_text_roundtrip_and_none():
    assert decrypt_text(encrypt_text("记-2026-001")) == "记-2026-001"
    assert decrypt_text(encrypt_text("")) == ""
    assert encrypt_text(None) is None
    assert decrypt_text(None) is None
    # 每次加密结果都不同(随机 IV),但都能解回同一明文。
    assert encrypt_text("abc") != encrypt_text("abc")


def test_number_precision_lossless():
    cases = [
        (0, Decimal("0.00")),
        (0.1, Decimal("0.10")),
        (1234.5, Decimal("1234.50")),
        (1234.56, Decimal("1234.56")),
        (9999999999.99, Decimal("9999999999.99")),
        ("123.456", Decimal("123.46")),  # str 输入也按 2 位小数语义
        (5000.005, Decimal("5000.01")),  # HALF_UP 进位
    ]
    for raw, expected in cases:
        token = encrypt_number(raw)
        assert isinstance(token, str) and token.startswith("gAAAAA")
        assert decrypt_decimal(token) == expected
        assert round(decrypt_number(token), 2) == float(expected)
    assert encrypt_number(None) is None
    assert decrypt_number(None) is None
    assert decrypt_decimal(None) is None


def test_no_key_raises(monkeypatch, field_key):
    monkeypatch.delenv("ASSET_FIELD_KEY", raising=False)
    monkeypatch.setattr(settings, "asset_field_key", "")
    with pytest.raises(AssetFieldCryptoError, match="ASSET_FIELD_KEY"):
        encrypt_text("记-2026-001")
    with pytest.raises(AssetFieldCryptoError, match="ASSET_FIELD_KEY"):
        encrypt_number(100)


def test_invalid_key_raises(monkeypatch):
    monkeypatch.setenv("ASSET_FIELD_KEY", "not-a-valid-fernet-key")
    with pytest.raises(AssetFieldCryptoError, match="Fernet key"):
        encrypt_text("x")


def test_wrong_key_decrypt_raises(monkeypatch, field_key):
    token = encrypt_text("记-2026-001")
    monkeypatch.setenv("ASSET_FIELD_KEY", Fernet.generate_key().decode("ascii"))
    with pytest.raises(AssetFieldCryptoError, match="解密失败"):
        decrypt_text(token)


def test_settings_fallback_when_env_unset(monkeypatch, field_key):
    """环境变数未设时读 settings.asset_field_key(.env 注入)。"""
    monkeypatch.delenv("ASSET_FIELD_KEY", raising=False)
    monkeypatch.setattr(settings, "asset_field_key", field_key)
    assert decrypt_text(encrypt_text("记-2026-001")) == "记-2026-001"


# ── 模型:落库密文、读出明文 ─────────────────────────────


def test_model_stores_ciphertext_reads_plaintext(engine):
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = Session()
    try:
        card = AssetCard(
            asset_code="ZC0001",
            label_code="ZC0001X",
            name="测试电脑",
            category_code="A01",
            original_value=12345.67,
            net_value=12000.00,
            voucher_no="记-2026-001",
        )
        db.add(card)
        db.commit()
        # 落库是密文:原始 SQL 读到的不是明文,且是 Fernet token 形态。
        with engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT original_value, net_value, voucher_no "
                    "FROM asset_cards WHERE id = :id"
                ),
                {"id": card.id},
            ).one()
        for stored in row:
            assert isinstance(stored, str)
            assert stored.startswith("gAAAAA")
            assert "12345" not in stored and "记-2026" not in stored
        # 读出是明文:ORM 侧类型不变(float/str),数值精度无损。
        db.expire_all()
        got = db.get(AssetCard, card.id)
        assert isinstance(got.original_value, float)
        assert got.original_value == 12345.67
        assert got.net_value == 12000.00
        assert got.voucher_no == "记-2026-001"
        # NULL 保持 NULL,不加密、不报错。
        empty = AssetCard(
            asset_code="ZC0002", label_code="ZC0002X",
            name="无价资产", category_code="A01",
        )
        db.add(empty)
        db.commit()
        assert empty.original_value is None
        assert empty.net_value is None
        assert empty.voucher_no is None
    finally:
        db.close()
        Base.metadata.drop_all(engine)


def test_model_no_key_raises(engine):
    """无密钥时写加密字段明确报错,不静默存明文。"""
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = Session()
    try:
        import os

        old = os.environ.pop("ASSET_FIELD_KEY", None)
        settings_backup = settings.asset_field_key
        settings.asset_field_key = ""
        try:
            db.add(AssetCard(
                asset_code="ZC0003", label_code="ZC0003X",
                name="无密钥卡", category_code="A01",
                original_value=100,
            ))
            # SQLAlchemy 把 bind 阶段的加密错误包成 StatementError,
            # 原始错误在 .orig 里:必须是 AssetFieldCryptoError。
            with pytest.raises(sa.exc.StatementError) as excinfo:
                db.commit()
            orig = getattr(excinfo.value, "orig", None) or excinfo.value.__cause__
            assert isinstance(orig, AssetFieldCryptoError)
            assert "ASSET_FIELD_KEY" in str(excinfo.value)
            db.rollback()
        finally:
            if old is not None:
                os.environ["ASSET_FIELD_KEY"] = old
            settings.asset_field_key = settings_backup
    finally:
        db.close()
        Base.metadata.drop_all(engine)


# ── 迁移 0045:upgrade/downgrade 值不变 ───────────────────


def _build_old_table(engine):
    meta = sa.MetaData()
    table = sa.Table("asset_cards", meta, *_old_table_columns())
    meta.create_all(engine)
    return table


def _raw_values(engine):
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT id, original_value, net_value, voucher_no "
                "FROM asset_cards ORDER BY id"
            )
        ).fetchall()
    return [tuple(r) for r in rows]


def test_migration_upgrade_downgrade_roundtrip(engine, field_key):
    table = _build_old_table(engine)
    with engine.begin() as conn:
        conn.execute(table.insert().values([
            {
                "id": 1, "original_value": Decimal("12345.67"),
                "net_value": Decimal("12000.00"),
                "voucher_no": "记-2026-001", "name": "测试电脑",
            },
            {
                "id": 2, "original_value": None, "net_value": Decimal("0.10"),
                "voucher_no": None, "name": "部分空值",
            },
        ]))
    assert _raw_values(engine)[0][1] == 12345.67

    _run_migration(engine, migration_0045.upgrade)
    rows = _raw_values(engine)
    # 升级后:有值变密文,NULL 仍是 NULL;密文可解回原明文。
    assert rows[0][1].startswith("gAAAAA")
    assert rows[0][2].startswith("gAAAAA")
    assert rows[0][3].startswith("gAAAAA")
    assert rows[1][1] is None
    assert rows[1][3] is None
    fernet = Fernet(field_key.encode("ascii"))
    assert fernet.decrypt(rows[0][1].encode()).decode() == "12345.67"
    assert fernet.decrypt(rows[0][2].encode()).decode() == "12000.00"
    assert fernet.decrypt(rows[0][3].encode()).decode() == "记-2026-001"
    assert fernet.decrypt(rows[1][2].encode()).decode() == "0.10"
    # 列类型已是 Text。
    types = {c["name"]: str(c["type"]) for c in sa.inspect(engine).get_columns("asset_cards")}
    assert types["original_value"] == "TEXT"

    # 重复跑 upgrade 不重复加密(幂等):密文原样不动。
    before = _raw_values(engine)
    _run_migration(engine, migration_0045.upgrade)
    assert _raw_values(engine) == before

    _run_migration(engine, migration_0045.downgrade)
    rows = _raw_values(engine)
    # 回滚后:值回到原明文,列类型回到 Numeric/String。
    assert Decimal(str(rows[0][1])) == Decimal("12345.67")
    assert Decimal(str(rows[0][2])) == Decimal("12000.00")
    assert rows[0][3] == "记-2026-001"
    assert rows[1][1] is None
    assert Decimal(str(rows[1][2])) == Decimal("0.10")
    assert rows[1][3] is None
    types = {c["name"]: str(c["type"]) for c in sa.inspect(engine).get_columns("asset_cards")}
    assert "NUMERIC" in types["original_value"]
    assert "VARCHAR" in types["voucher_no"]


def test_migration_upgrade_no_key_fails(engine, monkeypatch):
    """无密钥时迁移明确失败,不改表、不跳过。"""
    _build_old_table(engine)
    monkeypatch.delenv("ASSET_FIELD_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ASSET_FIELD_KEY"):
        _run_migration(engine, migration_0045.upgrade)
    # 表未动:仍是旧类型、旧明文值。
    types = {c["name"]: str(c["type"]) for c in sa.inspect(engine).get_columns("asset_cards")}
    assert "NUMERIC" in types["original_value"]
