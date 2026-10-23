"""Fable 5 最终总体检 A/B 的回归测试:SECRET_KEY 防呆、HTTPS 自动开 cookie Secure。"""

import re

from app.core.config import Settings


def _mk(**kw) -> Settings:
    # _env_file=None:不读取任何 .env,测试只看传入值与衍生逻辑
    return Settings(_env_file=None, **kw)


# ── A:SECRET_KEY 防呆 ──────────────────────────────────────
def test_default_secret_is_replaced_with_random():
    s = _mk(secret_key="dev-insecure-change-me")
    assert s.secret_key != "dev-insecure-change-me"
    assert re.fullmatch(r"[0-9a-f]{64}", s.secret_key)


def test_example_secret_is_replaced():
    s = _mk(secret_key="please-change-this-to-a-random-secret")
    assert re.fullmatch(r"[0-9a-f]{64}", s.secret_key)


def test_empty_secret_is_replaced():
    s = _mk(secret_key="")
    assert re.fullmatch(r"[0-9a-f]{64}", s.secret_key)


def test_real_secret_is_preserved():
    s = _mk(secret_key="a-real-configured-secret-value-123")
    assert s.secret_key == "a-real-configured-secret-value-123"


def test_two_defaults_get_different_random_keys():
    assert _mk(secret_key="").secret_key != _mk(secret_key="").secret_key


# ── B:SITE_ADDRESS 网域 → cookie_secure 自动 True ──────────
def test_domain_enables_cookie_secure():
    assert _mk(secret_key="x-real", site_address="school.example.edu.tw").cookie_secure is True


def test_no_domain_keeps_cookie_secure_false():
    assert _mk(secret_key="x-real").cookie_secure is False


def test_port_only_site_address_is_not_a_domain():
    assert _mk(secret_key="x-real", site_address=":80").cookie_secure is False


def test_explicit_cookie_secure_overrides_derivation():
    # 设了网域但显式 COOKIE_SECURE=false → 尊重显式设置,不自动翻 True
    s = _mk(secret_key="x-real", site_address="school.example.edu.tw", cookie_secure=False)
    assert s.cookie_secure is False
