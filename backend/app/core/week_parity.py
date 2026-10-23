"""单周/双周的判定(v1.3.0)。实作在 `app.solver.week_parity`。

排课引擎(`app.solver`)只能引用自己的套件(见 tests/solver/test_purity.py),
所以判定逻辑放在引擎那边,这里转出给服务层使用。
"""

from app.solver.week_parity import (
    EVEN,
    ODD,
    PARITIES,
    PARITY_CN,
    PARITY_SHORT,
    fmt_periods,
    overlaps,
    runs_in_week,
    week_number,
    week_parity,
    weekly_load,
)

__all__ = [
    "EVEN", "ODD", "PARITIES", "PARITY_CN", "PARITY_SHORT", "fmt_periods", "overlaps",
    "runs_in_week", "week_number", "week_parity", "weekly_load",
]
