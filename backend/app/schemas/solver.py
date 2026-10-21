"""排课引擎相关 schema(pre-flight 报告、软约束设置与达成度)。"""

from pydantic import BaseModel, Field


class PreflightIssue(BaseModel):
    level: str  # error / warning
    code: str
    message: str
    subject_type: str  # teacher / class / room / assignment / semester
    subject_id: int
    detail: dict = {}


class PreflightOut(BaseModel):
    """排课前置检查报告。ok=False 时 errors 必然非空,自动排课应被挡下。"""

    semester_id: int
    semester_label: str
    ok: bool
    error_count: int
    warning_count: int
    issues: list[PreflightIssue] = []
    # 供 UI 显示规模
    class_count: int
    teacher_count: int
    assignment_count: int
    total_periods: int


# ── 软约束设置与达成度(M3-3)────────────
class ConstraintConfigIn(BaseModel):
    """权重 0 = 关闭该项软约束。设置 UI 于 v2 才做,先以 API 调整。"""

    daily_subject_cap: int = Field(default=2, ge=1, le=8)
    teacher_daily_max: int = Field(default=6, ge=1, le=12)
    teacher_consecutive_max: int = Field(default=3, ge=1, le=12)
    weights: dict[str, int] = {}


class ConstraintConfigOut(ConstraintConfigIn):
    semester_id: int
    weight_names: dict[str, str] = {}  # S1 → 「教师偏好时段」


class SoftScoreOut(BaseModel):
    code: str
    name: str
    weight: int
    opportunities: int  # 满分
    satisfied: int      # 得分
    violations: int
    penalty: int
    rate: float
    details: list[str] = []


class SoftReportOut(BaseModel):
    total_penalty: int
    items: list[SoftScoreOut] = []


# ── 冲突定位与部分排课(M3-5)──────────
class ConflictCauseOut(BaseModel):
    code: str  # H3 / H4 / H9 / H10 / structural,或 pre-flight 检查代码
    scope_type: str
    scope_id: int
    scope_name: str
    message: str  # 人话 + 具体数字
    suggestion: str
    relaxable: bool = False
    detail: dict = {}


class ConflictReportOut(BaseModel):
    status: str
    source: str  # preflight / analysis / none
    mode: str  # each / joint / structural
    headline: str
    complete: bool = True
    relaxable_codes: list[str] = []
    causes: list[ConflictCauseOut] = []


class RelaxableOption(BaseModel):
    code: str
    name: str


class UnscheduledCourseOut(BaseModel):
    # 一笔 = 一个排课单位(跑班群组含多笔成员配课;未排节数只算一次,见 M6-3)
    assignment_ids: list[int] = []
    subject_name: str
    class_names: list[str] = []
    periods: int
    reason: str = ""  # 完全排不下的原因;solver 自行取舍掉的则为空


# ── 自动排课任务(M3-4)────────────────
class AutoScheduleRequest(BaseModel):
    """timeout 默认 10 分钟(architecture.md §3.3),可设置。"""

    max_seconds: int = Field(default=600, ge=10, le=3600)
    seed: int = Field(default=0, ge=0)
    # 部分排课:允许少数课务未排入,并可勾选放宽的硬约束(M3-5)
    allow_partial: bool = False
    relax: list[str] = []


class AutoScheduleAccepted(BaseModel):
    job_id: str


class SolveJobOut(BaseModel):
    job_id: str
    created_at: float = 0.0
    status: str  # queued / running / finished / failed / cancelled
    semester_id: int
    source_timetable_id: int
    source_name: str
    max_seconds: float
    elapsed: float
    solutions: int
    objective: float | None = None
    result_timetable_id: int | None = None
    result_name: str | None = None
    error: str | None = None
    report: SoftReportOut | None = None
    phase: str = "solving"  # solving / explaining
    partial: bool = False
    conflict: ConflictReportOut | None = None
    unscheduled: list[UnscheduledCourseOut] | None = None
