"""阅卷与成绩录入服务(KW-30~35):阅卷分工、成绩设置、大题小分、成绩录入/导入/提交、进度看板、补考。

权限口径:
- 阅卷分工、成绩设置、补考场次只允许 admin/director。
- 成绩录入/导入/提交:任课教师只限本人所教班级+本科目,按配课数据校验
  (CourseAssignment -> AssignmentTeacher -> SchedulingUnitMember -> ClassUnit,
  与 exam_scopes 任教班级同一溯源口径,再按本科目收紧);admin/director 不限。
- 读接口按可见范围过滤:教师只看本人所教班级+本科目的成绩。
- 任课教师取法:同一教师在本考试学期内的配课;跨学期配课不算入本次考试。

成绩口径:
- 满分取该科本次考试 full_score,未设则取科目分值设置,都没有取 100。
- 超满分或分数小于 0 即 422;itemized 模式下总分须等于小分之和,否则 422。
- 缺考 score 为空;作弊按 cheating_score_mode 记 0 分或空;
  免考 score 为空;缺考是否计入统计由 absent_counts 控制,默认不计入,
  免考永不计入统计。
- 补考处理口径 makeup_mode 只存配置:separate 单独标注并列保存;
  override 覆盖、max 取高只存配置,暂不改变正考分,等学校定了再实现。
"""

import io

from fastapi import HTTPException, status
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.assignment import (
    AssignmentTeacher,
    CourseAssignment,
    SchedulingUnitMember,
)
from app.models.basedata import ClassUnit, Subject, Teacher
from app.models.exam import Exam, ExamParticipant, ExamSubject
from app.models.exam_foundation import Student, SubjectScoreSetting
from app.models.exam_scores import (
    CHEATING_SCORE_MODES,
    ENTRY_MODES,
    MAKEUP_MODES,
    MAKEUP_SCORE_STATUSES,
    MARKING_ROLES,
    MARKING_SCOPE_TYPES,
    SCORE_STATUSES,
    ExamMakeup,
    ExamMakeupScore,
    ExamMarkingAssignment,
    ExamScore,
    ExamScoreItem,
    ExamScoreItemScore,
    ExamScoreSetting,
)
from app.models.user import Role, User
from app.services.exam import get_exam, require_exam_not_archived
from app.services.exam_scopes import can_manage_students, visible_class_ids

HEADER_ROWS = 3  # 模板固定三列表头:栏名 + 说明 + 范例,第 4 行起读数据

# 成绩导入模板栏位:(栏名, 说明, 范例)
SCORE_TEMPLATE_COLUMNS = [
    ("学号", "必填,须为本次考试参试学生", "20260101"),
    ("姓名", "仅供核对,导入时以学号为准", "张三"),
    ("班级", "仅供核对", "701"),
    ("成绩", "正常必填,0 到满分之间;缺考/免考留空", "88"),
    ("状态", "选填:正常/缺考/作弊/免考,默认正常", "正常"),
]


def _is_manager(db: Session, user: User) -> bool:
    return can_manage_students(db, user)


def _require_manager(db: Session, user: User) -> None:
    if not _is_manager(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "权限不足")


def _teacher_ids(db: Session, user: User) -> set[int]:
    rows = db.scalars(select(Teacher.id).where(Teacher.user_id == user.id)).all()
    return set(rows)


def teaching_pairs(db: Session, user: User, semester_id: int) -> set[tuple[int, int]]:
    """该账号在本考试学期内任教的 (班级 id, 科目 id) 集合。

    配课溯源:CourseAssignment(subject_id) -> AssignmentTeacher(teacher_id)
    -> SchedulingUnitMember(class_unit_id),与 exam_scopes 任教班级同一口径。
    """
    teacher_ids = _teacher_ids(db, user)
    if not teacher_ids:
        return set()
    rows = db.execute(
        select(SchedulingUnitMember.class_unit_id, CourseAssignment.subject_id)
        .join(
            CourseAssignment,
            CourseAssignment.scheduling_unit_id
            == SchedulingUnitMember.scheduling_unit_id,
        )
        .join(
            AssignmentTeacher,
            AssignmentTeacher.course_assignment_id == CourseAssignment.id,
        )
        .where(
            AssignmentTeacher.teacher_id.in_(teacher_ids),
            CourseAssignment.semester_id == semester_id,
        )
    ).all()
    return {(class_id, subject_id) for class_id, subject_id in rows}


