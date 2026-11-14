"""成绩分析服务(KW-41~51):汇总、排名、率值、分段、临界生、目标生、
进退步、质量对比、个人趋势、等第转换、报表包。

分析结果实时计算,不另存结果表。

统计口径:
- 缺考按第 5 批 ExamScoreSetting.absent_counts 执行:默认不计入;
  设为计入时缺考按 0 分计入;免考永不计入。
- 作弊按 cheating_score_mode 已折算进 ExamScore.score:记 0 分的计入,
  记空的不计入。
- 总分 = 本次考试各科计入分数之和;一名学生至少有一科计入分数才有总分,
  全科缺考/免考的学生不进总分统计与总分排名。
- 及格线/优秀线:本次考试科目阈值覆盖 > 科目分值设置 > 默认 60/85;
  总分及格线/优秀线 = 各科线之和。
- 标准差用总体标准差;率值均为百分比(0~100),数值保留两位小数。
- 排名默认 dense(同分同名次),可配 competition(同分并列占位)。
"""

import io
import statistics

from fastapi import HTTPException, status
from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.basedata import ClassUnit, Subject
from app.models.exam import EXAM_STATUS_ORDER, Exam, ExamParticipant, ExamSubject
from app.models.exam_analysis import (
    DEFAULT_GRADE_BANDS,
    RANK_TIE_RULES,
    ExamAnalysisSetting,
    ExamGradeBand,
    ExamSubjectThreshold,
    ExamTargetStudent,
)
from app.models.exam_foundation import Student, SubjectScoreSetting
from app.models.exam_scores import ExamScore, ExamScoreSetting
from app.models.user import User
from app.services.exam import get_exam
from app.services.exam_scopes import (
    exam_roles,
    require_student_visible,
    visible_class_ids,
    visible_grade_set,
)
from app.services.exam_scores import full_score_for

DEFAULT_PASS_LINE = 60.0
DEFAULT_EXCELLENT_LINE = 85.0


def _round(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


def _fmt_num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(round(value, 2))


# ── 基础加载 ──────────────────────────────
def _participants(db: Session, exam: Exam) -> list[ExamParticipant]:
    return list(
        db.scalars(
            select(ExamParticipant)
            .where(ExamParticipant.exam_id == exam.id)
            .order_by(ExamParticipant.id)
        ).all()
    )


def _visible_participants(
    db: Session, user: User, exam: Exam,
    grade: int | None = None, class_unit_id: int | None = None,
) -> list[ExamParticipant]:
    """按可见范围过滤参试名单;显式筛的班级/年级超出范围时 403。"""
    class_ids = visible_class_ids(db, user)
    grade_set = visible_grade_set(db, user)
    if class_unit_id is not None:
        if class_ids is not None and class_unit_id not in class_ids:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "无权查看该班级(不在你的可见班级范围内)"
            )
    if grade is not None and grade_set is not None and grade not in grade_set:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "无权查看该年级(不在你的可见年级范围内)"
        )
    rows = _participants(db, exam)
    classes = {
        c.id: c
        for c in db.scalars(select(ClassUnit)).all()
    }
    out = []
    for p in rows:
        if class_ids is not None and p.class_unit_id not in class_ids:
            continue
        cls = classes.get(p.class_unit_id)
        if grade is not None and (cls is None or cls.grade != grade):
            continue
        if grade_set is not None:
            if cls is None or cls.grade not in grade_set:
                continue
        if class_unit_id is not None and p.class_unit_id != class_unit_id:
            continue
        out.append(p)
    return out


