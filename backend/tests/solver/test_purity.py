"""M3-1 验收③:solver 套件不得依赖 ORM 或 Web 层。

引擎必须能独立测试、独立跑在 worker 容器,且不被 SQLAlchemy 的 lazy loading 拖垮。
以 AST 静态扫描取代 import-linter(少一个 dev 依赖,规则也更明确)。
"""

import ast
from pathlib import Path

import app.solver

SOLVER_DIR = Path(app.solver.__file__).parent

# solver 只能 import 标准函式库与自己
FORBIDDEN_PREFIXES = ("app.models", "app.api", "app.services", "app.core", "sqlalchemy", "fastapi")


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_solver_imports_neither_orm_nor_web():
    offenders: list[str] = []
    for path in sorted(SOLVER_DIR.glob("*.py")):
        for module in _imported_modules(path):
            if module.startswith(FORBIDDEN_PREFIXES):
                offenders.append(f"{path.name} → {module}")
    assert not offenders, f"solver 不得 import 这些模组:{offenders}"


def test_solver_only_imports_itself_within_app():
    for path in sorted(SOLVER_DIR.glob("*.py")):
        for module in _imported_modules(path):
            if module.startswith("app.") and not module.startswith("app.solver"):
                raise AssertionError(f"{path.name} import 了 {module}")
