"""特殊日课表 schema。"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ScopeType = Literal["school", "grade"]
Recurrence = Literal["single", "weekly", "monthly"]


class SpecialDayEntryIn(BaseModel):
    class_unit_id: int
    period_no: int = Field(ge=1)
    # 空 = 该节取消
    course_assignment_id: int | None = None


class SpecialDayRuleCreate(BaseModel):
    title: str = Field(min_length=1, max_length=128)
    scope_type: ScopeType
    scope_id: int | None = None
    recurrence: Recurrence
    single_date: date | None = None
    weekday: int | None = Field(default=None, ge=1, le=7)
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    start_date: date | None = None
    end_date: date | None = None
    entries: list[SpecialDayEntryIn] = []

    @model_validator(mode="after")
    def _check(self) -> "SpecialDayRuleCreate":
        if self.scope_type == "school" and self.scope_id is not None:
            raise ValueError("全校范围不需要 scope_id")
        if self.scope_type == "grade" and self.scope_id is None:
            raise ValueError("年级范围必须提供 scope_id(年级)")
        if self.recurrence == "single" and self.single_date is None:
            raise ValueError("单次规则必须提供 single_date")
        if self.recurrence == "weekly" and self.weekday is None:
            raise ValueError("每周规则必须提供 weekday(1=周一..7=周日)")
        if self.recurrence == "monthly" and self.day_of_month is None:
            raise ValueError("每月规则必须提供 day_of_month(1..31)")
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("结束日期不可早于开始日期")
        seen: set[tuple[int, int]] = set()
        for e in self.entries:
            key = (e.class_unit_id, e.period_no)
            if key in seen:
                raise ValueError("同一规则内同一班级同一节次不可重复")
            seen.add(key)
        return self


class SpecialDayRuleUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=128)
    scope_type: ScopeType | None = None
    scope_id: int | None = None
    recurrence: Recurrence | None = None
    single_date: date | None = None
    weekday: int | None = Field(default=None, ge=1, le=7)
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    start_date: date | None = None
    end_date: date | None = None


class SpecialDayEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    class_unit_id: int
    period_no: int
    course_assignment_id: int | None = None


class SpecialDayRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    semester_id: int
    title: str
    scope_type: str
    scope_id: int | None = None
    recurrence: str
    single_date: date | None = None
    weekday: int | None = None
    day_of_month: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_active: bool
    entries: list[SpecialDayEntryOut] = []


class SpecialDayExpandedOut(BaseModel):
    """仪表板覆盖显示用:某天某班某节的特殊日结果。"""

    date: date
    class_unit_id: int
    class_name: str
    period_no: int
    rule_id: int
    course_assignment_id: int | None = None
    subject_name: str | None = None
    teacher_names: list[str] = []
