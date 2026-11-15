"""通用审批流引擎服务(学校资产管理系统一期 #5/#79/#80)。

所有业务单据共用:可配置节点、会签/或签、转交、退回、超时提醒。
超时提醒:配置 + 待办标记(mark_overdue),定时推送接入后续批次。

岗位分离(#80):同一人提交的单据不能自己审批,act() 时拦截并返回
明确错误;建卡与入账确认分岗由调用方在单据层用不同角色实现,本引擎
保证"申请人 != 审批人"这一层。
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.asset_approval import ApprovalFlow, ApprovalInstance, ApprovalNode
from app.models.asset_config import AssetParam
from app.models.user import Role, User
from app.services.asset_audit import log_asset_action


class ApprovalError(ValueError):
    """审批流业务错误,API 层按 status_code 转 HTTP 状态。

    岗位分离与角色不符属于越权(403),其余流程错误为 400。
    """

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def get_timeout_hours(db: Session) -> int:
    row = db.query(AssetParam).filter_by(key="approval.timeout_hours").first()
    try:
        return int(row.value) if row else 72
    except ValueError:
        return 72


def _nodes_for_amount(nodes: list[dict], amount: float | None) -> list[dict]:
    """按金额门槛过滤节点(#79):金额低于 min_amount 的节点跳过。"""
    kept = []
    for node in nodes:
        threshold = node.get("min_amount")
        if threshold is not None and amount is not None and amount < threshold:
            continue
        if threshold is not None and amount is None:
            continue
        kept.append(node)
    return kept or nodes[:1]


def create_instance(
    db: Session,
    user: User,
    *,
    doc_type: str,
    doc_id: int,
    doc_no: str | None = None,
    amount: float | None = None,
    flow: ApprovalFlow | None = None,
) -> ApprovalInstance:
    """为一份单据创建审批流程实例,按金额过滤节点后生成节点实例。"""
    flow = flow or db.query(ApprovalFlow).filter_by(
        doc_type=doc_type, is_active=True
    ).first() or db.query(ApprovalFlow).filter_by(doc_type="通用", is_active=True).first()
    if flow is None:
        raise ApprovalError(f"没有可用的审批流(doc_type={doc_type})")
    nodes_cfg = _nodes_for_amount(list(flow.nodes or []), amount)
    if not nodes_cfg:
        raise ApprovalError("审批流没有配置任何节点")
    inst = ApprovalInstance(
        flow_id=flow.id,
        doc_type=doc_type,
        doc_id=doc_id,
        doc_no=doc_no,
        applicant_id=user.id,
        applicant_name=user.display_name or user.username,
        amount=amount,
        status="进行中",
        current_step=int(nodes_cfg[0]["step"]),
        deadline=datetime.now(UTC) + timedelta(hours=get_timeout_hours(db)),
    )
    db.add(inst)
    db.flush()
    for cfg in nodes_cfg:
        db.add(ApprovalNode(
            instance_id=inst.id,
            step=int(cfg["step"]),
            role=str(cfg["role"]),
            mode=str(cfg.get("mode", "any")),
            required_approvals=int(cfg.get("required_approvals", 1)),
            status="待审批",
        ))
    db.flush()
    log_asset_action(
        db, user, "asset_approval_create",
        target_type="approval_instance", target_id=inst.id,
        detail=f"发起审批 {doc_type}#{doc_id} 单号{doc_no or ''}",
    )
    return inst


def _current_node(db: Session, inst: ApprovalInstance) -> ApprovalNode | None:
    return db.query(ApprovalNode).filter_by(
        instance_id=inst.id, step=inst.current_step, status="待审批",
    ).first()


def _advance_or_finish(db: Session, inst: ApprovalInstance, user: User) -> None:
    nxt = db.query(ApprovalNode).filter(
        ApprovalNode.instance_id == inst.id,
        ApprovalNode.step > inst.current_step,
        ApprovalNode.status == "待审批",
    ).order_by(ApprovalNode.step).first()
    if nxt is None:
        inst.status = "已通过"
    else:
        inst.current_step = nxt.step


def act(
    db: Session,
    user: User,
    inst: ApprovalInstance,
    *,
    action: str,
    comment: str | None = None,
) -> ApprovalInstance:
    """审批动作:approve(通过)/reject(退回)。

    拦截:
    - 申请人自己审批 → ApprovalError(岗位分离 #80);
    - 审批人角色与当前节点要求不符(非 admin) → ApprovalError(403);
    - 已结束的流程不可再操作。
    会签(all):同一节点须满 required_approvals 人通过才进入下一步。
    """
    if inst.status != "进行中":
        raise ApprovalError(f"流程已结束(状态={inst.status}),不可再操作")
    # 岗位分离:申请与审批不能同一人(#80)。
    if user.id == inst.applicant_id:
        log_asset_action(
            db, user, "asset_approval_act",
            target_type="approval_instance", target_id=inst.id,
            detail="岗位分离拦截:申请人不能审批自己的单据",
        )
        raise ApprovalError("申请与审批不能为同一人", status_code=403)
    node = _current_node(db, inst)
    if node is None:
        raise ApprovalError("当前没有待审批节点")
    # 节点角色检查:admin 为超级用户可代审。
    if Role.admin.value not in user.role_names and node.role not in user.role_names:
        log_asset_action(
            db, user, "asset_approval_act",
            target_type="approval_instance", target_id=inst.id,
            detail=f"角色不符:当前节点要求 {node.role}",
        )
        raise ApprovalError(f"当前节点要求 {node.role} 角色审批", status_code=403)
    if action == "reject":
        node.status = "已退回"
        node.comment = comment
        node.acted_by = user.id
        node.acted_at = datetime.now(UTC)
        inst.status = "已退回"
        log_asset_action(
            db, user, "asset_approval_return",
            target_type="approval_instance", target_id=inst.id,
            detail=f"退回 {inst.doc_type}#{inst.doc_id} 理由:{comment or ''}",
        )
        return inst
    if action != "approve":
        raise ApprovalError(f"未知审批动作 {action}")
    approvals = list(node.approvals or [])
    if user.id in approvals:
        raise ApprovalError("您已在本节点审批过,不可重复审批")
    approvals.append(user.id)
    node.approvals = approvals
    node.acted_by = user.id
    node.acted_at = datetime.now(UTC)
    node.comment = comment
    if len(approvals) >= node.required_approvals:
        node.status = "已通过"
        _advance_or_finish(db, inst, user)
    log_asset_action(
        db, user, "asset_approval_act",
        target_type="approval_instance", target_id=inst.id,
        detail=f"审批通过 {inst.doc_type}#{inst.doc_id} 第{node.step}步 "
               f"({len(approvals)}/{node.required_approvals})",
    )
    return inst


def transfer(
    db: Session,
    user: User,
    inst: ApprovalInstance,
    *,
    to_role: str,
    comment: str | None = None,
) -> ApprovalInstance:
    """转交:当前节点改派给另一角色,全程留痕。申请人不得转交自己的单据。"""
    if inst.status != "进行中":
        raise ApprovalError(f"流程已结束(状态={inst.status}),不可转交")
    if user.id == inst.applicant_id:
        raise ApprovalError("申请人不能转交自己的单据", status_code=403)
    node = _current_node(db, inst)
    if node is None:
        raise ApprovalError("当前没有待审批节点")
    old_role = node.role
    node.role = to_role
    node.status = "待审批"
    inst.status = "进行中"
    log_asset_action(
        db, user, "asset_approval_transfer",
        target_type="approval_instance", target_id=inst.id,
        detail=f"转交 {inst.doc_type}#{inst.doc_id} 第{node.step}步 "
               f"{old_role}→{to_role} 理由:{comment or ''}",
    )
    return inst


def mark_overdue(db: Session, user: User | None = None) -> list[int]:
    """超时标记:超过 deadline 仍进行中的实例打 is_overdue 待办标记。

    只标记、不自动流转、不推送;定时推送接入后续批次。
    """
    now = datetime.now(UTC)
    rows = db.query(ApprovalInstance).filter(
        ApprovalInstance.status == "进行中",
        ApprovalInstance.is_overdue.is_(False),
        ApprovalInstance.deadline.isnot(None),
        ApprovalInstance.deadline < now,
    ).all()
    ids = []
    for inst in rows:
        inst.is_overdue = True
        inst.overdue_at = now
        ids.append(inst.id)
        log_asset_action(
            db, user, "asset_approval_overdue",
            target_type="approval_instance", target_id=inst.id,
            detail=f"审批超时待办 {inst.doc_type}#{inst.doc_id}",
        )
    db.flush()
    return ids
