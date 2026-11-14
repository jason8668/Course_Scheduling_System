"""考务审计日志(KW-64)。

复用已有 AuditLog 表,不新建审计表。动作名以 EXAM_AUDIT_ACTIONS
为共用登记册:本批及后续批次记录考务关键操作时,动作名先补进
登记册再调用 log_exam_action;未在册的动作名仍可写入(不抛错),
避免并行批次因登记滞后被挡住,但新动作应当先登记。

审计日志不可删除:audit 查询接口只有 GET,没有任何删除接口,
本模块也不提供删除函数。
"""

from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.user import User

#: 考务审计动作名登记册(后续批次共用,新动作先补进这里再使用)。
EXAM_AUDIT_ACTIONS = frozenset(
    {
        "exam_student_create",
        "exam_student_update",
        "exam_student_import",
        "exam_student_export",
        "exam_student_status_change",
        "exam_parent_create",
        "exam_parent_update",
        "exam_parent_delete",
        "exam_subject_setting_update",
        "exam_number_rule_update",
        "exam_number_generate",
        "exam_subject_leader_assign",
        "exam_subject_leader_remove",
        "exam_create",
        "exam_update",
        "exam_status_change",
        "exam_copy",
        "exam_subject_update",
        "exam_participant_generate",
        "exam_participant_update",
        "exam_paper_info_update",
        "exam_special_arrangement_create",
        "exam_special_arrangement_update",
        "exam_special_arrangement_delete",
        "exam_room_create",
        "exam_room_delete",
        "exam_arrangement_rule_update",
        "exam_arrange",
        "exam_arrangement_move",
        "exam_arrangement_swap",
        "exam_arrangement_lock",
        "exam_arrangement_unlock",
        "exam_invigilation_rule_update",
        "exam_invigilator_pool_update",
        "exam_invigilate",
        "exam_invigilation_create",
        "exam_invigilation_update",
        "exam_invigilation_delete",
        "exam_patrol_create",
        "exam_patrol_update",
        "exam_patrol_delete",
        "exam_discipline_create",
        "exam_discipline_update",
        "exam_discipline_delete",
        "exam_score_settings_update",
        "exam_marking_assignment_create",
        "exam_marking_assignment_delete",
        "exam_score_item_create",
        "exam_score_item_delete",
        "exam_score_update",
        "exam_score_submit",
        "exam_score_import",
        "exam_makeup_create",
        "exam_makeup_delete",
        "exam_makeup_score_update",
        "exam_publish_settings_update",
        "exam_proofreading_submit",
        "exam_proofreading_decide",
        "exam_score_lock_create",
        "exam_score_lock_delete",
        "exam_score_change_request_create",
        "exam_score_change_decide",
        "exam_publish_batch_create",
        "exam_publish_batch_withdraw",
        "exam_publish_due",
        "exam_objection_create",
        "exam_objection_reply",
        "exam_objection_close",
        "exam_analysis_settings_update",
        "exam_subject_threshold_update",
        "exam_target_student_create",
        "exam_target_student_delete",
        "exam_grade_band_update",
        "exam_report_pack_export",
        "exam_report_settings_update",
        "exam_account_provision",
        "exam_account_password_reset",
        "exam_grade_book_export",
        "exam_notification_settings_update",
        "exam_schedule_notify",
        "exam_invigilation_notify",
        "exam_score_deadline_notify",
        "exam_publish_notify",
        "exam_notification_remind_due",
        "exam_notification_resend",
        "exam_archive_create",
        "exam_archive_delete",
        "exam_archive_download",
        "exam_backup_export",
    }
)


def log_exam_action(
    db: Session,
    user: User | None,
    action: str,
    target_type: str = "",
    target_id: int | None = None,
    detail: str = "",
) -> AuditLog:
    """写一条考务审计记录并回传该记录。

    username 为快照,账号删除后仍可辨识;detail 超长时截断到 500 字
    以内(与 AuditLog.detail 栏位长度一致)。只写库不提交,由调用方
    决定提交时机;写后 flush,使调用方能立即拿到记录 id。
    """
    log = AuditLog(
        user_id=user.id if user is not None else None,
        username=user.username if user is not None else "",
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=(detail or "")[:500],
    )
    db.add(log)
    db.flush()
    return log
