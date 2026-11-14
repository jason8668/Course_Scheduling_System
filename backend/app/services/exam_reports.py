"""成绩单与查询服务(KW-52~54/56):班级成绩单、个人成绩单、教师端查询、
成绩归档表导出。

总分与排名复用第 7 批 exam_analysis 的口径(_Context 总分、
_assign_ranks 并列规则、分析设置的 rank_tie_rule),不在此另写一套:
总分按分析口径计入(缺考按 absent_counts、免考永不计入),排名在
全校参试名单上算,避免按可见范围切片后名次失真。

只有教师与教务可看成绩:教师端只看发布批次覆盖的班级;
管理员/教务不限。不设学生/家长账号与自助查询。
"""

import io

from fastapi import HTTPException, status
from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.basedata import ClassUnit, Subject, Teacher
from app.models.exam import Exam, ExamParticipant, ExamSubject
from app.models.exam_foundation import Student
from app.models.user import Role, User
from app.services.exam_analysis import (
    _Context,
    _assign_ranks,
    _participants,
    get_analysis_settings,
)
from app.services.exam_publish import is_score_published
from app.services.exam_scores import teaching_pairs
from app.services.exam_scopes import (
    can_manage_students,
    require_student_visible,
    visible_class_ids,
)


# ── 共用小工具 ──────────────────────────────
def _is_manager(db: Session, user: User) -> bool:
    return can_manage_students(db, user)


def _homeroom_class_ids(db: Session, user: User) -> set[int]:
    """该账号担任班主任的班级 id 集合。"""
    teacher_ids = db.scalars(
        select(Teacher.id).where(Teacher.user_id == user.id)
    ).all()
    if not teacher_ids:
        return set()
    return set(
        db.scalars(
            select(ClassUnit.id).where(
                ClassUnit.homeroom_teacher_id.in_(teacher_ids)
            )
        ).all()
    )


def _is_class_published(db: Session, exam: Exam, class_unit_id: int) -> bool:
    """该班成绩是否已被发布批次覆盖。"""
    cls = db.get(ClassUnit, class_unit_id)
    if cls is None:
        return False
    return is_score_published(db, exam.id, cls.grade, class_unit_id)


def _require_teacher_published(db: Session, exam: Exam, class_unit_id: int) -> None:
    if not _is_class_published(db, exam, class_unit_id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "该班级成绩尚未发布"
        )


def _report_context(db: Session, exam: Exam):
    """成绩单共用上下文:全校参试名单上的总分、班级排名、年级排名。"""
    participants = _participants(db, exam)
    ctx = _Context(db, exam, participants)
    rule = get_analysis_settings(db, exam).rank_tie_rule
    totals = ctx.totals()
    grade_ranks = _assign_ranks(totals, rule)
    groups: dict[int, dict[int, float]] = {}
    for p in participants:
        if p.student_id in totals:
            groups.setdefault(p.class_unit_id, {})[p.student_id] = totals[
                p.student_id
            ]
    class_ranks: dict[int, int] = {}
    for group_values in groups.values():
        class_ranks.update(_assign_ranks(group_values, rule))
    return ctx, totals, class_ranks, grade_ranks


def _student_card(
    ctx: _Context,
    totals: dict[int, float],
    class_ranks: dict[int, int],
    grade_ranks: dict[int, int],
    participant: ExamParticipant,
) -> dict:
    """一名学生的成绩单卡片:各科原始分与状态、总分、班级/年级排名。"""
    sid = participant.student_id
    student = ctx.students.get(sid)
    cls = ctx.classes.get(participant.class_unit_id)
    subjects = []
    for r in ctx.subjects:
        row = ctx.score_rows.get((sid, r.subject_id))
        subjects.append({
            "subject_id": r.subject_id,
            "subject_name": ctx.subject_names.get(r.subject_id, ""),
            "score": row.score if row is not None else None,
            "status": row.status if row is not None else "未录入",
        })
    return {
        "student_id": sid,
        "student_no": student.student_no if student else "",
        "student_name": student.name if student else "",
        "class_name": cls.name if cls else "",
        "subjects": subjects,
        "total": totals.get(sid),
        "class_rank": class_ranks.get(sid),
        "grade_rank": grade_ranks.get(sid),
    }


# ── KW-52 班级成绩单 ──────────────────────────────
def class_report_card(
    db: Session, user: User, exam: Exam, class_unit_id: int,
) -> dict:
    cls = db.get(ClassUnit, class_unit_id)
    if cls is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到班级")
    if not _is_manager(db, user):
        if Role.teacher.value not in user.role_names:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "只有班主任与教务可以查看班级成绩单"
            )
        if class_unit_id not in _homeroom_class_ids(db, user):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "只有该班班主任可以查看班级成绩单"
            )
        _require_teacher_published(db, exam, class_unit_id)
    participants = [
        p for p in _participants(db, exam)
        if p.class_unit_id == class_unit_id
    ]
    ctx, totals, class_ranks, grade_ranks = _report_context(db, exam)
    students = [
        _student_card(ctx, totals, class_ranks, grade_ranks, p)
        for p in sorted(
            participants,
            key=lambda p: (
                ctx.students.get(p.student_id).student_no
                if ctx.students.get(p.student_id) else ""
            ),
        )
    ]
    for card in students:
        card.pop("class_name", None)
    return {
        "class_unit_id": cls.id,
        "class_name": cls.name,
        "students": students,
    }


