"""成绩分析 schema(KW-41~51)。"""

from pydantic import BaseModel, ConfigDict, Field


class AnalysisSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    exam_id: int
    rank_tie_rule: str = "dense"
    segment_size: int = 10
    critical_total_line: float | None = None
    critical_margin: float = 5
    subject_critical_margin: float = 5


class AnalysisSettingsPut(BaseModel):
    rank_tie_rule: str = "dense"
    segment_size: int = 10
    critical_total_line: float | None = None
    critical_margin: float = 5
    subject_critical_margin: float = 5


class SubjectThresholdOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    exam_id: int
    subject_id: int
    subject_name: str = ""
    pass_line: float | None = None
    excellent_line: float | None = None


class SubjectThresholdIn(BaseModel):
    subject_id: int
    pass_line: float | None = None
    excellent_line: float | None = None


class SubjectThresholdPut(BaseModel):
    items: list[SubjectThresholdIn] = []


class SubjectThresholdListOut(BaseModel):
    items: list[SubjectThresholdOut]


class SubjectStatsOut(BaseModel):
    subject_id: int
    subject_name: str = ""
    count: int
    avg: float | None = None
    max: float | None = None
    min: float | None = None
    std: float | None = None
    pass_rate: float = 0
    excellent_rate: float = 0
    low_rate: float = 0


class TotalsOut(BaseModel):
    count: int
    avg: float | None = None
    max: float | None = None
    min: float | None = None
    std: float | None = None


class AnalysisSummaryOut(BaseModel):
    scope: str
    totals: TotalsOut
    subjects: list[SubjectStatsOut]


class RankingItemOut(BaseModel):
    student_id: int
    student_no: str = ""
    student_name: str = ""
    class_name: str = ""
    total: float | None = None
    rank: int


class RankingListOut(BaseModel):
    items: list[RankingItemOut]
    total: int


class SegmentOut(BaseModel):
    label: str
    count: int
    pct: float


class SegmentListOut(BaseModel):
    segments: list[SegmentOut]


class SubjectGapOut(BaseModel):
    subject_name: str = ""
    score: float | None = None
    gap: float | None = None


class CriticalItemOut(BaseModel):
    student_id: int
    student_no: str = ""
    student_name: str = ""
    class_name: str = ""
    total: float | None = None
    gap_to_line: float | None = None
    subject_gaps: list[SubjectGapOut] = []


class CriticalListOut(BaseModel):
    items: list[CriticalItemOut]


class TargetStudentIn(BaseModel):
    student_id: int
    target_total: float | None = None
    note: str | None = None


class TargetStudentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    exam_id: int
    student_id: int
    student_no: str = ""
    student_name: str = ""
    class_name: str = ""
    target_total: float | None = None
    note: str | None = None


class TargetStudentListOut(BaseModel):
    items: list[TargetStudentOut]


class TargetTrackingItemOut(BaseModel):
    student_id: int
    student_no: str = ""
    student_name: str = ""
    class_name: str = ""
    target_total: float | None = None
    total: float | None = None
    reached: bool = False
    weak_subjects: list[str] = []


class TargetTrackingListOut(BaseModel):
    items: list[TargetTrackingItemOut]


class ProgressItemOut(BaseModel):
    student_id: int
    student_no: str = ""
    student_name: str = ""
    class_name: str = ""
    prev_total: float | None = None
    total: float | None = None
    prev_rank: int | None = None
    rank: int | None = None
    delta: int | None = None


class ProgressListOut(BaseModel):
    items: list[ProgressItemOut]
    top_improved: list[ProgressItemOut] = []
    top_declined: list[ProgressItemOut] = []
    message: str | None = None


class QualityClassSubjectOut(BaseModel):
    class_unit_id: int
    class_name: str = ""
    avg: float | None = None
    pass_rate: float = 0
    excellent_rate: float = 0


class QualitySubjectOut(BaseModel):
    subject_id: int
    subject_name: str = ""
    classes: list[QualityClassSubjectOut]


class QualityClassSubjectRateOut(BaseModel):
    subject_id: int
    subject_name: str = ""
    avg: float | None = None
    pass_rate: float = 0


class QualityClassOut(BaseModel):
    class_unit_id: int
    class_name: str = ""
    subjects: list[QualityClassSubjectRateOut]


class QualityCompareOut(BaseModel):
    subjects: list[QualitySubjectOut]
    classes: list[QualityClassOut]


class TrendExamOut(BaseModel):
    exam_id: int
    exam_name: str = ""
    exam_date: str | None = None
    total: float | None = None
    subjects: dict[str, float | None] = {}


class TrendOut(BaseModel):
    student_id: int
    student_name: str = ""
    exams: list[TrendExamOut]


class GradeBandIn(BaseModel):
    subject_id: int | None = None
    grade_label: str = Field(min_length=1, max_length=8)
    min_score: float
    max_score: float


class GradeBandPut(BaseModel):
    items: list[GradeBandIn] = []


class GradeBandOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    exam_id: int
    subject_id: int | None = None
    grade_label: str
    min_score: float
    max_score: float


class GradeBandListOut(BaseModel):
    items: list[GradeBandOut]


class GradeDistributionBandOut(BaseModel):
    grade_label: str
    count: int
    pct: float


class GradeDistributionOut(BaseModel):
    bands: list[GradeDistributionBandOut]
