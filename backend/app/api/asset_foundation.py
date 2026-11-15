"""资产地基 API(学校资产管理系统一期第 1 批)。

挂在 /api/asset 下。复用现有登录与鉴权(#77),不新建登录入口;
资产操作按八类角色(#78)做权限依赖,越权返回 403 并记审计日志。
状态没有直接修改端点(#15):状态转移只走 /assets/{id}/transition,
且必须带业务单据类型与单号;核销走 /assets/{id}/retire。
"""

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import get_active_user
from app.core.db import get_db
from app.models.asset_approval import ApprovalFlow, ApprovalInstance, ApprovalNode
from app.models.asset_card import AssetCard, AssetStatus, SyncStatus
from app.models.asset_disposal import AssetDisposalOrder, AssetDisposalRecovery
from app.models.asset_category import AssetCategory, AssetCategoryFinanceMap
from app.models.asset_config import AssetCodeRule, AssetDictionary, AssetParam
from app.models.asset_sync import AssetFieldMapping
from app.models.audit import AuditLog
from app.models.basedata import Room
from app.models.user import ASSET_ROLE_LABELS, Role, User
from app.schemas.asset import (
    ApprovalActIn,
    ApprovalFlowIn,
    ApprovalFlowOut,
    ApprovalInstanceIn,
    ApprovalInstanceOut,
    ApprovalNodeOut,
    ApprovalTransferIn,
    AssetCardCreate,
    AssetCardListOut,
    AssetCardOut,
    AssetCardUpdate,
    AssetCategoryCreate,
    AssetCategoryOut,
    AssetCategoryUpdate,
    AssetCodeRuleIn,
    AssetCodeRuleOut,
    AssetDictionaryIn,
    AssetDictionaryOut,
    AssetFieldMappingIn,
    AssetFieldMappingOut,
    AssetFieldMappingUpdate,
    AssetParamIn,
    AssetParamOut,
    AssetRoomExtensionIn,
    AssetRoomExtensionOut,
    AssetTransitionIn,
    FinanceMapIn,
    FinanceMapOut,
    LabelVerifyOut,
    SyncAdapterOut,
)
from app.services import asset_approval as approval_svc
from app.services import asset_disposal as disposal_svc
from app.services import asset_foundation as asset_svc
from app.services.asset_audit import log_asset_action
from app.services.asset_seed import seed_asset_foundation
from app.services.asset_sync_adapter import ADAPTER_BOUNDARY_NOTE, get_adapter

router = APIRouter(tags=["asset"])


def require_asset_roles(*roles: Role) -> Callable[..., User]:
    """资产角色依赖:越权时先记审计日志再返回 403(#78/#82)。"""
    allowed = {r.value for r in roles}

    def checker(
        db: Session = Depends(get_db),
        user: User = Depends(get_active_user),
    ) -> User:
        names = user.role_names
        if Role.admin.value in names or allowed & names:
            return user
        log_asset_action(
            db, user, "asset_access_denied",
            target_type="asset_permission",
            detail=f"越权访问:需要角色 {sorted(allowed)},实际角色 {sorted(names)}",
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")

    return checker


#: 写资产台账的角色(#78):资产管理员;admin 为超级用户一律通过。
asset_writer = require_asset_roles(Role.asset_admin)
admin_only = require_asset_roles(Role.admin)
finance_or_admin = require_asset_roles(Role.asset_finance, Role.admin)
auditor_or_admin = require_asset_roles(Role.asset_auditor, Role.admin)


def _get_card_or_404(db: Session, asset_id: int) -> AssetCard:
    card = db.get(AssetCard, asset_id)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "资产卡不存在")
    return card


def _get_flow_or_404(db: Session, flow_id: int) -> ApprovalFlow:
    flow = db.get(ApprovalFlow, flow_id)
    if flow is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "审批流不存在")
    return flow


def _get_instance_or_404(db: Session, instance_id: int) -> ApprovalInstance:
    inst = db.get(ApprovalInstance, instance_id)
    if inst is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "审批实例不存在")
    return inst


def _instance_out(db: Session, inst: ApprovalInstance) -> ApprovalInstanceOut:
    nodes = db.query(ApprovalNode).filter_by(instance_id=inst.id).order_by(
        ApprovalNode.step
    ).all()
    out = ApprovalInstanceOut.model_validate(inst)
    out.nodes = [ApprovalNodeOut.model_validate(n) for n in nodes]
    return out


