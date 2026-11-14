"""考试管理 schema(KW-08~14):考试、日程、参试名单、命题信息、特殊考生安排。"""

from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field

from app.models.exam import ARRANGEMENT_TYPES, EXAM_TYPES, PARTICIPANT_STATUSES


class ExamSubjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    subject_id: int
    subject_name: str = ""
    exam_date: date
    start_time: time
    end_time: time
    full_score: float | None = None


class ExamSubjectIn(BaseModel):
    subject_id: int
    exam_date: date
    start_time: time
    end_time: time
    full_score: float | None = Field(default=None, gt=0)


class ExamSubjectsPut(BaseModel):
    subjects: list[ExamSubjectIn]


class ExamSubjectsOut(BaseModel):
    items: list[ExamSubjectOut]


class ExamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    semester_id: int
    name: str
    exam_type: str
    grades: list[int] = []
    status: str
    description: str | None = None
    created_at: datetime | None = None


class ExamDetailOut(ExamOut):
    subjects: list[ExamSubjectOut] = []
    participant_count: int = 0


class ExamListOut(BaseModel):
    items: list[ExamOut]
    total: int


class ExamCreate(BaseModel):
    semester_id: int
    name: str = Field(min_length=1, max_length=64)
    exam_type: str = Field(default="月考", max_length=20)
    grades: list[int] = Field(min_length=1)
    description: str | None = Field(default=None, max_length=512)


class ExamUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    exam_type: str | None = Field(default=None, max_length=20)
    grades: list[int] | None = None
    description: str | None = Field(default=None, max_length=512)


class ExamStatusIn(BaseModel):
    to_status: str
    note: str | None = Field(default=None, max_length=256)


class ExamCopyIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    semester_id: int | None = None


class ScheduleConflictOut(BaseModel):
    subject_id: int
    subject_name: str = ""
    reason: str


class ScheduleCheckOut(BaseModel):
    conflicts: list[ScheduleConflictOut] = []


class ParticipantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    exam_id: int
    student_id: int
    student_no: str = ""
    student_name: str = ""
    class_unit_id: int
    class_name: str = ""
    grade: int | None = None
    status: str
    note: str | None = None


class ParticipantListOut(BaseModel):
    items: list[ParticipantOut]
    total: int


class ParticipantAddIn(BaseModel):
    student_id: int
    note: str | None = Field(default=None, max_length=256)


class ParticipantBulkAddIn(BaseModel):
    """批量增补参试学生:一次勾选多人,共用一个备注;已在名单/不存在/不属于本学期者计入跳过,不中断整批。"""

    student_ids: list[int] = Field(min_length=1)
    note: str | None = Field(default=None, max_length=256)


class ParticipantUpdateIn(BaseModel):
    status: str | None = None
    note: str | None = Field(default=None, max_length=256)


class ParticipantGenerateOut(BaseModel):
    created: int = 0
    skipped: int = 0


class PaperInfoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    subject_id: int
    subject_name: str = ""
    setter_teacher_id: int | None = None
    setter_teacher_name: str | None = None
    reviewer_teacher_id: int | None = None
    reviewer_teacher_name: str | None = None
    paper_count: int | None = None


class PaperInfoIn(BaseModel):
    subject_id: int
    setter_teacher_id: int | None = None
    reviewer_teacher_id: int | None = None
    paper_count: int | None = Field(default=None, ge=0)


class PaperInfoPut(BaseModel):
    items: list[PaperInfoIn]


class PaperInfoListOut(BaseModel):
    items: list[PaperInfoOut]


class SpecialArrangementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    exam_id: int
    student_id: int
    student_no: str = ""
    student_name: str = ""
    class_unit_id: int | None = None
    class_name: str = ""
    arrangement_type: str
    detail: str | None = None
    status: str


class SpecialArrangementListOut(BaseModel):
    items: list[SpecialArrangementOut]


class SpecialArrangementIn(BaseModel):
    student_id: int
    arrangement_type: str = Field(max_length=20)
    detail: str | None = Field(default=None, max_length=512)


class SpecialArrangementUpdateIn(BaseModel):
    arrangement_type: str | None = Field(default=None, max_length=20)
    detail: str | None = Field(default=None, max_length=512)
    status: str | None = None


# 供服务层校验用的常量导出(与模型层同一口径)。
EXAM_TYPE_VALUES = EXAM_TYPES
PARTICIPANT_STATUS_VALUES = PARTICIPANT_STATUSES
ARRANGEMENT_TYPE_VALUES = ARRANGEMENT_TYPES
