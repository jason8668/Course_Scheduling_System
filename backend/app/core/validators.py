"""轻量栏位验证工具(不引入 email-validator 依赖)。"""

import re

# 务实的 Email 格式检查:本地部分@网域.顶级,不含空白;不追求 RFC 5322 完整性
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(value: str) -> bool:
    return bool(_EMAIL_RE.match(value))