# ── 角色清单(#78,供前端展示) ──────────────────────────────
@router.get("/roles", response_model=dict)
def list_asset_roles(user: User = Depends(get_active_user)):
    return {"roles": [
        {"value": k, "label": v} for k, v in ASSET_ROLE_LABELS.items()
    ]}


# ── 资产分类字典 #16 ──────────────────────────────
@router.get("/categories", response_model=list[AssetCategoryOut])
def list_categories(
    level: int | None = None,
    parent_code: str | None = None,
    is_active: bool | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    q = db.query(AssetCategory)
    if level is not None:
        q = q.filter_by(level=level)
    if parent_code is not None:
        q = q.filter_by(parent_code=parent_code)
    if is_active is not None:
        q = q.filter_by(is_active=is_active)
    return q.order_by(AssetCategory.sort_order, AssetCategory.code).all()


@router.post("/categories", response_model=AssetCategoryOut,
             status_code=status.HTTP_201_CREATED)
def create_category(
    body: AssetCategoryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(admin_only),
):
    if body.is_reportable:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "上报分类不得自行新增,只能在官方分类下增加校内管理标签",
        )
    if db.query(AssetCategory).filter_by(code=body.code).first():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"分类代码已存在:{body.code}")
    row = AssetCategory(
        code=body.code, name=body.name, level=body.level,
        parent_code=body.parent_code, is_reportable=False, origin="school",
    )
    db.add(row)
    db.flush()
    log_asset_action(
        db, user, "asset_category_create",
        target_type="asset_category", target_id=row.id,
        detail=f"新建校内分类标签 {body.code} {body.name}",
    )
    db.commit()
    return row


@router.patch("/categories/{code}", response_model=AssetCategoryOut)
def update_category(
    code: str,
    body: AssetCategoryUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(admin_only),
):
    row = db.query(AssetCategory).filter_by(code=code).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "分类不存在")
    before = {"is_active": row.is_active, "sort_order": row.sort_order}
    if body.is_active is not None:
        row.is_active = body.is_active
    if body.sort_order is not None:
        row.sort_order = body.sort_order
    log_asset_action(
        db, user, "asset_category_update",
        target_type="asset_category", target_id=row.id,
        detail=f"维护分类 {code}(上报分类代码与名称已锁定,本次只改启用/排序)",
        before=before,
        after={"is_active": row.is_active, "sort_order": row.sort_order},
    )
    db.commit()
    return row


@router.get("/categories/{code}/finance-map", response_model=list[FinanceMapOut])
def list_finance_map(
    code: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    return db.query(AssetCategoryFinanceMap).filter_by(category_code=code).all()


@router.post("/categories/{code}/finance-map", response_model=FinanceMapOut,
             status_code=status.HTTP_201_CREATED)
def upsert_finance_map(
    code: str,
    body: FinanceMapIn,
    db: Session = Depends(get_db),
    user: User = Depends(finance_or_admin),
):
    if not db.query(AssetCategory).filter_by(code=code).first():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "分类不存在")
    row = db.query(AssetCategoryFinanceMap).filter_by(
        category_code=code, finance_subject_code=body.finance_subject_code,
    ).first()
    if row is None:
        row = AssetCategoryFinanceMap(category_code=code)
        db.add(row)
    row.finance_subject_code = body.finance_subject_code
    row.finance_subject_name = body.finance_subject_name
    row.is_default = body.is_default
    row.note = body.note
    db.flush()
    log_asset_action(
        db, user, "asset_finance_map_update",
        target_type="asset_category_finance_map", target_id=row.id,
        detail=f"维护分类对照 {code} → {body.finance_subject_name}",
    )
    db.commit()
    return row


# ── 编码规则 #17 ──────────────────────────────
@router.get("/code-rules", response_model=list[AssetCodeRuleOut])
def list_code_rules(
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    return db.query(AssetCodeRule).order_by(AssetCodeRule.id).all()


@router.post("/code-rules", response_model=AssetCodeRuleOut,
             status_code=status.HTTP_201_CREATED)
def create_code_rule(
    body: AssetCodeRuleIn,
    db: Session = Depends(get_db),
    user: User = Depends(admin_only),
):
    row = AssetCodeRule(
        name=body.name, prefix=body.prefix, include_year=body.include_year,
        include_category=body.include_category,
        sequence_width=body.sequence_width, is_active=False, note=body.note,
    )
    db.add(row)
    db.flush()
    log_asset_action(
        db, user, "asset_code_rule_update",
        target_type="asset_code_rule", target_id=row.id,
        detail=f"新增编码规则 {body.name} 前缀{body.prefix}",
    )
    db.commit()
    return row


@router.post("/code-rules/{rule_id}/activate", response_model=AssetCodeRuleOut)
def activate_code_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(admin_only),
):
    row = db.get(AssetCodeRule, rule_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "编码规则不存在")
    db.query(AssetCodeRule).update({"is_active": False})
    row.is_active = True
    log_asset_action(
        db, user, "asset_code_rule_update",
        target_type="asset_code_rule", target_id=row.id,
        detail=f"启用编码规则 {row.name}",
    )
    db.commit()
    return row


