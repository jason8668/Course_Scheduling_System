"""成绩单与查询服务(KW-52~56):班级成绩单、个人成绩单、教师端查询、
学生/家长自助查询、学生/家长账号开通、成绩归档表导出。

总分与排名复用第 7 批 exam_analysis 的口径(_Context 总分、
_assign_ranks 并列规则、分析设置的 rank_tie_rule),不在此另写一套:
总分按分析口径计入(缺考按 absent_counts、免考永不计入),排名在
全校参试名单上算,避免按可见范围切片后名次失真。

发布可见性(KW-39 publish_order 在此落地):
- 教师端不受 publish_order 限制,只看发布批次覆盖的班级;
  管理员/教务不限。
- 学生/家长:teachers_first(默认)须同时满足批次覆盖与考试状态
  已到"已发布成绩";sync 只须批次覆盖;未发布一律 403。
"""

import io
import secrets
import string

from fastapi import HTTPException, status
from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.models.basedata import ClassUnit, Subject, Teacher
from app.models.exam import EXAM_STATUS_ORDER, Exam, ExamParticipant, ExamSubject
from app.models.exam_foundation import ParentContact, Student
from app.models.exam_reports import ExamAccountLink, ExamReportSetting
from app.models.semester import Semester
from app.models.user import Role, User
from app.services.exam_analysis import (
    _Context,
    _assign_ranks,
    _participants,
    get_analysis_settings,
)
from app.services.exam_publish import (
    get_settings as get_publish_settings,
)
from app.services.exam_publish import is_score_published
from app.services.exam_scores import teaching_pairs
from app.services.exam_scopes import (
    can_manage_students,
    require_student_visible,
    visible_class_ids,
)
from app.services.users import create_user


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


def _family_can_view(db: Session, exam: Exam, participant: ExamParticipant) -> bool:
    """学生/家长是否可见该生本次考试成绩。

    teachers_first(默认):批次覆盖 + 考试状态已到"已发布成绩";
    sync:只要批次覆盖;未发布一律不可见。
    """
    if not _is_class_published(db, exam, participant.class_unit_id):
        return False
    setting = get_publish_settings(db, exam)
    order = setting.publish_order if setting else "teachers_first"
    if order == "sync":
        return True
    return EXAM_STATUS_ORDER.index(exam.status) >= EXAM_STATUS_ORDER.index(
        "已发布成绩"
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


def _apply_parent_rank_settings(card: dict, setting: ExamReportSetting) -> dict:
    """家长版/学生自助版:按设置决定是否保留排名键。"""
    out = dict(card)
    if not setting.parent_show_class_rank:
        out.pop("class_rank", None)
    if not setting.parent_show_grade_rank:
        out.pop("grade_rank", None)
    return out


# ── 成绩单显示设置(KW-53) ──────────────────────────────
def get_report_setting(db: Session, exam: Exam) -> ExamReportSetting:
    row = db.scalar(
        select(ExamReportSetting).where(ExamReportSetting.exam_id == exam.id)
    )
    if row is not None:
        return row
    return ExamReportSetting(
        exam_id=exam.id,
        parent_show_grade_rank=False,
        parent_show_class_rank=False,
    )


def report_setting_out(exam: Exam, row: ExamReportSetting) -> dict:
    return {
        "exam_id": exam.id,
        "parent_show_grade_rank": row.parent_show_grade_rank,
        "parent_show_class_rank": row.parent_show_class_rank,
    }


def upsert_report_setting(
    db: Session, exam: Exam,
    parent_show_grade_rank: bool, parent_show_class_rank: bool,
) -> ExamReportSetting:
    row = db.scalar(
        select(ExamReportSetting).where(ExamReportSetting.exam_id == exam.id)
    )
    if row is None:
        row = ExamReportSetting(exam_id=exam.id)
        db.add(row)
    row.parent_show_grade_rank = parent_show_grade_rank
    row.parent_show_class_rank = parent_show_class_rank
    db.flush()
    return row


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


# ── KW-55 学生/家长自助查询 ──────────────────────────────
def _require_family_role(user: User) -> None:
    names = user.role_names
    if Role.student.value not in names and Role.parent.value not in names:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "只有学生与家长账号可以查询本人成绩"
        )


