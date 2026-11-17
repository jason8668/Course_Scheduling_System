"""ORM models 汇总。

新增 model 时在此 import,Alembic 的 autogenerate 与 env.py 才能侦测到 metadata。
"""

from app.models.app_setting import AppSetting
from app.models.asset_approval import (
    ApprovalFlow,
    ApprovalInstance,
    ApprovalNode,
)
from app.models.asset_card import (
    AssetCard,
    AssetRoomExtension,
    AssetStatus,
    BorrowStatus,
    SyncStatus,
)
from app.models.asset_category import (
    TOP_LEVEL_CATEGORIES,
    AssetCategory,
    AssetCategoryFinanceMap,
)
from app.models.asset_config import (
    AssetCodeRule,
    AssetDictionary,
    AssetParam,
)
from app.models.asset_circulation import (
    AssetBorrowOrder,
    AssetGroupCustody,
    AssetHandoverItem,
    AssetHandoverOrder,
    AssetIssueOrder,
    AssetReminder,
    AssetRepairOrder,
    AssetReservation,
    AssetReturnOrder,
    AssetTransferOrder,
)
from app.models.asset_inventory import (
    AssetInventoryDifference,
    AssetInventoryPlan,
    AssetInventoryRecord,
    AssetInventoryTask,
)
from app.models.asset_ledger import (
    AcceptanceStatus,
    AssetAcceptance,
    AssetAttachment,
    AssetBatch,
    AssetSyncSelection,
    IntakeType,
)
from app.models.asset_department import AssetDepartment
from app.models.asset_disposal import (
    AssetDisposalAppraisal,
    AssetDisposalOrder,
    AssetDisposalPackage,
    AssetDisposalRecovery,
)
from app.models.asset_sync import AssetFieldMapping
from app.models.asset_sync_exec import (
    AssetSyncBatch,
    AssetSyncBatchItem,
    AssetSyncLog,
)
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
    # ── 学校资产管理系统一期地基批(#5/#10/#11/#15/#16/#17/#76/#78/#79/#80/#81/#82/#85/#86/#104)
    "AssetCard",
    "AssetDepartment",
    "AssetStatus",
    "BorrowStatus",
    "SyncStatus",
    "AssetRoomExtension",
    "AssetCategory",
    "AssetCategoryFinanceMap",
    "TOP_LEVEL_CATEGORIES",
    "AssetDictionary",
    "AssetParam",
    "AssetCodeRule",
    "ApprovalFlow",
    "ApprovalInstance",
    "ApprovalNode",
    "AssetFieldMapping",
    # ── 学校资产管理系统一期第 4 批(#42-#44/#48/#49/#51/#52)
    "AssetInventoryPlan",
    "AssetInventoryTask",
    "AssetInventoryRecord",
    "AssetInventoryDifference",
    # ── 学校资产管理系统一期第 2 批(#12/#14/#19-#28/#87-#90)
    "AssetAcceptance",
    "AcceptanceStatus",
    "AssetAttachment",
    "AssetBatch",
    "AssetSyncSelection",
    "IntakeType",
]
