"""考试归档、历史对比与备份导出服务(KW-65~67)。

归档口径:
- 只有状态已到“已发布成绩”的考试可以归档,归档后状态推进到“已归档”
  (走已有状态机,不另造状态);已归档过再次归档 409。
- 归档时生成 manifest 快照:参试人数、编排人数、监考人次、成绩条数、
  发布批次、各科均分与总分均分,存 JSON 文本。
- 归档包 zip 按需生成,不落盘:参试名单、考场编排、监考表、成绩册、
  分析报表各一个 Excel 表,考场编排/成绩册/分析报表复用已有导出逻辑。
- 归档后只读由 app/services/exam.require_exam_not_archived 在各写路径
  入口把关,见 exam_scores / exam_arrangement / exam_invigilation /
  exam 四个服务的写函数。
- 对比口径:同科目(按科目名称匹配,跨学期科目 id 不同)均分、及格率、
  优秀率、总分均分的变化值(B−A);无共同科目时 subjects 为空并返回提示。
- 备份导出只出接口,不做自动备份任务;备份频率与存放位置由学校
  信息安全要求决定。
"""

import io
import json
import zipfile

from fastapi import HTTPException, status
from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.basedata import ClassUnit, Room, Subject, Teacher
from app.models.exam import Exam, ExamGrade, ExamParticipant
from app.models.exam_archive import ExamArchive
from app.models.exam_arrangement import ExamRoomAssignment
from app.models.exam_foundation import Student
from app.models.exam_invigilation import ExamDiscipline, ExamInvigilation
from app.models.exam_notifications import ExamNotificationLog
from app.models.exam_publish import ExamPublishBatch
from app.models.exam_scores import ExamScore
from app.models.semester import Semester
from app.models.user import User
from app.services import exam as exam_svc
from app.services import exam_analysis as analysis_svc
from app.services import exam_arrangement as arrangement_svc
from app.services import exam_invigilation as invigilation_svc
from app.services import exam_reports as reports_svc
from app.services.exam import get_exam, require_exam_visible


def _round(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


def _sheet_header(ws, headers: list[str]) -> None:
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)


def _workbook_bytes(wb: Workbook) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── 归档(KW-65) ──────────────────────────────
def get_archive(db: Session, exam_id: int) -> ExamArchive | None:
    return db.scalar(
        select(ExamArchive).where(ExamArchive.exam_id == exam_id)
    )


def _build_manifest(db: Session, user: User, exam: Exam) -> dict:
    participant_count = db.scalar(
        select(func.count())
        .select_from(ExamParticipant)
        .where(ExamParticipant.exam_id == exam.id)
    ) or 0
    arrangement_count = db.scalar(
        select(func.count())
        .select_from(ExamRoomAssignment)
        .where(ExamRoomAssignment.exam_id == exam.id)
    ) or 0
    invigilation_count = db.scalar(
        select(func.count())
        .select_from(ExamInvigilation)
        .where(ExamInvigilation.exam_id == exam.id)
    ) or 0
    score_count = db.scalar(
        select(func.count())
        .select_from(ExamScore)
        .where(ExamScore.exam_id == exam.id)
    ) or 0
    batches = db.scalars(
        select(ExamPublishBatch)
        .where(ExamPublishBatch.exam_id == exam.id)
        .order_by(ExamPublishBatch.id)
    ).all()
    summary = analysis_svc.analysis_summary(db, user, exam, "grade", None, None)
    return {
        "exam_id": exam.id,
        "exam_name": exam.name,
        "semester_id": exam.semester_id,
        "participant_count": participant_count,
        "arrangement_count": arrangement_count,
        "invigilation_count": invigilation_count,
        "score_count": score_count,
        "publish_batches": [
            {
                "scope_type": b.scope_type,
                "scope_value": b.scope_value,
                "status": b.status,
            }
            for b in batches
        ],
        "subject_avgs": [
            {
                "subject_id": s["subject_id"],
                "subject_name": s["subject_name"],
                "avg": s["avg"],
                "pass_rate": s["pass_rate"],
                "excellent_rate": s["excellent_rate"],
            }
            for s in summary["subjects"]
        ],
        "total_avg": summary["totals"]["avg"],
    }


def archive_out(row: ExamArchive) -> dict:
    return {
        "archive_id": row.id,
        "exam_id": row.exam_id,
        "archived_by": row.archived_by,
        "archived_at": row.archived_at,
        "manifest": json.loads(row.manifest or "{}"),
        "note": row.note,
    }