class _Context:
    """一次分析共用的数据:名单、学生、班级、科目、成绩、阈值、缺考口径。"""

    def __init__(self, db: Session, exam: Exam, participants: list[ExamParticipant]):
        self.db = db
        self.exam = exam
        self.participants = participants
        self.student_ids = [p.student_id for p in participants]
        self.students = {
            s.id: s
            for s in db.scalars(
                select(Student).where(Student.id.in_(self.student_ids))
            ).all()
        } if self.student_ids else {}
        self.classes = {c.id: c for c in db.scalars(select(ClassUnit)).all()}
        self.subjects = list(
            db.scalars(
                select(ExamSubject)
                .where(ExamSubject.exam_id == exam.id)
                .order_by(ExamSubject.exam_date, ExamSubject.start_time)
            ).all()
        )
        self.subject_names = {
            s.id: s.name
            for s in db.scalars(
                select(Subject).where(
                    Subject.id.in_({r.subject_id for r in self.subjects})
                )
            ).all()
        } if self.subjects else {}
        self.score_rows = {
            (r.student_id, r.subject_id): r
            for r in db.scalars(
                select(ExamScore).where(ExamScore.exam_id == exam.id)
            ).all()
        }
        setting = db.scalar(
            select(ExamScoreSetting).where(ExamScoreSetting.exam_id == exam.id)
        )
        self.absent_counts = setting.absent_counts if setting else False
        thresholds = db.scalars(
            select(ExamSubjectThreshold).where(
                ExamSubjectThreshold.exam_id == exam.id
            )
        ).all()
        self.threshold_map = {t.subject_id: t for t in thresholds}
        base_settings = {
            s.subject_id: s
            for s in db.scalars(
                select(SubjectScoreSetting).where(
                    SubjectScoreSetting.semester_id == exam.semester_id
                )
            ).all()
        }
        self.base_settings = base_settings

    def counted_value(self, student_id: int, subject_id: int) -> float | None:
        """该生该科计入统计的分数;不计入时回传 None。

        免考永不计入;缺考按 absent_counts 计入为 0 或不计入;
        作弊已按 cheating_score_mode 折算进 score(0 计入,空不计入)。
        """
        row = self.score_rows.get((student_id, subject_id))
        if row is None:
            return None
        if row.status == "免考":
            return None
        if row.status == "缺考":
            return 0.0 if self.absent_counts else None
        return row.score

    def pass_line(self, subject_id: int) -> float:
        t = self.threshold_map.get(subject_id)
        if t is not None and t.pass_line is not None:
            return t.pass_line
        base = self.base_settings.get(subject_id)
        if base is not None:
            return base.pass_line
        return DEFAULT_PASS_LINE

    def excellent_line(self, subject_id: int) -> float:
        t = self.threshold_map.get(subject_id)
        if t is not None and t.excellent_line is not None:
            return t.excellent_line
        base = self.base_settings.get(subject_id)
        if base is not None:
            return base.excellent_line
        return DEFAULT_EXCELLENT_LINE

    def total_pass_line(self) -> float:
        return sum(self.pass_line(r.subject_id) for r in self.subjects)

    def total_excellent_line(self) -> float:
        return sum(self.excellent_line(r.subject_id) for r in self.subjects)

    def totals(self) -> dict[int, float]:
        """每名学生的总分;至少一科计入才有总分。"""
        out: dict[int, float] = {}
        for p in self.participants:
            values = [
                self.counted_value(p.student_id, r.subject_id)
                for r in self.subjects
            ]
            counted = [v for v in values if v is not None]
            if counted:
                out[p.student_id] = round(sum(counted), 2)
        return out

    def subject_values(self, subject_id: int) -> dict[int, float]:
        return {
            p.student_id: v
            for p in self.participants
            if (v := self.counted_value(p.student_id, subject_id)) is not None
        }

    def student_info(self, student_id: int) -> dict:
        student = self.students.get(student_id)
        participant = next(
            (p for p in self.participants if p.student_id == student_id), None
        )
        cls = self.classes.get(participant.class_unit_id) if participant else None
        return {
            "student_id": student_id,
            "student_no": student.student_no if student else "",
            "student_name": student.name if student else "",
            "class_name": cls.name if cls else "",
        }


def _stats(values: list[float]) -> dict:
    if not values:
        return {"count": 0, "avg": None, "max": None, "min": None, "std": None}
    return {
        "count": len(values),
        "avg": _round(sum(values) / len(values)),
        "max": _round(max(values)),
        "min": _round(min(values)),
        "std": _round(statistics.pstdev(values)) if len(values) > 1 else 0.0,
    }


def _rates(values: list[float], pass_line: float, excellent_line: float) -> dict:
    if not values:
        return {"pass_rate": 0.0, "excellent_rate": 0.0, "low_rate": 0.0}
    n = len(values)
    passed = sum(1 for v in values if v >= pass_line)
    excellent = sum(1 for v in values if v >= excellent_line)
    low = sum(1 for v in values if v < pass_line)
    return {
        "pass_rate": round(passed / n * 100, 2),
        "excellent_rate": round(excellent / n * 100, 2),
        "low_rate": round(low / n * 100, 2),
    }


def _assign_ranks(
    totals: dict[int, float], rule: str
) -> dict[int, int]:
    """按总分从高到低排名;dense 同分同名次,competition 同分并列占位。"""
    ordered = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
    ranks: dict[int, int] = {}
    prev_value: float | None = None
    prev_rank = 0
    for idx, (sid, value) in enumerate(ordered, start=1):
        if prev_value is not None and value == prev_value:
            ranks[sid] = prev_rank
        else:
            rank = prev_rank + 1 if rule == "dense" else idx
            ranks[sid] = rank
            prev_rank = rank
        prev_value = value
    return ranks


def _rank_items(ctx: _Context, values: dict[int, float], rule: str) -> list[dict]:
    ranks = _assign_ranks(values, rule)
    items = []
    for sid, value in values.items():
        info = ctx.student_info(sid)
        items.append({**info, "total": _round(value), "rank": ranks[sid]})
    items.sort(key=lambda x: (x["rank"], x["student_no"]))
    return items


# ── 分析设置(KW-41~45 共用) ──────────────────────────────
def get_analysis_settings(db: Session, exam: Exam) -> ExamAnalysisSetting:
    row = db.scalar(
        select(ExamAnalysisSetting).where(ExamAnalysisSetting.exam_id == exam.id)
    )
    if row is not None:
        return row
    return ExamAnalysisSetting(
        exam_id=exam.id, rank_tie_rule="dense", segment_size=10,
        critical_total_line=None, critical_margin=5, subject_critical_margin=5,
    )