@router.get("/code-rules/preview", response_model=dict)
def preview_asset_code(
    category_code: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    try:
        code = asset_svc.generate_asset_code(db, category_code)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return {"asset_code": code, "label_code": asset_svc.make_label_code(code)}


# ── 资产卡 #10/#11/#15/#85/#86 ──────────────────────────────
@router.get("/assets", response_model=AssetCardListOut)
def list_assets(
    category_code: str | None = None,
    status_: str | None = Query(default=None, alias="status"),
    sync_status: str | None = None,
    manage_dept: str | None = None,
    custodian_name: str | None = None,
    room_id: int | None = None,
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    query = db.query(AssetCard)
    if category_code:
        query = query.filter(AssetCard.category_code.like(f"{category_code}%"))
    if status_:
        if status_ not in {s.value for s in AssetStatus}:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"未知资产状态 {status_}")
        query = query.filter_by(status=status_)
    if sync_status:
        if sync_status not in {s.value for s in SyncStatus}:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"未知同步状态 {sync_status}")
        query = query.filter_by(sync_status=sync_status)
    if manage_dept:
        query = query.filter_by(manage_dept=manage_dept)
    if custodian_name:
        query = query.filter(AssetCard.custodian_name.like(f"%{custodian_name}%"))
    if room_id is not None:
        query = query.filter_by(room_id=room_id)
    if q:
        query = query.filter(
            (AssetCard.name.like(f"%{q}%")) | (AssetCard.asset_code.like(f"%{q}%"))
        )
    total = query.count()
    rows = query.order_by(AssetCard.id.desc()).offset(offset).limit(limit).all()
    return AssetCardListOut(items=[AssetCardOut.model_validate(r) for r in rows], total=total)


