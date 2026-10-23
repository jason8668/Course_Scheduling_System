"""校历活动 schema(批次 #4)。"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

EventType = Literal["holiday", "activity", "exam", "other"]
ScopeType = Literal["school", "grade", "class"]


def _validate_dates_and_periods(
    start_date: date | None,
    end_date: date | None,
    period_start: int | None,
    period_end: int | None,
) -> None:
    if start_date is not None and end_date is not None and end_date < start_date:
        raise ValueError("结束日期不可早于开始日期")
    if (period_start is None) != (period_end is None):
        raise ValueError("period_start 与 period_end 必须成对提供")
    if period_start is not None and period_end is not None:
        if period_start < 1 or period_end < 1:
            raise ValueError("节次必须 >= 1")
        if period_start > period_end:
            raise ValueError("period_start 不可大于 period_end")


class CalendarEventCreate(BaseModel):
    # semester_id 在 body 中给出;API 也接受 ?semester_id= 查询参数作为回退,
    # 故此处设为可选,缺失时由 API 层回 422。
    semester_id: int | None = None
    title: str = Field(min_length=1, max_length=128)
    event_type: EventType
    scope_type: ScopeType
    scope_id: int | None = None
    start_date: date
    end_date: date
    period_start: int | None = None
    period_end: int | None = None
    weekly_recurring: bool = False
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _check(self) -> "CalendarEventCreate":
        _validate_dates_and_periods(
            self.start_date, self.end_date, self.period_start, self.period_end
        )
        return self


class CalendarEventUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=128)
    event_type: EventType | None = None
    scope_type: ScopeType | None = None
    scope_id: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    period_start: int | None = None
    period_end: int | None = None
    weekly_recurring: bool | None = None
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _check(self) -> "CalendarEventUpdate":
        # 仅校验本次 payload 内同时给出的栏位;只给一个节次栏位时,
        # 是否成对要看与既有值合并后的结果,由 API 层校验。
        if self.start_date is not None and self.end_date is not None:
            _validate_dates_and_periods(
                self.start_date, self.end_date, None, None
            )
        if self.period_start is not None and self.period_end is not None:
            _validate_dates_and_periods(
                None, None, self.period_start, self.period_end
            )
        return self


class CalendarEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    semester_id: int
    title: str
    event_type: str
    scope_type: str
    scope_id: int | None = None
    start_date: date
    end_date: date
    period_start: int | None = None
    period_end: int | None = None
    weekly_recurring: bool = False
    note: str | None = None
    created_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