def analysis_settings_out(exam: Exam, row: ExamAnalysisSetting) -> dict:
    return {
        "exam_id": exam.id,
        "rank_tie_rule": row.rank_tie_rule,
        "segment_size": row.segment_size,
        "critical_total_line": row.critical_total_line,
        "critical_margin": row.critical_margin,
        "subject_critical_margin": row.subject_critical_margin,
    }


def upsert_analysis_settings(
    db: Session, exam: Exam, rank_tie_rule: str, segment_size: int,
    critical_total_line: float | None, critical_margin: float,
    subject_critical_margin: float,
) -> ExamAnalysisSetting:
    if rank_tie_rule not in RANK_TIE_RULES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "并列名次规则只能是 dense 或 competition"
        )
    if segment_size is None or int(segment_size) < 1 or int(segment_size) > 100:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "分段粒度须在 1 到 100 分之间"
        )
    if critical_margin is None or critical_margin < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "临界浮动分值不能小于 0")
    if subject_critical_margin is None or subject_critical_margin < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "单科临界浮动分值不能小于 0")
    if critical_total_line is not None and critical_total_line < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "总分临界线不能小于 0")
    row = db.scalar(
        select(ExamAnalysisSetting).where(ExamAnalysisSetting.exam_id == exam.id)
    )
    if row is None:
        row = ExamAnalysisSetting(exam_id=exam.id)
        db.add(row)
    row.rank_tie_rule = rank_tie_rule
    row.segment_size = int(segment_size)
    row.critical_total_line = critical_total_line
    row.critical_margin = critical_margin
    row.subject_critical_margin = subject_critical_margin
    db.commit()
    db.refresh(row)
    return row


# ── 科目阈值覆盖(KW-43) ──────────────────────────────
def list_thresholds(db: Session, exam: Exam) -> list[dict]:
    rows = db.scalars(
        select(ExamSubjectThreshold)
        .where(ExamSubjectThreshold.exam_id == exam.id)
        .order_by(ExamSubjectThreshold.subject_id)
    ).all()
    ctx_subjects = {
        r.subject_id: r for r in db.scalars(
            select(ExamSubject).where(ExamSubject.exam_id == exam.id)
        ).all()
    }
    names = {
        s.id: s.name
        for s in db.scalars(
            select(Subject).where(
                Subject.id.in_({r.subject_id for r in rows})
            )
        ).all()
    } if rows else {}
    return [
        {
            "id": r.id,
            "exam_id": r.exam_id,
            "subject_id": r.subject_id,
            "subject_name": names.get(r.subject_id, ""),
            "pass_line": r.pass_line,
            "excellent_line": r.excellent_line,
        }
        for r in rows
    ]


def replace_thresholds(
    db: Session, exam: Exam, items: list[dict]
) -> list[dict]:
    """全量替换本次考试的科目阈值覆盖;空清单即清空全部覆盖。"""
    valid_subjects = {
        r.subject_id
        for r in db.scalars(
            select(ExamSubject).where(ExamSubject.exam_id == exam.id)
        ).all()
    }
    seen: set[int] = set()
    for item in items:
        sid = item["subject_id"]
        if sid not in valid_subjects:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "阈值清单含本次考试以外的科目")
        if sid in seen:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "阈值清单含重复科目")
        seen.add(sid)
        for key in ("pass_line", "excellent_line"):
            value = item.get(key)
            if value is not None and value < 0:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "及格线与优秀线不能小于 0")
    db.query(ExamSubjectThreshold).filter(
        ExamSubjectThreshold.exam_id == exam.id
    ).delete(synchronize_session=False)
    for item in items:
        db.add(ExamSubjectThreshold(
            exam_id=exam.id,
            subject_id=item["subject_id"],
            pass_line=item.get("pass_line"),
            excellent_line=item.get("excellent_line"),
        ))
    db.commit()
    return list_thresholds(db, exam)


# ── KW-41 汇总 ──────────────────────────────
def analysis_summary(
    db: Session, user: User, exam: Exam,
    scope: str, grade: int | None, class_unit_id: int | None,
) -> dict:
    if scope not in ("grade", "class"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "汇总层级只能是年级或班级")
    if scope == "class" and class_unit_id is None:
        # 未指明班级时按年级口径汇总(全部可见学生),scope 原样回传。
        scope = "grade"
    participants = _visible_participants(db, user, exam, grade, class_unit_id)
    ctx = _Context(db, exam, participants)
    totals = ctx.totals()
    total_values = list(totals.values())
    total_stats = _stats(total_values)
    total_rates = _rates(
        total_values, ctx.total_pass_line(), ctx.total_excellent_line()
    )
    total_stats.update(total_rates)
    subjects_out = []
    for r in ctx.subjects:
        values = list(ctx.subject_values(r.subject_id).values())
        item = _stats(values)
        item.update(_rates(values, ctx.pass_line(r.subject_id), ctx.excellent_line(r.subject_id)))
        subjects_out.append({
            "subject_id": r.subject_id,
            "subject_name": ctx.subject_names.get(r.subject_id, ""),
            **item,
        })
    return {
        "scope": scope,
        "totals": {
            "count": total_stats["count"],
            "avg": total_stats["avg"],
            "max": total_stats["max"],
            "min": total_stats["min"],
            "std": total_stats["std"],
        },
        "subjects": subjects_out,
    }


