"""考试管理服务(KW-08~14):考试创建、日程、参试名单、状态流转、复制、命题信息、特殊考生安排。

权限口径:
- 写操作只允许 admin/director,由 API 层 require_roles + can_manage_students 把关。
- 读操作按 exam_scopes 的可见范围过滤:教师只能看到参试年级与本人可见年级
  有交集的考试,参试名单只看本人可见班级,特殊考生安排同理。
- 日程冲突只提示、不阻断:科间冲突必查;与已发布课表冲突只在有已发布课表
  且能取到节次墙钟时间时才查,无已发布课表则只查科间冲突。
"""

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.assignment import CourseAssignment, SchedulingUnitMember
from app.models.basedata import ClassUnit, Subject, Teacher
from app.models.exam import (
    ARRANGEMENT_STATUSES,
    ARRANGEMENT_TYPES,
    EXAM_STATUS_ORDER,
    EXAM_STATUSES,
    EXAM_TYPES,
    PARTICIPANT_STATUSES,
    Exam,
    ExamGrade,
    ExamPaperInfo,
    ExamParticipant,
    ExamSpecialArrangement,
    ExamStatusChange,
    ExamSubject,
)
from app.models.exam_foundation import Student
from app.models.period import Period, PeriodTable
from app.models.semester import Semester
from app.models.timetable import ScheduleEntry, Timetable, TimetableStatus
from app.models.user import Role, User
from app.schemas.exam import (
    ExamDetailOut,
    ExamOut,
    ExamSubjectOut,
    PaperInfoOut,
    ParticipantOut,
    ScheduleConflictOut,
    SpecialArrangementOut,
)
from app.services.exam_scopes import (
    can_manage_students,
    visible_class_ids,
    visible_grade_set,
)


def _require_semester(db: Session, semester_id: int) -> Semester:
    sem = db.get(Semester, semester_id)
    if sem is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到学期")
    return sem


def _require_exam(db: Session, exam_id: int) -> Exam:
    exam = db.get(Exam, exam_id)
    if exam is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到考试")
    return exam


def get_exam(db: Session, exam_id: int) -> Exam:
    """取一次考试;找不到 404。"""
    return _require_exam(db, exam_id)


def _exam_grades(db: Session, exam_id: int) -> list[int]:
    return sorted(
        db.scalars(
            select(ExamGrade.grade).where(ExamGrade.exam_id == exam_id)
        ).all()
    )


def _require_draft(exam: Exam) -> None:
    if exam.status != "草稿":
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"只有草稿状态的考试可以修改,当前状态为{exam.status}"
        )


def require_exam_not_archived(db: Session, exam_id: int) -> Exam:
    """归档后只读拦截(KW-65):已归档的考试一切写操作 403。

    各写服务(成绩、编排、监考、考试修改)在写函数入口调用本函数;
    考试不存在时 404,已归档时 403。
    """
    exam = _require_exam(db, exam_id)
    if exam.status == "已归档":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "考试已归档,只读,不可修改"
        )
    return exam


def require_exam_visible(db: Session, user: User, exam: Exam) -> None:
    """考试可见性拦截:教师只能看参试年级与本人可见年级有交集的考试。"""
    grade_set = visible_grade_set(db, user)
    if grade_set is None:
        return
    if not set(_exam_grades(db, exam.id)) & grade_set:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "无权查看该考试(参试年级不在你的可见年级范围内)"
        )


def _check_list_scope(db: Session, user: User, class_unit_id: int | None) -> None:
    """名单类列表显式筛班级越出可见范围时直接 403,不静默回空列表。"""
    if class_unit_id is None:
        return
    class_ids = visible_class_ids(db, user)
    if class_ids is not None and class_unit_id not in class_ids:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "无权查看该班级(不在你的可见班级范围内)"
        )


def to_exam_out(db: Session, exam: Exam) -> ExamOut:
    return ExamOut(
        id=exam.id,
        semester_id=exam.semester_id,
        name=exam.name,
        exam_type=exam.exam_type,
        grades=_exam_grades(db, exam.id),
        status=exam.status,
        description=exam.description,
        created_at=exam.created_at,
    )


