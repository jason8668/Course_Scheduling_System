"""资产审计日志(学校资产管理系统一期 #82)。

复用已有 AuditLog 表,不新建审计表。动作名以 ASSET_AUDIT_ACTIONS
为共用登记册:本批及后续批次记录资产关键操作时,动作名先补进登记册
再调用 log_asset_action;未在册的动作名仍可写入(不抛错),避免并行
批次因登记滞后被挡住。

审计日志不可删除:asset 查询接口只有 GET,没有任何删除接口,本模块
也不提供删除函数。支持操作前后值对照查询:before/after 以紧凑 JSON
记进 detail(受 AuditLog.detail 500 字限制,超长截断并标注)。
"""

import json

from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.user import User

#: 资产审计动作名登记册(后续批次共用,新动作先补进这里再使用)。
ASSET_AUDIT_ACTIONS = frozenset(
    {
        "asset_category_create",
        "asset_category_update",
        "asset_finance_map_update",
        "asset_card_create",
        "asset_card_update",
        "asset_card_retire",
        "asset_status_transition",
        "asset_status_transition_denied",
        "asset_code_rule_update",
        "asset_dictionary_update",
        "asset_param_update",
        "asset_field_mapping_update",
        "asset_room_extension_update",
        "asset_access_denied",
        "asset_approval_flow_create",
        "asset_approval_create",
        "asset_approval_act",
        "asset_approval_transfer",
        "asset_approval_return",
        "asset_approval_overdue",
        "asset_sync_adapter_info",
        # ── 第 2 批:台账/入库验收/手动勾选(#8/#9/#12/#13/#14/#19-#28/#87-#90)
        "asset_ledger_export",
        "asset_ledger_search",
        "asset_bulk_update",
        "asset_label_print",
        "asset_attachment_upload",
        "asset_attachment_delete",
        "asset_idle_refresh",
        "asset_acceptance_create",
        "asset_acceptance_confirm",
        "asset_bulk_create",
        "asset_booking_confirm",
        "asset_booking_pending_export",
        "asset_sync_select",
        "asset_sync_unselect",
        # ── 第 3 批:领用/借用/归还/调拨/移交/工作台(#30-#35/#37/#39/#40/#1-#3/#6/#7)
        "asset_issue_create",
        "asset_issue_issue",
        "asset_issue_confirm",
        "asset_borrow_create",
        "asset_borrow_overdue",
        "asset_borrow_remind",
        "asset_reservation_create",
        "asset_reservation_checkout",
        "asset_reservation_release",
        "asset_return_create",
        "asset_return_scan",
        "asset_group_custody_create",
        "asset_transfer_create",
        "asset_transfer_confirm_in",
        "asset_transfer_finalize",
        "asset_handover_create",
        "asset_handover_item_confirm",
        "asset_handover_complete",
        "asset_handover_warn",
        "asset_reminder_create",
        "asset_repair_placeholder_create",
        "asset_workspace_scan",
        # ── 第 4 批:维修保养与盘点清查(#42-#44/#48/#49/#51/#52)
        "asset_repair_create",
        "asset_repair_dispatch",
        "asset_repair_record",
        "asset_repair_confirm",
        "asset_repair_scan",
        "asset_repair_scan_out_of_scope",
        "asset_inventory_plan_create",
        "asset_inventory_task_create",
        "asset_inventory_scan",
        "asset_inventory_scan_out_of_scope",
        "asset_inventory_unlabelled",
        "asset_inventory_diff_compute",
        "asset_inventory_diff_resolve",
        "asset_inventory_close",
        "asset_inventory_due_scan",
        # ── 第 5 批:处置报废与同步执行(#54~#58/#91~#104/#116)
        "asset_disposal_create",
        "asset_disposal_appraise",
        "asset_disposal_appraisal_close",
        "asset_disposal_select_official",
        "asset_disposal_package_create",
        "asset_disposal_official_reply",
        "asset_disposal_retire",
        "asset_disposal_recovery_create",
        "asset_sync_validate",
        "asset_sync_batch_create",
        "asset_sync_export",
        "asset_sync_backfill",
        "asset_sync_confirm",
        "asset_sync_backlog_scan",
        "asset_sync_execute_denied",
    }
)

#: detail 栏位上限(AuditLog.detail String(500));前后值对照截断后仍可辨识。
_DETAIL_LIMIT = 500


def _compact(values: dict | None) -> str:
    if not values:
        return ""
    text = json.dumps(values, ensure_ascii=False, sort_keys=True)
    return text


def log_asset_action(
    db: Session,
    user: User | None,
    action: str,
    *,
    target_type: str = "",
    target_id: int | None = None,
    detail: str = "",
    before: dict | None = None,
    after: dict | None = None,
) -> AuditLog:
    """写一条资产审计日志。before/after 用于操作前后值对照查询。"""
    parts = [detail] if detail else []
    if before is not None or after is not None:
        parts.append(f"改前:{_compact(before)}")
        parts.append(f"改后:{_compact(after)}")
    full = " | ".join(p for p in parts if p)
    if len(full) > _DETAIL_LIMIT:
        full = full[: _DETAIL_LIMIT - 3] + "..."
    row = AuditLog(
        user_id=user.id if user else None,
        username=user.username if user else "",
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=full,
    )
    db.add(row)
    db.flush()
    return row