def _require_exam_subject(db: Session, exam: Exam, subject_id: int) -> ExamSubject:
    row = db.scalar(
        select(ExamSubject).where(
            ExamSubject.exam_id == exam.id,
            ExamSubject.subject_id == subject_id,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到该考试科目")
    return row


def full_score_for(db: Session, exam: Exam, subject_id: int) -> float:
    """满分:本次考试该科 full_score,未设取科目分值设置,都没有取 100。"""
    row = db.scalar(
        select(ExamSubject).where(
            ExamSubject.exam_id == exam.id,
            ExamSubject.subject_id == subject_id,
        )
    )
    if row is not None and row.full_score is not None:
        return row.full_score
    setting = db.scalar(
        select(SubjectScoreSetting).where(
            SubjectScoreSetting.semester_id == exam.semester_id,
            SubjectScoreSetting.subject_id == subject_id,
        )
    )
    if setting is not None:
        return setting.full_score
    return 100.0


def _require_can_enter(
    db: Session, user: User, exam: Exam, subject_id: int,
    class_unit_ids: set[int] | None = None,
) -> None:
    """成绩写权限:教务不限;任课教师须教本科目,且目标班级须为本人所教班级。

    class_unit_ids 为空表示只校验"是否教本科目"(如导入前置校验)。
    """
    if _is_manager(db, user):
        return
    names = user.role_names
    if Role.teacher.value not in names:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "只有任课教师与教务可以录入成绩")
    pairs = teaching_pairs(db, user, exam.semester_id)
    own_classes = {c for c, s in pairs if s == subject_id}
    if not own_classes:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "你未任教该科目,无权录入该科成绩"
        )
    if class_unit_ids:
        outside = class_unit_ids - own_classes
        if outside:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "只能录入本人所教班级的成绩"
            )


def _check_score_range(score: float | None, full: float) -> None:
    if score is None:
        return
    if score < 0 or score > full:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"分数须在 0 到满分 {full:g} 之间",
        )


def _effective_score(
    entry_status: str, score: float | None, settings: ExamScoreSetting
) -> float | None:
    """按状态折算最终入库分数:缺考/免考为空;作弊按配置记 0 或空。"""
    if entry_status in ("缺考", "免考"):
        return None
    if entry_status == "作弊":
        return 0.0 if settings.cheating_score_mode == "zero" else None
    return score


def get_settings(db: Session, exam: Exam) -> ExamScoreSetting:
    """取成绩设置;未设过回传默认值(不入库)。"""
    row = db.scalar(
        select(ExamScoreSetting).where(ExamScoreSetting.exam_id == exam.id)
    )
    if row is not None:
        return row
    # 未设过回传默认值(不入库);须显式填默认值,列 default 只在 INSERT 时生效。
    return ExamScoreSetting(
        exam_id=exam.id, entry_mode="total_only", makeup_mode="separate",
        cheating_score_mode="zero", absent_counts=False, score_deadline=None,
    )


def upsert_settings(
    db: Session, exam: Exam, entry_mode: str, makeup_mode: str,
    cheating_score_mode: str, absent_counts: bool, score_deadline,
) -> ExamScoreSetting:
    require_exam_not_archived(db, exam.id)
    if entry_mode not in ENTRY_MODES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "录入模式只能是只录总分或录大题小分")
    if makeup_mode not in MAKEUP_MODES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "补考处理口径无效")
    if cheating_score_mode not in CHEATING_SCORE_MODES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "作弊记分方式无效")
    row = db.scalar(
        select(ExamScoreSetting).where(ExamScoreSetting.exam_id == exam.id)
    )
    if row is None:
        row = ExamScoreSetting(exam_id=exam.id)
        db.add(row)
    row.entry_mode = entry_mode
    row.makeup_mode = makeup_mode
    row.cheating_score_mode = cheating_score_mode
    row.absent_counts = absent_counts
    row.score_deadline = score_deadline
    db.commit()
    db.refresh(row)
    return row


def settings_out(exam: Exam, row: ExamScoreSetting) -> dict:
    return {
        "exam_id": exam.id,
        "entry_mode": row.entry_mode,
        "makeup_mode": row.makeup_mode,
        "cheating_score_mode": row.cheating_score_mode,
        "absent_counts": row.absent_counts,
        "score_deadline": (
            row.score_deadline.isoformat() if row.score_deadline else None
        ),
    }


