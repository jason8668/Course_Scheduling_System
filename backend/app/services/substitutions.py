"""调代课处置(M4-2,architecture.md §5.3)。

指派即生效:建立/更新处置 → 受影响节次转『已确认』并记下处理教师 → 通知处理教师。
没有邀请/婉拒;通知只是正式告知 +「确认收到」。

各处置的课时:代课计、并班/自习/不处理不计(§5.4 月结)。
调课(swap)要验两位教师交换后都无冲突,拒绝时说出是谁在哪一节撞课。
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.models.assignment import AssignmentTeacher, CourseAssignment
from app.models.basedata import Subject, Teacher
from app.models.leave import (
    AffectedPeriod,
    AffectedStatus,
    LeaveRequest,
    LeaveStatus,
)
from app.models.notification import NotificationType
from app.models.substitution import (
    SUBSTITUTION_TYPE_CN,
    TYPES_WITH_HANDLER,
    Substitution,
    SubstitutionType,
)
from app.models.timetable import ScheduleEntry
from app.services import notifications
from app.services.availability import Availability
from app.services.swap_options import SwapChecker, block_periods


class SubstitutionError(Exception):
    """处置不合法(呼叫端转为 400/409)。"""


def _wd(weekday: int) -> str:
    names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return names[weekday - 1] if 1 <= weekday <= 7 else f"星期{weekday}"


def _counts_default(sub_type: str) -> bool:
    return sub_type == SubstitutionType.substitute.value


def _funding_default(sub_type: str, counts_toward_hours: bool) -> str:
    """没填计费方式时的默认:跟著「代课课时 计入/不计」开关走。

    简化后界面不再让选谁出钱,代课单上只印计入课时或不计入课时。
    """
    if sub_type != SubstitutionType.substitute.value:
        return ""
    return "计入课时" if counts_toward_hours else "不计入课时"


def assign(
    db: Session,
    affected: AffectedPeriod,
    *,
    sub_type: str,
    handler_teacher_id: int | None,
    counts_toward_hours: bool | None,
    funding_source: str,
    swap_entry_id: int | None,
    swap_date: date | None,
    created_by_user_id: int | None,
    created_by_name: str,
    swap_period_no: int | None = None,
    availability: Availability | None = None,
) -> Substitution:
    """对一个受影响节次做处置。呼叫端负责 commit。"""
    if affected.status == AffectedStatus.cancelled.value:
        raise SubstitutionError("此节次已因销假取消,无法处置")
    if affected.status == AffectedStatus.completed.value or clock.is_past_slot(
        affected.date, affected.end_time
    ):
        raise SubstitutionError("此节次已结束,无法变更处置")
    if sub_type not in set(SubstitutionType):
        raise SubstitutionError(f"未知的处置方式:{sub_type}")

    av = availability or Availability(db, affected.semester_id)
    handler = _resolve_handler(db, affected, sub_type, handler_teacher_id, av)

    swap_fields: dict = {}
    if sub_type == SubstitutionType.swap.value:
        swap_fields = _validate_swap(
            db, affected, handler, swap_entry_id, swap_date, swap_period_no, av)

    counts = _counts_default(sub_type) if counts_toward_hours is None else counts_toward_hours

    sub = db.scalar(select(Substitution).where(Substitution.affected_period_id == affected.id))
    if sub is None:
        sub = Substitution(semester_id=affected.semester_id, affected_period_id=affected.id)
        db.add(sub)
    sub.type = sub_type
    sub.handler_teacher_id = handler.id if handler else None
    sub.counts_toward_hours = counts
    sub.funding_source = funding_source or _funding_default(sub_type, counts)
    sub.created_by_user_id = created_by_user_id
    sub.created_by_name = created_by_name
    for k, v in swap_fields.items():
        setattr(sub, k, v)
    if sub_type != SubstitutionType.swap.value:
        _clear_swap(sub)

    affected.status = AffectedStatus.resolved.value
    affected.handler_teacher_id = handler.id if handler else None
    db.flush()

    if handler is not None:
        _notify_handler(db, affected, sub, handler)
    return sub


@dataclass(frozen=True, slots=True)
class BatchSkip:
    """整批指派时没派成的一节,以及原因(代课老师那节有课、节次已结束…)。"""

    affected_period_id: int
    date: date
    period_name: str
    class_names: str
    subject_name: str
    reason: str


def assign_batch(
    db: Session,
    leave: LeaveRequest,
    *,
    handler_teacher_id: int,
    funding_source: str,
    counts_toward_hours: bool | None,
    on_date: date | None,
    created_by_user_id: int | None,
    created_by_name: str,
    allowed_grades: set[int] | None = None,
) -> tuple[list[Substitution], list[BatchSkip]]:
    """把一张假单(或其中一天)还没处理的节次,一次指派给同一位代课老师(#36)。

    班主任请整天或好几天假时,一节一节点同一位代课老师要点几十次。这里逐节沿用 `assign`
    ——检查规则完全一样——派得成的就派,派不成的(代课老师那一节自己有课、节次已结束)
    跳过并回报原因,由组长另外找人。已经处理过的节次不动。呼叫端负责 commit。

    allowed_grades 给定时(有年级权限的组长),范围外的节次不派、记为跳过并说明
    原因——跨年级的节次留给有权限的组长处理,而不是整批被挡下。
    """
    pending = sorted(
        (
            ap for ap in leave.affected_periods
            if ap.status == AffectedStatus.pending.value
            and (on_date is None or ap.date == on_date)
        ),
        key=lambda ap: (ap.date, ap.period_no),
    )
    if not pending:
        raise SubstitutionError(
            "这一天没有待处理的节次" if on_date else "这张假单没有待处理的节次")

    done: list[Substitution] = []
    skipped: list[BatchSkip] = []
    for ap in pending:
        if allowed_grades is not None:
            from app.services import grade_scopes as _gs
            _grades = _gs.source_grades(db, ap.schedule_entry_id, ap.course_assignment_id)
            if _grades and not _grades <= allowed_grades:
                skipped.append(BatchSkip(
                    affected_period_id=ap.id, date=ap.date, period_name=ap.period_name,
                    class_names=ap.class_names, subject_name=ap.subject_name,
                    reason="超出你的年级权限,已跳过",
                ))
                continue
        try:
            done.append(assign(
                db, ap,
                sub_type=SubstitutionType.substitute.value,
                handler_teacher_id=handler_teacher_id,
                counts_toward_hours=counts_toward_hours, funding_source=funding_source,
                swap_entry_id=None, swap_date=None,
                created_by_user_id=created_by_user_id, created_by_name=created_by_name,
            ))
        except SubstitutionError as exc:
            skipped.append(BatchSkip(
                affected_period_id=ap.id, date=ap.date, period_name=ap.period_name,
                class_names=ap.class_names, subject_name=ap.subject_name, reason=str(exc),
            ))
    return done, skipped


def _resolve_handler(
    db: Session,
    affected: AffectedPeriod,
    sub_type: str,
    handler_teacher_id: int | None,
    av: Availability,
) -> Teacher | None:
    if sub_type not in TYPES_WITH_HANDLER:
        return None  # 自习/不处理没有处理教师
    if handler_teacher_id is None:
        raise SubstitutionError(f"「{SUBSTITUTION_TYPE_CN[sub_type]}」需要指定教师")

    teacher = db.scalar(
        select(Teacher).where(
            Teacher.id == handler_teacher_id, Teacher.semester_id == affected.semester_id
        )
    )
    if teacher is None:
        raise SubstitutionError("找不到指定的教师")
    if teacher.id == affected.leave_request.teacher_id:
        raise SubstitutionError("不能指派请假教师代自己的课")

    # 代课/并班:接手者在该时段必须是空的(调课的冲突另由 _validate_swap 检查)
    if sub_type != SubstitutionType.swap.value:
        conflict = av.conflict_for(teacher.id, affected.date, av.slot_of(affected))
        if conflict is not None:
            raise SubstitutionError(
                f"{teacher.name} {affected.date} {affected.period_name} {conflict.detail},无法指派"
            )
    return teacher


def _validate_swap(
    db: Session,
    affected: AffectedPeriod,
    handler: Teacher | None,
    swap_entry_id: int | None,
    swap_date: date | None,
    swap_period_no: int | None,
    av: Availability,
) -> dict:
    """调课:乙(handler)代甲请假那节;甲(请假教师)于 swap_date 补乙原本的 swap_entry。

    先验组合本身成立(是已发布课表里乙的课、日期星期相符),再交给 `SwapChecker`
    验「乙能来、甲能补」——与「可对调节次」清单同一套规则,清单上的一定送得出去:
      ① 乙 在甲请假那节有空(没课、没请假、没被安排代别班)
      ② swap_entry 确实是乙在已发布课表里的课,且 swap_date 是那节课真的会上的日子;
         连堂格位以 swap_period_no 指定换其中哪一节(空 = 第一节)
      ③ 甲 在 swap_date 那节有空;乙那节没请假、也没已经换给别人;日期在学期内且还没上过
    任一不成立即拒绝并指名道姓。
    """
    if handler is None:
        raise SubstitutionError("调课需要指定对调教师")
    if swap_entry_id is None or swap_date is None:
        raise SubstitutionError("调课需要指定对调的节次与补课日期")

    entry = db.get(ScheduleEntry, swap_entry_id)
    if entry is None or av.timetable is None or entry.timetable_id != av.timetable.id:
        raise SubstitutionError("找不到要对调的节次(需为已发布课表中的课)")
    teaches = db.scalar(
        select(AssignmentTeacher).where(
            AssignmentTeacher.course_assignment_id == entry.course_assignment_id,
            AssignmentTeacher.teacher_id == handler.id,
        )
    )
    if teaches is None:
        raise SubstitutionError(f"要对调的节次不是 {handler.name} 的课")
    if swap_date.isoweekday() != entry.weekday:
        raise SubstitutionError(
            f"{swap_date} 是 {_wd(swap_date.isoweekday())},"
            f"但对调的课在 {_wd(entry.weekday)},补课日期与该节课星期不符"
        )
    if not av.entry_runs_on(entry, swap_date):
        week = "单周" if av.week_of(swap_date) == "odd" else "双周"
        raise SubstitutionError(f"{swap_date} 是{week},那一周没有这堂课(单双周的课)")
    period_no = entry.period_no if swap_period_no is None else swap_period_no
    if period_no not in block_periods(av, entry):
        raise SubstitutionError("指定的节次不在这堂课的时段内")
    if swap_date == affected.date and period_no == affected.period_no:
        raise SubstitutionError("补课的节次不能是请假的同一节")

    swap_assignment = db.get(CourseAssignment, entry.course_assignment_id)
    if swap_assignment is None:
        raise SubstitutionError("要对调的节次已无对应配课")

    checker = SwapChecker(db, affected, av)
    blocked = checker.partner_blocker(handler)
    if blocked is not None:
        raise SubstitutionError(f"{blocked},无法对调")
    blocked = checker.option_blocker(handler, entry, swap_date, period_no)
    if blocked is not None:
        subj = db.get(Subject, swap_assignment.subject_id)
        raise SubstitutionError(blocked + (f"(对调的是{subj.name})" if subj else ""))

    subject = db.get(Subject, swap_assignment.subject_id)
    classes = "、".join(m.class_unit.name for m in swap_assignment.scheduling_unit.members)
    return {
        "swap_date": swap_date,
        "swap_period_no": period_no,
        "swap_period_name": _entry_period_name(av, entry, period_no),
        "swap_class_names": classes,
        "swap_subject_name": subject.name if subject else "",
        "swap_entry_id": entry.id,
    }


def _entry_period_name(av: Availability, entry: ScheduleEntry, period_no: int) -> str:
    p = av.entry_period(entry, period_no)
    return p.name if p else f"第 {period_no} 格"


def _clear_swap(sub: Substitution) -> None:
    sub.swap_date = None
    sub.swap_period_no = None
    sub.swap_period_name = ""
    sub.swap_class_names = ""
    sub.swap_subject_name = ""
    sub.swap_entry_id = None


def _notify_handler(
    db: Session, affected: AffectedPeriod, sub: Substitution, handler: Teacher
) -> None:
    absent = affected.leave_request.teacher
    type_cn = SUBSTITUTION_TYPE_CN[sub.type]
    where = f"{affected.date} {affected.period_name}({affected.class_names}{affected.subject_name})"
    if sub.type == SubstitutionType.swap.value:
        body = (
            f"请于 {where} 代 {absent.name} 一节;"
            f"{absent.name} 将于 {sub.swap_date} {sub.swap_period_name} 补您的"
            f"{sub.swap_class_names}{sub.swap_subject_name}"
        )
    else:
        body = f"请于 {where} {type_cn} {absent.name} 的课"
    notifications.notify(
        db, semester_id=affected.semester_id, teacher_id=handler.id,
        type=NotificationType.substitution_assigned,
        title=f"{type_cn}通知:{affected.date} {affected.period_name}",
        body=body,
    )
    if sub.type == SubstitutionType.swap.value:
        # 调课多了一个要到场的人:请假的甲得回来补乙那节。只通知乙,甲就会漏掉补课。
        notifications.notify(
            db, semester_id=affected.semester_id, teacher_id=absent.id,
            type=NotificationType.substitution_assigned,
            title=f"调课补课通知:{sub.swap_date} {sub.swap_period_name}",
            body=(
                f"{handler.name} 将于 {where} 代您上课;"
                f"请您于 {sub.swap_date} {sub.swap_period_name} 补上 {handler.name} 的"
                f"{sub.swap_class_names}{sub.swap_subject_name}"
            ),
        )


def clear(db: Session, affected: AffectedPeriod, *, actor_name: str) -> None:
    """撤回处置:受影响节次退回『待处理』,已指派的教师收到取消通知。呼叫端负责 commit。"""
    if affected.leave_request.status == LeaveStatus.cancelled.value:
        raise SubstitutionError("此假单已销假")
    if clock.is_past_slot(affected.date, affected.end_time):
        raise SubstitutionError("此节次已结束,无法撤回处置")
    sub = db.scalar(select(Substitution).where(Substitution.affected_period_id == affected.id))
    if sub is None:
        return
    if sub.handler_teacher_id is not None:
        notifications.notify(
            db, semester_id=affected.semester_id, teacher_id=sub.handler_teacher_id,
            type=NotificationType.substitution_cancelled,
            title=f"原订{SUBSTITUTION_TYPE_CN[sub.type]}已取消",
            body=f"{actor_name} 取消了 {affected.date} {affected.period_name} 的处置",
        )
    if sub.type == SubstitutionType.swap.value:
        notifications.notify(
            db, semester_id=affected.semester_id, teacher_id=affected.leave_request.teacher_id,
            type=NotificationType.substitution_cancelled,
            title="原订调课已取消",
            body=(
                f"{actor_name} 取消了 {affected.date} {affected.period_name} 的调课;"
                f"您不必于 {sub.swap_date} {sub.swap_period_name} 补课"
            ),
        )
    db.delete(sub)
    affected.status = AffectedStatus.pending.value
    affected.handler_teacher_id = None
    db.flush()