# ── KW-42 排名 ──────────────────────────────
def analysis_rankings(
    db: Session, user: User, exam: Exam,
    scope: str, subject_id: int | None,
    grade: int | None, class_unit_id: int | None,
) -> dict:
    if scope not in ("grade", "class"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "排名范围只能是年级或班级")
    if subject_id is not None:
        valid = {
            r.subject_id
            for r in db.scalars(
                select(ExamSubject).where(ExamSubject.exam_id == exam.id)
            ).all()
        }
        if subject_id not in valid:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到该考试科目")
    participants = _visible_participants(db, user, exam, grade, class_unit_id)
    ctx = _Context(db, exam, participants)
    settings = get_analysis_settings(db, exam)
    items: list[dict] = []
    if scope == "grade":
        values = (
            ctx.totals() if subject_id is None
            else ctx.subject_values(subject_id)
        )
        items = _rank_items(ctx, values, settings.rank_tie_rule)
    else:
        # 班级排名:按学生快照班级分组,组内排名;未指明班级时各班分别排名。
        groups: dict[int, dict[int, float]] = {}
        values = (
            ctx.totals() if subject_id is None
            else ctx.subject_values(subject_id)
        )
        for p in participants:
            if p.student_id in values:
                groups.setdefault(p.class_unit_id, {})[p.student_id] = values[p.student_id]
        for group_values in groups.values():
            items.extend(_rank_items(ctx, group_values, settings.rank_tie_rule))
        items.sort(key=lambda x: (x["class_name"], x["rank"], x["student_no"]))
    return {"items": items, "total": len(items)}


# ── KW-44 分数段分布 ──────────────────────────────
def analysis_segments(
    db: Session, user: User, exam: Exam,
    subject_id: int | None, scope: str,
    grade: int | None, class_unit_id: int | None,
) -> dict:
    if scope not in ("grade", "class"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "分布范围只能是年级或班级")
    if scope == "class" and class_unit_id is None:
        scope = "grade"
    participants = _visible_participants(db, user, exam, grade, class_unit_id)
    ctx = _Context(db, exam, participants)
    settings = get_analysis_settings(db, exam)
    size = settings.segment_size
    if subject_id is None:
        values = list(ctx.totals().values())
        top = sum(full_score_for(db, exam, r.subject_id) for r in ctx.subjects)
    else:
        valid = {r.subject_id for r in ctx.subjects}
        if subject_id not in valid:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到该考试科目")
        values = list(ctx.subject_values(subject_id).values())
        top = full_score_for(db, exam, subject_id)
    segments = []
    total = len(values)
    lo = 0.0
    while lo < top:
        hi = min(lo + size, top)
        is_last = hi >= top
        if is_last:
            count = sum(1 for v in values if lo <= v <= hi)
        else:
            count = sum(1 for v in values if lo <= v < hi)
        segments.append({
            "label": f"{_fmt_num(lo)}-{_fmt_num(hi)}",
            "count": count,
            "pct": round(count / total * 100, 2) if total else 0.0,
        })
        lo = hi
    return {"segments": segments}


# ── KW-45 临界生 ──────────────────────────────
def analysis_critical(db: Session, user: User, exam: Exam) -> dict:
    participants = _visible_participants(db, user, exam)
    ctx = _Context(db, exam, participants)
    settings = get_analysis_settings(db, exam)
    totals = ctx.totals()
    items = []
    for p in participants:
        sid = p.student_id
        total = totals.get(sid)
        gap_to_line = None
        total_hit = False
        if settings.critical_total_line is not None and total is not None:
            gap_to_line = _round(total - settings.critical_total_line)
            total_hit = abs(total - settings.critical_total_line) <= settings.critical_margin
        subject_gaps = []
        for r in ctx.subjects:
            value = ctx.counted_value(sid, r.subject_id)
            if value is None:
                continue
            gap = _round(value - ctx.pass_line(r.subject_id))
            if abs(value - ctx.pass_line(r.subject_id)) <= settings.subject_critical_margin:
                subject_gaps.append({
                    "subject_name": ctx.subject_names.get(r.subject_id, ""),
                    "score": _round(value),
                    "gap": gap,
                })
        if not total_hit and not subject_gaps:
            continue
        info = ctx.student_info(sid)
        items.append({
            **info,
            "total": _round(total) if total is not None else None,
            "gap_to_line": gap_to_line,
            "subject_gaps": subject_gaps,
        })
    items.sort(key=lambda x: (x["class_name"], x["student_no"]))
    return {"items": items}


