"""测试用的日期基准:一律由「执行当日」推算,不硬编。

**为什么不能硬编未来日期**:`clock.is_past_slot` 以真实时钟判定节次是否已上过。
日期一旦成为过去,代课指派会被 409 拒绝、销假不再级联——整套测试在某个没人动过
程序码的早晨无声转红(原本埋的引信是 2026-11-11)。

用法:`from tests.dates import SEM_START, SEM_END, WED`。星期采 ISO(1=周一 … 7=周日),
与 `ScheduleEntry.weekday` 及 `leaves.expand` 的 `isoweekday()` 同一套。
"""

from datetime import date, timedelta

# 基准周距今的最小天数。取 14 天的理由:
#   1. 基准周的每一节都必须还没上过——若取「今天」,下午跑测试时上午的节次已过期。
#   2. 有测试会往前一周找日子,前一周也必须仍在未来。
LEAD_DAYS = 14

# 学期起讫相对基准周留的缓冲(要能容下 CROSS_WED2 这种往后数周的日子)。
_SEM_LEAD = timedelta(days=30)
_SEM_TAIL = timedelta(days=60)


def on_or_after(weekday: int, day: date) -> date:
    """`day` 当天或之后、最近的指定 ISO 星期(1=周一 … 7=周日)。"""
    if not 1 <= weekday <= 7:
        raise ValueError(f"weekday 需为 1~7(ISO),得到 {weekday}")
    return day + timedelta(days=(weekday - day.isoweekday()) % 7)


def base_monday(today: date | None = None) -> date:
    """基准测试周的周一:距今至少 `LEAD_DAYS` 天,且该周一到「下周三」落在同一个月。

    同月是硬需求,不是美观:代课推荐的公平计数与月结统计都以「受影响节次那一天的月份」
    为范围(`_monthly_sub_counts`)。若 WED 与 WED2 跨月,「林师本月已代 1 节」在 WED2
    那个月会归零,「本月代课少者优先」就验不到。跨月的案例另由 `cross_month_wednesday` 负责。
    """
    mon = on_or_after(1, (today or date.today()) + timedelta(days=LEAD_DAYS))
    for _ in range(6):
        if (mon + timedelta(days=9)).month == mon.month:  # +9 天 = 下周三
            return mon
        mon += timedelta(days=7)
    raise AssertionError("六周内必有一个「当周到下周三同月」的周一")  # pragma: no cover


def cross_month_wednesday(today: date | None = None) -> date:
    """一个周三,且「下一个周三」落在不同月份(供跨月假单拆帐测试)。

    任何连续 5 周内必有一个月底的周三,故有限次即可找到。
    """
    wed = on_or_after(3, base_monday(today))
    for _ in range(6):
        if (wed + timedelta(days=7)).month != wed.month:
            return wed
        wed += timedelta(days=7)
    raise AssertionError("六周内必有跨月的周三,推算逻辑有误")  # pragma: no cover


MON = base_monday()
TUE = MON + timedelta(days=1)
WED = MON + timedelta(days=2)
THU = MON + timedelta(days=3)
FRI = MON + timedelta(days=4)
SAT = MON + timedelta(days=5)
SUN = MON + timedelta(days=6)
NEXT_MON = MON + timedelta(days=7)
WED2 = WED + timedelta(days=7)  # 下周三(swap 补课、跨周统计用)

# 跨月的两个周三(11/25 与 12/02 那组硬编日期的动态版)
CROSS_WED = cross_month_wednesday()
CROSS_WED2 = CROSS_WED + timedelta(days=7)

# 学期起讫:包住上面所有日子,前后各留缓冲供「学期外」的边界测试
SEM_START = MON - _SEM_LEAD
SEM_END = max(WED2, CROSS_WED2) + _SEM_TAIL
BEFORE_SEM = SEM_START - timedelta(days=1)
AFTER_SEM = SEM_END + timedelta(days=1)
