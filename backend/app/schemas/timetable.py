"""课表(timetable / schedule_entry)与冲突检查 schema。"""

from datetime import date, time

from pydantic import BaseModel, ConfigDict, Field


class TimetableCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class ScheduleEntryOut(BaseModel):
    id: int
    course_assignment_id: int
    weekday: int
    period_no: int
    span: int
    locked: bool
    subject: str
    teachers: list[str] = []
    classes: list[str] = []
    unit_type: str
    unit_name: str
    room: str | None = None
    # id 供前端三视角精确筛选(姓名/班名可能重复,不可当键)
    teacher_ids: list[int] = []
    class_ids: list[int] = []
    room_id: int | None = None
    # 单双周(v1.3.0):None = 每周;odd / even = 只上单周 / 双周
    week_parity: str | None = None


class TimetableBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    semester_id: int
    name: str
    status: str
    entry_count: int = 0


class TimetableOut(BaseModel):
    id: int
    semester_id: int
    name: str
    status: str
    entries: list[ScheduleEntryOut] = []
    # 发布后回填:今日之后、依旧课表展开的受影响节次数(>0 提醒组长重新查看调代课)
    stale_affected: int = 0


class ConflictOut(BaseModel):
    code: str
    message: str


class CheckRequest(BaseModel):
    course_assignment_id: int
    weekday: int = Field(ge=1, le=7)
    period_no: int = Field(ge=1)
    span: int = Field(default=1, ge=1, le=8)
    ignore_entry_id: int | None = None  # 移动既有格位时,忽略自身
    room_id: int | None = None  # 本格位使用的场地(空=沿用配课场地)


class CheckResponse(BaseModel):
    ok: bool
    conflicts: list[ConflictOut] = []


class PlaceRequest(BaseModel):
    course_assignment_id: int
    weekday: int = Field(ge=1, le=7)
    period_no: int = Field(ge=1)
    span: int = Field(default=1, ge=1, le=8)
    room_id: int | None = None  # 本格位使用的场地(空=沿用配课场地)


class MoveRequest(BaseModel):
    weekday: int = Field(ge=1, le=7)
    period_no: int = Field(ge=1)


# ── 版本管理与发布 ────────────────────
class TimetableRename(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class UnplacedItem(BaseModel):
    course_assignment_id: int
    subject: str
    classes: list[str] = []
    teachers: list[str] = []
    required: int
    placed: int
    remaining: int
    # 自动排课当时 solver 说的「为什么排不下」(手动未排完则为空,M6-3)
    reason: str = ""


class CompletenessOut(BaseModel):
    required: int
    placed: int
    remaining: int
    complete: bool
    unplaced: list[UnplacedItem] = []


class CheckIssueOut(BaseModel):
    code: str     # H1..H10 / room_type
    label: str    # 「教师冲堂」等分组标题
    message: str


class TimetableCheckOut(BaseModel):
    """课表检查:硬约束违规 + 完整性(未排完)。两者都没有才算 ok。"""

    ok: bool
    issues: list[CheckIssueOut] = []
    completeness: CompletenessOut


class UnavailableHitOut(BaseModel):
    timetable_id: int
    timetable_name: str
    timetable_status: str
    weekday: int
    period_no: int
    period_name: str
    subject: str
    classes: str
    text: str


# ── 全员唯读课表查询 ──────────────────
class PublicSemester(BaseModel):
    id: int
    label: str
    start_date: date | None = None
    end_date: date | None = None
    current_week_number: int | None = None
    current_week_parity: str | None = None


class NamedBrief(BaseModel):
    id: int
    name: str


class PublicClass(BaseModel):
    id: int
    name: str
    grade: int
    period_table_id: int | None = None


class PublicPeriod(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    weekday: int
    period_no: int
    name: str
    start_time: time | None = None
    end_time: time | None = None
    type: str


class PublicPeriodTable(BaseModel):
    id: int
    name: str
    num_weekdays: int
    is_default: bool
    periods: list[PublicPeriod] = []


class PublishedTimetableOut(BaseModel):
    """已发布课表 + 查询页所需的全部选项,一次回传(教师端只打这一支)。"""

    id: int
    semester_id: int
    semester_label: str
    name: str
    status: str
    entries: list[ScheduleEntryOut] = []
    classes: list[PublicClass] = []
    teachers: list[NamedBrief] = []
    rooms: list[NamedBrief] = []
    period_tables: list[PublicPeriodTable] = []
