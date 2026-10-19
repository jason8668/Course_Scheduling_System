"""三套学制验证资料集(tasks.md 测试策略总则第 1 点,全案共用)。

- `build_elementary_small`   小学 6 班(包班+科任、周三下午空、导师时间)
- `build_junior_high_mid`    初中 12 班(领域课程+弹性课程+兼行政减课教师)
- `build_vocational_high`    技高 15 班 3 科(3 连堂实习+工场+业界师资+跑班群组)

三套资料皆已于 `tests/test_fixtures.py` 验证自洽(无超课时、班级节数不超可排格数、
场地需求不超供给、跑班群组成员同节次表),可直接喂给 M3 排课引擎。
"""

from ._common import Builder, Fixture, room_demand, teacher_available_slots
from .elementary import build_elementary_small
from .junior_high import build_junior_high_mid
from .scale import build_large_school
from .vocational import build_vocational_high

__all__ = [
    "Builder",
    "Fixture",
    "build_elementary_small",
    "build_junior_high_mid",
    "build_large_school",
    "build_vocational_high",
    "room_demand",
    "teacher_available_slots",
]