def _linked_student_ids(db: Session, user: User) -> list[int]:
    return list(
        db.scalars(
            select(ExamAccountLink.student_id).where(
                ExamAccountLink.user_id == user.id
            )
        ).all()
    )


def my_scores(db: Session, user: User, exam: Exam) -> dict:
    _require_family_role(user)
    participants = {
        p.student_id: p for p in _participants(db, exam)
    }
    mine = [
        sid for sid in _linked_student_ids(db, user) if sid in participants
    ]
    if not mine:
        return {"items": []}
    visible = [
        sid for sid in mine
        if _family_can_view(db, exam, participants[sid])
    ]
    if not visible:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "本次考试成绩尚未发布"
        )
    ctx, totals, class_ranks, grade_ranks = _report_context(db, exam)
    setting = get_report_setting(db, exam)
    items = []
    for sid in sorted(
        visible,
        key=lambda s: (
            ctx.students.get(s).student_no if ctx.students.get(s) else ""
        ),
    ):
        card = _student_card(
            ctx, totals, class_ranks, grade_ranks, participants[sid]
        )
        card = _apply_parent_rank_settings(card, setting)
        card.pop("class_name", None)
        items.append({
            "exam_id": exam.id,
            "exam_name": exam.name,
            **card,
        })
    return {"items": items}


def my_report_card(
    db: Session, user: User, exam: Exam, student_id: int,
) -> dict:
    _require_family_role(user)
    link = db.scalar(
        select(ExamAccountLink).where(
            ExamAccountLink.user_id == user.id,
            ExamAccountLink.student_id == student_id,
        )
    )
    if link is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "只能查看本人(孩子)的成绩单"
        )
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
    if not _family_can_view(db, exam, participant):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "本次考试成绩尚未发布"
        )
    ctx, totals, class_ranks, grade_ranks = _report_context(db, exam)
    setting = get_report_setting(db, exam)
    card = _student_card(
        ctx, totals, class_ranks, grade_ranks, participant
    )
    return _apply_parent_rank_settings(card, setting)


# ── KW-55 账号开通与管理 ──────────────────────────────
def _gen_password(length: int = 10) -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.isdigit() for c in password) and any(
            c.isalpha() for c in password
        ):
            return password


def _get_user_by_username(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == username))


def _has_link(db: Session, user_id: int, student_id: int) -> bool:
    return (
        db.scalar(
            select(ExamAccountLink.id).where(
                ExamAccountLink.user_id == user_id,
                ExamAccountLink.student_id == student_id,
            )
        )
        is not None
    )


def _add_link(
    db: Session, user_id: int, student_id: int,
    semester_id: int, relation: str,
) -> None:
    if _has_link(db, user_id, student_id):
        return
    db.add(ExamAccountLink(
        user_id=user_id, student_id=student_id,
        semester_id=semester_id, relation=relation,
    ))