def _subject_name_map(db: Session, subject_ids: set[int]) -> dict[int, str]:
    if not subject_ids:
        return {}
    rows = db.scalars(
        select(Subject).where(Subject.id.in_(subject_ids))
    ).all()
    return {s.id: s.name for s in rows}


def _exam_subject_outs(db: Session, exam_id: int) -> list[ExamSubjectOut]:
    rows = db.scalars(
        select(ExamSubject)
        .where(ExamSubject.exam_id == exam_id)
        .order_by(ExamSubject.exam_date, ExamSubject.start_time)
    ).all()
    names = _subject_name_map(db, {r.subject_id for r in rows})
    return [
        ExamSubjectOut(
            subject_id=r.subject_id,
            subject_name=names.get(r.subject_id, ""),
            exam_date=r.exam_date,
            start_time=r.start_time,
            end_time=r.end_time,
            full_score=r.full_score,
        )
        for r in rows
    ]


def to_exam_detail(db: Session, exam: Exam) -> ExamDetailOut:
    out = to_exam_out(db, exam)
    count = db.scalar(
        select(func.count())
        .select_from(ExamParticipant)
        .where(ExamParticipant.exam_id == exam.id)
    ) or 0
    return ExamDetailOut(
        **out.model_dump(),
        subjects=_exam_subject_outs(db, exam.id),
        participant_count=count,
    )


# ── 考试列表/创建/修改 ──────────────────────────────
def list_exams(
    db: Session,
    user: User,
    semester_id: int | None = None,
    status_filter: str | None = None,
    q: str | None = None,
) -> tuple[list[Exam], int]:
    grade_set = visible_grade_set(db, user)
    stmt = select(Exam)
    if semester_id is not None:
        _require_semester(db, semester_id)
        stmt = stmt.where(Exam.semester_id == semester_id)
    if status_filter:
        if status_filter not in EXAM_STATUSES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "考试状态无效")
        stmt = stmt.where(Exam.status == status_filter)
    if q:
        stmt = stmt.where(Exam.name.contains(q))
    if grade_set is not None:
        if not grade_set:
            return [], 0
        visible_exam_ids = select(ExamGrade.exam_id).where(
            ExamGrade.grade.in_(grade_set)
        )
        stmt = stmt.where(Exam.id.in_(visible_exam_ids))
    rows = db.scalars(stmt.order_by(Exam.created_at.desc(), Exam.id.desc())).all()
    return list(rows), len(rows)


def create_exam(
    db: Session,
    user: User,
    semester_id: int,
    name: str,
    exam_type: str,
    grades: list[int],
    description: str | None,
) -> Exam:
    _require_semester(db, semester_id)
    if exam_type not in EXAM_TYPES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"考试类型只能是{ '、'.join(EXAM_TYPES) }",
        )
    if not grades:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "参试年级至少选一个")
    exam = Exam(
        semester_id=semester_id,
        name=name,
        exam_type=exam_type,
        description=description,
        status="草稿",
        created_by=user.id,
    )
    db.add(exam)
    db.flush()
    for g in sorted(set(grades)):
        db.add(ExamGrade(exam_id=exam.id, grade=g))
    db.add(ExamStatusChange(
        exam_id=exam.id, from_status=None, to_status="草稿",
        changed_by=user.id, note="新建考试",
    ))
    db.commit()
    db.refresh(exam)
    return exam


def update_exam(
    db: Session,
    exam: Exam,
    name: str | None,
    exam_type: str | None,
    grades: list[int] | None,
    description: str | None,
) -> Exam:
    require_exam_not_archived(db, exam.id)
    _require_draft(exam)
    if exam_type is not None and exam_type not in EXAM_TYPES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"考试类型只能是{ '、'.join(EXAM_TYPES) }",
        )
    if name is not None:
        exam.name = name
    if exam_type is not None:
        exam.exam_type = exam_type
    if description is not None:
        exam.description = description
    if grades is not None:
        if not grades:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "参试年级至少选一个")
        db.query(ExamGrade).filter(ExamGrade.exam_id == exam.id).delete()
        for g in sorted(set(grades)):
            db.add(ExamGrade(exam_id=exam.id, grade=g))
    db.commit()
    db.refresh(exam)
    return exam