# ── 阅卷分工(KW-30) ──────────────────────────────
def list_marking_assignments(
    db: Session, exam: Exam, subject_id: int | None
) -> tuple[list[dict], int]:
    stmt = select(ExamMarkingAssignment).where(
        ExamMarkingAssignment.exam_id == exam.id
    )
    if subject_id is not None:
        _require_exam_subject(db, exam, subject_id)
        stmt = stmt.where(ExamMarkingAssignment.subject_id == subject_id)
    rows = db.scalars(stmt.order_by(ExamMarkingAssignment.id)).all()
    subject_names = {
        s.id: s.name
        for s in db.scalars(
            select(Subject).where(
                Subject.id.in_({r.subject_id for r in rows})
            )
        ).all()
    } if rows else {}
    teacher_names = {
        t.id: t.name
        for t in db.scalars(
            select(Teacher).where(
                Teacher.id.in_({r.teacher_id for r in rows})
            )
        ).all()
    } if rows else {}
    items = [
        {
            "id": r.id,
            "exam_id": r.exam_id,
            "subject_id": r.subject_id,
            "subject_name": subject_names.get(r.subject_id, ""),
            "teacher_id": r.teacher_id,
            "teacher_name": teacher_names.get(r.teacher_id, ""),
            "role": r.role,
            "scope_type": r.scope_type,
            "scope_value": r.scope_value,
        }
        for r in rows
    ]
    return items, len(items)


def create_marking_assignment(
    db: Session, exam: Exam, subject_id: int, teacher_id: int,
    role: str, scope_type: str, scope_value: str | None,
) -> ExamMarkingAssignment:
    require_exam_not_archived(db, exam.id)
    _require_exam_subject(db, exam, subject_id)
    if db.get(Teacher, teacher_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到教师")
    if role not in MARKING_ROLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "阅卷角色只能是阅卷组长或阅卷教师")
    if scope_type not in MARKING_SCOPE_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "分工方式只能是按题或按班")
    dup = db.scalar(
        select(ExamMarkingAssignment.id).where(
            ExamMarkingAssignment.exam_id == exam.id,
            ExamMarkingAssignment.subject_id == subject_id,
            ExamMarkingAssignment.teacher_id == teacher_id,
        )
    )
    if dup is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "该教师已登记本科目阅卷分工")
    row = ExamMarkingAssignment(
        exam_id=exam.id, subject_id=subject_id, teacher_id=teacher_id,
        role=role, scope_type=scope_type, scope_value=scope_value,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_marking_assignment(db: Session, exam: Exam, mid: int) -> None:
    require_exam_not_archived(db, exam.id)
    row = db.get(ExamMarkingAssignment, mid)
    if row is None or row.exam_id != exam.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到阅卷分工")
    db.delete(row)
    db.commit()


# ── 大题小分(KW-31) ──────────────────────────────
def list_score_items(
    db: Session, exam: Exam, subject_id: int
) -> tuple[list[ExamScoreItem], int]:
    _require_exam_subject(db, exam, subject_id)
    rows = db.scalars(
        select(ExamScoreItem).where(
            ExamScoreItem.exam_id == exam.id,
            ExamScoreItem.subject_id == subject_id,
        ).order_by(ExamScoreItem.sort_order, ExamScoreItem.id)
    ).all()
    return list(rows), len(rows)


def create_score_item(
    db: Session, exam: Exam, subject_id: int, name: str, max_score: float
) -> ExamScoreItem:
    require_exam_not_archived(db, exam.id)
    _require_exam_subject(db, exam, subject_id)
    dup = db.scalar(
        select(ExamScoreItem.id).where(
            ExamScoreItem.exam_id == exam.id,
            ExamScoreItem.subject_id == subject_id,
            ExamScoreItem.name == name,
        )
    )
    if dup is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "该科目已有同名大题")
    last_order = db.scalar(
        select(func.max(ExamScoreItem.sort_order)).where(
            ExamScoreItem.exam_id == exam.id,
            ExamScoreItem.subject_id == subject_id,
        )
    )
    row = ExamScoreItem(
        exam_id=exam.id, subject_id=subject_id, name=name,
        max_score=max_score, sort_order=(last_order or 0) + 1,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_score_item(db: Session, exam: Exam, iid: int) -> None:
    require_exam_not_archived(db, exam.id)
    row = db.get(ExamScoreItem, iid)
    if row is None or row.exam_id != exam.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到大题")
    used = db.scalar(
        select(func.count()).select_from(ExamScoreItemScore).where(
            ExamScoreItemScore.item_id == row.id
        )
    ) or 0
    if used:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "该大题已有录入数据,请先清除相关小分再删除"
        )
    db.delete(row)
    db.commit()


# ── 成绩录入(KW-31/33) ──────────────────────────────
def _participants_by_id(
    db: Session, exam: Exam
) -> dict[int, ExamParticipant]:
    rows = db.scalars(
        select(ExamParticipant).where(ExamParticipant.exam_id == exam.id)
    ).all()
    return {r.student_id: r for r in rows}