def provision_accounts(db: Session, semester_id: int) -> dict:
    """教务一键按学期生成学生与家长账号;已存在账号跳过不重复建。

    学生账号用户名=学号;家长账号用户名=家长手机号,同一手机号多子女
    只建一个账号、关联多个学生。初始口令只在本次回传中出现一次,
    已存在账号不回传口令。首次登录须改密(must_change_password)。
    """
    semester = db.get(Semester, semester_id)
    if semester is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到学期")
    students = db.scalars(
        select(Student)
        .where(
            Student.semester_id == semester_id,
            Student.status == "在读",
        )
        .order_by(Student.student_no)
    ).all()
    credentials: list[dict] = []
    students_created = 0
    for student in students:
        existing = _get_user_by_username(db, student.student_no)
        if existing is not None:
            # 用户名已被占用:已关联则幂等跳过;被他人占用也跳过,不合并身份。
            continue
        password = _gen_password()
        user = create_user(
            db,
            username=student.student_no,
            password=password,
            roles=[Role.student],
            display_name=student.name,
            must_change_password=True,
        )
        _add_link(db, user.id, student.id, semester_id, "本人")
        students_created += 1
        credentials.append({
            "username": student.student_no,
            "role": "student",
            "initial_password": password,
            "student_name": student.name,
        })
    # 家长按手机号归并:同一手机号只建一个账号,关联全部子女。
    contacts = db.scalars(
        select(ParentContact)
        .join(Student, ParentContact.student_id == Student.id)
        .where(Student.semester_id == semester_id)
        .order_by(ParentContact.phone, ParentContact.id)
    ).all()
    by_phone: dict[str, list[tuple[Student, ParentContact]]] = {}
    students_by_id = {s.id: s for s in students}
    for contact in contacts:
        phone = (contact.phone or "").strip()
        if not phone:
            continue
        student = students_by_id.get(contact.student_id)
        if student is None:
            continue
        by_phone.setdefault(phone, []).append((student, contact))
    parents_created = 0
    for phone, pairs in by_phone.items():
        # 同一手机号同一子女去重(父亲/母亲留了同一号码时只关联一次)。
        seen: dict[int, str] = {}
        for student, contact in pairs:
            relation = (contact.relation or "").strip() or "其他"
            seen.setdefault(student.id, relation)
        existing = _get_user_by_username(db, phone)
        if existing is not None:
            if Role.parent.value not in existing.role_names:
                # 手机号与已有非家长账号冲突,不合并身份。
                continue
            for student_id, relation in seen.items():
                _add_link(db, existing.id, student_id, semester_id, relation)
            continue
        password = _gen_password()
        display_name = pairs[0][1].name or phone
        user = create_user(
            db,
            username=phone,
            password=password,
            roles=[Role.parent],
            display_name=display_name,
            must_change_password=True,
        )
        for student_id, relation in seen.items():
            _add_link(db, user.id, student_id, semester_id, relation)
        parents_created += 1
        credentials.append({
            "username": phone,
            "role": "parent",
            "initial_password": password,
            "student_name": "、".join(
                students_by_id[sid].name for sid in seen
            ),
        })
    db.flush()
    return {
        "students_created": students_created,
        "parents_created": parents_created,
        "credentials": credentials,
    }


def list_accounts(
    db: Session,
    semester_id: int | None,
    role: str | None,
    q: str | None,
) -> dict:
    if role is not None and role not in ("student", "parent"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "角色只能是 student 或 parent"
        )
    link_stmt = select(ExamAccountLink)
    if semester_id is not None:
        link_stmt = link_stmt.where(
            ExamAccountLink.semester_id == semester_id
        )
    links = db.scalars(link_stmt).all()
    student_ids = {link.student_id for link in links}
    students = {
        s.id: s
        for s in db.scalars(
            select(Student).where(Student.id.in_(student_ids))
        ).all()
    } if student_ids else {}
    by_user: dict[int, list[ExamAccountLink]] = {}
    for link in links:
        by_user.setdefault(link.user_id, []).append(link)
    users = db.scalars(
        select(User).where(User.id.in_(list(by_user)))
    ).all() if by_user else []
    items = []
    for user in sorted(users, key=lambda u: u.username):
        names = user.role_names
        user_role = (
            "student" if Role.student.value in names else "parent"
        )
        if role is not None and user_role != role:
            continue
        student_names = [
            students[link.student_id].name
            for link in by_user[user.id]
            if link.student_id in students
        ]
        if q:
            keyword = q.strip()
            if (
                keyword
                and keyword not in user.username
                and not any(keyword in name for name in student_names)
            ):
                continue
        items.append({
            "user_id": user.id,
            "username": user.username,
            "role": user_role,
            "student_names": student_names,
            "must_change_password": user.must_change_password,
        })
    return {"items": items, "total": len(items)}


def reset_account_password(
    db: Session, user_id: int, new_password: str,
) -> User:
    user = db.get(User, user_id)
    if user is None or not (
        {Role.student.value, Role.parent.value} & user.role_names
    ):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "找不到学生或家长账号"
        )
    if len(new_password or "") < settings.min_password_length:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"新密码至少需 {settings.min_password_length} 个字符",
        )
    user.password_hash = hash_password(new_password)
    user.must_change_password = True
    db.flush()
    return user


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
