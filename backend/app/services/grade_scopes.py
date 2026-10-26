"""帐号—年级权限(按年级排课)。三种角色:管理员、年级主任、普通老师(教学组长已停用)。

核心语意只有一个:`allowed_grades(db, user)`:

- 回传 None = 不受限:只有管理员。
- 回传年级集合 = 该帐号的排课写操作只允许在这些年级内;空集合 = 没有排课权限。

年级主任本身就是老师:管理员在账号年级页给他配年级,就是任命——不配年级,
他就只能当任课老师用(排课写操作一律拒绝,自动排课也开不起来);配了年级,
他才能排那个年级的课。年级取自配课单位的成员班(与代课推荐的年级溯源同一
口径),不依赖前端传来的年级栏位——前端的筛选只是方便,真正的拦截永远在后端算。
"""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assignment import CourseAssignment, SchedulingUnitMember
from app.models.basedata import ClassUnit
from app.models.timetable import ScheduleEntry
from app.models.user import Role, User, UserGradeScope


def allowed_grades(db: Session, user: User) -> set[int] | None:
    """该帐号允许操作的年级;None 表示不受限(仅管理员)。

    主任未配任何年级时回传空集合——不是不受限,是没有排课权限;配了年级才有
    那些年级的排课权限。普通老师同样回空集合(主任身份由管理员配年级授予)。
    """
    names = user.role_names
    if Role.admin.value in names:
        return None
    rows = db.scalars(
        select(UserGradeScope.grade).where(UserGradeScope.user_id == user.id)
    ).all()
    return set(rows)


def require_grades(db: Session, user: User, grades: set[int]) -> None:
    """写操作拦截:目标年级超出帐号范围时 403。空年级集合不拦(无法溯源时放行)。"""
    allowed = allowed_grades(db, user)
    if allowed is None or not grades:
        return
    if not grades <= allowed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"超出你的年级权限(可操作:{'、'.join(str(g) for g in sorted(allowed))}年级)",
        )


def require_can_publish(db: Session, user: User) -> None:
    """发布课表:管理员可发布;已任命的主任(配了年级)可发布;其余 403。

    课表一学期只有一张,不按年级切分——发布是整校动作,不适用 require_grades
    的年级包含检查;但未任命(无年级)的主任仍无权发布,须先由管理员配年级。
    """
    allowed = allowed_grades(db, user)
    if allowed is None or len(allowed) > 0:
        return
    raise HTTPException(
        status.HTTP_403_FORBIDDEN, "你还没有被分配年级,请联系系统管理员",
    )


def assignment_grades(db: Session, assignment_id: int) -> set[int]:
    """一门配课所教的年级(排课单位成员班的年级)。"""
    rows = db.execute(
        select(ClassUnit.grade)
        .join(SchedulingUnitMember, SchedulingUnitMember.class_unit_id == ClassUnit.id)
        .join(CourseAssignment,
              CourseAssignment.scheduling_unit_id == SchedulingUnitMember.scheduling_unit_id)
        .where(CourseAssignment.id == assignment_id)
    ).all()
    return {g for (g,) in rows}


def unit_grades(db: Session, unit_id: int) -> set[int]:
    """一个排课单位所含班级的年级。"""
    rows = db.execute(
        select(ClassUnit.grade)
        .join(SchedulingUnitMember, SchedulingUnitMember.class_unit_id == ClassUnit.id)
        .where(SchedulingUnitMember.scheduling_unit_id == unit_id)
    ).all()
    return {g for (g,) in rows}


def source_grades(
    db: Session,
    schedule_entry_id: int | None,
    course_assignment_id: int | None,
) -> set[int]:
    """受影响节次原来那格课的年级(溯源课表条目,改版后对不上则为空→放行)。"""
    assignment_id = course_assignment_id
    if schedule_entry_id is not None:
        entry = db.get(ScheduleEntry, schedule_entry_id)
        if entry is not None:
            assignment_id = entry.course_assignment_id
    if assignment_id is None:
        return set()
    return assignment_grades(db, assignment_id)


def require_unrestricted(db: Session, user: User) -> None:
    """整校级操作(发布、改名、删除课表):有年级限制的帐号一律 403。"""
    if allowed_grades(db, user) is not None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "你只有部分年级的权限,整校操作请交给主任或管理员",
        )


def user_grades(db: Session, user_id: int) -> list[int]:
    """管理员视图:某帐号已配的年级(升序)。"""
    return sorted(db.scalars(
        select(UserGradeScope.grade).where(UserGradeScope.user_id == user_id)
    ).all())


def set_user_grades(db: Session, user_id: int, grades: list[int]) -> list[int]:
    """管理员替换某帐号的年级(整批覆盖,去重升序)。"""
    wanted = sorted(set(grades))
    db.query(UserGradeScope).filter(UserGradeScope.user_id == user_id).delete()
    for g in wanted:
        db.add(UserGradeScope(user_id=user_id, grade=g))
    db.flush()
    return wanted