# ── KW-46 目标生 ──────────────────────────────
def list_target_students(db: Session, user: User, exam: Exam) -> list[dict]:
    participants = _visible_participants(db, user, exam)
    visible_ids = {p.student_id for p in participants}
    rows = db.scalars(
        select(ExamTargetStudent)
        .where(ExamTargetStudent.exam_id == exam.id)
        .order_by(ExamTargetStudent.id)
    ).all()
    ctx = _Context(db, exam, participants)
    out = []
    for r in rows:
        if r.student_id not in visible_ids:
            continue
        info = ctx.student_info(r.student_id)
        out.append({
            "id": r.id,
            "exam_id": r.exam_id,
            "student_id": r.student_id,
            "student_no": info["student_no"],
            "student_name": info["student_name"],
            "class_name": info["class_name"],
            "target_total": r.target_total,
            "note": r.note,
        })
    return out


def create_target_student(
    db: Session, exam: Exam, student_id: int,
    target_total: float | None, note: str | None,
) -> ExamTargetStudent:
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到学生")
    in_list = db.scalar(
        select(ExamParticipant.id).where(
            ExamParticipant.exam_id == exam.id,
            ExamParticipant.student_id == student_id,
        )
    )
    if in_list is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "该学生不在本次考试参试名单中"
        )
    dup = db.scalar(
        select(ExamTargetStudent.id).where(
            ExamTargetStudent.exam_id == exam.id,
            ExamTargetStudent.student_id == student_id,
        )
    )
    if dup is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "该学生已在目标生名单中")
    if target_total is not None and target_total < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "目标总分不能小于 0")
    row = ExamTargetStudent(
        exam_id=exam.id, student_id=student_id,
        target_total=target_total, note=note,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_target_student(db: Session, exam: Exam, tid: int) -> None:
    row = db.get(ExamTargetStudent, tid)
    if row is None or row.exam_id != exam.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到目标生")
    db.delete(row)
    db.commit()


def target_tracking(db: Session, user: User, exam: Exam) -> dict:
    participants = _visible_participants(db, user, exam)
    ctx = _Context(db, exam, participants)
    totals = ctx.totals()
    rows = db.scalars(
        select(ExamTargetStudent)
        .where(ExamTargetStudent.exam_id == exam.id)
        .order_by(ExamTargetStudent.id)
    ).all()
    visible_ids = {p.student_id for p in participants}
    items = []
    for r in rows:
        if r.student_id not in visible_ids:
            continue
        info = ctx.student_info(r.student_id)
        total = totals.get(r.student_id)
        weak = []
        for subj in ctx.subjects:
            value = ctx.counted_value(r.student_id, subj.subject_id)
            if value is not None and value < ctx.pass_line(subj.subject_id):
                weak.append(ctx.subject_names.get(subj.subject_id, ""))
        reached = (
            total is not None
            and r.target_total is not None
            and total >= r.target_total
        )
        items.append({
            **info,
            "target_total": r.target_total,
            "total": _round(total) if total is not None else None,
            "reached": reached,
            "weak_subjects": weak,
        })
    items.sort(key=lambda x: (x["class_name"], x["student_no"]))
    return {"items": items}


# ── KW-47 进退步 ──────────────────────────────
def _find_previous_exam(db: Session, exam: Exam) -> Exam | None:
    """上一次同类考试:同学期、同 exam_type、创建时间早于本次、
    状态已到“已发布成绩”或之后;取最近的一次。"""
    published_idx = EXAM_STATUS_ORDER.index("已发布成绩")
    candidates = db.scalars(
        select(Exam).where(
            Exam.semester_id == exam.semester_id,
            Exam.exam_type == exam.exam_type,
            Exam.id != exam.id,
        )
    ).all()
    earlier = [
        e for e in candidates
        if (e.created_at, e.id) < (exam.created_at, exam.id)
        and EXAM_STATUS_ORDER.index(e.status) >= published_idx
    ]
    if not earlier:
        return None
    earlier.sort(key=lambda e: (e.created_at, e.id), reverse=True)
    return earlier[0]


def analysis_progress(db: Session, user: User, exam: Exam) -> dict:
    prev = _find_previous_exam(db, exam)
    if prev is None:
        return {
            "items": [], "top_improved": [], "top_declined": [],
            "message": "暂无上次同类考试，无法对比",
        }
    settings = get_analysis_settings(db, exam)
    cur_ctx = _Context(db, exam, _visible_participants(db, user, exam))
    prev_ctx = _Context(db, prev, _visible_participants(db, user, prev))
    cur_totals = cur_ctx.totals()
    prev_totals = prev_ctx.totals()
    cur_ranks = _assign_ranks(cur_totals, settings.rank_tie_rule)
    prev_ranks = _assign_ranks(prev_totals, settings.rank_tie_rule)
    items = []
    for sid in sorted(
        set(cur_totals) & set(prev_totals),
        key=lambda s: (cur_ctx.student_info(s)["class_name"], cur_ctx.student_info(s)["student_no"]),
    ):
        info = cur_ctx.student_info(sid)
        delta = prev_ranks[sid] - cur_ranks[sid]
        items.append({
            **info,
            "prev_total": _round(prev_totals[sid]),
            "total": _round(cur_totals[sid]),
            "prev_rank": prev_ranks[sid],
            "rank": cur_ranks[sid],
            "delta": delta,
        })
    items.sort(key=lambda x: (-x["delta"], x["student_no"]))
    top_improved = [i for i in items if i["delta"] > 0][:10]
    top_declined = sorted(
        [i for i in items if i["delta"] < 0],
        key=lambda x: (x["delta"], x["student_no"]),
    )[:10]
    return {
        "items": items,
        "top_improved": top_improved,
        "top_declined": top_declined,
        "message": None,
    }


# ── KW-48 质量对比 ──────────────────────────────
def require_quality_compare_visible(db: Session, user: User, exam: Exam, grade: int | None) -> None:
    """仅 admin/director 与年级组长本年级可见,其余 403。"""
    roles = exam_roles(db, user)
    if "admin" in roles or "academic" in roles:
        return
    if "grade_leader" in roles:
        grade_set = visible_grade_set(db, user)
        if grade is not None:
            if grade_set is not None and grade not in grade_set:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN, "年级组长只能查看本年级的质量对比"
                )
            return
        return
    raise HTTPException(
        status.HTTP_403_FORBIDDEN, "质量对比仅对管理角色开放"
    )


