"""考场编排 schema(KW-15~22):考场、规则、编排结果、座位表、锁定。"""

from pydantic import BaseModel, ConfigDict, Field


class ExamRoomIn(BaseModel):
    room_id: int
    capacity: int | None = Field(default=None, gt=0)
    room_type: str = Field(default="普通", max_length=20)
    is_special: bool = False


class ExamRoomOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    exam_id: int
    room_id: int
    room_name: str = ""
    capacity: int | None = None
    room_type: str
    is_special: bool


class ExamRoomBulkAddIn(BaseModel):
    """批量添加考场:一次勾选多间教室,类型与特殊标记对所选全部生效;
    人数上限不填时每间用各自教室的容量,填了则对所选全部生效。"""

    room_ids: list[int] = Field(min_length=1)
    capacity: int | None = Field(default=None, gt=0)
    room_type: str = Field(default="普通", max_length=20)
    is_special: bool = False


class ExamRoomBulkOut(BaseModel):
    created: int = 0
    skipped: int = 0


class ExamRoomListOut(BaseModel):
    items: list[ExamRoomOut]
    total: int


class ArrangementRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    exam_id: int
    mode: str
    scatter_same_class: bool
    max_per_room: int


class ArrangementRuleIn(BaseModel):
    mode: str
    scatter_same_class: bool = True
    max_per_room: int = Field(default=30, ge=1)


class ArrangeIn(BaseModel):
    subject_id: int | None = None


class ArrangeOut(BaseModel):
    assigned: int
    rooms_used: int
    warnings: list[str] = []


class AssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    exam_id: int
    subject_id: int
    subject_name: str = ""
    room_id: int
    room_name: str = ""
    student_id: int
    student_no: str = ""
    exam_no: str = ""
    student_name: str = ""
    class_name: str = ""
    grade: int | None = None
    seat_no: int
    special_note: str = ""


class AssignmentListOut(BaseModel):
    items: list[AssignmentOut]
    total: int


class ArrangementMoveIn(BaseModel):
    assignment_id: int
    to_room_id: int
    seat_no: int | None = Field(default=None, ge=1)


class ArrangementSwapIn(BaseModel):
    assignment_id_a: int
    assignment_id_b: int


class SeatEntryOut(BaseModel):
    seat_no: int
    student_no: str = ""
    exam_no: str = ""
    student_name: str = ""
    class_name: str = ""
    grade: int | None = None
    special_note: str = ""


class RoomSeatMapOut(BaseModel):
    room_id: int
    room_name: str = ""
    seats: list[SeatEntryOut] = []


class SeatMapOut(BaseModel):
    rooms: list[RoomSeatMapOut] = []


class ArrangementLockIn(BaseModel):
    note: str | None = Field(default=None, max_length=256)


class AdmissionTicketSubjectOut(BaseModel):
    """准考证上某科的日程与考场座位;未编排时考场与座位号为空。"""

    subject_id: int
    subject_name: str = ""
    exam_date: str = ""
    start_time: str = ""
    end_time: str = ""
    room_name: str = ""
    seat_no: int | None = None


class AdmissionTicketOut(BaseModel):
    student_id: int
    student_no: str = ""
    exam_no: str = ""
    student_name: str = ""
    class_name: str = ""
    grade: int | None = None
    subjects: list[AdmissionTicketSubjectOut] = []


class AdmissionTicketListOut(BaseModel):
    items: list[AdmissionTicketOut]
    total: int


class ArrangementLockOut(BaseModel):
    locked: bool
    locked_by: str | None = None
    locked_at: str | None = None
