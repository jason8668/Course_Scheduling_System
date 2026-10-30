"""行政值日 schema。"""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class DutyTeacherOut(BaseModel):
    id: int
    name: str
    admin_title: str | None = None


class DutyPatternOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    weekday: int
    teacher_id: int
    teacher_name: str | None = None


class DutyOverrideOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date: date
    teacher_id: int
    teacher_name: str | None = None
    reason: str | None = None


class DutySwapRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date: date
    from_teacher_id: int
    from_teacher_name: str | None = None
    to_teacher_id: int
    to_teacher_name: str | None = None
    status: str


class DutyRosterOut(BaseModel):
    patterns: list[DutyPatternOut]
    overrides: list[DutyOverrideOut]
    swap_requests: list[DutySwapRequestOut]
    eligible: list[DutyTeacherOut]


class DutyPatternIn(BaseModel):
    weekday: int = Field(ge=1, le=7)
    teacher_id: int


class DutyOverrideIn(BaseModel):
    date: date
    teacher_id: int
    reason: str | None = None


class DutySwapRequestIn(BaseModel):
    date: date
    to_teacher_id: int
