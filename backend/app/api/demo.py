"""示范资料:一键建出一所完整的示范初中。管理员专用。

存在的理由:刚装好的系统是空的,要看到自动排课做了什么,得先手 key 十八个班级、
四十几位教师、四百多笔配课。这道门槛会挡掉绝大多数想评估这套系统的人。

安全性:只在「完全没有任何学期」时才允许执行。用学期是否为空来判断不够——
用户可能已经开了新学期正准备建资料,一键灌进 18 个班会让他不知所措。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import require_roles
from app.core.db import get_db
from app.models.audit import AuditLog
from app.models.user import Role, User
from app.services import demo_data

router = APIRouter(tags=["demo"])

admin_only = require_roles(Role.admin)


class DemoDataOut(BaseModel):
    semester_id: int
    school_name: str
    classes: int
    teachers: int
    subjects: int
    rooms: int
    assignments: int
    total_periods: int
    max_overtime_used: int
    under_target: int


class DemoDataStatus(BaseModel):
    available: bool
    reason: str = ""
    school_name: str = ""


@router.get("/demo-data", response_model=DemoDataStatus)
def demo_status(db: Session = Depends(get_db), _: User = Depends(admin_only)):
    """能不能载入示范资料。前端用它决定按钮要不要 disable。"""
    spec_name = demo_data.load_spec()["school_name"]
    if demo_data.any_semester_exists(db):
        return DemoDataStatus(
            available=False,
            reason="系统已有学期资料。示范资料只能建在全新的系统上,以免覆盖你的正式资料。",
            school_name=spec_name,
        )
    return DemoDataStatus(available=True, school_name=spec_name)


@router.post("/demo-data", response_model=DemoDataOut, status_code=status.HTTP_201_CREATED)
def create_demo_data(db: Session = Depends(get_db), user: User = Depends(admin_only)):
    if demo_data.any_semester_exists(db):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "系统已有学期资料,无法载入示范资料。"
            "示范资料是给全新系统试用的;若要重来,请先删除既有学期。",
        )
    summary = demo_data.generate(db)
    db.add(AuditLog(
        user_id=user.id, username=user.username, action="create_demo_data",
        target_type="semester", target_id=summary.semester_id,
        detail=(
            f"载入示范资料:{summary.classes} 班、{summary.teachers} 位教师、"
            f"{summary.assignments} 笔配课,共 {summary.total_periods} 节"
        ),
    ))
    db.commit()
    return DemoDataOut(**summary.__dict__)