# ── 状态流转(KW-11) ──────────────────────────────
def change_exam_status(
    db: Session, user: User, exam: Exam, to_status: str, note: str | None
) -> Exam:
    """只允许按顺序前进一位;回退到任一更早状态只允许 admin/director。

    同一状态、跳级前进、未知状态一律 400;无回退权限 403。
    每次流转写一条 ExamStatusChange 记录。
    """
    if to_status not in EXAM_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "考试状态无效")
    cur_idx = EXAM_STATUS_ORDER.index(exam.status)
    new_idx = EXAM_STATUS_ORDER.index(to_status)
    if new_idx == cur_idx:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "考试状态没有变化")
    if new_idx < cur_idx:
        names = user.role_names
        if Role.admin.value not in names and Role.director.value not in names:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "只有管理员或教务可以将考试状态回退"
            )
    elif new_idx != cur_idx + 1:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"考试状态只能按顺序流转,当前{exam.status}下一步只能是{EXAM_STATUS_ORDER[cur_idx + 1]}",
        )
    old = exam.status
    exam.status = to_status
    db.add(ExamStatusChange(
        exam_id=exam.id, from_status=old, to_status=to_status,
        changed_by=user.id, note=note,
    ))
    db.commit()
    db.refresh(exam)
    return exam


# ── 复制(KW-12) ──────────────────────────────
def copy_exam(
    db: Session, user: User, exam: Exam, name: str, semester_id: int | None
) -> Exam:
    """复制科目、日程结构与编排规则(科目、分值、日程);参试名单与命题信息不复制。

    目标学期与源考试不同学期时,科目按名称在目标学期匹配,匹配不上的科目不复制。
    """
    target_semester_id = semester_id if semester_id is not None else exam.semester_id
    _require_semester(db, target_semester_id)
    grades = _exam_grades(db, exam.id)
    new_exam = create_exam(
        db, user, target_semester_id, name, exam.exam_type, grades, exam.description,
    )
    src_subjects = db.scalars(
        select(ExamSubject).where(ExamSubject.exam_id == exam.id)
    ).all()
    if target_semester_id == exam.semester_id:
        name_to_id: dict[str, int] = {}
        for r in src_subjects:
            db.add(ExamSubject(
                exam_id=new_exam.id,
                subject_id=r.subject_id,
                exam_date=r.exam_date,
                start_time=r.start_time,
                end_time=r.end_time,
                full_score=r.full_score,
            ))
    else:
        target_subjects = {
            s.name: s.id
            for s in db.scalars(
                select(Subject).where(Subject.semester_id == target_semester_id)
            ).all()
        }
        src_names = _subject_name_map(db, {r.subject_id for r in src_subjects})
        for r in src_subjects:
            target_id = target_subjects.get(src_names.get(r.subject_id, ""))
            if target_id is None:
                continue
            db.add(ExamSubject(
                exam_id=new_exam.id,
                subject_id=target_id,
                exam_date=r.exam_date,
                start_time=r.start_time,
                end_time=r.end_time,
                full_score=r.full_score,
            ))
    db.commit()
    db.refresh(new_exam)
    return new_exam


# ── 考试科目与日程(KW-09) ──────────────────────────────
def upsert_exam_subjects(
    db: Session, exam: Exam, subjects: list[dict]
) -> list[ExamSubjectOut]:
    """批量 upsert 考试科目与日程;仅草稿可改,已存在科目更新,新科目新增。

    不删除未出现在本次清单里的科目(只做 upsert,不做全量替换)。
    """
    _require_draft(exam)
    _require_semester(db, exam.semester_id)
    subject_ids = {s["subject_id"] for s in subjects}
    valid = {
        s.id
        for s in db.scalars(
            select(Subject).where(
                Subject.semester_id == exam.semester_id,
                Subject.id.in_(subject_ids),
            )
        ).all()
    }
    if len(valid) != len(subject_ids):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "科目清单含无效或跨学期的科目")
    for s in subjects:
        if s["end_time"] <= s["start_time"]:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "考试结束时间必须晚于开始时间")
    saved = {
        r.subject_id: r
        for r in db.scalars(
            select(ExamSubject).where(
                ExamSubject.exam_id == exam.id,
                ExamSubject.subject_id.in_(subject_ids),
            )
        ).all()
    }
    for s in subjects:
        row = saved.get(s["subject_id"])
        if row is None:
            row = ExamSubject(exam_id=exam.id, subject_id=s["subject_id"])
            db.add(row)
        row.exam_date = s["exam_date"]
        row.start_time = s["start_time"]
        row.end_time = s["end_time"]
        row.full_score = s.get("full_score")
    db.commit()
    return _exam_subject_outs(db, exam.id)


