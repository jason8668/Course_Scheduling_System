"""调代课处置与代课推荐 schema(M4-2)。"""

from datetime import date, time

from pydantic import BaseModel, Field

# 栏位名 date 会遮蔽同名型别,故以别名标注
_Date = date


class CandidateOut(BaseModel):
    teacher_id: int
    teacher_name: str
    same_grade: bool = False
    same_subject: bool
    at_school_that_day: bool
    sub_periods_this_month: int
    reasons: list[str] = []


class RecommendationOut(BaseModel):
    affected_period_id: int
    candidates: list[CandidateOut] = []
    no_candidate_hint: str = ""


class AssignRequest(BaseModel):
    """指派处置。type=substitute/swap/merge 需 handler_teacher_id;swap 另需 swap_*。"""

    type: str  # substitute / swap / merge / self_study / cancel
    handler_teacher_id: int | None = None
    counts_toward_hours: bool | None = None  # 空=依处置默认(代课计、其余不计)
    funding_source: str = Field(default="", max_length=32)
    # 调课:乙的某节课(schedule_entry)与甲补课的日期
    swap_entry_id: int | None = None
    swap_date: date | None = None
    swap_period_no: int | None = None  # 连堂格位换其中哪一节;空 = 第一节


class BatchAssignRequest(BaseModel):
    """整批指派代课:一张假单(或其中一天)还没处理的节次,全部派给同一位老师。"""

    handler_teacher_id: int
    funding_source: str = Field(default="", max_length=32)
    counts_toward_hours: bool | None = None
    date: _Date | None = None  # 空 = 整张假单


class BatchSkipOut(BaseModel):
    affected_period_id: int
    date: _Date
    period_name: str
    class_names: str
    subject_name: str
    reason: str


class BatchAssignOut(BaseModel):
    assigned: int
    skipped: list[BatchSkipOut] = []


class SubstitutionOut(BaseModel):
    id: int
    affected_period_id: int
    type: str
    type_label: str
    handler_teacher_id: int | None = None
    handler_name: str | None = None
    counts_toward_hours: bool
    funding_source: str
    swap_date: date | None = None
    swap_period_name: str = ""
    swap_class_names: str = ""
    swap_subject_name: str = ""
    created_by_name: str


class SwapOptionOut(BaseModel):
    entry_id: int
    date: date
    weekday: int
    period_no: int
    period_name: str
    class_names: str
    subject_name: str
    same_class: bool
    in_block: bool = False


class SwapPartnerOut(BaseModel):
    teacher_id: int
    teacher_name: str
    teaches_same_class: bool
    blocked_reason: str = ""
    options: list[SwapOptionOut] = []


class SwapOptionsOut(BaseModel):
    """可对调节次:请假那周起数周内,乙能来、甲能补的每一个组合。"""

    affected_period_id: int
    date_from: date
    date_to: date
    partners: list[SwapPartnerOut] = []



class SlipRowOut(BaseModel):
    ordinal: int
    start_time: time | None = None
    end_time: time | None = None
    afternoon_starts: bool = False


class SlipCellOut(BaseModel):
    date: _Date
    weekday: int
    ordinal: int
    subject_name: str
    actor: str  # 第三行:调课单写上课老师;代课单写「班级[代]」或「老师[代]」
    code: str
    time_note: str = ""  # 跨节次表的格子:实际上课时间(与格线那一列不同时才有)


class SlipWeekOut(BaseModel):
    monday: _Date
    days: list[_Date] = []
    cells: list[SlipCellOut] = []


class SlipOut(BaseModel):
    kind: str  # teacher / class
    teacher_name: str = ""
    class_names: str
    date_from: _Date
    date_to: _Date
    absent_teacher_name: str = ""  # 代课单:请假教师
    leave_type_name: str = ""      # 代课单:假别
    funding_label: str = ""        # 代课单:计费方式
    rows: list[SlipRowOut] = []
    weeks: list[SlipWeekOut] = []


class SlipsOut(BaseModel):
    """通知单:先每位教师一张,再每个班一张。"""

    title: str
    kind: str = "swap"  # swap / substitute:决定纸本抬头
    slips: list[SlipOut] = []
