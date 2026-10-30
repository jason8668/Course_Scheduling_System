"""行政值日解析:某天的值日老师 = 当天覆盖 > 每周轮值。

值日不算课时、不占课,故不在 teaching_hours 里出现;提醒另见 duty_reminders。
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.basedata import Teacher
from app.models.duty import DutyOverride, DutyPattern, is_admin_post


def eligible_teachers(db: Session, semester_id: int) -> list[Teacher]:
    """轮值人选:本学期在职且行政岗位的老师。"""
    teachers = db.scalars(
        select(Teacher).where(
            Teacher.semester_id == semester_id, Teacher.is_active.is_(True)
        )
    ).all()
    return [t for t in teachers if is_admin_post(t)]


def duty_teacher_id(db: Session, semester_id: int, on: date) -> int | None:
    """某天的值日老师 id:先查当天覆盖,再查周几轮值,都没有回 None。"""
    override = db.scalar(
        select(DutyOverride).where(
            DutyOverride.semester_id == semester_id, DutyOverride.date == on
        )
    )
    if override is not None:
        return override.teacher_id
    pattern = db.scalar(
        select(DutyPattern).where(
            DutyPattern.semester_id == semester_id,
            DutyPattern.weekday == on.isoweekday(),
        )
    )
    return pattern.teacher_id if pattern is not None else None


def duty_teacher(db: Session, semester_id: int, on: date) -> Teacher | None:
    tid = duty_teacher_id(db, semester_id, on)
    return db.get(Teacher, tid) if tid is not None else None