def _times_overlap(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end


def check_schedule(db: Session, exam: Exam) -> list[ScheduleConflictOut]:
    """日程冲突检查,只提示不阻断。

    1) 科间冲突:同一学生同一时段有两科(同日时间重叠即算冲突,参试年级相同)。
    2) 与已发布课表冲突:考试日对应星期,参试年级班级在已发布课表该节次有课,
       且节次墙钟时间与考试时间重叠。无已发布课表、或取不到节次时间时只查科间冲突。
    """
    subjects = _exam_subject_outs(db, exam.id)
    conflicts: list[ScheduleConflictOut] = []
    seen: set[tuple[int, str]] = set()

    def _add(subject_id: int, subject_name: str, reason: str) -> None:
        key = (subject_id, reason)
        if key in seen:
            return
        seen.add(key)
        conflicts.append(ScheduleConflictOut(
            subject_id=subject_id, subject_name=subject_name, reason=reason,
        ))

    # 1) 科间冲突
    for i, a in enumerate(subjects):
        for b in subjects[i + 1:]:
            if a.exam_date != b.exam_date:
                continue
            if not _times_overlap(a.start_time, a.end_time, b.start_time, b.end_time):
                continue
            day = a.exam_date.isoformat()
            _add(a.subject_id, a.subject_name,
                 f"与{b.subject_name}考试时间重叠({day} {a.start_time.strftime('%H:%M')}-{a.end_time.strftime('%H:%M')})")
            _add(b.subject_id, b.subject_name,
                 f"与{a.subject_name}考试时间重叠({day} {b.start_time.strftime('%H:%M')}-{b.end_time.strftime('%H:%M')})")

    # 2) 与已发布课表冲突
    tt = db.scalar(
        select(Timetable).where(
            Timetable.semester_id == exam.semester_id,
            Timetable.status == TimetableStatus.published.value,
        )
    )
    if tt is None or not subjects:
        return conflicts
    grades = _exam_grades(db, exam.id)
    classes = db.scalars(
        select(ClassUnit).where(
            ClassUnit.semester_id == exam.semester_id,
            ClassUnit.grade.in_(grades),
        )
    ).all()
    if not classes:
        return conflicts
    class_ids = {c.id for c in classes}
    class_map = {c.id: c for c in classes}
    # 节次墙钟时间:先取班级节次表,缺省取学期默认节次表。
    default_table = db.scalar(
        select(PeriodTable).where(
            PeriodTable.semester_id == exam.semester_id,
            PeriodTable.is_default.is_(True),
        )
    )
    period_map: dict[tuple[int, int, int], Period] = {}
    table_ids = {c.period_table_id for c in classes if c.period_table_id}
    if default_table is not None:
        table_ids.add(default_table.id)
    if table_ids:
        for p in db.scalars(
            select(Period).where(Period.period_table_id.in_(table_ids))
        ).all():
            period_map[(p.period_table_id, p.weekday, p.period_no)] = p
    entries = db.execute(
        select(
            ScheduleEntry.weekday,
            ScheduleEntry.period_no,
            SchedulingUnitMember.class_unit_id,
            CourseAssignment.subject_id,
        )
        .join(
            CourseAssignment,
            CourseAssignment.id == ScheduleEntry.course_assignment_id,
        )
        .join(
            SchedulingUnitMember,
            SchedulingUnitMember.scheduling_unit_id
            == CourseAssignment.scheduling_unit_id,
        )
        .where(
            ScheduleEntry.timetable_id == tt.id,
            SchedulingUnitMember.class_unit_id.in_(class_ids),
        )
    ).all()
    course_names = _subject_name_map(
        db, {row[3] for row in entries if row[3] is not None}
    )
    for subj in subjects:
        weekday = subj.exam_date.isoweekday()  # 1=周一
        for entry_weekday, period_no, class_unit_id, course_subject_id in entries:
            if entry_weekday != weekday:
                continue
            cls = class_map.get(class_unit_id)
            if cls is None:
                continue
            table_id = cls.period_table_id or (
                default_table.id if default_table is not None else None
            )
            if table_id is None:
                continue
            period = period_map.get((table_id, weekday, period_no))
            if period is None or period.start_time is None or period.end_time is None:
                continue
            if not _times_overlap(
                subj.start_time, subj.end_time, period.start_time, period.end_time
            ):
                continue
            course_name = course_names.get(course_subject_id, "")
            _add(subj.subject_id, subj.subject_name,
                 f"与已发布课表冲突:{cls.name}班周{weekday}第{period_no}节"
                 f"({course_name})与本次{subj.subject_name}考试时间重叠")
    return conflicts


# ── 参试名单(KW-10) ──────────────────────────────
def _participant_out(db: Session, p: ExamParticipant) -> ParticipantOut:
    student = db.get(Student, p.student_id)
    cls = db.get(ClassUnit, p.class_unit_id)
    return ParticipantOut(
        id=p.id,
        exam_id=p.exam_id,
        student_id=p.student_id,
        student_no=student.student_no if student else "",
        student_name=student.name if student else "",
        class_unit_id=p.class_unit_id,
        class_name=cls.name if cls else "",
        grade=cls.grade if cls else None,
        status=p.status,
        note=p.note,
    )


def list_participants(
    db: Session,
    user: User,
    exam: Exam,
    class_unit_id: int | None = None,
    status_filter: str | None = None,
    q: str | None = None,
) -> tuple[list[ParticipantOut], int]:
    require_exam_visible(db, user, exam)
    _check_list_scope(db, user, class_unit_id)
    class_ids = visible_class_ids(db, user)
    stmt = select(ExamParticipant).where(ExamParticipant.exam_id == exam.id)
    if class_ids is not None:
        stmt = stmt.where(ExamParticipant.class_unit_id.in_(class_ids))
    if class_unit_id is not None:
        stmt = stmt.where(ExamParticipant.class_unit_id == class_unit_id)
    if status_filter:
        if status_filter not in PARTICIPANT_STATUSES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "参试状态只能是正常、缺考或免考")
        stmt = stmt.where(ExamParticipant.status == status_filter)
    rows = db.scalars(stmt.order_by(ExamParticipant.id)).all()
    out = [_participant_out(db, p) for p in rows]
    if q:
        out = [o for o in out if q in o.student_name or q in o.student_no]
    return out, len(out)