def _score_rows_by_student(
    db: Session, exam: Exam, subject_id: int
) -> dict[int, ExamScore]:
    rows = db.scalars(
        select(ExamScore).where(
            ExamScore.exam_id == exam.id,
            ExamScore.subject_id == subject_id,
        )
    ).all()
    return {r.student_id: r for r in rows}


def _item_scores_by_score_id(
    db: Session, score_ids: set[int]
) -> dict[int, list[ExamScoreItemScore]]:
    if not score_ids:
        return {}
    rows = db.scalars(
        select(ExamScoreItemScore).where(
            ExamScoreItemScore.score_id.in_(score_ids)
        )
    ).all()
    out: dict[int, list[ExamScoreItemScore]] = {}
    for r in rows:
        out.setdefault(r.score_id, []).append(r)
    return out


def list_scores(
    db: Session, user: User, exam: Exam,
    subject_id: int, class_unit_id: int | None = None,
    status_filter: str | None = None, q: str | None = None,
) -> tuple[list[dict], int]:
    """成绩列表:以参试名单为准,无成绩行也列出(分数为空、状态正常、未提交)。

    任课教师只看本人所教班级+本科目;显式筛的班级超出可见范围时 403。
    """
    _require_exam_subject(db, exam, subject_id)
    class_ids = visible_class_ids(db, user)
    if class_unit_id is not None:
        if class_ids is not None and class_unit_id not in class_ids:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "无权查看该班级(不在你的可见班级范围内)"
            )
    participants = _participants_by_id(db, exam)
    pairs = None
    if not _is_manager(db, user):
        pairs = teaching_pairs(db, user, exam.semester_id)
    student_ids = sorted(participants)
    students = {
        s.id: s
        for s in db.scalars(
            select(Student).where(Student.id.in_(student_ids))
        ).all()
    } if student_ids else {}
    _all_classes = db.scalars(select(ClassUnit)).all()
    class_names = {c.id: c.name for c in _all_classes}
    class_grades = {c.id: c.grade for c in _all_classes}
    score_rows = _score_rows_by_student(db, exam, subject_id)
    item_names = {
        it.id: it.name
        for it in db.scalars(
            select(ExamScoreItem).where(
                ExamScoreItem.exam_id == exam.id,
                ExamScoreItem.subject_id == subject_id,
            )
        ).all()
    }
    item_scores = _item_scores_by_score_id(
        db, {r.id for r in score_rows.values()}
    )
    items: list[dict] = []
    for sid in student_ids:
        p = participants[sid]
        if class_unit_id is not None and p.class_unit_id != class_unit_id:
            continue
        if pairs is not None and (p.class_unit_id, subject_id) not in pairs:
            continue
        student = students.get(sid)
        if q and student is not None:
            if q not in student.name and q not in student.student_no:
                continue
        row = score_rows.get(sid)
        entry_status = row.status if row else "正常"
        if status_filter is not None and entry_status != status_filter:
            continue
        sub_items = []
        if row is not None:
            for iv in sorted(
                item_scores.get(row.id, []), key=lambda x: x.item_id
            ):
                sub_items.append({
                    "item_id": iv.item_id,
                    "name": item_names.get(iv.item_id, ""),
                    "value": iv.value,
                })
        items.append({
            "id": row.id if row else None,
            "exam_id": exam.id,
            "subject_id": subject_id,
            "student_id": sid,
            "student_no": student.student_no if student else "",
            "student_name": student.name if student else "",
            "class_name": class_names.get(p.class_unit_id, ""),
            "grade": class_grades.get(p.class_unit_id),
            "score": row.score if row else None,
            "status": entry_status,
            "submitted": row.submitted if row else False,
            "items": sub_items,
        })
    items.sort(key=lambda x: (x["class_name"], x["student_no"]))
    return items, len(items)