def quality_compare(
    db: Session, user: User, exam: Exam, grade: int | None
) -> dict:
    participants = _visible_participants(db, user, exam, grade)
    ctx = _Context(db, exam, participants)
    class_ids = sorted(
        {p.class_unit_id for p in participants},
        key=lambda cid: ctx.classes[cid].name if cid in ctx.classes else "",
    )
    subjects_out = []
    for r in ctx.subjects:
        classes_out = []
        for cid in class_ids:
            members = [p for p in participants if p.class_unit_id == cid]
            sub_ctx = _Context(db, exam, members)
            values = list(sub_ctx.subject_values(r.subject_id).values())
            rates = _rates(values, ctx.pass_line(r.subject_id), ctx.excellent_line(r.subject_id))
            classes_out.append({
                "class_unit_id": cid,
                "class_name": ctx.classes[cid].name if cid in ctx.classes else "",
                "avg": _stats(values)["avg"],
                "pass_rate": rates["pass_rate"],
                "excellent_rate": rates["excellent_rate"],
            })
        subjects_out.append({
            "subject_id": r.subject_id,
            "subject_name": ctx.subject_names.get(r.subject_id, ""),
            "classes": classes_out,
        })
    classes_out = []
    for cid in class_ids:
        members = [p for p in participants if p.class_unit_id == cid]
        sub_ctx = _Context(db, exam, members)
        subjects_of_class = []
        for r in ctx.subjects:
            values = list(sub_ctx.subject_values(r.subject_id).values())
            rates = _rates(values, ctx.pass_line(r.subject_id), ctx.excellent_line(r.subject_id))
            subjects_of_class.append({
                "subject_id": r.subject_id,
                "subject_name": ctx.subject_names.get(r.subject_id, ""),
                "avg": _stats(values)["avg"],
                "pass_rate": rates["pass_rate"],
            })
        classes_out.append({
            "class_unit_id": cid,
            "class_name": ctx.classes[cid].name if cid in ctx.classes else "",
            "subjects": subjects_of_class,
        })
    return {"subjects": subjects_out, "classes": classes_out}


# ── KW-49 个人趋势 ──────────────────────────────
def student_trend(db: Session, user: User, exam: Exam, student_id: int) -> dict:
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到学生")
    require_student_visible(db, user, student)
    exams = db.scalars(
        select(Exam)
        .where(Exam.semester_id == exam.semester_id)
        .order_by(Exam.created_at, Exam.id)
    ).all()
    participant_exam_ids = {
        e_id for (e_id,) in db.execute(
            select(ExamParticipant.exam_id).where(
                ExamParticipant.student_id == student_id
            )
        ).all()
    }
    out_exams = []
    for e in exams:
        if e.id not in participant_exam_ids:
            continue
        parts = [
            p for p in _participants(db, e) if p.student_id == student_id
        ]
        ctx = _Context(db, e, parts)
        totals = ctx.totals()
        subjects: dict[str, float | None] = {}
        for r in ctx.subjects:
            row = ctx.score_rows.get((student_id, r.subject_id))
            if row is None:
                continue
            subjects[ctx.subject_names.get(r.subject_id, "")] = _round(
                ctx.counted_value(student_id, r.subject_id)
            )
        subject_dates = [
            r.exam_date for r in ctx.subjects if r.exam_date is not None
        ]
        exam_date = (
            min(subject_dates).isoformat() if subject_dates
            else (e.created_at.date().isoformat() if e.created_at else None)
        )
        out_exams.append({
            "exam_id": e.id,
            "exam_name": e.name,
            "exam_date": exam_date,
            "total": _round(totals.get(student_id)) if student_id in totals else None,
            "subjects": subjects,
        })
    return {
        "student_id": student.id,
        "student_name": student.name,
        "exams": out_exams,
    }


