"""单周/双周的判定(v1.3.0)。

规则(用户定案):**学期开始那一周是第 1 周 = 单周**,之后每周固定轮流,放假、段考
都不调整。周以周一为起点,所以学期若从周三开始,那一周仍是第 1 周。

配课的 `week_parity`:None = 每周都上;"odd" = 只上单周;"even" = 只上双周。

这个模组不碰资料库;服务层请由 `app.core.week_parity` 引用。
"""

from datetime import date, timedelta

ODD = "odd"
EVEN = "even"
PARITIES = (ODD, EVEN)
PARITY_CN = {ODD: "单周", EVEN: "双周"}
PARITY_SHORT = {ODD: "单", EVEN: "双"}


def week_parity(semester_start: date | None, day: date) -> str | None:
    """day 是单周还是双周;学期没有开始日期时无从判断,回 None(视为每周都适用)。"""
    if semester_start is None:
        return None
    first_monday = semester_start - timedelta(days=semester_start.weekday())
    week_index = (day - first_monday).days // 7  # 第 1 周 = 0
    return ODD if week_index % 2 == 0 else EVEN


def week_number(semester_start: date | None, day: date) -> int | None:
    """第几周(从 1 起算);学期开始前回 0 或负数。"""
    if semester_start is None:
        return None
    first_monday = semester_start - timedelta(days=semester_start.weekday())
    return (day - first_monday).days // 7 + 1


def runs_in_week(lesson_parity: str | None, week: str | None) -> bool:
    """这堂课在这一周有没有上:每周的课一定有;单双周的课只在对应的那一周。"""
    return lesson_parity is None or week is None or lesson_parity == week


def overlaps(a: str | None, b: str | None) -> bool:
    """两堂课会不会在同一周碰在一起:单周的课和双周的课永远不会。"""
    return a is None or b is None or a == b


def weekly_load(periods_per_week: int, parity: str | None) -> float:
    """平均每周的节数:隔周的课算一半(用户定案:课时按实际上课量)。"""
    return periods_per_week / 2 if parity else float(periods_per_week)


def fmt_periods(n: float) -> str:
    """课时显示:整数不带小数(20),半节带一位(20.5)。"""
    return str(int(n)) if float(n).is_integer() else f"{n:.1f}"
