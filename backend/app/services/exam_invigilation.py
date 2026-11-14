"""监考安排服务(KW-23~29):规则、教师池、自动排监考、手工调整、巡考、
监考表两视图、工作量统计、考风考纪记录。

权限口径:写操作只允许 admin/director(由 API 层 require_roles +
can_manage_students 把关),考风考纪登记例外,监考教师本人也可登记
本人监考场次的考生;读操作按 exam_scopes 的可见范围过滤,教师只看
本人相关的监考与本人可见班级的考风考纪。

自动排监考口径(已冻结,见汇报):
- 候选人 = 监考教师池中 eligible 的在职教师;未建池时默认本学期
  全部在职教师。均衡按本场考试已有监考总场次排序,场次少的优先,
  同场次按教师 id 排序,保证结果稳定。
- 回避规则按 (科目, 考场) 执行:避本科 = 教师任教科目含该科;
  避本班 = 该考场该科编排的考生班级含教师任班主任的班级;编排未跑
  时考场班级未知,退回用本次考试全部参试班级判断(宁可少排,不错排)。
- 时间冲突进 warnings,不静默跳过:与已发布课表冲突、与同一时段
  已排监考冲突的教师不排进该场,各写一条警告;人选不足导致考场
  未排满时也写一条警告。已排过的不重复排,只补足缺额。
- 主监/副监暂不区分,role 统一为“监考”。
"""

from datetime import time as _time
from io import BytesIO

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.assignment import (
    AssignmentTeacher,
    CourseAssignment,
    SchedulingUnitMember,
)
from app.models.basedata import ClassUnit, Room, Subject, Teacher, teacher_subjects
from app.models.exam import Exam, ExamParticipant, ExamSubject
from app.models.exam_arrangement import ExamRoom, ExamRoomAssignment
from app.models.exam_foundation import Student
from app.models.exam_invigilation import (
    DEFAULT_AVOID_OWN_CLASS,
    DEFAULT_AVOID_OWN_SUBJECT,
    DEFAULT_INVIGILATORS_PER_ROOM,
    DISCIPLINE_TYPES,
    INVIGILATION_ROLE,
    ExamDiscipline,
    ExamInvigilation,
    ExamInvigilationRule,
    ExamInvigilatorPool,
    ExamPatrol,
)
from app.models.period import Period, PeriodTable
from app.models.timetable import ScheduleEntry, Timetable, TimetableStatus
from app.models.user import User
from app.services.exam import require_exam_not_archived
from app.services.exam_scopes import can_manage_students, visible_class_ids


