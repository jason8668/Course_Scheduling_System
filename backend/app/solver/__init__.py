"""OR-Tools CP-SAT 排课引擎(architecture.md §3)。

**架构规则(以 tests/solver/test_purity.py 强制):**
本套件不得 import `app.models` / `app.api` / `app.services`,也不得 import SQLAlchemy。
引擎只认得 `problem.py` 的纯 dataclass;DB → Problem 的转换在 `app.services.solver_data`。

- `problem.py`     问题描述(节次、教师、班级、场地、配课)与时段重叠判定(D7)
- `preflight.py`   排课前的必要条件检查(§3.4),拦掉多数资料错误
- `model_builder.py`     CP-SAT 硬约束建模(M3-2)
- `conflict_explainer.py` 无解时的冲突定位(M3-5)
"""
