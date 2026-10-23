"""调课通知单(教师调课单、班级调课单)的资料组装(v1.2.2)。

版面照使用学校现行的纸本:一张周课表,只在「有异动的格子」写上
「日期 / 科目 / 实际上课的老师 / [调MM-DD_星期节次]」,中括号指向对调的另一节。
格线与跨周分页等共用部分见 `slip_layout`。

**一笔调课 = 两个异动格。** 甲请假那节改由乙上;乙原本那节改由甲上。

- 教师调课单:每位老师一张,只列他「要去上」的那一格(空出来的那一格不列——
  他那节不用去,纸本上也没有)。
- 班级调课单:每个班一张,列该班所有异动格。

**科目怎么写。** 同班互调时,科目跟著老师走(学生只是两科前后对换):乙在甲那节上乙自己的科目。
跨班对调时乙去的是甲的班、上的是甲那一节的课,科目沿用该节原本的科目。

本模组只读,不写资料库;资料全部来自已成立调课的快照栏位与节次表。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.leave import AffectedPeriod, AffectedStatus, LeaveRequest, LeaveStatus
from app.models.substitution import Substitution, SubstitutionType
from app.models.timetable import ScheduleEntry
from app.services.slip_layout import Move, SlipError, Slips, Tables, assemble, school_title


def _moves(db: Session, tables: Tables, ap: AffectedPeriod, sub: Substitution) -> list[Move]:
    absent = ap.leave_request.teacher
    partner = sub.handler
    if partner is None or sub.swap_date is None or sub.swap_period_no is None:
        raise SlipError("这笔调课资料不完整(对调教师或补课节次已被删除),无法打印")
    same_class = ap.class_names == sub.swap_class_names
    leave_table = tables.of_assignment(ap.course_assignment_id)
    entry = db.get(ScheduleEntry, sub.swap_entry_id) if sub.swap_entry_id else None
    swap_table = tables.of_assignment(entry.course_assignment_id) if entry else leave_table
    swap_wd, leave_wd = sub.swap_date.isoweekday(), ap.date.isoweekday()
    swap_ord = tables.ordinal(swap_table, swap_wd, sub.swap_period_no)
    leave_ord = tables.ordinal(leave_table, leave_wd, ap.period_no)
    return [
        Move(  # 请假那节:改由乙上
            date=ap.date, period_no=ap.period_no, class_names=ap.class_names,
            subject_name=sub.swap_subject_name if same_class else ap.subject_name,
            teacher_id=partner.id, teacher_name=partner.name, table_id=leave_table,
            code=f"调{sub.swap_date:%m-%d}_{swap_wd}{swap_ord}",
        ),
        Move(  # 乙原本那节:改由甲上
            date=sub.swap_date, period_no=sub.swap_period_no, class_names=sub.swap_class_names,
            subject_name=ap.subject_name if same_class else sub.swap_subject_name,
            teacher_id=absent.id, teacher_name=absent.name, table_id=swap_table,
            code=f"调{ap.date:%m-%d}_{leave_wd}{leave_ord}",
        ),
    ]


def build(db: Session, semester_id: int, affected_ids: list[int]) -> Slips:
    """把指定的调课组成通知单:先每位老师一张(依出场顺序),再每个班一张。

    非调课、已撤回或已销假的节次略过;一笔有效的调课都没有时抛 `SlipError`。
    """
    rows = db.execute(
        select(AffectedPeriod, Substitution)
        .join(Substitution, Substitution.affected_period_id == AffectedPeriod.id)
        .join(LeaveRequest, AffectedPeriod.leave_request_id == LeaveRequest.id)
        .where(
            AffectedPeriod.id.in_(affected_ids),
            AffectedPeriod.semester_id == semester_id,
            Substitution.type == SubstitutionType.swap.value,
            AffectedPeriod.status != AffectedStatus.cancelled.value,
            LeaveRequest.status == LeaveStatus.registered.value,
        )
        .order_by(AffectedPeriod.date, AffectedPeriod.period_no)
    ).all()
    if not rows:
        raise SlipError("选取的节次中没有已成立的调课")

    tables = Tables(db)
    moves: list[Move] = []
    for ap, sub in rows:
        moves.extend(_moves(db, tables, ap, sub))

    by_teacher: dict[int, list[Move]] = {}
    by_class: dict[str, list[Move]] = {}
    for m in moves:
        by_teacher.setdefault(m.teacher_id, []).append(m)
        by_class.setdefault(m.class_names, []).append(m)

    result = Slips(title=school_title(db, semester_id), kind="swap")
    for ms in by_teacher.values():
        result.slips.append(assemble(tables, "teacher", ms[0].teacher_name, ms, _actor))
    for ms in by_class.values():
        result.slips.append(assemble(tables, "class", "", ms, _actor))
    return result


def _actor(m: Move) -> str:
    """调课单的第三行:实际上课的老师(教师单与班级单相同)。"""
    return m.teacher_name