def create_archive(
    db: Session, user: User, exam: Exam, note: str | None
) -> ExamArchive:
    """归档:状态须已到“已发布成绩”,归档后推进到“已归档”。"""
    if get_archive(db, exam.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "该考试已归档")
    if exam.status != "已发布成绩":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"只有已发布成绩的考试可以归档,当前状态为{exam.status}",
        )
    manifest = _build_manifest(db, user, exam)
    row = ExamArchive(
        exam_id=exam.id,
        archived_by=user.id,
        manifest=json.dumps(manifest, ensure_ascii=False),
        note=note,
    )
    db.add(row)
    db.flush()
    exam_svc.change_exam_status(db, user, exam, "已归档", note)
    db.refresh(row)
    return row


def delete_archive(
    db: Session, user: User, exam: Exam, archive: ExamArchive
) -> None:
    """取消归档:删归档记录,考试状态回到“已发布成绩”。"""
    db.delete(archive)
    db.flush()
    exam_svc.change_exam_status(db, user, exam, "已发布成绩", "取消归档")


# ── 历史查询(KW-66) ──────────────────────────────
def list_archives(
    db: Session,
    user: User,
    semester_id: int | None = None,
    q: str | None = None,
    status_filter: str | None = None,
) -> tuple[list[dict], int]:
    """历史档案列表:按可见范围过滤;status 筛选已归档/未归档。"""
    if status_filter is not None and status_filter not in ("已归档", "未归档"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "归档状态筛选只能是已归档或未归档"
        )
    exams, _ = exam_svc.list_exams(db, user, semester_id, None, q)
    archive_map = {}
    if exams:
        archive_map = {
            a.exam_id: a
            for a in db.scalars(
                select(ExamArchive).where(
                    ExamArchive.exam_id.in_([e.id for e in exams])
                )
            ).all()
        }
    items = []
    for exam in exams:
        archive = archive_map.get(exam.id)
        if status_filter == "已归档" and archive is None:
            continue
        if status_filter == "未归档" and archive is not None:
            continue
        items.append({
            "exam_id": exam.id,
            "exam_name": exam.name,
            "exam_type": exam.exam_type,
            "semester_id": exam.semester_id,
            "status": exam.status,
            "archived_at": archive.archived_at if archive else None,
            "archived_by": archive.archived_by if archive else None,
        })
    return items, len(items)


def compare_exams(db: Session, user: User, exam_a: Exam, exam_b: Exam) -> dict:
    """两次考试整体对比:同科目均分、及格率、优秀率、总分均分的变化值(B−A)。

    科目按名称匹配(跨学期科目 id 不同,按名称才是同一科目);
    无共同科目时 subjects 为空并返回提示。
    """
    require_exam_visible(db, user, exam_a)
    require_exam_visible(db, user, exam_b)
    summary_a = analysis_svc.analysis_summary(db, user, exam_a, "grade", None, None)
    summary_b = analysis_svc.analysis_summary(db, user, exam_b, "grade", None, None)
    by_name_a = {s["subject_name"]: s for s in summary_a["subjects"]}
    by_name_b = {s["subject_name"]: s for s in summary_b["subjects"]}
    common = [name for name in by_name_a if name in by_name_b]
    subjects = []
    for name in common:
        a = by_name_a[name]
        b = by_name_b[name]
        subjects.append({
            "subject_id": a["subject_id"],
            "subject_name": name,
            "avg_a": a["avg"],
            "avg_b": b["avg"],
            "delta_avg": _round(b["avg"] - a["avg"])
            if a["avg"] is not None and b["avg"] is not None else None,
            "pass_rate_a": a["pass_rate"],
            "pass_rate_b": b["pass_rate"],
            "delta_pass_rate": _round(b["pass_rate"] - a["pass_rate"])
            if a["pass_rate"] is not None and b["pass_rate"] is not None else None,
            "excellent_rate_a": a["excellent_rate"],
            "excellent_rate_b": b["excellent_rate"],
            "delta_excellent_rate": _round(b["excellent_rate"] - a["excellent_rate"])
            if a["excellent_rate"] is not None and b["excellent_rate"] is not None else None,
        })
    total_avg_a = summary_a["totals"]["avg"]
    total_avg_b = summary_b["totals"]["avg"]
    return {
        "exam_a": {"id": exam_a.id, "name": exam_a.name},
        "exam_b": {"id": exam_b.id, "name": exam_b.name},
        "subjects": subjects,
        "total_avg_a": total_avg_a,
        "total_avg_b": total_avg_b,
        "delta_total_avg": _round(total_avg_b - total_avg_a)
        if total_avg_a is not None and total_avg_b is not None else None,
        "message": "两次考试无共同科目，无法对比" if not subjects else None,
    }