def _times_overlap(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end


def _teacher_ids_for_user(db: Session, user: User) -> set[int]:
    """该账号绑定的全部 Teacher 记录 id(跨学期并集)。"""
    return set(
        db.scalars(
            select(Teacher.id).where(Teacher.user_id == user.id)
        ).all()
    )


def _subject_name_map(db: Session, subject_ids: set[int]) -> dict[int, str]:
    if not subject_ids:
        return {}
    return {
        s.id: s.name
        for s in db.scalars(
            select(Subject).where(Subject.id.in_(subject_ids))
        ).all()
    }


def _room_name_map(db: Session, room_ids: set[int]) -> dict[int, str]:
    if not room_ids:
        return {}
    return {
        r.id: r.name
        for r in db.scalars(select(Room).where(Room.id.in_(room_ids))).all()
    }


def _teacher_name_map(db: Session, teacher_ids: set[int]) -> dict[int, str]:
    if not teacher_ids:
        return {}
    return {
        t.id: t.name
        for t in db.scalars(
            select(Teacher).where(Teacher.id.in_(teacher_ids))
        ).all()
    }


def _require_exam_subject(db: Session, exam: Exam, subject_id: int) -> ExamSubject:
    subj = db.scalar(
        select(ExamSubject).where(
            ExamSubject.exam_id == exam.id,
            ExamSubject.subject_id == subject_id,
        )
    )
    if subj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到该考试科目")
    return subj


def _require_exam_room(db: Session, exam: Exam, room_id: int) -> ExamRoom:
    row = db.scalar(
        select(ExamRoom).where(
            ExamRoom.exam_id == exam.id, ExamRoom.room_id == room_id
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到考场")
    return row


def _require_semester_teacher(db: Session, exam: Exam, teacher_id: int) -> Teacher:
    teacher = db.get(Teacher, teacher_id)
    if teacher is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到教师")
    if teacher.semester_id != exam.semester_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "教师不属于本考试学期")
    return teacher


# ── 规则(KW-23) ──────────────────────────────
def get_rule(db: Session, exam: Exam) -> ExamInvigilationRule:
    row = db.scalar(
        select(ExamInvigilationRule).where(
            ExamInvigilationRule.exam_id == exam.id
        )
    )
    if row is not None:
        return row
    return ExamInvigilationRule(
        exam_id=exam.id,
        avoid_own_class=DEFAULT_AVOID_OWN_CLASS,
        avoid_own_subject=DEFAULT_AVOID_OWN_SUBJECT,
        invigilators_per_room=DEFAULT_INVIGILATORS_PER_ROOM,
    )


def upsert_rule(
    db: Session, exam: Exam,
    avoid_own_class: bool, avoid_own_subject: bool, invigilators_per_room: int,
) -> ExamInvigilationRule:
    require_exam_not_archived(db, exam.id)
    if invigilators_per_room < 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "每考场监考人数至少为 1")
    row = db.scalar(
        select(ExamInvigilationRule).where(
            ExamInvigilationRule.exam_id == exam.id
        )
    )
    if row is None:
        row = ExamInvigilationRule(exam_id=exam.id)
        db.add(row)
    row.avoid_own_class = avoid_own_class
    row.avoid_own_subject = avoid_own_subject
    row.invigilators_per_room = invigilators_per_room
    db.commit()
    db.refresh(row)
    return row


# ── 教师池(KW-23) ──────────────────────────────
def list_pool(db: Session, exam: Exam) -> tuple[list[dict], int]:
    """未建池时返回本学期全部在职教师(eligible=true);建池后返回池内行。"""
    rows = db.scalars(
        select(ExamInvigilatorPool).where(
            ExamInvigilatorPool.exam_id == exam.id
        ).order_by(ExamInvigilatorPool.teacher_id)
    ).all()
    if not rows:
        teachers = db.scalars(
            select(Teacher).where(
                Teacher.semester_id == exam.semester_id,
                Teacher.is_active.is_(True),
            ).order_by(Teacher.id)
        ).all()
        items = [
            {"teacher_id": t.id, "teacher_name": t.name, "eligible": True}
            for t in teachers
        ]
        return items, len(items)
    names = _teacher_name_map(db, {r.teacher_id for r in rows})
    items = [
        {
            "teacher_id": r.teacher_id,
            "teacher_name": names.get(r.teacher_id, ""),
            "eligible": r.eligible,
        }
        for r in rows
        if r.teacher_id in names
    ]
    return items, len(items)


def upsert_pool(
    db: Session, exam: Exam, items: list[dict]
) -> tuple[list[dict], int]:
    require_exam_not_archived(db, exam.id)
    for it in items:
        _require_semester_teacher(db, exam, it["teacher_id"])
    db.query(ExamInvigilatorPool).filter(
        ExamInvigilatorPool.exam_id == exam.id
    ).delete(synchronize_session=False)
    for it in items:
        db.add(ExamInvigilatorPool(
            exam_id=exam.id,
            teacher_id=it["teacher_id"],
            eligible=bool(it.get("eligible", True)),
        ))
    db.commit()
    return list_pool(db, exam)


def _eligible_teachers(db: Session, exam: Exam) -> list[Teacher]:
    """自动排监考的候选人:池内 eligible 的在职教师;未建池时全部在职教师。"""
    pool_ids = {
        r.teacher_id: r.eligible
        for r in db.scalars(
            select(ExamInvigilatorPool).where(
                ExamInvigilatorPool.exam_id == exam.id
            )
        ).all()
    }
    teachers = db.scalars(
        select(Teacher).where(
            Teacher.semester_id == exam.semester_id,
            Teacher.is_active.is_(True),
        ).order_by(Teacher.id)
    ).all()
    if not pool_ids:
        return teachers
    return [t for t in teachers if pool_ids.get(t.id, False)]


def _pool_eligible(db: Session, exam: Exam, teacher_id: int) -> bool:
    """手工指定时校验:建池后停用的教师不允许排入;未建池时一律允许。"""
    row = db.scalar(
        select(ExamInvigilatorPool).where(
            ExamInvigilatorPool.exam_id == exam.id,
            ExamInvigilatorPool.teacher_id == teacher_id,
        )
    )
    if row is None:
        has_pool = db.scalar(
            select(func.count()).select_from(ExamInvigilatorPool).where(
                ExamInvigilatorPool.exam_id == exam.id
            )
        ) or 0
        return has_pool == 0
    return row.eligible


# ── 冲突检测(KW-24) ──────────────────────────────
def _timetable_conflict(
    db: Session, exam: Exam, teacher_id: int,
    exam_date, start_time: _time, end_time: _time,
) -> str | None:
    """与已发布课表冲突时返回冲突说明,无冲突返回 None。

    口径与考试日程检查一致:只查已发布课表,以节次墙钟时间判定重叠。
    """
    tt = db.scalar(
        select(Timetable).where(
            Timetable.semester_id == exam.semester_id,
            Timetable.status == TimetableStatus.published.value,
        )
    )
    if tt is None:
        return None
    weekday = exam_date.isoweekday()
    ca_ids = {
        r for (r,) in db.execute(
            select(AssignmentTeacher.course_assignment_id).where(
                AssignmentTeacher.teacher_id == teacher_id
            )
        ).all()
    }
    if not ca_ids:
        return None
    entries = db.execute(
        select(ScheduleEntry.course_assignment_id, ScheduleEntry.period_no)
        .where(
            ScheduleEntry.timetable_id == tt.id,
            ScheduleEntry.course_assignment_id.in_(ca_ids),
            ScheduleEntry.weekday == weekday,
        )
    ).all()
    if not entries:
        return None
    cas = {
        c.id: c
        for c in db.scalars(
            select(CourseAssignment).where(CourseAssignment.id.in_(ca_ids))
        ).all()
    }
    members = db.execute(
        select(
            SchedulingUnitMember.scheduling_unit_id,
            SchedulingUnitMember.class_unit_id,
        ).where(
            SchedulingUnitMember.scheduling_unit_id.in_(
                {c.scheduling_unit_id for c in cas.values()}
            )
        )
    ).all()
    unit_classes: dict[int, list[int]] = {}
    for uid, cid in members:
        unit_classes.setdefault(uid, []).append(cid)
    all_class_ids = {cid for v in unit_classes.values() for cid in v}
    classes = {
        c.id: c
        for c in db.scalars(
            select(ClassUnit).where(ClassUnit.id.in_(all_class_ids))
        ).all()
    } if all_class_ids else {}
    default_table = db.scalar(
        select(PeriodTable).where(
            PeriodTable.semester_id == exam.semester_id,
            PeriodTable.is_default.is_(True),
        )
    )
    table_ids = {c.period_table_id for c in classes.values() if c.period_table_id}
    if default_table is not None:
        table_ids.add(default_table.id)
    period_map: dict[tuple[int, int, int], Period] = {}
    if table_ids:
        for p in db.scalars(
            select(Period).where(Period.period_table_id.in_(table_ids))
        ).all():
            period_map[(p.period_table_id, p.weekday, p.period_no)] = p
    subject_names = _subject_name_map(
        db, {c.subject_id for c in cas.values() if c.subject_id}
    )
    for ca_id, period_no in entries:
        ca = cas.get(ca_id)
        if ca is None:
            continue
        for class_id in unit_classes.get(ca.scheduling_unit_id, []):
            cls = classes.get(class_id)
            if cls is None:
                continue
            table_id = cls.period_table_id or (
                default_table.id if default_table is not None else None
            )
            if table_id is None:
                continue
            period = period_map.get((table_id, weekday, period_no))
            if (
                period is None
                or period.start_time is None
                or period.end_time is None
            ):
                continue
            if not _times_overlap(
                start_time, end_time, period.start_time, period.end_time
            ):
                continue
            return (
                f"与已发布课表冲突:{cls.name}班周{weekday}第{period_no}节"
                f"({subject_names.get(ca.subject_id, '')})"
            )
    return None


def _invigilation_conflict(
    db: Session, exam_id: int, teacher_id: int,
    exam_date, start_time: _time, end_time: _time,
    exclude_id: int | None = None,
) -> tuple[ExamInvigilation, ExamSubject] | None:
    """与同一时段已排监考冲突时返回 (监考行, 科目行),无冲突返回 None。"""
    rows = db.execute(
        select(ExamInvigilation, ExamSubject)
        .join(
            ExamSubject,
            (ExamSubject.exam_id == ExamInvigilation.exam_id)
            & (ExamSubject.subject_id == ExamInvigilation.subject_id),
        )
        .where(
            ExamInvigilation.exam_id == exam_id,
            ExamInvigilation.teacher_id == teacher_id,
            ExamSubject.exam_date == exam_date,
        )
    ).all()
    for inv, subj in rows:
        if exclude_id is not None and inv.id == exclude_id:
            continue
        if _times_overlap(start_time, end_time, subj.start_time, subj.end_time):
            return inv, subj
    return None


# ── 自动排监考(KW-24) ──────────────────────────────
def auto_invigilate(
    db: Session, exam: Exam, subject_id: int | None
) -> dict:
    require_exam_not_archived(db, exam.id)
    """自动排监考;返回 {"assigned": 新增条数, "warnings": [...]}。

    已排过的不重复排,只补足每考场缺额;不指定科目则排全部科目。
    """
    rooms = db.scalars(
        select(ExamRoom).where(ExamRoom.exam_id == exam.id)
        .order_by(ExamRoom.id)
    ).all()
    if not rooms:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "请先设置考场再排监考")
    if subject_id is not None:
        subjects = [_require_exam_subject(db, exam, subject_id)]
    else:
        subjects = db.scalars(
            select(ExamSubject).where(ExamSubject.exam_id == exam.id)
            .order_by(ExamSubject.exam_date, ExamSubject.start_time)
        ).all()
    if not subjects:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "考试尚未设置科目,请先设置科目再排监考"
        )
    rule = get_rule(db, exam)
    candidates = _eligible_teachers(db, exam)
    if not candidates:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "监考教师池为空,请先设置监考教师池")
    counts: dict[int, int] = {}
    for tid, n in db.execute(
        select(ExamInvigilation.teacher_id, func.count())
        .where(ExamInvigilation.exam_id == exam.id)
        .group_by(ExamInvigilation.teacher_id)
    ).all():
        counts[tid] = n
    # 教师任教科目(避本科)与班主任班级(避本班)。
    teacher_subject_ids: dict[int, set[int]] = {}
    for tid, sid in db.execute(
        select(teacher_subjects.c.teacher_id, teacher_subjects.c.subject_id)
    ).all():
        teacher_subject_ids.setdefault(tid, set()).add(sid)
    homeroom_classes: dict[int, set[int]] = {}
    for cid, tid in db.execute(
        select(ClassUnit.id, ClassUnit.homeroom_teacher_id)
        .where(ClassUnit.homeroom_teacher_id.is_not(None))
    ).all():
        homeroom_classes.setdefault(tid, set()).add(cid)
    # 每 (科目, 考场) 的考生班级:编排未跑时退回用全部参试班级。
    room_classes: dict[tuple[int, int], set[int]] = {}
    for subj_id, room_id, class_id in db.execute(
        select(
            ExamRoomAssignment.subject_id,
            ExamRoomAssignment.room_id,
            ExamParticipant.class_unit_id,
        )
        .join(
            ExamParticipant,
            (ExamParticipant.exam_id == ExamRoomAssignment.exam_id)
            & (ExamParticipant.student_id == ExamRoomAssignment.student_id),
        )
        .where(ExamRoomAssignment.exam_id == exam.id)
    ).all():
        room_classes.setdefault((subj_id, room_id), set()).add(class_id)
    participant_classes = {
        cid for (cid,) in db.execute(
            select(ExamParticipant.class_unit_id).where(
                ExamParticipant.exam_id == exam.id
            )
        ).all()
    }
    subject_names = _subject_name_map(db, {s.subject_id for s in subjects})
    room_names = _room_name_map(db, {r.room_id for r in rooms})
    warnings: list[str] = []
    assigned = 0
    for subj in subjects:
        subj_name = subject_names.get(subj.subject_id, "")
        for room in rooms:
            room_name = room_names.get(room.room_id, "")
            existing = db.scalars(
                select(ExamInvigilation).where(
                    ExamInvigilation.exam_id == exam.id,
                    ExamInvigilation.subject_id == subj.subject_id,
                    ExamInvigilation.room_id == room.room_id,
                )
            ).all()
            existing_ids = {e.teacher_id for e in existing}
            need = rule.invigilators_per_room - len(existing)
            if need <= 0:
                continue
            cls_set = room_classes.get(
                (subj.subject_id, room.room_id), participant_classes
            )
            ordered = sorted(
                candidates, key=lambda t: (counts.get(t.id, 0), t.id)
            )
            for teacher in ordered:
                if need <= 0:
                    break
                if teacher.id in existing_ids:
                    continue
                if (
                    rule.avoid_own_subject
                    and subj.subject_id
                    in teacher_subject_ids.get(teacher.id, set())
                ):
                    continue
                if (
                    rule.avoid_own_class
                    and homeroom_classes.get(teacher.id, set()) & cls_set
                ):
                    continue
                conflict = _timetable_conflict(
                    db, exam, teacher.id,
                    subj.exam_date, subj.start_time, subj.end_time,
                )
                if conflict is not None:
                    warnings.append(
                        f"教师{teacher.name}未排入{subj_name}考试"
                        f"{room_name}考场:{conflict}"
                    )
                    continue
                clash = _invigilation_conflict(
                    db, exam.id, teacher.id,
                    subj.exam_date, subj.start_time, subj.end_time,
                )
                if clash is not None:
                    other_inv, other_subj = clash
                    other_room = room_names.get(other_inv.room_id, "")
                    warnings.append(
                        f"教师{teacher.name}未排入{subj_name}考试"
                        f"{room_name}考场:同一时段已有监考安排"
                        f"({subject_names.get(other_subj.subject_id, '')}"
                        f"·{other_room}考场)"
                    )
                    continue
                db.add(ExamInvigilation(
                    exam_id=exam.id,
                    subject_id=subj.subject_id,
                    room_id=room.room_id,
                    teacher_id=teacher.id,
                    role=INVIGILATION_ROLE,
                ))
                db.flush()
                counts[teacher.id] = counts.get(teacher.id, 0) + 1
                existing_ids.add(teacher.id)
                assigned += 1
                need -= 1
            if need > 0:
                warnings.append(
                    f"{room_name}考场{subj_name}考试仅安排"
                    f"{rule.invigilators_per_room - need}人,缺少{need}人"
                    f"(可选监考教师不足)"
                )
    db.commit()
    return {"assigned": assigned, "warnings": warnings}


