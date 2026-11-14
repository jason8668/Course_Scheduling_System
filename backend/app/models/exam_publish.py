"""成绩发布与校对锁定模型(KW-36~40):发布设置、双人校对、成绩锁定、改分审批、发布批次、成绩异议。

校对人 proofreader_id 存 User id(校对决定按登录账号判定);校对范围按科目+班级,
class_unit_id 为空表示该科目全部班级。锁定按科目+班级,全科锁 class_unit_id 为空。
改分审批层级由发布设置 approval_levels 控制,每层决定单独留痕。
发布批次 scope_type 为年级/班级,scope_value 存年级数字或班级 id。
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

PROOFREADER_ROLES = ("subject_leader", "peer_teacher")
PROOFREADING_STATUSES = ("待校对", "通过", "退回")
CHANGE_REQUEST_STATUSES = ("待审批", "已通过", "已驳回")
CHANGE_DECISIONS = ("通过", "驳回")
PUBLISH_SCOPE_TYPES = ("年级", "班级")
PUBLISH_BATCH_STATUSES = ("待发布", "已发布", "已撤回")
OBJECTION_STATUSES = ("待复核", "已回复", "已关闭")


class ExamPublishSetting(Base):
    """发布设置(KW-36/38/39/40):一次考试一条,未设过用默认值。

    proofreader_role:subject_leader 教研组长 / peer_teacher 同组教师。
    approval_levels:1 一层审批 / 2 两层审批(教研组长→教务)。
    objection_open:是否开放异议入口,默认 true。
    """

    __tablename__ = "exam_publish_settings"
    __table_args__ = (
        UniqueConstraint("exam_id", name="uq_exam_publish_settings_exam"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    proofreader_role: Mapped[str] = mapped_column(String(20), default="subject_leader")
    approval_levels: Mapped[int] = mapped_column(Integer, default=1)
    objection_open: Mapped[bool] = mapped_column(Boolean, default=True)


class ExamProofreading(Base):
    """双人校对记录(KW-36):成绩提交后由第二人校对确认,通过才能锁定。

    submitted_by 为提交校对的用户 id(一般为成绩录入教师);
    proofreader_id 为指定的校对人用户 id;status 待校对/通过/退回。
    """

    __tablename__ = "exam_proofreadings"

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    class_unit_id: Mapped[int | None] = mapped_column(
        ForeignKey("class_units.id", ondelete="CASCADE"), nullable=True, index=True
    )
    submitted_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    proofreader_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default="待校对")  # 待校对/通过/退回
    note: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExamScoreLock(Base):
    """成绩锁定(KW-37):按科目+班级锁,锁定后本人不能直接改分,只能走改分审批。

    class_unit_id 为空表示该科目全部班级都锁。唯一约束
    (exam_id, subject_id, class_unit_id);空班级的重复由服务层拦(空值在
    唯一约束里互不相等)。
    """

    __tablename__ = "exam_score_locks"
    __table_args__ = (
        UniqueConstraint(
            "exam_id", "subject_id", "class_unit_id",
            name="uq_exam_score_locks_exam_subject_class",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    class_unit_id: Mapped[int | None] = mapped_column(
        ForeignKey("class_units.id", ondelete="CASCADE"), nullable=True, index=True
    )
    locked_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    locked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExamScoreChangeRequest(Base):
    """改分申请(KW-38):锁定后改分须提交申请,审批通过后生效。

    old_score 从 ExamScore 取,缺考等空分时为空;status 待审批/已通过/已驳回。
    """

    __tablename__ = "exam_score_change_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    score_id: Mapped[int] = mapped_column(
        ForeignKey("exam_scores.id", ondelete="CASCADE"), index=True
    )
    old_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    new_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(20), default="待审批")  # 待审批/已通过/已驳回
    requested_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExamScoreChangeApproval(Base):
    """改分审批决定(KW-38):每层决定单独一行,前后值与审批人全程留痕。

    level 1/2;decision 通过/驳回;唯一约束 (request_id, level)。
    """

    __tablename__ = "exam_score_change_approvals"
    __table_args__ = (
        UniqueConstraint(
            "request_id", "level",
            name="uq_exam_score_change_approvals_request_level",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(
        ForeignKey("exam_score_change_requests.id", ondelete="CASCADE"), index=True
    )
    level: Mapped[int] = mapped_column(Integer)
    approver_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decision: Mapped[str] = mapped_column(String(20))  # 通过/驳回
    note: Mapped[str | None] = mapped_column(String(512), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExamPublishBatch(Base):
    """成绩发布批次(KW-39):教务按年级或按班级分批发布,也可定时发布。

    scope_type 年级/班级;scope_value 存年级数字或班级 id。
    publish_at 为空表示立即发布;未来时间表示定时发布,未到时状态为待发布。
    status 待发布/已发布/已撤回。
    """

    __tablename__ = "exam_publish_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    scope_type: Mapped[str] = mapped_column(String(20))  # 年级/班级
    scope_value: Mapped[int] = mapped_column(Integer)
    publish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="待发布")  # 待发布/已发布/已撤回
    published_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExamObjection(Base):
    """成绩异议(KW-40):教师/教务代学生登记异议,任课教师复核后回复,形成闭环。

    由教师/教务代登,raised_by_role 注明代登人角色(教师/教务/管理员)。
    status 待复核/已回复/已关闭。
    """

    __tablename__ = "exam_objections"

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), index=True
    )
    score_id: Mapped[int] = mapped_column(
        ForeignKey("exam_scores.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    content: Mapped[str] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(String(20), default="待复核")  # 待复核/已回复/已关闭
    reply: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    replied_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    raised_by_role: Mapped[str] = mapped_column(String(20), default="教师")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