# ── KW-53 个人成绩单(教师/教务完整版) ──────────────────────────────
def student_report_card(
    db: Session, user: User, exam: Exam, student_id: int,
) -> dict:
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到学生")
    participant = db.scalar(
        select(ExamParticipant).where(
            ExamParticipant.exam_id == exam.id,
            ExamParticipant.student_id == student_id,
        )
    )
    if participant is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "该学生不在本次考试参试名单中"
        )
    if not _is_manager(db, user):
        if Role.teacher.value not in user.role_names:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "只有教师与教务可以查看个人成绩单"
            )
        require_student_visible(db, user, student)
        _require_teacher_published(db, exam, participant.class_unit_id)
    ctx, totals, class_ranks, grade_ranks = _report_context(db, exam)
    return _student_card(ctx, totals, class_ranks, grade_ranks, participant)


# ── KW-54 教师端成绩查询 ──────────────────────────────
def teacher_scores(
    db: Session, user: User, exam: Exam,
    subject_id: int | None, class_unit_id: int | None, q: str | None,
) -> dict:
    if subject_id is not None:
        row = db.scalar(
            select(ExamSubject).where(
                ExamSubject.exam_id == exam.id,
                ExamSubject.subject_id == subject_id,
            )
        )
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到该考试科目")
    if class_unit_id is not None and db.get(ClassUnit, class_unit_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到班级")
    manager = _is_manager(db, user)
    if not manager and Role.teacher.value not in user.role_names:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "只有教师与教务可以查询成绩"
        )
    pairs: set[tuple[int, int]] = set()
    homeroom: set[int] = set()
    class_ids: set[int] | None = None
    if not manager:
        pairs = teaching_pairs(db, user, exam.semester_id)
        homeroom = _homeroom_class_ids(db, user)
        class_ids = visible_class_ids(db, user)
        if class_unit_id is not None:
            if class_ids is not None and class_unit_id not in class_ids:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN,
                    "无权查看该班级(不在你的可见班级范围内)",
                )
            _require_teacher_published(db, exam, class_unit_id)
        if subject_id is not None:
            teaches_subject = any(s == subject_id for _, s in pairs)
            if not teaches_subject and not homeroom:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN, "你未任教该科目,无权查询该科成绩"
                )
            if (
                class_unit_id is not None
                and (class_unit_id, subject_id) not in pairs
                and class_unit_id not in homeroom
            ):
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN,
                    "只能查询本人所教班级、所教科目的成绩",
                )
    ctx, totals, class_ranks, grade_ranks = _report_context(db, exam)
    subject_order = [r.subject_id for r in ctx.subjects]
    items: list[dict] = []
    for p in _participants(db, exam):
        if class_unit_id is not None and p.class_unit_id != class_unit_id:
            continue
        if not manager:
            if class_ids is not None and p.class_unit_id not in class_ids:
                continue
            if not _is_class_published(db, exam, p.class_unit_id):
                continue
        student = ctx.students.get(p.student_id)
        if student is None:
            continue
        if q:
            keyword = q.strip()
            if keyword and keyword not in student.student_no and keyword not in student.name:
                continue
        cls = ctx.classes.get(p.class_unit_id)
        subject_ids = (
            [subject_id] if subject_id is not None else subject_order
        )
        for sid in subject_ids:
            if not manager:
                if (p.class_unit_id, sid) not in pairs and p.class_unit_id not in homeroom:
                    continue
            row = ctx.score_rows.get((p.student_id, sid))
            items.append({
                "student_id": p.student_id,
                "student_no": student.student_no,
                "student_name": student.name,
                "class_name": cls.name if cls else "",
                "subject_id": sid,
                "subject_name": ctx.subject_names.get(sid, ""),
                "score": row.score if row is not None else None,
                "status": row.status if row is not None else "未录入",
                "total": totals.get(p.student_id),
                "class_rank": class_ranks.get(p.student_id),
                "grade_rank": grade_ranks.get(p.student_id),
            })
    items.sort(key=lambda i: (
        i["class_name"], i["student_no"],
        subject_order.index(i["subject_id"])
        if i["subject_id"] in subject_order else 0,
    ))
    return {"items": items, "total": len(items)}


# ── KW-56 成绩归档表导出 ──────────────────────────────
def build_grade_book(db: Session, exam: Exam) -> bytes:
    """完整成绩册 Excel:学号、姓名、班级、各科原始分、总分、班级排名、年级排名。"""
    ctx, totals, class_ranks, grade_ranks = _report_context(db, exam)
    wb = Workbook()
    ws = wb.active
    ws.title = "成绩册"
    headers = (
        ["学号", "姓名", "班级"]
        + [ctx.subject_names.get(r.subject_id, "") for r in ctx.subjects]
        + ["总分", "班级排名", "年级排名"]
    )
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    participants = sorted(
        _participants(db, exam),
        key=lambda p: (
            ctx.classes.get(p.class_unit_id).name
            if ctx.classes.get(p.class_unit_id) else "",
            ctx.students.get(p.student_id).student_no
            if ctx.students.get(p.student_id) else "",
        ),
    )
    for p in participants:
        student = ctx.students.get(p.student_id)
        cls = ctx.classes.get(p.class_unit_id)
        row = [
            student.student_no if student else "",
            student.name if student else "",
            cls.name if cls else "",
        ]
        for r in ctx.subjects:
            score_row = ctx.score_rows.get((p.student_id, r.subject_id))
            row.append(score_row.score if score_row is not None else None)
        row.append(totals.get(p.student_id))
        row.append(class_ranks.get(p.student_id))
        row.append(grade_ranks.get(p.student_id))
        ws.append(row)
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 14
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