# ── 监考安排查询 / 手工调整(KW-25) ──────────────────────────────
def _invigilation_out(
    db: Session, row: ExamInvigilation,
    subject_names: dict[int, str],
    room_names: dict[int, str],
    teacher_names: dict[int, str],
) -> dict:
    return {
        "id": row.id,
        "exam_id": row.exam_id,
        "subject_id": row.subject_id,
        "subject_name": subject_names.get(row.subject_id, ""),
        "room_id": row.room_id,
        "room_name": room_names.get(row.room_id, ""),
        "teacher_id": row.teacher_id,
        "teacher_name": teacher_names.get(row.teacher_id, ""),
        "role": row.role,
    }


def _visible_invigilations(
    db: Session, user: User, exam: Exam,
    subject_id: int | None = None,
    room_id: int | None = None,
    teacher_id: int | None = None,
) -> list[ExamInvigilation]:
    """按可见范围过滤后的监考安排(教师只看本人相关的监考)。"""
    stmt = select(ExamInvigilation).where(ExamInvigilation.exam_id == exam.id)
    if subject_id is not None:
        stmt = stmt.where(ExamInvigilation.subject_id == subject_id)
    if room_id is not None:
        stmt = stmt.where(ExamInvigilation.room_id == room_id)
    if teacher_id is not None:
        stmt = stmt.where(ExamInvigilation.teacher_id == teacher_id)
    rows = db.scalars(stmt.order_by(ExamInvigilation.id)).all()
    class_ids = visible_class_ids(db, user)
    if class_ids is None:
        return list(rows)
    own_ids = _teacher_ids_for_user(db, user)
    return [r for r in rows if r.teacher_id in own_ids]


