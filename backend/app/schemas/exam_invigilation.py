"""监考安排 schema(KW-23~29):规则、教师池、监考安排、巡考、监考表、工作量、考风考纪。"""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class InvigilationRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    exam_id: int
    avoid_own_class: bool = True
    avoid_own_subject: bool = True
    invigilators_per_room: int = 2


class InvigilationRuleIn(BaseModel):
    avoid_own_class: bool = True
    avoid_own_subject: bool = True
    invigilators_per_room: int = Field(default=2, ge=1)


class InvigilatorPoolItemOut(BaseModel):
    teacher_id: int
    teacher_name: str = ""
    eligible: bool = True


class InvigilatorPoolOut(BaseModel):
    items: list[InvigilatorPoolItemOut]
    total: int


class InvigilatorPoolItemIn(BaseModel):
    teacher_id: int
    eligible: bool = True


class InvigilatorPoolIn(BaseModel):
    items: list[InvigilatorPoolItemIn] = []


class InvigilateIn(BaseModel):
    subject_id: int | None = None


class InvigilateOut(BaseModel):
    assigned: int
    warnings: list[str] = []


class InvigilationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    exam_id: int
    subject_id: int
    subject_name: str = ""
    room_id: int
    room_name: str = ""
    teacher_id: int
    teacher_name: str = ""
    role: str = "监考"


class InvigilationListOut(BaseModel):
    items: list[InvigilationOut]
    total: int


class InvigilationIn(BaseModel):
    subject_id: int
    room_id: int
    teacher_id: int
    role: str | None = Field(default=None, max_length=20)


class InvigilationBulkAddIn(BaseModel):
    """批量手工安排监考:同一科目同一考场一次勾选多位教师,角色对所选全部生效。"""

    subject_id: int
    room_id: int
    teacher_ids: list[int] = Field(min_length=1)
    role: str | None = Field(default=None, max_length=20)


class InvigilationBulkOut(BaseModel):
    created: int = 0
    skipped: int = 0


class InvigilationPatchIn(BaseModel):
    teacher_id: int | None = None
    role: str | None = Field(default=None, max_length=20)


class PatrolOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    exam_id: int
    exam_date: date
    teacher_id: int
    teacher_name: str = ""
    scope: str = ""
    note: str | None = None


class PatrolListOut(BaseModel):
    items: list[PatrolOut]
    total: int


class PatrolIn(BaseModel):
    exam_date: date
    teacher_id: int
    scope: str = Field(max_length=256)
    note: str | None = Field(default=None, max_length=256)


class PatrolPatchIn(BaseModel):
    exam_date: date | None = None
    teacher_id: int | None = None
    scope: str | None = Field(default=None, max_length=256)
    note: str | None = Field(default=None, max_length=256)


class SheetSessionOut(BaseModel):
    subject_name: str = ""
    exam_date: str = ""
    start_time: str = ""
    end_time: str = ""
    room_name: str = ""


class SheetTeacherOut(BaseModel):
    teacher_id: int
    teacher_name: str = ""
    sessions: list[SheetSessionOut] = []


class TeacherSheetOut(BaseModel):
    teachers: list[SheetTeacherOut] = []


class RoomSheetSessionOut(BaseModel):
    subject_name: str = ""
    exam_date: str = ""
    start_time: str = ""
    end_time: str = ""
    teachers: list[str] = []


class RoomSheetOut(BaseModel):
    room_id: int
    room_name: str = ""
    sessions: list[RoomSheetSessionOut] = []


class RoomSheetListOut(BaseModel):
    rooms: list[RoomSheetOut] = []


class WorkloadItemOut(BaseModel):
    teacher_id: int
    teacher_name: str = ""
    sessions: int = 0
    minutes: int = 0


class WorkloadOut(BaseModel):
    items: list[WorkloadItemOut]
    total: int


class DisciplineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    exam_id: int
    subject_id: int
    subject_name: str = ""
    student_id: int
    student_no: str = ""
    student_name: str = ""
    class_name: str = ""
    type: str = ""
    description: str | None = None
    handling: str | None = None
    recorded_by: int | None = None
    recorded_by_name: str = ""
    created_at: str = ""


class DisciplineListOut(BaseModel):
    items: list[DisciplineOut]
    total: int


class DisciplineIn(BaseModel):
    subject_id: int
    student_id: int
    type: str = Field(max_length=20)
    description: str | None = Field(default=None, max_length=512)
    handling: str | None = Field(default=None, max_length=512)


class DisciplinePatchIn(BaseModel):
    subject_id: int | None = None
    student_id: int | None = None
    type: str | None = Field(default=None, max_length=20)
    description: str | None = Field(default=None, max_length=512)
    handling: str | None = Field(default=None, max_length=512)