def upsert_scores(
    db: Session, user: User, exam: Exam, subject_id: int,
    entries: list[dict],
) -> int:
    require_exam_not_archived(db, exam.id)
    """批量 upsert 成绩:先全量校验,通过后才写库(任一错误都不写)。

    校验顺序:科目存在 -> 写权限(任课只限本人班级科目) -> 逐条校验
    (学生须在参试名单、状态合法、分数范围、itemized 求和)。
    """
    _require_exam_subject(db, exam, subject_id)
    settings = get_settings(db, exam)
    full = full_score_for(db, exam, subject_id)
    participants = _participants_by_id(db, exam)
    # 写权限:目标班级集合先算出来,任课教师越权直接 403。
    target_classes = {
        participants[e["student_id"]].class_unit_id
        for e in entries
        if e["student_id"] in participants
    }
    _require_can_enter(db, user, exam, subject_id, target_classes)
    # KW-37 锁定检查:目标班级中任一已锁定即 403,只走改分审批。
    # 局部导入,避免与 exam_publish 服务互相导入。
    from app.services.exam_publish import require_scores_not_locked

    require_scores_not_locked(db, exam.id, subject_id, target_classes)
    items_by_id: dict[int, ExamScoreItem] = {}
    if settings.entry_mode == "itemized":
        items_by_id = {
            it.id: it
            for it in db.scalars(
                select(ExamScoreItem).where(
                    ExamScoreItem.exam_id == exam.id,
                    ExamScoreItem.subject_id == subject_id,
                )
            ).all()
        }
    # ── 全量校验(不写库) ──
    normalized: list[dict] = []
    for e in entries:
        student_id = e["student_id"]
        if student_id not in participants:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"学生 id {student_id} 不在本次考试参试名单中",
            )
        entry_status = e.get("status") or "正常"
        if entry_status not in SCORE_STATUSES:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"成绩状态只能是正常、缺考、作弊或免考",
            )
        raw_score = e.get("score")
        raw_items = e.get("items") or []
        if entry_status in ("缺考", "免考", "作弊"):
            effective = _effective_score(entry_status, raw_score, settings)
            normalized.append({
                "student_id": student_id, "status": entry_status,
                "score": effective, "items": [],
            })
            continue
        # 正常
        if settings.entry_mode == "itemized" and raw_items:
            seen_items: set[int] = set()
            total = 0.0
            for iv in raw_items:
                item = items_by_id.get(iv["item_id"])
                if item is None:
                    raise HTTPException(
                        status.HTTP_422_UNPROCESSABLE_ENTITY,
                        f"大题 id {iv['item_id']} 不存在",
                    )
                if iv["item_id"] in seen_items:
                    raise HTTPException(
                        status.HTTP_422_UNPROCESSABLE_ENTITY,
                        f"大题「{item.name}」重复录入",
                    )
                seen_items.add(iv["item_id"])
                if iv["value"] < 0 or iv["value"] > item.max_score:
                    raise HTTPException(
                        status.HTTP_422_UNPROCESSABLE_ENTITY,
                        f"大题「{item.name}」小分须在 0 到 {item.max_score:g} 之间",
                    )
                total += iv["value"]
            if raw_score is not None and abs(raw_score - total) > 1e-6:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"总分须等于小分之和({total:g}),当前总分 {raw_score:g}",
                )
            _check_score_range(total, full)
            normalized.append({
                "student_id": student_id, "status": entry_status,
                "score": total, "items": raw_items,
            })
        else:
            _check_score_range(raw_score, full)
            normalized.append({
                "student_id": student_id, "status": entry_status,
                "score": raw_score, "items": [],
            })
    # ── 校验全过才写库 ──
    existing = _score_rows_by_student(db, exam, subject_id)
    for n in normalized:
        row = existing.get(n["student_id"])
        if row is None:
            row = ExamScore(
                exam_id=exam.id, subject_id=subject_id,
                student_id=n["student_id"],
            )
            db.add(row)
            db.flush()
            existing[n["student_id"]] = row
        row.score = n["score"]
        row.status = n["status"]
        # 小分:先清旧的,再写新的;非 itemized 或无小分时即为清空。
        db.query(ExamScoreItemScore).filter(
            ExamScoreItemScore.score_id == row.id
        ).delete(synchronize_session=False)
        for iv in n["items"]:
            db.add(ExamScoreItemScore(
                score_id=row.id, item_id=iv["item_id"], value=iv["value"],
            ))
    db.commit()
    return len(normalized)


def submit_scores(
    db: Session, user: User, exam: Exam, subject_id: int,
    class_unit_id: int | None = None,
) -> int:
    require_exam_not_archived(db, exam.id)
    """把该范围未提交的成绩标为已提交;只标已有成绩行,不为未录学生建行。"""
    _require_exam_subject(db, exam, subject_id)
    participants = _participants_by_id(db, exam)
    if class_unit_id is not None:
        if class_unit_id not in {p.class_unit_id for p in participants.values()}:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "该班级不在本次考试参试名单中")
        _require_can_enter(db, user, exam, subject_id, {class_unit_id})
        allowed_classes = {class_unit_id}
    elif _is_manager(db, user):
        allowed_classes = None
    else:
        pairs = teaching_pairs(db, user, exam.semester_id)
        allowed_classes = {c for c, s in pairs if s == subject_id}
        if not allowed_classes:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "你未任教该科目,无权提交该科成绩"
            )
    stmt = select(ExamScore).where(
        ExamScore.exam_id == exam.id,
        ExamScore.subject_id == subject_id,
        ExamScore.submitted.is_(False),
    )
    rows = db.scalars(stmt).all()
    count = 0
    for row in rows:
        p = participants.get(row.student_id)
        if p is None:
            continue
        if allowed_classes is not None and p.class_unit_id not in allowed_classes:
            continue
        row.submitted = True
        row.submitted_by = user.id
        count += 1
    db.commit()
    return count


