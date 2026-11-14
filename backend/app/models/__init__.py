"""ORM models 汇总。

新增 model 时在此 import,Alembic 的 autogenerate 与 env.py 才能侦测到 metadata。
"""

from app.models.app_setting import AppSetting
from app.models.assignment import (
    AssignmentTeacher,
    BlockRule,
    CourseAssignment,
    SchedulingUnit,
    SchedulingUnitMember,
    SchedulingUnitType,
)
from app.models.audit import AuditLog
from app.models.basedata import (
    ClassTrack,
    ClassUnit,
    Room,
    RoomType,
    Subject,
    Teacher,
    TeacherRuleType,
    TeacherTimeRule,
)
from app.models.calendar import SchoolCalendarEvent
from app.models.constraint import ConstraintConfig
from app.models.exam import (
    Exam,
    ExamGrade,
    ExamPaperInfo,
    ExamParticipant,
    ExamSpecialArrangement,
    ExamStatusChange,
    ExamSubject,
)
from app.models.exam_arrangement import (
    ExamArrangementLock,
    ExamArrangementRule,
    ExamRoom,
    ExamRoomAssignment,
)
from app.models.exam_analysis import (
    ExamAnalysisSetting,
    ExamGradeBand,
    ExamSubjectThreshold,
    ExamTargetStudent,
)
from app.models.exam_archive import ExamArchive
from app.models.exam_foundation import (
    ExamNumberRule,
    Student,
    StudentStatusChange,
    SubjectScoreSetting,
)
from app.models.exam_invigilation import (
    ExamDiscipline,
    ExamInvigilation,
    ExamInvigilationRule,
    ExamInvigilatorPool,
    ExamPatrol,
)
from app.models.exam_notifications import ExamNotificationLog, ExamNotificationSetting
from app.models.exam_publish import (
    ExamObjection,
    ExamProofreading,
    ExamPublishBatch,
    ExamPublishSetting,
    ExamScoreChangeApproval,
    ExamScoreChangeRequest,
    ExamScoreLock,
)
from app.models.exam_scores import (
    ExamMakeup,
    ExamMakeupScore,
    ExamMarkingAssignment,
    ExamScore,
    ExamScoreItem,
    ExamScoreItemScore,
    ExamScoreSetting,
)
from app.models.exam_scopes import SubjectLeader
from app.models.leave import (
    LEAVE_TYPE_CN,
    AffectedPeriod,
    AffectedStatus,
    LeaveRequest,
    LeaveStatus,
    LeaveType,
)
from app.models.notification import Notification, NotificationType
from app.models.period import Period, PeriodTable, PeriodType
from app.models.semester import Semester, SemesterStatus
from app.models.special_day import SpecialDayEntry, SpecialDayReminderLog, SpecialDayRule
from app.models.substitution import (
    SUBSTITUTION_TYPE_CN,
    Substitution,
    SubstitutionType,
)
from app.models.teacher_swap import TeacherSwap, TeacherSwapReminderLog
from app.models.timetable import ScheduleEntry, Timetable, TimetableStatus
from app.models.user import Role, User, UserRole
from app.models.wizard import WizardState

__all__ = [
    "Role",
    "User",
    "UserRole",
    "Semester",
    "SemesterStatus",
    "PeriodTable",
    "Period",
    "PeriodType",
    "Subject",
    "Teacher",
    "TeacherTimeRule",
    "TeacherRuleType",
    "Room",
    "RoomType",
    "ClassUnit",
    "ClassTrack",
    "WizardState",
    "SchedulingUnit",
    "SchedulingUnitMember",
    "SchedulingUnitType",
    "CourseAssignment",
    "AssignmentTeacher",
    "BlockRule",
    "Timetable",
    "ScheduleEntry",
    "TimetableStatus",
    "AuditLog",
    "AppSetting",
    "ConstraintConfig",
    "LeaveRequest",
    "LeaveType",
    "LeaveStatus",
    "AffectedPeriod",
    "AffectedStatus",
    "LEAVE_TYPE_CN",
    "Notification",
    "NotificationType",
    "Substitution",
    "SubstitutionType",
    "SUBSTITUTION_TYPE_CN",
    "SchoolCalendarEvent",
    "SpecialDayRule",
    "SpecialDayEntry",
    "SpecialDayReminderLog",
    "DutyPattern",
    "DutyOverride",
    "DutySwapRequest",
    "DutyReminderLog",
    "Exam",
    "ExamAnalysisSetting",
    "ExamArchive",
    "ExamArrangementLock",
    "ExamArrangementRule",
    "ExamDiscipline",
    "ExamGrade",
    "ExamGradeBand",
    "ExamInvigilation",
    "ExamInvigilationRule",
    "ExamInvigilatorPool",
    "ExamMakeup",
    "ExamMakeupScore",
    "ExamMarkingAssignment",
    "ExamNumberRule",
    "ExamNotificationLog",
    "ExamNotificationSetting",
    "ExamObjection",
    "ExamPaperInfo",
    "ExamParticipant",
    "ExamPatrol",
    "ExamProofreading",
    "ExamPublishBatch",
    "ExamPublishSetting",
    "ExamRoom",
    "ExamRoomAssignment",
    "ExamScore",
    "ExamScoreChangeApproval",
    "ExamScoreChangeRequest",
    "ExamScoreItem",
    "ExamScoreItemScore",
    "ExamScoreLock",
    "ExamScoreSetting",
    "ExamSpecialArrangement",
    "ExamStatusChange",
    "ExamSubject",
    "ExamSubjectThreshold",
    "ExamTargetStudent",
    "Student",
    "StudentStatusChange",
    "SubjectLeader",
    "SubjectScoreSetting",
    "TeacherSwap",
    "TeacherSwapReminderLog",
]
