"""部门字典 API(学校资产管理系统一期补半成品 #76)。

挂在 /api/asset 下。部门原先是资产卡上的自由字符串,同义写法会漏数;
本接口收敛口径:字典行唯一名称 + 资产卡外键 manage_dept_id /
use_dept_id,原字符串列保留兼容。

- GET /departments:列表(任意登录用户可读,供台账筛选与建卡下拉用)。
- POST /departments、PATCH /departments/{id}、DELETE /departments/{id}:
  仅 admin / asset_admin(用现有 require_asset_roles)。
- GET /departments/unclaimed:待认领区——字典里没有、但资产卡上仍有
  原字符串值的部门,按出现次数列出。
- POST /departments/{id}/claim:把某个原字符串值认领进指定字典行
  (资产卡的外键按名字回填)。
- POST /departments/reconcile:全量重新对齐——凡资产卡字符串与字典名
  一致且外键为空的,补上外键(入库建卡只传字符串时用它补齐)。

删除守则:外键引用或字符串仍等于部门名的资产卡存在时不可删,须先
认领/改名处理;改名时同步改写资产卡上等于旧名的字符串,不断口径。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.asset_foundation import require_asset_roles
from app.core.auth import get_active_user
from app.core.db import get_db
from app.models.asset_card import AssetCard
from app.models.asset_department import AssetDepartment
from app.models.user import Role, User
from app.services.asset_audit import log_asset_action

router = APIRouter(tags=["asset"])

#: 部门字典写权限:admin 为超级用户一律通过(#78 同口径)。
dept_writer = require_asset_roles(Role.asset_admin)


class AssetDepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    code: str | None = Field(default=None, max_length=32)
    parent_id: int | None = None


class AssetDepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    code: str | None = Field(default=None, max_length=32)
    parent_id: int | None = None
    is_active: bool | None = None


class AssetDepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str | None = None
    parent_id: int | None = None
    parent_name: str | None = None
    is_active: bool
    manage_count: int = 0
    use_count: int = 0
    asset_count: int = 0


class UnclaimedDepartmentOut(BaseModel):
    name: str
    manage_count: int = 0
    use_count: int = 0
    total_count: int = 0


class ClaimIn(BaseModel):
    #: 资产卡上的原字符串部门名,如“教务”。
    name: str = Field(min_length=1, max_length=64)
    #: 只认领管理部门 / 只认领使用部门 / 两边都认领。
    field: str = Field(default="both", pattern="^(manage|use|both)$")


class ReconcileOut(BaseModel):
    updated_manage: int = 0
    updated_use: int = 0


def _get_dept_or_404(db: Session, dept_id: int) -> AssetDepartment:
    row = db.get(AssetDepartment, dept_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "部门不存在")
    return row


def _check_parent(db: Session, dept_id: int | None, parent_id: int | None) -> None:
    if parent_id is None:
        return
    if dept_id is not None and parent_id == dept_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "上级部门不能是自己")
    parent = db.get(AssetDepartment, parent_id)
    if parent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "上级部门不存在")
    if dept_id is not None and parent.parent_id == dept_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "上级部门不能是自己的下级")


def _counts(db: Session, row: AssetDepartment) -> tuple[int, int]:
    """引用数:外键指向该行,或字符串仍等于部门名的资产卡都算。"""
    manage = db.query(func.count(AssetCard.id)).filter(
        or_(AssetCard.manage_dept_id == row.id, AssetCard.manage_dept == row.name)
    ).scalar() or 0
    use = db.query(func.count(AssetCard.id)).filter(
        or_(AssetCard.use_dept_id == row.id, AssetCard.use_dept == row.name)
    ).scalar() or 0
    return manage, use


def _out(db: Session, row: AssetDepartment) -> AssetDepartmentOut:
    out = AssetDepartmentOut.model_validate(row)
    if row.parent_id is not None:
        parent = db.get(AssetDepartment, row.parent_id)
        out.parent_name = parent.name if parent else None
    manage, use = _counts(db, row)
    out.manage_count = manage
    out.use_count = use
    out.asset_count = manage + use
    return out


def _backfill_name(db: Session, dept: AssetDepartment, field: str,
                   match_name: str | None = None) -> tuple[int, int]:
    """按名字回填外键:字符串等于 match_name(默认部门名)的卡,
    把对应外键指向该行。"""
    match_name = match_name if match_name is not None else dept.name
    updated_manage = 0
    updated_use = 0
    if field in ("manage", "both"):
        updated_manage = db.query(AssetCard).filter(
            AssetCard.manage_dept == match_name,
            AssetCard.manage_dept_id.is_(None),
        ).update({"manage_dept_id": dept.id}, synchronize_session=False)
    if field in ("use", "both"):
        updated_use = db.query(AssetCard).filter(
            AssetCard.use_dept == match_name,
            AssetCard.use_dept_id.is_(None),
        ).update({"use_dept_id": dept.id}, synchronize_session=False)
    return updated_manage, updated_use


@router.get("/departments", response_model=list[AssetDepartmentOut])
def list_departments(
    is_active: bool | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    q = db.query(AssetDepartment)
    if is_active is not None:
        q = q.filter_by(is_active=is_active)
    return [_out(db, row) for row in q.order_by(AssetDepartment.name).all()]


@router.get("/departments/unclaimed", response_model=list[UnclaimedDepartmentOut])
def list_unclaimed_departments(
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """待认领:字典里没有、但资产卡上仍有原字符串值的部门名。"""
    known = {name for (name,) in db.query(AssetDepartment.name).all()}
    rows: dict[str, UnclaimedDepartmentOut] = {}
    for (name, count) in db.query(
        AssetCard.manage_dept, func.count(AssetCard.id)
    ).filter(
        AssetCard.manage_dept.is_not(None), AssetCard.manage_dept != "",
    ).group_by(AssetCard.manage_dept).all():
        if name in known:
            continue
        rows.setdefault(name, UnclaimedDepartmentOut(name=name)).manage_count = count
    for (name, count) in db.query(
        AssetCard.use_dept, func.count(AssetCard.id)
    ).filter(
        AssetCard.use_dept.is_not(None), AssetCard.use_dept != "",
    ).group_by(AssetCard.use_dept).all():
        if name in known:
            continue
        rows.setdefault(name, UnclaimedDepartmentOut(name=name)).use_count = count
    out = list(rows.values())
    for row in out:
        row.total_count = row.manage_count + row.use_count
    return sorted(out, key=lambda r: (-r.total_count, r.name))


@router.post("/departments", response_model=AssetDepartmentOut,
             status_code=status.HTTP_201_CREATED)
def create_department(
    body: AssetDepartmentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(dept_writer),
):
    if db.query(AssetDepartment).filter_by(name=body.name).first():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"部门已存在:{body.name}")
    if body.code and db.query(AssetDepartment).filter_by(code=body.code).first():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"部门代码已存在:{body.code}")
    _check_parent(db, None, body.parent_id)
    row = AssetDepartment(
        name=body.name, code=body.code, parent_id=body.parent_id)
    db.add(row)
    db.flush()
    # 新字典名若与资产卡原字符串一致,顺手把外键补上,免得再跑一次对齐。
    _backfill_name(db, row, "both")
    log_asset_action(
        db, user, "asset_department_create",
        target_type="asset_department", target_id=row.id,
        detail=f"新增部门字典 {body.name}",
    )
    db.commit()
    return _out(db, row)


@router.patch("/departments/{dept_id}", response_model=AssetDepartmentOut)
def update_department(
    dept_id: int,
    body: AssetDepartmentUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(dept_writer),
):
    row = _get_dept_or_404(db, dept_id)
    data = body.model_dump(exclude_unset=True)
    old_name = row.name
    if "name" in data and data["name"] != old_name:
        if db.query(AssetDepartment).filter(
            AssetDepartment.name == data["name"],
            AssetDepartment.id != dept_id,
        ).first():
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"部门已存在:{data['name']}")
    if "code" in data and data["code"]:
        if db.query(AssetDepartment).filter(
            AssetDepartment.code == data["code"],
            AssetDepartment.id != dept_id,
        ).first():
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"部门代码已存在:{data['code']}")
    if "parent_id" in data:
        _check_parent(db, dept_id, data["parent_id"])
    before = {"name": row.name, "code": row.code, "is_active": row.is_active}
    for key, value in data.items():
        setattr(row, key, value)
    if "name" in data and data["name"] != old_name:
        # 改名不断口径:资产卡上等于旧名的字符串同步改成新名。
        db.query(AssetCard).filter(
            AssetCard.manage_dept == old_name,
        ).update({"manage_dept": data["name"]}, synchronize_session=False)
        db.query(AssetCard).filter(
            AssetCard.use_dept == old_name,
        ).update({"use_dept": data["name"]}, synchronize_session=False)
    log_asset_action(
        db, user, "asset_department_update",
        target_type="asset_department", target_id=row.id,
        detail=f"维护部门字典 {old_name}",
        before={k: str(v) for k, v in before.items()},
        after={k: str(v) for k, v in data.items()},
    )
    db.commit()
    return _out(db, row)


@router.delete("/departments/{dept_id}", response_model=dict)
def delete_department(
    dept_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(dept_writer),
):
    row = _get_dept_or_404(db, dept_id)
    manage, use = _counts(db, row)
    if manage + use > 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"部门 {row.name} 仍被 {manage + use} 件资产引用,不可删:"
            "请先把资产卡改到其他部门,或在待认领区处理",
        )
    if db.query(AssetDepartment).filter_by(parent_id=dept_id).first():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"部门 {row.name} 下仍有下级部门,不可删")
    log_asset_action(
        db, user, "asset_department_delete",
        target_type="asset_department", target_id=row.id,
        detail=f"删除部门字典 {row.name}",
    )
    name = row.name
    db.delete(row)
    db.commit()
    return {"deleted": dept_id, "name": name}


@router.post("/departments/{dept_id}/claim", response_model=dict)
def claim_department_name(
    dept_id: int,
    body: ClaimIn,
    db: Session = Depends(get_db),
    user: User = Depends(dept_writer),
):
    """认领:把资产卡上的某个原字符串部门名并入指定字典行。"""
    row = _get_dept_or_404(db, dept_id)
    if db.query(AssetDepartment).filter_by(name=body.name).first():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{body.name} 已是字典部门,无需认领:"
            "请直接改资产卡的部门,或在待认领区处理其他写法",
        )
    updated_manage, updated_use = _backfill_name(db, row, body.field, body.name)
    # 认领后字符串口径统一成字典名,下次不再出现在待认领区。
    if body.field in ("manage", "both"):
        db.query(AssetCard).filter(
            AssetCard.manage_dept == body.name,
        ).update({"manage_dept": row.name}, synchronize_session=False)
    if body.field in ("use", "both"):
        db.query(AssetCard).filter(
            AssetCard.use_dept == body.name,
        ).update({"use_dept": row.name}, synchronize_session=False)
    log_asset_action(
        db, user, "asset_department_claim",
        target_type="asset_department", target_id=row.id,
        detail=f"认领原部门名 {body.name} 并入 {row.name}"
               f"(管理部门 {updated_manage} 件,使用部门 {updated_use} 件)",
    )
    db.commit()
    return {
        "department_id": row.id, "department_name": row.name,
        "claimed_name": body.name, "field": body.field,
        "updated_manage": updated_manage, "updated_use": updated_use,
    }


@router.post("/departments/reconcile", response_model=ReconcileOut)
def reconcile_departments(
    db: Session = Depends(get_db),
    user: User = Depends(dept_writer),
):
    """全量重新对齐:字符串与字典名一致且外键为空的资产卡,补上外键。"""
    total_manage = 0
    total_use = 0
    for dept in db.query(AssetDepartment).filter_by(is_active=True).all():
        updated_manage, updated_use = _backfill_name(db, dept, "both")
        total_manage += updated_manage
        total_use += updated_use
    log_asset_action(
        db, user, "asset_department_reconcile",
        target_type="asset_department",
        detail=f"部门字典重新对齐(管理部门 {total_manage} 件,使用部门 {total_use} 件)",
    )
    db.commit()
    return ReconcileOut(updated_manage=total_manage, updated_use=total_use)