# ── 成绩导入(KW-32) ──────────────────────────────
def build_score_template(db: Session, exam: Exam, subject_id: int) -> bytes:
    """成绩导入模板:固定三列表头(栏名/说明/范例),第 4 行起读数据。"""
    _require_exam_subject(db, exam, subject_id)
    full = full_score_for(db, exam, subject_id)
    wb = Workbook()
    ws = wb.active
    ws.title = "成绩"
    ws.append([c[0] for c in SCORE_TEMPLATE_COLUMNS])
    ws.append([c[1] for c in SCORE_TEMPLATE_COLUMNS])
    ws.append([c[2] for c in SCORE_TEMPLATE_COLUMNS])
    ws["D2"] = f"正常必填,0 到 {full:g} 分之间;缺考/免考留空"
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 18
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _cell(row: tuple, i: int) -> str | None:
    if i >= len(row) or row[i] is None:
        return None
    text = str(row[i]).strip()
    return text or None


def _parse_score_cell(text: str | None, row_no: int, errors: list[dict]) -> float | None:
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        errors.append({"row": row_no, "message": f"第 {row_no} 行:成绩「{text}」不是数字"})
        return None


def import_scores(
    db: Session, user: User, exam: Exam, subject_id: int, file_bytes: bytes
) -> dict:
    require_exam_not_archived(db, exam.id)
    """批量导入成绩:逐行报错,全部通过才入库;有错一行都不写。

    校验:学号须在参试名单、文件内不重复、分数范围、状态合法、
    缺考/免考须留空分数;任课教师的行须在其所教班级内。
    """
    _require_exam_subject(db, exam, subject_id)
    settings = get_settings(db, exam)
    full = full_score_for(db, exam, subject_id)
    _require_can_enter(db, user, exam, subject_id)
    participants = _participants_by_id(db, exam)
    students_by_no = {
        s.student_no: s
        for s in db.scalars(
            select(Student).where(
                Student.semester_id == exam.semester_id,
                Student.id.in_(set(participants)),
            )
        ).all()
    } if participants else {}
    pairs = None
    if not _is_manager(db, user):
        pairs = teaching_pairs(db, user, exam.semester_id)
    existing = _score_rows_by_student(db, exam, subject_id)
    errors: list[dict] = []
    seen: set[str] = set()
    pending: list[dict] = []
    try:
        wb = load_workbook(io.BytesIO(file_bytes), data_only=True)
    except Exception:
        return {"created": 0, "updated": 0, "errors": [{"row": 0, "message": "无法读取文件,请确认为有效的 Excel 文件"}]}
    ws = wb.active
    for idx, row in enumerate(
        ws.iter_rows(min_row=HEADER_ROWS + 1, values_only=True),
        start=HEADER_ROWS + 1,
    ):
        if row is None or all(c is None or str(c).strip() == "" for c in row):
            continue
        student_no = _cell(row, 0)
        score_text = _cell(row, 3)
        status_text = _cell(row, 4) or "正常"
        if not student_no:
            errors.append({"row": idx, "message": f"第 {idx} 行:学号必填"})
            continue
        if student_no in seen:
            errors.append({"row": idx, "message": f"第 {idx} 行:学号「{student_no}」在文件内重复"})
            continue
        seen.add(student_no)
        student = students_by_no.get(student_no)
        if student is None or student.id not in participants:
            errors.append({"row": idx, "message": f"第 {idx} 行:学号「{student_no}」不在本次考试参试名单中"})
            continue
        p = participants[student.id]
        if pairs is not None and (p.class_unit_id, subject_id) not in pairs:
            errors.append({"row": idx, "message": f"第 {idx} 行:学号「{student_no}」不在你所教班级内"})
            continue
        if status_text not in SCORE_STATUSES:
            errors.append({"row": idx, "message": f"第 {idx} 行:状态「{status_text}」无效,只能是正常、缺考、作弊或免考"})
            continue
        score = _parse_score_cell(score_text, idx, errors)
        if errors and errors[-1]["row"] == idx and "不是数字" in errors[-1]["message"]:
            continue
        if status_text in ("缺考", "免考"):
            if score_text is not None:
                errors.append({"row": idx, "message": f"第 {idx} 行:缺考或免考成绩须留空"})
                continue
            effective = None
        elif status_text == "作弊":
            effective = 0.0 if settings.cheating_score_mode == "zero" else None
        else:
            if score is None:
                errors.append({"row": idx, "message": f"第 {idx} 行:正常成绩必填"})
                continue
            if score < 0 or score > full:
                errors.append({"row": idx, "message": f"第 {idx} 行:分数须在 0 到满分 {full:g} 之间"})
                continue
            effective = score
        pending.append({
            "student_id": student.id, "status": status_text, "score": effective,
        })
    if errors:
        return {"created": 0, "updated": 0, "errors": errors}
    # KW-37 锁定检查:导入行涉及的班级已锁定即整批拒绝(抛 403),不写库。
    # 局部导入,避免与 exam_publish 服务互相导入。
    from app.services.exam_publish import require_scores_not_locked

    require_scores_not_locked(
        db, exam.id, subject_id,
        {participants[item["student_id"]].class_unit_id for item in pending},
    )
    created = 0
    updated = 0
    for item in pending:
        row = existing.get(item["student_id"])
        if row is None:
            row = ExamScore(
                exam_id=exam.id, subject_id=subject_id,
                student_id=item["student_id"],
            )
            db.add(row)
            db.flush()
            existing[item["student_id"]] = row
            created += 1
        else:
            updated += 1
        row.score = item["score"]
        row.status = item["status"]
        # 导入只录总分,清掉旧的小分,避免总分与小分之和不一致。
        db.query(ExamScoreItemScore).filter(
            ExamScoreItemScore.score_id == row.id
        ).delete(synchronize_session=False)
    db.commit()
    return {"created": created, "updated": updated, "errors": []}