def generate_participants(db: Session, exam: Exam) -> tuple[int, int]:
    """按参试年级从在读学生生成参试名单;已在名单里的跳过,重复生成不产生重复名单。"""
    grades = _exam_grades(db, exam.id)
    students = db.scalars(
        select(Student)
        .join(ClassUnit, ClassUnit.id == Student.class_unit_id)
        .where(
            Student.semester_id == exam.semester_id,
            ClassUnit.grade.in_(grades),
            Student.status == "在读",
        )
    ).all()
    existing = {
        sid
        for (sid,) in db.execute(
            select(ExamParticipant.student_id).where(
                ExamParticipant.exam_id == exam.id
            )
        ).all()
    }
    created = 0
    skipped = 0
    for s in students:
        if s.id in existing:
            skipped += 1
            continue
        db.add(ExamParticipant(
            exam_id=exam.id,
            student_id=s.id,
            class_unit_id=s.class_unit_id,
            status="正常",
        ))
        created += 1
    db.commit()
    return created, skipped


def add_participant(
    db: Session, exam: Exam, student_id: int, note: str | None
) -> ExamParticipant:
    """个别增补:借读、休学、特长生等不在自动生成范围的学生也可加入。"""
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到学生")
    if student.semester_id != exam.semester_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "学生不属于本考试学期")
    dup = db.scalar(
        select(ExamParticipant.id).where(
            ExamParticipant.exam_id == exam.id,
            ExamParticipant.student_id == student_id,
        )
    )
    if dup is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "该学生已在参试名单中")
    row = ExamParticipant(
        exam_id=exam.id,
        student_id=student.id,
        class_unit_id=student.class_unit_id,
        status="正常",
        note=note,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_participant(
    db: Session, exam: Exam, pid: int, status_value: str | None, note: str | None
) -> ExamParticipant:
    row = db.get(ExamParticipant, pid)
    if row is None or row.exam_id != exam.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到参试学生")
    if status_value is not None:
        if status_value not in PARTICIPANT_STATUSES:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "参试状态只能是正常、缺考或免考"
            )
        row.status = status_value
    if note is not None:
        row.note = note
    db.commit()
    db.refresh(row)
    return row


