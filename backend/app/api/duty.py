"""行政值日 API。

直接改(轮值/某天覆盖)只有管理员能做:值日是全校共用,年级主任改全校轮值
会越级影响别的年级,故与特殊日全校规则同一口径。
换班申请:值日老师本人发起,对方同意后才替换(只换当天,生成覆盖);
同意/拒绝只有对方老师能点(管理员要改直接走覆盖,不走申请)。
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import get_active_user, require_roles
from app.core.db import get_db
from app.models.basedata import Teacher
from app.models.duty import DutyOverride, DutyPattern, DutySwapRequest, is_admin_post
from app.models.notification import NotificationType
from app.models.semester import Semester
from app.models.user import Role, User
from app.schemas.duty import (
    DutyOverrideIn,
    DutyOverrideOut,
    DutyPatternIn,
    DutyPatternOut,
    DutyRosterOut,
    DutySwapRequestIn,
    DutySwapRequestOut,
    DutyTeacherOut,
)
from app.services import duty as duty_service
from app.services.notifications import notify
from app.services.teachers import current_teacher

router = APIRouter(tags=["duty"])
admin_only = require_roles(Role.admin)


def _get_semester(db: Session, semester_id: int) -> Semester:
    semester = db.get(Semester, semester_id)
    if semester is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到学期")
    return semester


def _check_eligible(db: Session, semester_id: int, teacher_id: int) -> Teacher:
    teacher = db.get(Teacher, teacher_id)
    if teacher is None or teacher.semester_id != semester_id or not teacher.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不是该学期在职教师")
    if not is_admin_post(teacher):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "轮值人选只有行政岗位老师")
    return teacher


def _name(db: Session, teacher_id: int) -> str | None:
    teacher = db.get(Teacher, teacher_id)
    return teacher.name if teacher else None


@router.get("/duty-roster", response_model=DutyRosterOut)
def get_roster(
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_active_user),
):
    _get_semester(db, semester_id)
    patterns = db.scalars(
        select(DutyPattern).where(DutyPattern.semester_id == semester_id)
        .order_by(DutyPattern.weekday)
    ).all()
    overrides = db.scalars(
        select(DutyOverride).where(DutyOverride.semester_id == semester_id)
        .order_by(DutyOverride.date)
    ).all()
    requests = db.scalars(
        select(DutySwapRequest).where(DutySwapRequest.semester_id == semester_id)
        .order_by(DutySwapRequest.date, DutySwapRequest.id)
    ).all()
    return DutyRosterOut(
        patterns=[DutyPatternOut(
            id=p.id, weekday=p.weekday, teacher_id=p.teacher_id,
            teacher_name=_name(db, p.teacher_id),
        ) for p in patterns],
        overrides=[DutyOverrideOut(
            id=o.id, date=o.date, teacher_id=o.teacher_id,
            teacher_name=_name(db, o.teacher_id), reason=o.reason,
        ) for o in overrides],
        swap_requests=[DutySwapRequestOut(
            id=r.id, date=r.date, from_teacher_id=r.from_teacher_id,
            from_teacher_name=_name(db, r.from_teacher_id),
            to_teacher_id=r.to_teacher_id,
            to_teacher_name=_name(db, r.to_teacher_id), status=r.status,
        ) for r in requests],
        eligible=[DutyTeacherOut(
            id=t.id, name=t.name, admin_title=t.admin_title,
        ) for t in duty_service.eligible_teachers(db, semester_id)],
    )


@router.put("/duty-roster/pattern", response_model=DutyRosterOut)
def set_pattern(
    body: DutyPatternIn,
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(admin_only),
):
    _get_semester(db, semester_id)
    _check_eligible(db, semester_id, body.teacher_id)
    existing = db.scalar(
        select(DutyPattern).where(
            DutyPattern.semester_id == semester_id, DutyPattern.weekday == body.weekday
        )
    )
    if existing is None:
        db.add(DutyPattern(
            semester_id=semester_id, weekday=body.weekday, teacher_id=body.teacher_id
        ))
    else:
        existing.teacher_id = body.teacher_id
    db.commit()
    return get_roster(semester_id, db, _)


@router.put("/duty-roster/override", response_model=DutyRosterOut)
def set_override(
    body: DutyOverrideIn,
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(admin_only),
):
    semester = _get_semester(db, semester_id)
    _check_eligible(db, semester_id, body.teacher_id)
    if semester.start_date and semester.end_date and not (
        semester.start_date <= body.date <= semester.end_date
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "日期不在学期内")
    existing = db.scalar(
        select(DutyOverride).where(
            DutyOverride.semester_id == semester_id, DutyOverride.date == body.date
        )
    )
    if existing is None:
        db.add(DutyOverride(
            semester_id=semester_id, date=body.date,
            teacher_id=body.teacher_id, reason=body.reason,
        ))
    else:
        existing.teacher_id = body.teacher_id
        existing.reason = body.reason
    db.commit()
    return get_roster(semester_id, db, _)


@router.delete("/duty-roster/override", status_code=status.HTTP_204_NO_CONTENT)
def delete_override(
    date: str = Query(...),
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(admin_only),
):
    from datetime import date as _date

    try:
        d = _date.fromisoformat(date)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "日期格式错误") from exc
    existing = db.scalar(
        select(DutyOverride).where(
            DutyOverride.semester_id == semester_id, DutyOverride.date == d
        )
    )
    if existing is not None:
        db.delete(existing)
        db.commit()


@router.post(
    "/duty-roster/swap-requests",
    response_model=DutySwapRequestOut, status_code=status.HTTP_201_CREATED,
)
def create_swap_request(
    body: DutySwapRequestIn,
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    semester = _get_semester(db, semester_id)
    me = current_teacher(db, user, semester_id)
    if me is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未绑定教师档案")
    current = duty_service.duty_teacher_id(db, semester_id, body.date)
    if current is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "那天没有值日安排,无法换班")
    if current != me.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "只能为自己值日的那天发起换班")
    if semester.start_date and semester.end_date and not (
        semester.start_date <= body.date <= semester.end_date
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "日期不在学期内")
    to_teacher = _check_eligible(db, semester_id, body.to_teacher_id)
    if body.to_teacher_id == me.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "换班对象不能是自己")
    pending = db.scalar(
        select(DutySwapRequest).where(
            DutySwapRequest.semester_id == semester_id,
            DutySwapRequest.date == body.date,
            DutySwapRequest.from_teacher_id == me.id,
            DutySwapRequest.status == "pending",
        )
    )
    if pending is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "那天已有待处理的换班申请")
    req = DutySwapRequest(
        semester_id=semester_id, date=body.date,
        from_teacher_id=me.id, to_teacher_id=body.to_teacher_id,
        status="pending", created_by=user.id,
    )
    db.add(req)
    db.flush()
    # 站内通知给对方老师(钉钉群不发:类型不在群发白名单,见 notifications)
    notify(
        db, semester_id=semester_id, teacher_id=body.to_teacher_id,
        type=NotificationType.duty_swap_requested,
        title="行政值日换班申请",
        body=f"{me.name}老师想把 {body.date.isoformat()} 的行政值日换给您,同意后当天值日就换成您。",
        link="/my",
    )
    db.commit()
    db.refresh(req)
    return DutySwapRequestOut(
        id=req.id, date=req.date, from_teacher_id=req.from_teacher_id,
        from_teacher_name=me.name, to_teacher_id=req.to_teacher_id,
        to_teacher_name=to_teacher.name, status=req.status,
    )


def _decide(
    db: Session, user: User, request_id: int, approve: bool,
) -> DutySwapRequestOut:
    req = db.get(DutySwapRequest, request_id)
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到换班申请")
    me = current_teacher(db, user, req.semester_id)
    if me is None or me.id != req.to_teacher_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "只有被换班的老师能同意或拒绝")
    if req.status != "pending":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "该申请已处理过")
    req.status = "approved" if approve else "rejected"
    req.decided_at = datetime.now()
    if approve:
        # 同意后替换:只换当天,生成覆盖,下周恢复原轮值
        existing = db.scalar(
            select(DutyOverride).where(
                DutyOverride.semester_id == req.semester_id, DutyOverride.date == req.date
            )
        )
        if existing is None:
            db.add(DutyOverride(
                semester_id=req.semester_id, date=req.date,
                teacher_id=req.to_teacher_id, reason="换班同意后替换",
            ))
        else:
            existing.teacher_id = req.to_teacher_id
            existing.reason = "换班同意后替换"
    db.commit()
    db.refresh(req)
    return DutySwapRequestOut(
        id=req.id, date=req.date, from_teacher_id=req.from_teacher_id,
        from_teacher_name=_name(db, req.from_teacher_id),
        to_teacher_id=req.to_teacher_id,
        to_teacher_name=_name(db, req.to_teacher_id), status=req.status,
    )


@router.post("/duty-roster/swap-requests/{request_id}/approve", response_model=DutySwapRequestOut)
def approve_swap(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    return _decide(db, user, request_id, True)


@router.post("/duty-roster/swap-requests/{request_id}/reject", response_model=DutySwapRequestOut)
def reject_swap(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    return _decide(db, user, request_id, False)