# ── KW-50 等第转换 ──────────────────────────────
def _default_band_dicts(exam_id: int, subject_id: int | None) -> list[dict]:
    return [
        {
            "id": 0,
            "exam_id": exam_id,
            "subject_id": subject_id,
            "grade_label": label,
            "min_score": low,
            "max_score": high,
        }
        for label, low, high in DEFAULT_GRADE_BANDS
    ]


def resolve_grade_bands(
    db: Session, exam: Exam, subject_id: int | None
) -> list[dict]:
    """取等第档:科目档 > 总分档 > 默认档;未存过档时回传默认档(不入库)。"""
    rows = db.scalars(
        select(ExamGradeBand)
        .where(
            ExamGradeBand.exam_id == exam.id,
            ExamGradeBand.subject_id == subject_id,
        )
        .order_by(ExamGradeBand.min_score.desc())
    ).all()
    if rows:
        return [
            {
                "id": r.id, "exam_id": r.exam_id, "subject_id": r.subject_id,
                "grade_label": r.grade_label, "min_score": r.min_score,
                "max_score": r.max_score,
            }
            for r in rows
        ]
    if subject_id is not None:
        total_rows = db.scalars(
            select(ExamGradeBand)
            .where(
                ExamGradeBand.exam_id == exam.id,
                ExamGradeBand.subject_id.is_(None),
            )
            .order_by(ExamGradeBand.min_score.desc())
        ).all()
        if total_rows:
            return [
                {
                    "id": r.id, "exam_id": r.exam_id, "subject_id": r.subject_id,
                    "grade_label": r.grade_label, "min_score": r.min_score,
                    "max_score": r.max_score,
                }
                for r in total_rows
            ]
    return _default_band_dicts(exam.id, subject_id)


def _grade_of(score: float, bands: list[dict]) -> str | None:
    """按 min_score 从高到低,分数大于等于下限的第一档;都不满足时兜底最低档。"""
    ordered = sorted(bands, key=lambda b: b["min_score"], reverse=True)
    for band in ordered:
        if score >= band["min_score"]:
            return band["grade_label"]
    return ordered[-1]["grade_label"] if ordered else None


def list_grade_bands(db: Session, exam: Exam, subject_id: int | None) -> list[dict]:
    return resolve_grade_bands(db, exam, subject_id)


def replace_grade_bands(db: Session, exam: Exam, items: list[dict]) -> list[dict]:
    """按档位所属范围(subject_id 含空)逐范围全量替换;未出现的范围不动。"""
    valid_subjects = {
        r.subject_id
        for r in db.scalars(
            select(ExamSubject).where(ExamSubject.exam_id == exam.id)
        ).all()
    }
    scopes: dict[int | None, list[dict]] = {}
    for item in items:
        sid = item.get("subject_id")
        if sid is not None and sid not in valid_subjects:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "等第档清单含本次考试以外的科目")
        label = item["grade_label"]
        low = item["min_score"]
        high = item["max_score"]
        if low > high:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"等第「{label}」下限不能高于上限"
            )
        scopes.setdefault(sid, []).append(item)
    for sid, scope_items in scopes.items():
        labels = [i["grade_label"] for i in scope_items]
        if len(labels) != len(set(labels)):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "同一范围内等第不能重复")
        if sid is None:
            db.query(ExamGradeBand).filter(
                ExamGradeBand.exam_id == exam.id,
                ExamGradeBand.subject_id.is_(None),
            ).delete(synchronize_session=False)
        else:
            db.query(ExamGradeBand).filter(
                ExamGradeBand.exam_id == exam.id,
                ExamGradeBand.subject_id == sid,
            ).delete(synchronize_session=False)
        for item in scope_items:
            db.add(ExamGradeBand(
                exam_id=exam.id,
                subject_id=sid,
                grade_label=item["grade_label"],
                min_score=item["min_score"],
                max_score=item["max_score"],
            ))
    db.commit()
    # 回传本次考试全部已存档位;未存过的范围前端以 GET 取默认档。
    rows = db.scalars(
        select(ExamGradeBand)
        .where(ExamGradeBand.exam_id == exam.id)
        .order_by(ExamGradeBand.subject_id.is_(None), ExamGradeBand.min_score.desc())
    ).all()
    return [
        {
            "id": r.id, "exam_id": r.exam_id, "subject_id": r.subject_id,
            "grade_label": r.grade_label, "min_score": r.min_score,
            "max_score": r.max_score,
        }
        for r in rows
    ]