def delete_participant(db: Session, exam: Exam, pid: int) -> None:
    row = db.get(ExamParticipant, pid)
    if row is None or row.exam_id != exam.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到参试学生")
    db.delete(row)
    db.commit()


# ── 命题信息(KW-13) ──────────────────────────────
def list_paper_info(db: Session, exam: Exam) -> list[PaperInfoOut]:
    rows = db.scalars(
        select(ExamPaperInfo)
        .where(ExamPaperInfo.exam_id == exam.id)
        .order_by(ExamPaperInfo.subject_id)
    ).all()
    names = _subject_name_map(db, {r.subject_id for r in rows})
    teacher_ids = {
        t for r in rows for t in (r.setter_teacher_id, r.reviewer_teacher_id)
        if t is not None
    }
    teacher_names: dict[int, str] = {}
    if teacher_ids:
        teacher_names = {
            t.id: t.name
            for t in db.scalars(select(Teacher).where(Teacher.id.in_(teacher_ids))).all()
        }
    return [
        PaperInfoOut(
            subject_id=r.subject_id,
            subject_name=names.get(r.subject_id, ""),
            setter_teacher_id=r.setter_teacher_id,
            setter_teacher_name=teacher_names.get(r.setter_teacher_id),
            reviewer_teacher_id=r.reviewer_teacher_id,
            reviewer_teacher_name=teacher_names.get(r.reviewer_teacher_id),
            paper_count=r.paper_count,
        )
        for r in rows
    ]


def upsert_paper_info(db: Session, exam: Exam, items: list[dict]) -> list[PaperInfoOut]:
    """批量 upsert 命题信息;只登记信息,不做题库组卷。"""
    subject_ids = {i["subject_id"] for i in items}
    valid_subjects = {
        s.id
        for s in db.scalars(
            select(Subject).where(
                Subject.semester_id == exam.semester_id,
                Subject.id.in_(subject_ids),
            )
        ).all()
    }
    if len(valid_subjects) != len(subject_ids):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "科目清单含无效或跨学期的科目")
    teacher_ids = {
        t for i in items
        for t in (i.get("setter_teacher_id"), i.get("reviewer_teacher_id"))
        if t is not None
    }
    if teacher_ids:
        valid_teachers = {
            t.id
            for t in db.scalars(select(Teacher).where(Teacher.id.in_(teacher_ids))).all()
        }
        if len(valid_teachers) != len(teacher_ids):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "命题或审题教师不存在")
    saved = {
        r.subject_id: r
        for r in db.scalars(
            select(ExamPaperInfo).where(
                ExamPaperInfo.exam_id == exam.id,
                ExamPaperInfo.subject_id.in_(subject_ids),
            )
        ).all()
    }
    for i in items:
        row = saved.get(i["subject_id"])
        if row is None:
            row = ExamPaperInfo(exam_id=exam.id, subject_id=i["subject_id"])
            db.add(row)
        row.setter_teacher_id = i.get("setter_teacher_id")
        row.reviewer_teacher_id = i.get("reviewer_teacher_id")
        row.paper_count = i.get("paper_count")
    db.commit()
    return list_paper_info(db, exam)


# ── 特殊考生安排(KW-14) ──────────────────────────────
def _arrangement_out(db: Session, r: ExamSpecialArrangement) -> SpecialArrangementOut:
    student = db.get(Student, r.student_id)
    cls = db.get(ClassUnit, student.class_unit_id) if student else None
    return SpecialArrangementOut(
        id=r.id,
        exam_id=r.exam_id,
        student_id=r.student_id,
        student_no=student.student_no if student else "",
        student_name=student.name if student else "",
        class_unit_id=student.class_unit_id if student else None,
        class_name=cls.name if cls else "",
        arrangement_type=r.arrangement_type,
        detail=r.detail,
        status=r.status,
    )