def list_invigilations(
    db: Session, user: User, exam: Exam,
    subject_id: int | None = None,
    room_id: int | None = None,
    teacher_id: int | None = None,
) -> tuple[list[dict], int]:
    rows = _visible_invigilations(db, user, exam, subject_id, room_id, teacher_id)
    subject_names = _subject_name_map(db, {r.subject_id for r in rows})
    room_names = _room_name_map(db, {r.room_id for r in rows})
    teacher_names = _teacher_name_map(db, {r.teacher_id for r in rows})
    items = [
        _invigilation_out(db, r, subject_names, room_names, teacher_names)
        for r in rows
    ]
    return items, len(items)


def _validate_manual_target(
    db: Session, exam: Exam,
    subject_id: int, room_id: int, teacher_id: int,
    exclude_id: int | None = None,
) -> tuple[ExamSubject, ExamRoom, Teacher]:
    """手工指定/替补的校验:科目、考场、教师归属与池内停用、同一时段重复排监。

    回避规则不拦手工指定(手工调整本身就是例外处理)。
    """
    subj = _require_exam_subject(db, exam, subject_id)
    room = _require_exam_room(db, exam, room_id)
    teacher = _require_semester_teacher(db, exam, teacher_id)
    if not teacher.is_active:
        raise HTTPException(status.HTTP_409_CONFLICT, "该教师已不在职")
    if not _pool_eligible(db, exam, teacher_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "该教师已在监考教师池中停用"
        )
    dup = db.scalar(
        select(ExamInvigilation.id).where(
            ExamInvigilation.exam_id == exam.id,
            ExamInvigilation.subject_id == subject_id,
            ExamInvigilation.room_id == room_id,
            ExamInvigilation.teacher_id == teacher_id,
            ExamInvigilation.id != (exclude_id or -1),
        )
    )
    if dup is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "该教师已安排在本考场监考"
        )
    clash = _invigilation_conflict(
        db, exam.id, teacher_id,
        subj.exam_date, subj.start_time, subj.end_time,
        exclude_id=exclude_id,
    )
    if clash is not None:
        other_inv, other_subj = clash
        if other_subj.subject_id == subject_id:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "该教师在本科目已有监考安排"
            )
        raise HTTPException(
            status.HTTP_409_CONFLICT, "该教师在同一时段已有监考安排"
        )
    return subj, room, teacher


