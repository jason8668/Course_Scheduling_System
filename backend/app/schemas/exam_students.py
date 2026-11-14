"""考务地基 schema(KW-01~07):学生、家长、异动、学科分值、考号规则。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.exam_foundation import CHANGE_TYPES, RULE_TYPES, STUDENT_STATUSES


class ParentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    relation: str | None = None
    phone: str | None = None


class ParentIn(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    relation: str | None = Field(default=None, max_length=20)
    phone: str | None = Field(default=None, max_length=32)


class StudentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    semester_id: int
    class_unit_id: int
    class_name: str = ""
    grade: int | None = None
    student_no: str
    name: str
    gender: str | None = None
    status: str
    exam_no: str | None = None
    parents: list[ParentOut] = []


class StudentCreate(BaseModel):
    semester_id: int
    class_unit_id: int
    student_no: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=32)
    gender: str | None = Field(default=None, max_length=8)
    status: str = "在读"
    exam_no: str | None = Field(default=None, max_length=32)


class StudentUpdate(BaseModel):
    """改姓名/性别/班级;不改 status,状态变更走专用异动接口。"""

    name: str | None = Field(default=None, min_length=1, max_length=32)
    gender: str | None = Field(default=None, max_length=8)
    class_unit_id: int | None = None


class StudentStatusChangeIn(BaseModel):
    to_status: str
    note: str | None = Field(default=None, max_length=256)
    new_class_unit_id: int | None = None
    change_type: str | None = None


class StudentStatusChangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    student_id: int
    change_type: str
    from_class_unit_id: int | None = None
    to_class_unit_id: int | None = None
    from_class_name: str | None = None
    to_class_name: str | None = None
    from_status: str | None = None
    to_status: str | None = None
    note: str | None = None
    changed_by: int | None = None
    created_at: datetime | None = None


class StudentListOut(BaseModel):
    items: list[StudentOut]
    total: int


class StatusChangeListOut(BaseModel):
    items: list[StudentStatusChangeOut]


class ImportResultOut(BaseModel):
    created: int = 0
    updated: int = 0
    errors: list[str] = []


class SubjectSettingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    subject_id: int
    subject_name: str = ""
    full_score: float = 100
    pass_line: float = 60
    excellent_line: float = 85
    counts_toward_total: bool = True
    conversion_ratio: float = 1.0


class SubjectSettingIn(BaseModel):
    subject_id: int
    full_score: float = Field(default=100, gt=0)
    pass_line: float = Field(default=60, ge=0)
    excellent_line: float = Field(default=85, ge=0)
    counts_toward_total: bool = True
    conversion_ratio: float = Field(default=1.0, gt=0)


class SubjectSettingsPut(BaseModel):
    semester_id: int
    settings: list[SubjectSettingIn]


class SubjectSettingsOut(BaseModel):
    items: list[SubjectSettingOut]


class ExamNumberRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    semester_id: int
    grade: int | None = None
    rule_type: str = "by_student_no"


class ExamNumberRulePut(BaseModel):
    semester_id: int
    grade: int | None = None
    rule_type: str = "by_student_no"


class ExamNumberGenerateIn(BaseModel):
    semester_id: int
    grade: int


class ExamNumberGenerateOut(BaseModel):
    generated: int = 0
    warning: str = ""