# ── 归档包下载(KW-65) ──────────────────────────────
def _participants_workbook(db: Session, exam: Exam) -> bytes:
    rows = db.scalars(
        select(ExamParticipant)
        .where(ExamParticipant.exam_id == exam.id)
        .order_by(ExamParticipant.id)
    ).all()
    students = {
        s.id: s
        for s in db.scalars(select(Student)).all()
    }
    classes = {c.id: c for c in db.scalars(select(ClassUnit)).all()}
    wb = Workbook()
    ws = wb.active
    ws.title = "参试名单"
    _sheet_header(ws, ["学号", "姓名", "班级", "参试状态", "备注"])
    for p in rows:
        student = students.get(p.student_id)
        cls = classes.get(p.class_unit_id)
        ws.append([
            student.student_no if student else "",
            student.name if student else "",
            cls.name if cls else "",
            p.status,
            p.note or "",
        ])
    return _workbook_bytes(wb)


def _invigilation_workbook(db: Session, user: User, exam: Exam) -> bytes:
    items, _ = invigilation_svc.list_invigilations(db, user, exam)
    wb = Workbook()
    ws = wb.active
    ws.title = "监考表"
    _sheet_header(ws, ["科目", "考场", "监考教师", "角色"])
    for it in items:
        ws.append([
            it["subject_name"], it["room_name"],
            it["teacher_name"], it["role"],
        ])
    return _workbook_bytes(wb)


def build_archive_zip(db: Session, user: User, exam: Exam) -> bytes:
    """归档包 zip:参试名单、考场编排、监考表、成绩册、分析报表各一表,按需生成,不落盘。"""
    files = [
        ("参试名单.xlsx", _participants_workbook(db, exam)),
        ("考场编排.xlsx", arrangement_svc.build_arrangement_workbook(
            db, user, exam, None)),
        ("监考表.xlsx", _invigilation_workbook(db, user, exam)),
        ("成绩册.xlsx", reports_svc.build_grade_book(db, exam)),
        ("分析报表.xlsx", analysis_svc.build_report_pack(db, user, exam)),
    ]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files:
            zf.writestr(name, data)
    return buf.getvalue()


# ── 备份导出(KW-67) ──────────────────────────────
def _semester_label(sem: Semester | None) -> str:
    return str(sem) if sem is not None else ""