def create_invigilation(
    db: Session, exam: Exam,
    subject_id: int, room_id: int, teacher_id: int, role: str | None,
) -> ExamInvigilation:
    require_exam_not_archived(db, exam.id)
    _validate_manual_target(db, exam, subject_id, room_id, teacher_id)
    row = ExamInvigilation(
        exam_id=exam.id,
        subject_id=subject_id,
        room_id=room_id,
        teacher_id=teacher_id,
        role=role or INVIGILATION_ROLE,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def create_invigilations_bulk(
    db: Session, exam: Exam,
    subject_id: int, room_id: int, teacher_ids: list[int], role: str | None,
) -> tuple[int, int]:
    """批量手工安排监考:同一科目同一考场一次勾选多位教师。
    已安排在本考场/不存在/不在职/池中停用/同一时段已有监考者计入跳过,不中断整批;一次提交。"""
    require_exam_not_archived(db, exam.id)
    _require_exam_subject(db, exam, subject_id)
    _require_exam_room(db, exam, room_id)
    created = 0
    skipped = 0
    for teacher_id in dict.fromkeys(teacher_ids):
        try:
            _validate_manual_target(db, exam, subject_id, room_id, teacher_id)
        except HTTPException:
            skipped += 1
            continue
        db.add(ExamInvigilation(
            exam_id=exam.id,
            subject_id=subject_id,
            room_id=room_id,
            teacher_id=teacher_id,
            role=role or INVIGILATION_ROLE,
        ))
        created += 1
    db.commit()
    return created, skipped


def invigilation_to_out(db: Session, row: ExamInvigilation) -> dict:
    subject_names = _subject_name_map(db, {row.subject_id})
    room_names = _room_name_map(db, {row.room_id})
    teacher_names = _teacher_name_map(db, {row.teacher_id})
    return _invigilation_out(db, row, subject_names, room_names, teacher_names)


def update_invigilation(
    db: Session, exam: Exam, iid: int,
    teacher_id: int | None, role: str | None,
) -> ExamInvigilation:
    require_exam_not_archived(db, exam.id)
    """替补换人(PATCH):只改教师和 role;换人时按手工指定口径重校验。"""
    row = db.get(ExamInvigilation, iid)
    if row is None or row.exam_id != exam.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到监考安排")
    if teacher_id is not None and teacher_id != row.teacher_id:
        _validate_manual_target(
            db, exam, row.subject_id, row.room_id, teacher_id,
            exclude_id=row.id,
        )
        row.teacher_id = teacher_id
    if role is not None:
        row.role = role
    db.commit()
    db.refresh(row)
    return row


def delete_invigilation(db: Session, exam: Exam, iid: int) -> None:
    require_exam_not_archived(db, exam.id)
    row = db.get(ExamInvigilation, iid)
    if row is None or row.exam_id != exam.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到监考安排")
    db.delete(row)
    db.commit()


# ── 巡考安排(KW-26) ──────────────────────────────
def list_patrols(
    db: Session, user: User, exam: Exam
) -> tuple[list[dict], int]:
    rows = db.scalars(
        select(ExamPatrol).where(ExamPatrol.exam_id == exam.id)
        .order_by(ExamPatrol.exam_date, ExamPatrol.id)
    ).all()
    class_ids = visible_class_ids(db, user)
    if class_ids is not None:
        own_ids = _teacher_ids_for_user(db, user)
        rows = [r for r in rows if r.teacher_id in own_ids]
    names = _teacher_name_map(db, {r.teacher_id for r in rows})
    items = [
        {
            "id": r.id,
            "exam_id": r.exam_id,
            "exam_date": r.exam_date,
            "teacher_id": r.teacher_id,
            "teacher_name": names.get(r.teacher_id, ""),
            "scope": r.scope,
            "note": r.note,
        }
        for r in rows
    ]
    return items, len(items)


def create_patrol(
    db: Session, exam: Exam,
    exam_date, teacher_id: int, scope: str, note: str | None,
) -> ExamPatrol:
    require_exam_not_archived(db, exam.id)
    _require_semester_teacher(db, exam, teacher_id)
    row = ExamPatrol(
        exam_id=exam.id, exam_date=exam_date,
        teacher_id=teacher_id, scope=scope, note=note,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def patrol_to_out(db: Session, row: ExamPatrol) -> dict:
    names = _teacher_name_map(db, {row.teacher_id})
    return {
        "id": row.id,
        "exam_id": row.exam_id,
        "exam_date": row.exam_date,
        "teacher_id": row.teacher_id,
        "teacher_name": names.get(row.teacher_id, ""),
        "scope": row.scope,
        "note": row.note,
    }


def update_patrol(
    db: Session, exam: Exam, pid: int,
    exam_date, teacher_id: int | None, scope: str | None, note: str | None,
) -> ExamPatrol:
    require_exam_not_archived(db, exam.id)
    row = db.get(ExamPatrol, pid)
    if row is None or row.exam_id != exam.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到巡考安排")
    if teacher_id is not None and teacher_id != row.teacher_id:
        _require_semester_teacher(db, exam, teacher_id)
        row.teacher_id = teacher_id
    if exam_date is not None:
        row.exam_date = exam_date
    if scope is not None:
        row.scope = scope
    if note is not None:
        row.note = note
    db.commit()
    db.refresh(row)
    return row


def delete_patrol(db: Session, exam: Exam, pid: int) -> None:
    require_exam_not_archived(db, exam.id)
    row = db.get(ExamPatrol, pid)
    if row is None or row.exam_id != exam.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到巡考安排")
    db.delete(row)
    db.commit()


# ── 监考表两视图(KW-27) ──────────────────────────────
def _sheet_rows(
    db: Session, user: User, exam: Exam, subject_id: int | None
) -> list[tuple[ExamInvigilation, ExamSubject]]:
    rows = _visible_invigilations(db, user, exam, subject_id=subject_id)
    subjects = {
        s.subject_id: s
        for s in db.scalars(
            select(ExamSubject).where(
                ExamSubject.exam_id == exam.id,
                ExamSubject.subject_id.in_({r.subject_id for r in rows}),
            )
        ).all()
    } if rows else {}
    return [(r, subjects.get(r.subject_id)) for r in rows]


def teacher_sheet(
    db: Session, user: User, exam: Exam, subject_id: int | None
) -> dict:
    pairs = _sheet_rows(db, user, exam, subject_id)
    room_names = _room_name_map(db, {r.room_id for r, _ in pairs})
    teacher_names = _teacher_name_map(db, {r.teacher_id for r, _ in pairs})
    subject_names = _subject_name_map(db, {r.subject_id for r, _ in pairs})
    grouped: dict[int, list[dict]] = {}
    for row, subj in pairs:
        if subj is None:
            continue
        grouped.setdefault(row.teacher_id, []).append({
            "subject_name": subject_names.get(row.subject_id, ""),
            "exam_date": subj.exam_date.isoformat(),
            "start_time": subj.start_time.strftime("%H:%M"),
            "end_time": subj.end_time.strftime("%H:%M"),
            "room_name": room_names.get(row.room_id, ""),
            "_sort": (subj.exam_date, subj.start_time),
        })
    teachers = []
    for tid in sorted(grouped, key=lambda t: teacher_names.get(t, "")):
        sessions = sorted(grouped[tid], key=lambda s: s["_sort"])
        for s in sessions:
            s.pop("_sort", None)
        teachers.append({
            "teacher_id": tid,
            "teacher_name": teacher_names.get(tid, ""),
            "sessions": sessions,
        })
    return {"teachers": teachers}


def room_sheet(
    db: Session, user: User, exam: Exam, subject_id: int | None
) -> dict:
    pairs = _sheet_rows(db, user, exam, subject_id)
    room_names = _room_name_map(db, {r.room_id for r, _ in pairs})
    teacher_names = _teacher_name_map(db, {r.teacher_id for r, _ in pairs})
    subject_names = _subject_name_map(db, {r.subject_id for r, _ in pairs})
    grouped: dict[int, dict[tuple, list[str]]] = {}
    for row, subj in pairs:
        if subj is None:
            continue
        key = (
            subj.subject_id, subj.exam_date,
            subj.start_time, subj.end_time,
        )
        grouped.setdefault(row.room_id, {}).setdefault(key, []).append(
            teacher_names.get(row.teacher_id, "")
        )
    rooms = []
    for rid in sorted(grouped, key=lambda r: room_names.get(r, "")):
        sessions = []
        for (sid, exam_date, start_time, end_time), names in sorted(
            grouped[rid].items(),
            key=lambda kv: (kv[0][1], kv[0][2]),
        ):
            sessions.append({
                "subject_name": subject_names.get(sid, ""),
                "exam_date": exam_date.isoformat(),
                "start_time": start_time.strftime("%H:%M"),
                "end_time": end_time.strftime("%H:%M"),
                "teachers": sorted(names),
            })
        rooms.append({
            "room_id": rid,
            "room_name": room_names.get(rid, ""),
            "sessions": sessions,
        })
    return {"rooms": rooms}


# ── 工作量统计(KW-28) ──────────────────────────────
def workload(
    db: Session, user: User, exam: Exam
) -> tuple[list[dict], int]:
    """每位教师监考场次与总时长(分钟,按科目起止时间算)。

    只出场次数据,不折算补贴、不与课时统计合并。
    """
    rows = _visible_invigilations(db, user, exam)
    subjects = {
        s.subject_id: s
        for s in db.scalars(
            select(ExamSubject).where(
                ExamSubject.exam_id == exam.id,
                ExamSubject.subject_id.in_({r.subject_id for r in rows}),
            )
        ).all()
    } if rows else {}
    teacher_names = _teacher_name_map(db, {r.teacher_id for r in rows})
    totals: dict[int, dict] = {}
    for row in rows:
        subj = subjects.get(row.subject_id)
        if subj is None:
            continue
        minutes = int(
            (subj.end_time.hour * 60 + subj.end_time.minute)
            - (subj.start_time.hour * 60 + subj.start_time.minute)
        )
        entry = totals.setdefault(
            row.teacher_id, {"sessions": 0, "minutes": 0}
        )
        entry["sessions"] += 1
        entry["minutes"] += minutes
    items = [
        {
            "teacher_id": tid,
            "teacher_name": teacher_names.get(tid, ""),
            "sessions": v["sessions"],
            "minutes": v["minutes"],
        }
        for tid, v in sorted(
            totals.items(), key=lambda kv: teacher_names.get(kv[0], "")
        )
    ]
    return items, len(items)


def build_workload_workbook(
    db: Session, user: User, exam: Exam
) -> bytes:
    """监考工作量表 Excel:教师、监考场次、总时长(分钟)。"""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, Side

    items, _ = workload(db, user, exam)
    wb = Workbook()
    ws = wb.active
    ws.title = "监考工作量"
    thin = Side(style="thin", color="999999")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    header_font = Font(bold=True)
    ws.append(["教师", "监考场次", "总时长(分钟)"])
    for cell in ws[1]:
        cell.font = header_font
        cell.border = border
        cell.alignment = Alignment(horizontal="center")
    for it in items:
        ws.append([it["teacher_name"], it["sessions"], it["minutes"]])
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.border = border
    for i, w in enumerate([16, 12, 16], start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── 考风考纪记录(KW-29) ──────────────────────────────
def _discipline_out(db: Session, row: ExamDiscipline) -> dict:
    subject_names = _subject_name_map(db, {row.subject_id})
    student = db.get(Student, row.student_id)
    class_name = ""
    if student is not None:
        cls = db.get(ClassUnit, student.class_unit_id)
        class_name = cls.name if cls else ""
    recorded_name = ""
    if row.recorded_by is not None:
        recorder = db.get(User, row.recorded_by)
        recorded_name = recorder.username if recorder else ""
    return {
        "id": row.id,
        "exam_id": row.exam_id,
        "subject_id": row.subject_id,
        "subject_name": subject_names.get(row.subject_id, ""),
        "student_id": row.student_id,
        "student_no": student.student_no if student else "",
        "student_name": student.name if student else "",
        "class_name": class_name,
        "type": row.type,
        "description": row.description,
        "handling": row.handling,
        "recorded_by": row.recorded_by,
        "recorded_by_name": recorded_name,
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


def _require_can_record_discipline(
    db: Session, user: User, exam: Exam, subject_id: int, student_id: int
) -> None:
    """考风考纪登记权限:教务可登记任意参试考生;监考教师只能登记
    本人监考场次的考生(该科该考场编排名单内的考生;编排未跑时退回
    以本人监考该科为准)。"""
    if can_manage_students(db, user):
        return
    own_ids = _teacher_ids_for_user(db, user)
    if not own_ids:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "只有监考教师本人可以登记考风考纪"
        )
    my_rooms = {
        r.room_id for r in db.scalars(
            select(ExamInvigilation).where(
                ExamInvigilation.exam_id == exam.id,
                ExamInvigilation.subject_id == subject_id,
                ExamInvigilation.teacher_id.in_(own_ids),
            )
        ).all()
    }
    if not my_rooms:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "只能登记本人监考场次的考风考纪"
        )
    assigned_rooms = {
        r.room_id for r in db.scalars(
            select(ExamRoomAssignment).where(
                ExamRoomAssignment.exam_id == exam.id,
                ExamRoomAssignment.subject_id == subject_id,
            )
        ).all()
    }
    if not assigned_rooms:
        return
    student_rooms = {
        r.room_id for r in db.scalars(
            select(ExamRoomAssignment).where(
                ExamRoomAssignment.exam_id == exam.id,
                ExamRoomAssignment.subject_id == subject_id,
                ExamRoomAssignment.student_id == student_id,
            )
        ).all()
    }
    if not (student_rooms & my_rooms):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "该考生不在你监考的考场"
        )


def list_discipline(
    db: Session, user: User, exam: Exam
) -> tuple[list[dict], int]:
    rows = db.scalars(
        select(ExamDiscipline).where(ExamDiscipline.exam_id == exam.id)
        .order_by(ExamDiscipline.id)
    ).all()
    class_ids = visible_class_ids(db, user)
    if class_ids is not None:
        students = {
            s.id: s
            for s in db.scalars(
                select(Student).where(
                    Student.id.in_({r.student_id for r in rows})
                )
            ).all()
        } if rows else {}
        rows = [
            r for r in rows
            if (
                students.get(r.student_id) is not None
                and students[r.student_id].class_unit_id in class_ids
            )
            or r.recorded_by == user.id
        ]
    items = [_discipline_out(db, r) for r in rows]
    return items, len(items)


def create_discipline(
    db: Session, user: User, exam: Exam,
    subject_id: int, student_id: int,
    type_: str, description: str | None, handling: str | None,
) -> ExamDiscipline:
    require_exam_not_archived(db, exam.id)
    _require_exam_subject(db, exam, subject_id)
    if type_ not in DISCIPLINE_TYPES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "类型只能是违纪、作弊或其他"
        )
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到该学生")
    participant = db.scalar(
        select(ExamParticipant).where(
            ExamParticipant.exam_id == exam.id,
            ExamParticipant.student_id == student_id,
        )
    )
    if participant is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "该考生不在本次考试参试名单中"
        )
    _require_can_record_discipline(db, user, exam, subject_id, student_id)
    row = ExamDiscipline(
        exam_id=exam.id,
        subject_id=subject_id,
        student_id=student_id,
        type=type_,
        description=description,
        handling=handling,
        recorded_by=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_discipline(
    db: Session, exam: Exam, did: int,
    subject_id: int | None, student_id: int | None,
    type_: str | None, description: str | None, handling: str | None,
) -> ExamDiscipline:
    require_exam_not_archived(db, exam.id)
    row = db.get(ExamDiscipline, did)
    if row is None or row.exam_id != exam.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到考风考纪记录")
    if subject_id is not None and subject_id != row.subject_id:
        _require_exam_subject(db, exam, subject_id)
        row.subject_id = subject_id
    if student_id is not None and student_id != row.student_id:
        student = db.get(Student, student_id)
        if student is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到该学生")
        participant = db.scalar(
            select(ExamParticipant).where(
                ExamParticipant.exam_id == exam.id,
                ExamParticipant.student_id == student_id,
            )
        )
        if participant is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "该考生不在本次考试参试名单中"
            )
        row.student_id = student_id
    if type_ is not None:
        if type_ not in DISCIPLINE_TYPES:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "类型只能是违纪、作弊或其他"
            )
        row.type = type_
    if description is not None:
        row.description = description
    if handling is not None:
        row.handling = handling
    db.commit()
    db.refresh(row)
    return row


def delete_discipline(db: Session, exam: Exam, did: int) -> None:
    require_exam_not_archived(db, exam.id)
    row = db.get(ExamDiscipline, did)
    if row is None or row.exam_id != exam.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到考风考纪记录")
    db.delete(row)
    db.commit()
