"""老师自主调课的展开口径,供课时统计与上课提醒共用。

一条生效(approved)的调课展开成两节(补课可空):
- 换课节:日期/节次/班级/配课,原任 -> 换课,课时 origin substitute
- 补课节:日期/节次/班级/配课,换课 -> 原任,课时 origin base
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assignment import CourseAssignment
from app.models.teacher_swap import TeacherSwap


@dataclass
class SwapTeaching:
    """一节实际由谁上:与课时/提醒的展开共用。"""

    swap_id: int
    class_date: date
    period_no: int
    class_unit_id: int
    assignment_id: int
    original_teacher_id: int
    handler_teacher_id: int
    origin: str  # substitute = 换课节(替别人上), base = 补课节(自己的课)


def approved_swaps(db: Session, semester_id: int) -> list[TeacherSwap]:
    return db.scalars(
        select(TeacherSwap).where(
            TeacherSwap.semester_id == semester_id,
            TeacherSwap.status == "approved",
        )
    ).all()


def swap_teachings(db: Session, semester_id: int) -> list[SwapTeaching]:
    """全部生效调课展开成实际授课节(含补课)。"""
    out: list[SwapTeaching] = []
    for s in approved_swaps(db, semester_id):
        out.append(SwapTeaching(
            swap_id=s.id, class_date=s.class_date, period_no=s.period_no,
            class_unit_id=s.class_unit_id, assignment_id=s.course_assignment_id,
            original_teacher_id=s.original_teacher_id,
            handler_teacher_id=s.handler_teacher_id, origin="substitute",
        ))
        if (
            s.makeup_date is not None and s.makeup_period_no is not None
            and s.makeup_class_unit_id is not None and s.makeup_assignment_id is not None
        ):
            out.append(SwapTeaching(
                swap_id=s.id, class_date=s.makeup_date, period_no=s.makeup_period_no,
                class_unit_id=s.makeup_class_unit_id,
                assignment_id=s.makeup_assignment_id,
                original_teacher_id=s.handler_teacher_id,
                handler_teacher_id=s.original_teacher_id, origin="base",
            ))
    return out


def assignment_teaches_class(db: Session, assignment_id: int, class_unit_id: int) -> bool:
    """配课是否教该班(排课单位成员含该班)。"""
    a = db.get(CourseAssignment, assignment_id)
    if a is None:
        return False
    return any(
        m.class_unit_id == class_unit_id for m in a.scheduling_unit.members
    )


def assignment_teachers(db: Session, assignment_id: int) -> list[int]:
    a = db.get(CourseAssignment, assignment_id)
    if a is None:
        return []
    return [at.teacher_id for at in a.teachers]