# ── 录入进度看板(KW-34) ──────────────────────────────
def score_progress(db: Session, user: User, exam: Exam) -> dict:
    """各科目、各班录入进度:未开始/录入中/已提交。

    total 为该班参试人数;entered 为已录人数(有分数,或已标记缺考/作弊/免考);
    submitted 为已提交人数。教师只看本人可见班级的进度。
    """
    subjects = db.scalars(
        select(ExamSubject).where(ExamSubject.exam_id == exam.id)
        .order_by(ExamSubject.exam_date, ExamSubject.start_time)
    ).all()
    participants = list(_participants_by_id(db, exam).values())
    class_ids = visible_class_ids(db, user)
    if class_ids is not None:
        participants = [p for p in participants if p.class_unit_id in class_ids]
    classes = {
        c.id: c
        for c in db.scalars(
            select(ClassUnit).where(
                ClassUnit.id.in_({p.class_unit_id for p in participants})
            )
        ).all()
    } if participants else {}
    subject_names = {
        s.id: s.name
        for s in db.scalars(
            select(Subject).where(
                Subject.id.in_({s.subject_id for s in subjects})
            )
        ).all()
    } if subjects else {}
    out_subjects = []
    for subj in subjects:
        rows = _score_rows_by_student(db, exam, subj.subject_id)
        by_class: dict[int, list[ExamParticipant]] = {}
        for p in participants:
            by_class.setdefault(p.class_unit_id, []).append(p)
        classes_out = []
        for cid in sorted(by_class, key=lambda c: classes.get(c).name if classes.get(c) else ""):
            plist = by_class[cid]
            total = len(plist)
            entered = 0
            submitted = 0
            for p in plist:
                r = rows.get(p.student_id)
                if r is None:
                    continue
                if r.score is not None or r.status != "正常":
                    entered += 1
                if r.submitted:
                    submitted += 1
            if total == 0 or entered == 0:
                status_text = "未开始"
            elif submitted >= total:
                status_text = "已提交"
            else:
                status_text = "录入中"
            classes_out.append({
                "class_unit_id": cid,
                "class_name": classes[cid].name if cid in classes else "",
                "grade": classes[cid].grade if cid in classes else None,
                "total": total,
                "entered": entered,
                "submitted": submitted,
                "status": status_text,
            })
        out_subjects.append({
            "subject_id": subj.subject_id,
            "subject_name": subject_names.get(subj.subject_id, ""),
            "classes": classes_out,
        })
    return {"subjects": out_subjects}


# ── 补考(KW-35) ──────────────────────────────
def list_makeups(db: Session, exam: Exam) -> tuple[list[ExamMakeup], int]:
    rows = db.scalars(
        select(ExamMakeup).where(ExamMakeup.exam_id == exam.id)
        .order_by(ExamMakeup.exam_date, ExamMakeup.id)
    ).all()
    return list(rows), len(rows)