def build_backup_workbook(db: Session, semester_id: int | None) -> bytes:
    """全量导出考务与成绩数据:学生、考试、参试名单、考场编排、
    监考安排、成绩、发布批次、考风考纪、通知记录,共九表。

    semester_id 为空时导出全部学期;指定学期时只导出该学期数据。
    """
    semester = None
    if semester_id is not None:
        semester = db.get(Semester, semester_id)
        if semester is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到学期")
    exams = db.scalars(
        select(Exam)
        .where(Exam.semester_id == semester_id)
        .order_by(Exam.id)
        if semester_id is not None
        else select(Exam).order_by(Exam.id)
    ).all()
    exam_ids = [e.id for e in exams]
    exam_map = {e.id: e for e in exams}
    semesters = {s.id: s for s in db.scalars(select(Semester)).all()}
    students = db.scalars(
        select(Student)
        .where(Student.semester_id == semester_id)
        .order_by(Student.id)
        if semester_id is not None
        else select(Student).order_by(Student.id)
    ).all()
    student_map = {s.id: s for s in students}
    student_ids = [s.id for s in students]
    classes = {c.id: c for c in db.scalars(select(ClassUnit)).all()}
    subjects = {s.id: s.name for s in db.scalars(select(Subject)).all()}
    teachers = {t.id: t.name for t in db.scalars(select(Teacher)).all()}
    rooms = {r.id: r.name for r in db.scalars(select(Room)).all()}
    grades_map: dict[int, list[int]] = {}
    for g in db.scalars(select(ExamGrade)).all():
        grades_map.setdefault(g.exam_id, []).append(g.grade)

    def _exam_name(exam_id: int) -> str:
        exam = exam_map.get(exam_id)
        return exam.name if exam else ""

    def _student(student_id: int) -> Student | None:
        return student_map.get(student_id)

    wb = Workbook()
    ws = wb.active
    ws.title = "学生"
    _sheet_header(ws, ["学期", "学号", "姓名", "性别", "班级", "状态", "考号"])
    for s in students:
        cls = classes.get(s.class_unit_id)
        ws.append([
            _semester_label(semesters.get(s.semester_id)),
            s.student_no, s.name, s.gender or "",
            cls.name if cls else "", s.status, s.exam_no or "",
        ])

    ws = wb.create_sheet("考试")
    _sheet_header(ws, ["考试名称", "类型", "学期", "状态", "参试年级", "说明"])
    for e in exams:
        ws.append([
            e.name, e.exam_type,
            _semester_label(semesters.get(e.semester_id)),
            e.status,
            "、".join(str(g) for g in sorted(grades_map.get(e.id, []))),
            e.description or "",
        ])

    ws = wb.create_sheet("参试名单")
    _sheet_header(ws, ["考试", "学号", "姓名", "班级", "参试状态", "备注"])
    participants = db.scalars(
        select(ExamParticipant)
        .where(ExamParticipant.exam_id.in_(exam_ids))
        .order_by(ExamParticipant.id)
    ).all() if exam_ids else []
    for p in participants:
        student = _student(p.student_id)
        cls = classes.get(p.class_unit_id)
        ws.append([
            _exam_name(p.exam_id),
            student.student_no if student else "",
            student.name if student else "",
            cls.name if cls else "", p.status, p.note or "",
        ])

    ws = wb.create_sheet("考场编排")
    _sheet_header(ws, ["考试", "科目", "考场", "座位号", "学号", "姓名"])
    assignments = db.scalars(
        select(ExamRoomAssignment)
        .where(ExamRoomAssignment.exam_id.in_(exam_ids))
        .order_by(ExamRoomAssignment.id)
    ).all() if exam_ids else []
    for a in assignments:
        student = _student(a.student_id)
        ws.append([
            _exam_name(a.exam_id), subjects.get(a.subject_id, ""),
            rooms.get(a.room_id, ""), a.seat_no,
            student.student_no if student else "",
            student.name if student else "",
        ])

    ws = wb.create_sheet("监考安排")
    _sheet_header(ws, ["考试", "科目", "考场", "监考教师", "角色"])
    invigilations = db.scalars(
        select(ExamInvigilation)
        .where(ExamInvigilation.exam_id.in_(exam_ids))
        .order_by(ExamInvigilation.id)
    ).all() if exam_ids else []
    for row in invigilations:
        ws.append([
            _exam_name(row.exam_id), subjects.get(row.subject_id, ""),
            rooms.get(row.room_id, ""), teachers.get(row.teacher_id, ""),
            row.role,
        ])

    ws = wb.create_sheet("成绩")
    _sheet_header(ws, ["考试", "科目", "学号", "姓名", "分数", "状态", "是否已提交"])
    scores = db.scalars(
        select(ExamScore)
        .where(ExamScore.exam_id.in_(exam_ids))
        .order_by(ExamScore.id)
    ).all() if exam_ids else []
    for row in scores:
        student = _student(row.student_id)
        ws.append([
            _exam_name(row.exam_id), subjects.get(row.subject_id, ""),
            student.student_no if student else "",
            student.name if student else "",
            row.score, row.status, "是" if row.submitted else "否",
        ])

    ws = wb.create_sheet("发布批次")
    _sheet_header(ws, ["考试", "范围类型", "范围", "发布时间", "状态"])
    batches = db.scalars(
        select(ExamPublishBatch)
        .where(ExamPublishBatch.exam_id.in_(exam_ids))
        .order_by(ExamPublishBatch.id)
    ).all() if exam_ids else []
    for b in batches:
        if b.scope_type == "班级":
            cls = classes.get(b.scope_value)
            scope = cls.name if cls else str(b.scope_value)
        else:
            scope = f"{b.scope_value}年级"
        ws.append([
            _exam_name(b.exam_id), b.scope_type, scope,
            b.publish_at, b.status,
        ])

    ws = wb.create_sheet("考风考纪")
    _sheet_header(ws, ["考试", "科目", "学号", "姓名", "类型", "描述", "处理"])
    disciplines = db.scalars(
        select(ExamDiscipline)
        .where(ExamDiscipline.exam_id.in_(exam_ids))
        .order_by(ExamDiscipline.id)
    ).all() if exam_ids else []
    for row in disciplines:
        student = _student(row.student_id)
        ws.append([
            _exam_name(row.exam_id), subjects.get(row.subject_id, ""),
            student.student_no if student else "",
            student.name if student else "",
            row.type, row.description or "", row.handling or "",
        ])

    ws = wb.create_sheet("通知记录")
    _sheet_header(ws, ["考试", "通知类型", "收件人", "渠道", "状态", "内容", "发送时间"])
    logs = db.scalars(
        select(ExamNotificationLog)
        .where(ExamNotificationLog.exam_id.in_(exam_ids))
        .order_by(ExamNotificationLog.id)
    ).all() if exam_ids else []
    for row in logs:
        ws.append([
            _exam_name(row.exam_id), row.notification_type,
            row.recipient_name, row.channel, row.status,
            row.message, row.sent_at,
        ])

    for sheet in wb.worksheets:
        for col in sheet.columns:
            sheet.column_dimensions[col[0].column_letter].width = 16
    return _workbook_bytes(wb)


def get_exam_for_api(db: Session, exam_id: int) -> Exam:
    return get_exam(db, exam_id)
