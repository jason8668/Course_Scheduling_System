"""阅卷与成绩录入 schema(KW-30~35)。"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class ScoreSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    exam_id: int
    entry_mode: str = "total_only"
    makeup_mode: str = "separate"
    cheating_score_mode: str = "zero"
    absent_counts: bool = False
    score_deadline: datetime | None = None


class ScoreSettingsPut(BaseModel):
    entry_mode: str = "total_only"
    makeup_mode: str = "separate"
    cheating_score_mode: str = "zero"
    absent_counts: bool = False
    score_deadline: datetime | None = None


class MarkingAssignmentIn(BaseModel):
    subject_id: int
    teacher_id: int
    role: str = "阅卷教师"
    scope_type: str = "按班"
    scope_value: str | None = None


class MarkingAssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    exam_id: int
    subject_id: int
    subject_name: str = ""
    teacher_id: int
    teacher_name: str = ""
    role: str
    scope_type: str
    scope_value: str | None = None


class MarkingAssignmentListOut(BaseModel):
    items: list[MarkingAssignmentOut]
    total: int


class ScoreItemIn(BaseModel):
    subject_id: int
    name: str = Field(min_length=1, max_length=64)
    max_score: float = Field(gt=0)


class ScoreItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    exam_id: int
    subject_id: int
    name: str
    max_score: float
    sort_order: int = 0


class ScoreItemListOut(BaseModel):
    items: list[ScoreItemOut]
    total: int


class ScoreItemValueIn(BaseModel):
    item_id: int
    value: float


class ScoreItemValueOut(BaseModel):
    item_id: int
    name: str = ""
    value: float


class ScoreEntryIn(BaseModel):
    student_id: int
    score: float | None = None
    status: str | None = None
    items: list[ScoreItemValueIn] | None = None


class ScorePutIn(BaseModel):
    subject_id: int
    scores: list[ScoreEntryIn]


class ScorePutOut(BaseModel):
    updated: int


class ScoreOut(BaseModel):
    id: int | None = None
    exam_id: int
    subject_id: int
    student_id: int
    student_no: str = ""
    student_name: str = ""
    class_name: str = ""
    score: float | None = None
    status: str = "正常"
    submitted: bool = False
    items: list[ScoreItemValueOut] = []


class ScoreListOut(BaseModel):
    items: list[ScoreOut]
    total: int


class ScoreSubmitIn(BaseModel):
    subject_id: int
    class_unit_id: int | None = None


class ScoreSubmitOut(BaseModel):
    submitted: int


class ImportErrorOut(BaseModel):
    row: int
    message: str


class ImportResultOut(BaseModel):
    created: int
    updated: int
    errors: list[ImportErrorOut]


class ProgressClassOut(BaseModel):
    class_unit_id: int
    class_name: str
    total: int
    entered: int
    submitted: int
    status: str


class ProgressSubjectOut(BaseModel):
    subject_id: int
    subject_name: str
    classes: list[ProgressClassOut]


class ScoreProgressOut(BaseModel):
    subjects: list[ProgressSubjectOut]


class MakeupIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    exam_date: date
    note: str | None = None


class MakeupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    exam_id: int
    name: str
    exam_date: date
    note: str | None = None


class MakeupListOut(BaseModel):
    items: list[MakeupOut]
    total: int


class MakeupScoreEntryIn(BaseModel):
    student_id: int
    score: float | None = None
    status: str | None = None


class MakeupScorePutIn(BaseModel):
    subject_id: int
    scores: list[MakeupScoreEntryIn]


class MakeupScoreOut(BaseModel):
    id: int | None = None
    makeup_id: int
    student_id: int
    student_no: str = ""
    student_name: str = ""
    class_name: str = ""
    subject_id: int
    score: float | None = None
    status: str = "正常"


class MakeupScoreListOut(BaseModel):
    items: list[MakeupScoreOut]
    total: int