def create_makeup(
    db: Session, exam: Exam, name: str, exam_date, note: str | None
) -> ExamMakeup:
    require_exam_not_archived(db, exam.id)
    row = ExamMakeup(
        exam_id=exam.id, name=name, exam_date=exam_date, note=note
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_makeup(db: Session, exam: Exam, mid: int) -> None:
    require_exam_not_archived(db, exam.id)
    row = db.get(ExamMakeup, mid)
    if row is None or row.exam_id != exam.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到补考场次")
    db.delete(row)
    db.commit()


def _require_makeup(db: Session, exam: Exam, mid: int) -> ExamMakeup:
    row = db.get(ExamMakeup, mid)
    if row is None or row.exam_id != exam.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到补考场次")
    return row


def list_makeup_scores(
    db: Session, user: User, exam: Exam, makeup: ExamMakeup,
    subject_id: int,
) -> tuple[list[dict], int]:
    """补考成绩列表:以参试名单为准,无补考成绩行也列出。"""
    _require_exam_subject(db, exam, subject_id)
    class_ids = visible_class_ids(db, user)
    participants = _participants_by_id(db, exam)
    pairs = None
    if not _is_manager(db, user):
        pairs = teaching_pairs(db, user, exam.semester_id)
    student_ids = sorted(participants)
    students = {
        s.id: s
        for s in db.scalars(
            select(Student).where(Student.id.in_(student_ids))
        ).all()
    } if student_ids else {}
    _all_classes = db.scalars(select(ClassUnit)).all()
    class_names = {c.id: c.name for c in _all_classes}
    class_grades = {c.id: c.grade for c in _all_classes}
    rows = {
        r.student_id: r
        for r in db.scalars(
            select(ExamMakeupScore).where(
                ExamMakeupScore.makeup_id == makeup.id,
                ExamMakeupScore.subject_id == subject_id,
            )
        ).all()
    }
    items: list[dict] = []
    for sid in student_ids:
        p = participants[sid]
        if pairs is not None and (p.class_unit_id, subject_id) not in pairs:
            continue
        if class_ids is not None and p.class_unit_id not in class_ids:
            continue
        student = students.get(sid)
        row = rows.get(sid)
        items.append({
            "id": row.id if row else None,
            "makeup_id": makeup.id,
            "student_id": sid,
            "student_no": student.student_no if student else "",
            "student_name": student.name if student else "",
            "class_name": class_names.get(p.class_unit_id, ""),
            "grade": class_grades.get(p.class_unit_id),
            "subject_id": subject_id,
            "score": row.score if row else None,
            "status": row.status if row else "正常",
        })
    items.sort(key=lambda x: (x["class_name"], x["student_no"]))
    return items, len(items)


def upsert_makeup_scores(
    db: Session, user: User, exam: Exam, makeup: ExamMakeup,
    subject_id: int, entries: list[dict],
) -> int:
    require_exam_not_archived(db, exam.id)
    """批量 upsert 补考成绩:先全量校验,通过后才写库。"""
    _require_exam_subject(db, exam, subject_id)
    full = full_score_for(db, exam, subject_id)
    participants = _participants_by_id(db, exam)
    target_classes = {
        participants[e["student_id"]].class_unit_id
        for e in entries
        if e["student_id"] in participants
    }
    _require_can_enter(db, user, exam, subject_id, target_classes)
    normalized: list[dict] = []
    for e in entries:
        student_id = e["student_id"]
        if student_id not in participants:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"学生 id {student_id} 不在本次考试参试名单中",
            )
        entry_status = e.get("status") or "正常"
        if entry_status not in MAKEUP_SCORE_STATUSES:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "补考成绩状态只能是正常、缺考或免考",
            )
        score = None if entry_status in ("缺考", "免考") else e.get("score")
        _check_score_range(score, full)
        normalized.append({
            "student_id": student_id, "status": entry_status, "score": score,
        })
    existing = {
        r.student_id: r
        for r in db.scalars(
            select(ExamMakeupScore).where(
                ExamMakeupScore.makeup_id == makeup.id,
                ExamMakeupScore.subject_id == subject_id,
            )
        ).all()
    }
    for n in normalized:
        row = existing.get(n["student_id"])
        if row is None:
            row = ExamMakeupScore(
                makeup_id=makeup.id, student_id=n["student_id"],
                subject_id=subject_id,
            )
            db.add(row)
            db.flush()
            existing[n["student_id"]] = row
        row.score = n["score"]
        row.status = n["status"]
    db.commit()
    return len(normalized)


def get_exam_for_api(db: Session, exam_id: int) -> Exam:
    return get_exam(db, exam_id)
