"""代课课时统计 schema(M4-5)。"""

from datetime import date

from pydantic import BaseModel

_Date = date


class StatDetailOut(BaseModel):
    handler_teacher_id: int
    handler_name: str
    date: _Date
    period_name: str
    class_names: str
    subject_name: str
    absent_teacher_name: str
    leave_type: str
    leave_type_label: str
    sub_type: str
    sub_type_label: str
    counts_toward_hours: bool
    funding_source: str
    pay_kind: str = "none"      # hourly / daily / none
    daily_shared: bool = False  # 日薪:当日与其他按日计酬代课老师分担


class TeacherSummaryOut(BaseModel):
    teacher_id: int
    teacher_name: str
    handled_count: int
    billable_count: int          # 课时计费节数(不含日薪)
    daily_days: int = 0          # 日薪天数
    daily_periods: int = 0       # 日薪那几天共代了几节
    daily_shared_days: int = 0   # 其中几天与其他按日计酬代课老师分担


class MonthlyReportOut(BaseModel):
    year: int
    month: int
    summaries: list[TeacherSummaryOut] = []
    details: list[StatDetailOut] = []
