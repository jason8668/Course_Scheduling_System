"""学校时区的「现在/今天」与「节次是否已上过」判定(config.tz,见 architecture.md D6)。

「已完成」不落盘成状态,而是**读取时推导**:一个受影响节次是否已经上过,由它的日期
与节次结束时间对照学校时区的现在决定。销假不得抹除已上过的课(课时照算)、已上过的
处置不得再变更——两道完整性关口都问这里,不依赖任何排程器。
"""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.core.config import settings


def school_now() -> datetime:
    return datetime.now(ZoneInfo(settings.tz))


def school_today() -> date:
    return school_now().date()


def is_past_slot(day: date, end_time: time | None) -> bool:
    """该节次相对学校时区的现在是否已经上过(结束)。

    当天以节次结束时间判定;节次表没填结束时间时保守视为尚未结束
    (整天内仍允许处置,与 leaves.expand 的保守策略一致)。
    """
    now = school_now()
    today = now.date()
    if day < today:
        return True
    if day > today:
        return False
    if end_time is None:
        return False
    return now.time() >= end_time