def list_special_arrangements(
    db: Session, user: User, exam: Exam
) -> list[SpecialArrangementOut]:
    """特殊考生安排读接口:教务与相关监考可见;教师只看本人可见班级的学生。

    本批尚未有监考安排数据(KW-23 后续批次),先按可见班级过滤;
    监考安排落地后,相关监考教师的可见范围由其监考班级决定。
    """
    require_exam_visible(db, user, exam)
    class_ids = visible_class_ids(db, user)
    rows = db.scalars(
        select(ExamSpecialArrangement)
        .where(ExamSpecialArrangement.exam_id == exam.id)
        .order_by(ExamSpecialArrangement.id)
    ).all()
    out = []
    for r in rows:
        student = db.get(Student, r.student_id)
        if class_ids is not None:
            if student is None or student.class_unit_id not in class_ids:
                continue
        out.append(_arrangement_out(db, r))
    return out


def create_special_arrangement(
    db: Session, exam: Exam, student_id: int, arrangement_type: str, detail: str | None
) -> ExamSpecialArrangement:
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到学生")
    if student.semester_id != exam.semester_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "学生不属于本考试学期")
    if arrangement_type not in ARRANGEMENT_TYPES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"安排类型只能是{ '、'.join(ARRANGEMENT_TYPES) }",
        )
    dup = db.scalar(
        select(ExamSpecialArrangement.id).where(
            ExamSpecialArrangement.exam_id == exam.id,
            ExamSpecialArrangement.student_id == student_id,
            ExamSpecialArrangement.arrangement_type == arrangement_type,
        )
    )
    if dup is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "该学生已有同类特殊安排")
    row = ExamSpecialArrangement(
        exam_id=exam.id,
        student_id=student_id,
        arrangement_type=arrangement_type,
        detail=detail,
        status="已登记",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_special_arrangement(
    db: Session,
    exam: Exam,
    sid: int,
    arrangement_type: str | None,
    detail: str | None,
    status_value: str | None,
) -> ExamSpecialArrangement:
    row = db.get(ExamSpecialArrangement, sid)
    if row is None or row.exam_id != exam.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到特殊考生安排")
    if arrangement_type is not None:
        if arrangement_type not in ARRANGEMENT_TYPES:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"安排类型只能是{ '、'.join(ARRANGEMENT_TYPES) }",
            )
        row.arrangement_type = arrangement_type
    if detail is not None:
        row.detail = detail
    if status_value is not None:
        if status_value not in ARRANGEMENT_STATUSES:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "安排状态只能是已登记或已安排"
            )
        row.status = status_value
    db.commit()
    db.refresh(row)
    return row


def delete_special_arrangement(db: Session, exam: Exam, sid: int) -> None:
    row = db.get(ExamSpecialArrangement, sid)
    if row is None or row.exam_id != exam.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到特殊考生安排")
    db.delete(row)
    db.commit()


# 供 API 层复用的组装函数(公开别名)。
def exam_subject_outs(db: Session, exam_id: int) -> list[ExamSubjectOut]:
    return _exam_subject_outs(db, exam_id)


def participant_out(db: Session, p: ExamParticipant) -> ParticipantOut:
    return _participant_out(db, p)


def arrangement_out(db: Session, r: ExamSpecialArrangement) -> SpecialArrangementOut:
    return _arrangement_out(db, r)


# 供 API 层复用的导出(权限把关与可见性检查共用 can_manage_students)。
__all__ = [
    "can_manage_students",
    "require_exam_not_archived",
    "list_exams",
    "create_exam",
    "update_exam",
    "change_exam_status",
    "copy_exam",
    "upsert_exam_subjects",
    "check_schedule",
    "list_participants",
    "generate_participants",
    "add_participant",
    "update_participant",
    "delete_participant",
    "list_paper_info",
    "upsert_paper_info",
    "list_special_arrangements",
    "create_special_arrangement",
    "update_special_arrangement",
    "delete_special_arrangement",
    "to_exam_out",
    "to_exam_detail",
    "require_exam_visible",
]
