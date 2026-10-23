"""M6-1:测试日期基准 helper 自身的单元测试。

这支 helper 是「所有调代课测试不会过期」的地基,它自己得先站得住。
"""

from datetime import date, timedelta

import pytest

from app.core.clock import is_past_slot
from tests import dates as d


@pytest.mark.parametrize("today", [
    date(2026, 7, 13),   # 周一(今天就是基准星期的边界)
    date(2026, 7, 15),   # 周三(卡片点名的边界:今天就是周三)
    date(2026, 7, 19),   # 周日
    date(2026, 12, 28),  # 跨年:基准周会落到隔年
    date(2028, 2, 26),   # 闰年 2/29 前后
])
def test_base_monday_is_a_future_monday(today):
    mon = d.base_monday(today)
    assert mon.isoweekday() == 1
    assert (mon - today).days >= d.LEAD_DAYS, "基准周必须距今至少 LEAD_DAYS,否则当天节次可能已上过"
    # 「本月代课少者优先」与月结统计都以节次日期的月份为范围,基准周与下周三必须同月
    assert (mon + timedelta(days=9)).month == mon.month


@pytest.mark.parametrize("offset", range(40))
def test_base_week_never_straddles_a_month_regardless_of_today(offset):
    """不论今天是哪一天,WED 与 WED2 都必须同月(2026-07-14 曾在此翻车:7/29 vs 8/5)。"""
    mon = d.base_monday(date(2026, 7, 1) + timedelta(days=offset))
    assert (mon + timedelta(days=2)).month == (mon + timedelta(days=9)).month


@pytest.mark.parametrize("weekday", [1, 2, 3, 4, 5, 6, 7])
def test_on_or_after_lands_on_the_asked_weekday(weekday):
    for offset in range(14):  # 涵盖「当天就是该星期」与其余每一种相对位置
        day = date(2026, 7, 13) + timedelta(days=offset)
        got = d.on_or_after(weekday, day)
        assert got.isoweekday() == weekday
        assert got >= day
        assert (got - day).days < 7


def test_on_or_after_returns_the_same_day_when_it_already_matches():
    wed = date(2026, 7, 15)  # 周三
    assert d.on_or_after(3, wed) == wed


def test_on_or_after_rejects_a_bad_weekday():
    with pytest.raises(ValueError):
        d.on_or_after(0, date(2026, 7, 13))


@pytest.mark.parametrize("today", [date(2026, 1, 5), date(2026, 7, 13), date(2027, 3, 1)])
def test_cross_month_wednesday_straddles_a_month_boundary(today):
    wed = d.cross_month_wednesday(today)
    nxt = wed + timedelta(days=7)
    assert wed.isoweekday() == 3 and nxt.isoweekday() == 3
    assert nxt.month != wed.month, "两个周三必须落在不同月份,跨月拆帐才验得到"
    assert wed >= d.base_monday(today)


def test_module_constants_are_a_consistent_future_week():
    assert [x.isoweekday() for x in (d.MON, d.WED, d.FRI, d.SAT)] == [1, 3, 5, 6]
    assert d.WED2 == d.WED + timedelta(days=7)
    assert d.NEXT_MON == d.MON + timedelta(days=7)
    # 每一个要拿来排课/请假的日子都还在未来(这正是硬编日期会失守的地方)
    for day in (d.MON, d.WED, d.FRI, d.WED2, d.CROSS_WED, d.CROSS_WED2):
        assert not is_past_slot(day, None) and day > date.today()


def test_semester_window_contains_every_test_day():
    for day in (d.MON, d.WED, d.FRI, d.SAT, d.WED2, d.CROSS_WED, d.CROSS_WED2):
        assert d.SEM_START < day < d.SEM_END
    assert d.BEFORE_SEM < d.SEM_START and d.AFTER_SEM > d.SEM_END
