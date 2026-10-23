"""代课通知单(教师代课单、班级代课单)的资料组装(v1.2.5)。

版面照使用学校现行的纸本:一张周课表,只在「有代课的格子」写上
「日期 / 科目 / 班级[代]」(教师单)或「日期 / 科目 / 代课老师[代]」(班级单)。
表头写代课教师(或代课班级)、请假教师、请假起讫、假别与计费方式。

**一笔代课 = 一个异动格**(不像调课要动两格):请假那节改由代课老师上。
并班比照办理,标记写「[并]」。

- 教师代课单:同一张假单里,每位代课老师一张。
- 班级代课单:同一张假单里,每个班一张。
- 跨周的假单一周一页(共用 `slip_layout`)。

表头的请假信息逐张假单不同,故分组时把假单一起当 key;跨假单批次打印时
会各自成张,不会把两位请假教师混在同一张纸上。

本模组只读,不写资料库。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.leave import (
    LEAVE_TYPE_CN,
    AffectedPeriod,
    AffectedStatus,
    LeaveRequest,
    LeaveStatus,
)
from app.models.substitution import Substitution, SubstitutionType
from app.services.slip_layout import Move, Slip, SlipError, Slips, Tables, assemble, school_title

# 代课单印得出来的处置:找人代(代课)与并入他班(并班),两者都有「接手的老师」
_PRINTABLE = (SubstitutionType.substitute.value, SubstitutionType.merge.value)
_MARK = {SubstitutionType.substitute.value: "[代]", SubstitutionType.merge.value: "[并]"}


def _teacher_actor(m: Move) -> str:
    """教师代课单的第三行:去哪一班代课。"""
    return f"{m.class_names}{m.mark}"


def _class_actor(m: Move) -> str:
    """班级代课单的第三行:这一节改由谁上。"""
    return f"{m.teacher_name}{m.mark}"


def _header(slip: Slip, leave: LeaveRequest, funding: str) -> Slip:
    """表头改写成纸本的样子:日期用请假起讫(不是只有被代的那几天)。"""
    slip.absent_teacher_name = leave.teacher.name
    slip.leave_type_name = LEAVE_TYPE_CN.get(leave.leave_type, leave.leave_type)
    slip.funding_label = funding
    slip.date_from = leave.start_date
    slip.date_to = leave.end_date
    return slip


def build(db: Session, semester_id: int, affected_ids: list[int]) -> Slips:
    """把指定的代课/并班组成通知单:先每位代课老师一张,再每个班一张。

    非代课/并班、没有指定教师、已撤回或已销假的节次略过;一笔都没有时抛 `SlipError`。
    """
    rows = db.execute(
        select(AffectedPeriod, Substitution)
        .join(Substitution, Substitution.affected_period_id == AffectedPeriod.id)
        .join(LeaveRequest, AffectedPeriod.leave_request_id == LeaveRequest.id)
        .where(
            AffectedPeriod.id.in_(affected_ids),
            AffectedPeriod.semester_id == semester_id,
            Substitution.type.in_(_PRINTABLE),
            Substitution.handler_teacher_id.is_not(None),
            AffectedPeriod.status != AffectedStatus.cancelled.value,
            LeaveRequest.status == LeaveStatus.registered.value,
        )
        .order_by(AffectedPeriod.date, AffectedPeriod.period_no)
    ).all()
    if not rows:
        raise SlipError("选取的节次中没有已指派的代课")

    tables = Tables(db)
    leaves: dict[int, LeaveRequest] = {}
    fundings: dict[int, str] = {}                     # 假单 → 计费方式(取第一个有填的)
    by_teacher: dict[tuple[int, int], list[Move]] = {}
    by_class: dict[tuple[int, str], list[Move]] = {}
    for ap, sub in rows:
        handler = sub.handler
        if handler is None:                           # 指派后教师被删:略过,不让整批印不出来
            continue
        leave = ap.leave_request
        leaves.setdefault(leave.id, leave)
        if sub.funding_source and not fundings.get(leave.id):
            fundings[leave.id] = sub.funding_source
        move = Move(
            date=ap.date, period_no=ap.period_no, class_names=ap.class_names,
            subject_name=ap.subject_name, teacher_id=handler.id, teacher_name=handler.name,
            table_id=tables.of_assignment(ap.course_assignment_id),
            mark=_MARK.get(sub.type, ""),
        )
        by_teacher.setdefault((leave.id, handler.id), []).append(move)
        by_class.setdefault((leave.id, ap.class_names), []).append(move)
    if not by_teacher:
        raise SlipError("选取的节次中没有已指派的代课")

    result = Slips(title=school_title(db), kind="substitute")
    for (leave_id, _), ms in by_teacher.items():
        slip = assemble(tables, "teacher", ms[0].teacher_name, ms, _teacher_actor)
        result.slips.append(_header(slip, leaves[leave_id], fundings.get(leave_id, "")))
    for (leave_id, _), ms in by_class.items():
        slip = assemble(tables, "class", "", ms, _class_actor)
        result.slips.append(_header(slip, leaves[leave_id], fundings.get(leave_id, "")))
    return result