def grade_distribution(
    db: Session, user: User, exam: Exam, subject_id: int | None
) -> dict:
    participants = _visible_participants(db, user, exam)
    ctx = _Context(db, exam, participants)
    bands = resolve_grade_bands(db, exam, subject_id)
    if subject_id is None:
        values = list(ctx.totals().values())
    else:
        valid = {r.subject_id for r in ctx.subjects}
        if subject_id not in valid:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到该考试科目")
        values = list(ctx.subject_values(subject_id).values())
    counts = {b["grade_label"]: 0 for b in bands}
    for v in values:
        label = _grade_of(v, bands)
        if label is not None:
            counts[label] = counts.get(label, 0) + 1
    total = len(values)
    ordered = sorted(bands, key=lambda b: b["min_score"], reverse=True)
    return {
        "bands": [
            {
                "grade_label": b["grade_label"],
                "count": counts.get(b["grade_label"], 0),
                "pct": round(counts.get(b["grade_label"], 0) / total * 100, 2) if total else 0.0,
            }
            for b in ordered
        ]
    }


# ── KW-51 报表包 ──────────────────────────────
def _sheet_header(ws, headers: list[str]) -> None:
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)


def build_report_pack(db: Session, user: User, exam: Exam) -> bytes:
    """质量分析会报表包:年级汇总、班级对比、学科分析、临界生、目标生。"""
    summary = analysis_summary(db, user, exam, "grade", None, None)
    quality = quality_compare(db, user, exam, None) if _can_quality_compare(db, user) else None
    critical = analysis_critical(db, user, exam)
    tracking = target_tracking(db, user, exam)
    wb = Workbook()
    # 年级汇总
    ws = wb.active
    ws.title = "年级汇总"
    _sheet_header(ws, ["科目", "人数", "平均分", "最高分", "最低分", "标准差", "及格率(%)", "优秀率(%)", "低分率(%)"])
    totals = summary["totals"]
    ws.append([
        "总分", totals["count"], totals["avg"], totals["max"], totals["min"], totals["std"],
        "", "", "",
    ])
    for s in summary["subjects"]:
        ws.append([
            s["subject_name"], s["count"], s["avg"], s["max"], s["min"], s["std"],
            s["pass_rate"], s["excellent_rate"], s["low_rate"],
        ])
    # 班级对比
    ws = wb.create_sheet("班级对比")
    _sheet_header(ws, ["班级", "科目", "人数", "平均分", "最高分", "最低分", "及格率(%)", "优秀率(%)"])
    participants = _visible_participants(db, user, exam)
    ctx = _Context(db, exam, participants)
    for cid in sorted(
        {p.class_unit_id for p in participants},
        key=lambda c: ctx.classes[c].name if c in ctx.classes else "",
    ):
        members = [p for p in participants if p.class_unit_id == cid]
        sub_ctx = _Context(db, exam, members)
        class_name = ctx.classes[cid].name if cid in ctx.classes else ""
        for r in ctx.subjects:
            values = list(sub_ctx.subject_values(r.subject_id).values())
            st = _stats(values)
            rates = _rates(values, ctx.pass_line(r.subject_id), ctx.excellent_line(r.subject_id))
            ws.append([
                class_name, ctx.subject_names.get(r.subject_id, ""), st["count"],
                st["avg"], st["max"], st["min"], rates["pass_rate"], rates["excellent_rate"],
            ])
    # 学科分析
    ws = wb.create_sheet("学科分析")
    _sheet_header(ws, ["科目", "班级", "平均分", "及格率(%)", "优秀率(%)"])
    if quality is not None:
        for subj in quality["subjects"]:
            for cls in subj["classes"]:
                ws.append([
                    subj["subject_name"], cls["class_name"], cls["avg"],
                    cls["pass_rate"], cls["excellent_rate"],
                ])
    # 临界生
    ws = wb.create_sheet("临界生")
    _sheet_header(ws, ["学号", "姓名", "班级", "总分", "距总分临界线", "单科临界"])
    for item in critical["items"]:
        ws.append([
            item["student_no"], item["student_name"], item["class_name"],
            item["total"], item["gap_to_line"],
            "、".join(
                f"{g['subject_name']}{g['score']}分(距及格线{g['gap']}分)"
                for g in item["subject_gaps"]
            ),
        ])
    # 目标生
    ws = wb.create_sheet("目标生")
    _sheet_header(ws, ["学号", "姓名", "班级", "目标总分", "实际总分", "是否达标", "短板科目"])
    for item in tracking["items"]:
        ws.append([
            item["student_no"], item["student_name"], item["class_name"],
            item["target_total"], item["total"],
            "是" if item["reached"] else "否",
            "、".join(item["weak_subjects"]),
        ])
    for sheet in wb.worksheets:
        for col in sheet.columns:
            sheet.column_dimensions[col[0].column_letter].width = 16
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _can_quality_compare(db: Session, user: User) -> bool:
    roles = exam_roles(db, user)
    return bool({"admin", "academic", "grade_leader"} & roles)


def get_exam_for_api(db: Session, exam_id: int) -> Exam:
    return get_exam(db, exam_id)