@router.get("/assets/by-code/{code}", response_model=AssetCardOut)
def get_asset_by_code(
    code: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """双号索引查询(#17):校内编号或官方编号均可查到同一张卡。"""
    card = db.query(AssetCard).filter(
        (AssetCard.asset_code == code) | (AssetCard.official_code == code)
    ).first()
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未找到该编号的资产卡")
    return card


@router.get("/assets/{asset_id}", response_model=AssetCardOut)
def get_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    return _get_card_or_404(db, asset_id)


@router.post("/assets", response_model=AssetCardOut, status_code=status.HTTP_201_CREATED)
def create_asset(
    body: AssetCardCreate,
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    try:
        card = asset_svc.create_asset_card(db, user, **body.model_dump())
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    db.commit()
    return card


@router.patch("/assets/{asset_id}", response_model=AssetCardOut)
def update_asset(
    asset_id: int,
    body: AssetCardUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    card = _get_card_or_404(db, asset_id)
    if card.is_retired:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "资产已核销封存,不可修改")
    data = body.model_dump(exclude_unset=True)
    before = {k: getattr(card, k) for k in data if hasattr(card, k)}
    for key, value in data.items():
        setattr(card, key, value)
    # 特性字段改后重新按分类模板校验。
    if "attributes" in data:
        try:
            asset_svc.validate_attributes(card.category_code, card.attributes)
        except ValueError as e:
            db.rollback()
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    log_asset_action(
        db, user, "asset_card_update",
        target_type="asset_card", target_id=card.id,
        detail=f"修改资产卡 {card.asset_code}",
        before={k: str(v) for k, v in before.items()},
        after={k: str(v) for k, v in data.items()},
    )
    db.commit()
    return card


@router.post("/assets/{asset_id}/transition", response_model=AssetCardOut)
def transition_asset_status(
    asset_id: int,
    body: AssetTransitionIn,
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """状态转移(#15):只能由业务单据驱动,须带单据类型与单号;非法转移拦截。"""
    card = _get_card_or_404(db, asset_id)
    try:
        asset_svc.transition_asset(
            db, user, card, body.to_status,
            doc_type=body.doc_type, doc_no=body.doc_no,
        )
    except ValueError as e:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    db.commit()
    return card


@router.post("/assets/{asset_id}/retire", response_model=AssetCardOut)
def retire_asset(
    asset_id: int,
    doc_type: str = Query(default="处置"),
    doc_no: str = Query(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(asset_writer),
):
    """核销(#11/#15):状态经 待处置 → 已核销,编号封存不复用。须带单据号。"""
    card = _get_card_or_404(db, asset_id)
    if not doc_no:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "核销须提供单据号(doc_no)")
    # 第 5 批 #58:单据号对应处置单时,未回填官方批复不得核销。
    disposal = db.query(AssetDisposalOrder).filter_by(doc_no=doc_no).first()
    if disposal is not None and not disposal.official_reply_no:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "未回填官方批复,不得核销")
    try:
        asset_svc.transition_asset(
            db, user, card, AssetStatus.retired.value,
            doc_type=doc_type, doc_no=doc_no,
        )
    except ValueError as e:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    log_asset_action(
        db, user, "asset_card_retire",
        target_type="asset_card", target_id=card.id,
        detail=f"核销资产 {card.asset_code} 单据{doc_type}#{doc_no} 编号封存",
    )
    if disposal is not None:
        # 第 5 批 #58:处置单置已核销并生成回收交接单骨架(待交接)。
        disposal.status = "已核销"
        if db.query(AssetDisposalRecovery).filter_by(
                disposal_id=disposal.id).first() is None:
            db.add(AssetDisposalRecovery(
                recovery_no=disposal_svc.next_recovery_no(
                    db, AssetDisposalRecovery),
                disposal_id=disposal.id, status="待交接", created_by=user.id,
            ))
        log_asset_action(
            db, user, "asset_disposal_retire",
            target_type="disposal_order", target_id=disposal.id,
            detail=f"核销处置 {disposal.doc_no} 资产{card.asset_code} "
                   f"批复{disposal.official_reply_no or ''} 编号封存",
        )
    db.commit()
    return card


@router.get("/assets/{asset_id}/label", response_model=LabelVerifyOut)
def verify_asset_label(
    asset_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    card = _get_card_or_404(db, asset_id)
    return LabelVerifyOut(
        asset_code=card.asset_code,
        label_code=card.label_code,
        valid=asset_svc.verify_label_code(card.label_code),
    )


# ── 房间扩展 #76 ──────────────────────────────
@router.get("/room-extensions", response_model=list[AssetRoomExtensionOut])
def list_room_extensions(
    room_id: int | None = None,
    building: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    from app.models.asset_card import AssetRoomExtension

    query = db.query(AssetRoomExtension)
    if room_id is not None:
        query = query.filter_by(room_id=room_id)
    if building:
        query = query.filter_by(building=building)
    return query.order_by(AssetRoomExtension.id).all()


@router.post("/room-extensions", response_model=AssetRoomExtensionOut,
             status_code=status.HTTP_201_CREATED)
def upsert_room_extension(
    body: AssetRoomExtensionIn,
    db: Session = Depends(get_db),
    user: User = Depends(admin_only),
):
    from app.models.asset_card import AssetRoomExtension

    if not db.get(Room, body.room_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "教室不存在(请复用智慧教务教室数据)")
    row = db.query(AssetRoomExtension).filter_by(room_id=body.room_id).first()
    if row is None:
        row = AssetRoomExtension(room_id=body.room_id)
        db.add(row)
    row.campus = body.campus
    row.building = body.building
    row.asset_package = body.asset_package
    row.note = body.note
    db.flush()
    log_asset_action(
        db, user, "asset_room_extension_update",
        target_type="asset_room_extension", target_id=row.id,
        detail=f"维护房间扩展 room_id={body.room_id} 楼栋{body.building or ''} "
               f"资产包{body.asset_package or ''}",
    )
    db.commit()
    return row


# ── 字典与参数 #81 ──────────────────────────────
@router.get("/dictionaries", response_model=list[AssetDictionaryOut])
def list_dictionaries(
    dict_type: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    q = db.query(AssetDictionary)
    if dict_type:
        q = q.filter_by(dict_type=dict_type)
    return q.order_by(AssetDictionary.dict_type, AssetDictionary.sort_order).all()


@router.post("/dictionaries", response_model=AssetDictionaryOut,
             status_code=status.HTTP_201_CREATED)
def create_dictionary(
    body: AssetDictionaryIn,
    db: Session = Depends(get_db),
    user: User = Depends(admin_only),
):
    if db.query(AssetDictionary).filter_by(
        dict_type=body.dict_type, code=body.code
    ).first():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "字典值已存在")
    row = AssetDictionary(
        dict_type=body.dict_type, code=body.code, label=body.label,
        is_system=False, sort_order=body.sort_order,
    )
    db.add(row)
    db.flush()
    log_asset_action(
        db, user, "asset_dictionary_update",
        target_type="asset_dictionary", target_id=row.id,
        detail=f"新增字典 {body.dict_type}:{body.code}={body.label}",
    )
    db.commit()
    return row


@router.get("/params", response_model=list[AssetParamOut])
def list_params(
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    return db.query(AssetParam).order_by(AssetParam.key).all()


@router.put("/params/{key}", response_model=AssetParamOut)
def update_param(
    key: str,
    body: AssetParamIn,
    db: Session = Depends(get_db),
    user: User = Depends(admin_only),
):
    row = db.query(AssetParam).filter_by(key=key).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "参数不存在")
    before = {"value": row.value}
    row.value = body.value
    row.updated_by = user.id
    log_asset_action(
        db, user, "asset_param_update",
        target_type="asset_param", target_id=row.id,
        detail=f"修改参数 {key}",
        before=before, after={"value": body.value},
    )
    db.commit()
    return row


# ── 审批流 #5/#79/#80 ──────────────────────────────
@router.get("/approval-flows", response_model=list[ApprovalFlowOut])
def list_approval_flows(
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    return db.query(ApprovalFlow).order_by(ApprovalFlow.id).all()


@router.post("/approval-flows", response_model=ApprovalFlowOut,
             status_code=status.HTTP_201_CREATED)
def create_approval_flow(
    body: ApprovalFlowIn,
    db: Session = Depends(get_db),
    user: User = Depends(admin_only),
):
    for node in body.nodes:
        if "step" not in node or "role" not in node:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "审批节点须含 step 与 role"
            )
        if node["role"] not in ASSET_ROLE_LABELS and node["role"] != "teacher":
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"未知审批角色 {node['role']}"
            )
    row = ApprovalFlow(doc_type=body.doc_type, name=body.name, nodes=body.nodes)
    db.add(row)
    db.flush()
    log_asset_action(
        db, user, "asset_approval_flow_create",
        target_type="approval_flow", target_id=row.id,
        detail=f"新建审批流 {body.doc_type}:{body.name}",
    )
    db.commit()
    return row


@router.post("/approval-instances", response_model=ApprovalInstanceOut,
             status_code=status.HTTP_201_CREATED)
def create_approval_instance(
    body: ApprovalInstanceIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    flow = None
    if body.flow_id is not None:
        flow = _get_flow_or_404(db, body.flow_id)
    try:
        inst = approval_svc.create_instance(
            db, user, doc_type=body.doc_type, doc_id=body.doc_id,
            doc_no=body.doc_no, amount=body.amount, flow=flow,
        )
    except approval_svc.ApprovalError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    db.commit()
    return _instance_out(db, inst)


@router.get("/approval-instances/{instance_id}", response_model=ApprovalInstanceOut)
def get_approval_instance(
    instance_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    return _instance_out(db, _get_instance_or_404(db, instance_id))


def _approval_error_to_http(
    db: Session,
    user: User,
    instance_id: int,
    exc: approval_svc.ApprovalError,
) -> HTTPException:
    """审批错误转 HTTP:403 越权须先把拦截记进审计再返回(回滚会丢掉
    服务层已写的拦截日志,故在此重记一次)。"""
    db.rollback()
    if exc.status_code == status.HTTP_403_FORBIDDEN:
        log_asset_action(
            db, user, "asset_approval_act",
            target_type="approval_instance", target_id=instance_id,
            detail=f"审批拦截:{exc}",
        )
        db.commit()
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.post("/approval-instances/{instance_id}/act",
             response_model=ApprovalInstanceOut)
def act_approval_instance(
    instance_id: int,
    body: ApprovalActIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    inst = _get_instance_or_404(db, instance_id)
    try:
        approval_svc.act(db, user, inst, action=body.action, comment=body.comment)
    except approval_svc.ApprovalError as e:
        raise _approval_error_to_http(db, user, instance_id, e) from e
    # 第 5 批:处置单审批结果回写处置单状态(#56)。
    disposal_svc.sync_disposal_approval_status(db, inst)
    db.commit()
    return _instance_out(db, inst)


@router.post("/approval-instances/{instance_id}/transfer",
             response_model=ApprovalInstanceOut)
def transfer_approval_instance(
    instance_id: int,
    body: ApprovalTransferIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    inst = _get_instance_or_404(db, instance_id)
    try:
        approval_svc.transfer(db, user, inst, to_role=body.to_role, comment=body.comment)
    except approval_svc.ApprovalError as e:
        raise _approval_error_to_http(db, user, instance_id, e) from e
    db.commit()
    return _instance_out(db, inst)


@router.post("/approval-instances/mark-overdue", response_model=dict)
def mark_approval_overdue(
    db: Session = Depends(get_db),
    user: User = Depends(admin_only),
):
    """超时标记(#5):扫描超期未审实例打待办标记。定时推送后续批次接入。"""
    ids = approval_svc.mark_overdue(db, user)
    db.commit()
    return {"marked": ids, "count": len(ids)}


# ── 字段映射 #104 ──────────────────────────────
@router.get("/field-mappings", response_model=list[AssetFieldMappingOut])
def list_field_mappings(
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    return db.query(AssetFieldMapping).order_by(AssetFieldMapping.sort_order).all()


@router.post("/field-mappings", response_model=AssetFieldMappingOut,
             status_code=status.HTTP_201_CREATED)
def create_field_mapping(
    body: AssetFieldMappingIn,
    db: Session = Depends(get_db),
    user: User = Depends(admin_only),
):
    if db.query(AssetFieldMapping).filter_by(
        local_field=body.local_field,
        official_template_version=body.official_template_version,
    ).first():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "该字段映射已存在")
    row = AssetFieldMapping(**body.model_dump())
    db.add(row)
    db.flush()
    log_asset_action(
        db, user, "asset_field_mapping_update",
        target_type="asset_field_mapping", target_id=row.id,
        detail=f"新增字段映射 {body.local_field} → {body.official_field}",
    )
    db.commit()
    return row


@router.patch("/field-mappings/{mapping_id}", response_model=AssetFieldMappingOut)
def update_field_mapping(
    mapping_id: int,
    body: AssetFieldMappingUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(admin_only),
):
    row = db.get(AssetFieldMapping, mapping_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "映射不存在")
    data = body.model_dump(exclude_unset=True)
    before = {k: getattr(row, k) for k in data}
    for key, value in data.items():
        setattr(row, key, value)
    log_asset_action(
        db, user, "asset_field_mapping_update",
        target_type="asset_field_mapping", target_id=row.id,
        detail=f"维护字段映射 {row.local_field}",
        before={k: str(v) for k, v in before.items()},
        after={k: str(v) for k, v in data.items()},
    )
    db.commit()
    return row


# ── 对接适配层占位 #106 ──────────────────────────────
@router.get("/sync/adapter", response_model=SyncAdapterOut)
def get_sync_adapter_info(
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    adapter = get_adapter()
    log_asset_action(
        db, user, "asset_sync_adapter_info",
        target_type="sync_adapter",
        detail="查询对接适配层状态:仅模板导出,无实时官方接口",
    )
    db.commit()
    return SyncAdapterOut(
        adapter=adapter.name,
        available=["template_export"],
        live_api=False,
        note=ADAPTER_BOUNDARY_NOTE,
    )


# ── 审计查询 #82(只读,无删除) ──────────────────────────────
@router.get("/audit", response_model=list[dict])
def list_asset_audit(
    target_type: str | None = None,
    target_id: int | None = None,
    action: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(auditor_or_admin),
):
    q = db.query(AuditLog).filter(AuditLog.action.like("asset_%"))
    if target_type:
        q = q.filter_by(target_type=target_type)
    if target_id is not None:
        q = q.filter_by(target_id=target_id)
    if action:
        q = q.filter_by(action=action)
    rows = q.order_by(AuditLog.id.desc()).limit(limit).all()
    return [
        {"id": r.id, "user_id": r.user_id, "username": r.username,
         "action": r.action, "target_type": r.target_type,
         "target_id": r.target_id, "detail": r.detail,
         "created_at": r.created_at.isoformat() if r.created_at else None}
        for r in rows
    ]


# ── 种子数据(幂等,供部署后补种;迁移 0039 已含同一份种子) ──
@router.post("/admin/seed", response_model=dict)
def seed_foundation(
    db: Session = Depends(get_db),
    user: User = Depends(admin_only),
):
    counts = seed_asset_foundation(db)
    db.commit()
    return {"seeded": counts}
