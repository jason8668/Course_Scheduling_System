"""考务地基服务(KW-01~07):学生档案、导入导出、异动、家长、分值、考号。

权限口径:
- 学生写操作(新增/修改/导入/异动/生成考号)只允许 admin/director,
  由 API 层 require_roles + can_manage_students 把关。
- 家长写操作例外(KW-05):班主任可改本班、教务可改全校。
- 科目设置(KW-06):admin/director 全可,教研组长只可管本科目。
- 读操作按 exam_scopes 的可见范围过滤,越权 403。
"""

import io

from fastapi import HTTPException, status
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.basedata import ClassUnit, Subject, Teacher
from app.models.exam_foundation import (
    CHANGE_TYPES,
    RULE_TYPES,
    STUDENT_GENDERS,
    STUDENT_STATUSES,
    ExamNumberRule,
    ParentContact,
    Student,
    StudentStatusChange,
    SubjectScoreSetting,
)
from app.models.exam_scopes import SubjectLeader
from app.models.semester import Semester
from app.models.user import User
from app.schemas.exam_students import (
    ParentOut,
    StudentOut,
    StudentStatusChangeOut,
    SubjectSettingOut,
)
from app.services.exam_scopes import (
    can_manage_students,
    can_manage_subject_settings,
    require_student_visible,
    visible_class_ids,
    visible_grade_set,
)

HEADER_ROWS = 3  # 范本固定三列表头:栏名 + 说明 + 范例,第 4 列起读数据

# 导入/导出模板栏位:(栏名, 说明, 范例)
STUDENT_TEMPLATE_COLUMNS = [
    ("学号", "必填,同一学期内唯一", "20260101"),
    ("姓名", "必填", "张三"),
    ("性别", "选填:男/女", "男"),
    ("班级", "必填,需为已建立的班名", "701"),
    ("状态", "选填:在读/休学/毕业,默认在读", "在读"),
    ("考号", "选填", "070001"),
    ("家长姓名", "选填", "张父"),
    ("家长关系", "选填:父亲/母亲/其他", "父亲"),
    ("家长电话", "选填", "13812345678"),
]

S_SHAPE_NO_SCORE_WARNING = "暂无上次成绩，暂按学号顺序编排"


def mask_phone(phone: str | None) -> str | None:
    """家长电话脱敏:13812345678 -> 138****5678。"""
    if not phone:
        return phone
    p = phone.strip()
    if len(p) >= 7:
        return f"{p[:3]}****{p[-4:]}"
    if len(p) > 4:
        return f"{p[:2]}****{p[-2:]}"
    return "****"


def _teacher_ids(db: Session, user: User) -> set[int]:
    rows = db.scalars(select(Teacher.id).where(Teacher.user_id == user.id)).all()
    return set(rows)


def _is_homeroom_of(db: Session, user: User, class_unit_id: int) -> bool:
    """该账号是否为指定班级的班主任。"""
    teacher_ids = _teacher_ids(db, user)
    if not teacher_ids:
        return False
    cls = db.get(ClassUnit, class_unit_id)
    return cls is not None and cls.homeroom_teacher_id in teacher_ids


def can_see_full_phone(db: Session, user: User, student: Student) -> bool:
    """详情页完整号码可见范围:教务/管理员全校,班主任仅本班。"""
    if can_manage_students(db, user):
        return True
    return _is_homeroom_of(db, user, student.class_unit_id)


def can_manage_parents(db: Session, user: User, student: Student) -> bool:
    """家长写权限(KW-05):教务可改全校,班主任只可改本班。"""
    if can_manage_students(db, user):
        return True
    return _is_homeroom_of(db, user, student.class_unit_id)


def _class_map(db: Session, semester_id: int) -> dict[int, ClassUnit]:
    rows = db.scalars(
        select(ClassUnit).where(ClassUnit.semester_id == semester_id)
    ).all()
    return {c.id: c for c in rows}


def to_student_out(db: Session, student: Student, full_phone: bool) -> StudentOut:
    """组装 StudentOut;列表一律脱敏,详情按权限决定是否给完整号码。"""
    cls = db.get(ClassUnit, student.class_unit_id)
    parents = [
        ParentOut(
            id=p.id,
            name=p.name,
            relation=p.relation,
            phone=p.phone if full_phone else mask_phone(p.phone),
        )
        for p in sorted(student.parents, key=lambda x: x.id)
    ]
    return StudentOut(
        id=student.id,
        semester_id=student.semester_id,
        class_unit_id=student.class_unit_id,
        class_name=cls.name if cls else "",
        grade=cls.grade if cls else None,
        student_no=student.student_no,
        name=student.name,
        gender=student.gender,
        status=student.status,
        exam_no=student.exam_no,
        parents=parents,
    )


def _require_semester(db: Session, semester_id: int) -> Semester:
    sem = db.get(Semester, semester_id)
    if sem is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到学期")
    return sem


def _require_class_in_semester(db: Session, semester_id: int, class_unit_id: int) -> ClassUnit:
    cls = db.get(ClassUnit, class_unit_id)
    if cls is None or cls.semester_id != semester_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "班级无效或不属于本学期")
    return cls


def _check_list_scope(
    db: Session, user: User, grade: int | None, class_unit_id: int | None
) -> None:
    """列表显式筛选项越出可见范围时直接 403,不静默回空列表。"""
    class_ids = visible_class_ids(db, user)
    grade_set = visible_grade_set(db, user)
    if class_unit_id is not None:
        if class_ids is not None and class_unit_id not in class_ids:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "无权查看该班级(不在你的可见班级范围内)")
        if grade_set is not None:
            cls = db.get(ClassUnit, class_unit_id)
            if cls is None or cls.grade not in grade_set:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "无权查看该班级(不在你的可见年级范围内)")
    if grade is not None and grade_set is not None and grade not in grade_set:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权查看该年级(不在你的可见年级范围内)")


def list_students(
    db: Session,
    user: User,
    semester_id: int,
    grade: int | None = None,
    class_unit_id: int | None = None,
    q: str | None = None,
    status_filter: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Student], int]:
    """按范围过滤列学生;返回 (当前页学生, 总数)。"""
    _require_semester(db, semester_id)
    _check_list_scope(db, user, grade, class_unit_id)
    class_ids = visible_class_ids(db, user)
    grade_set = visible_grade_set(db, user)
    stmt = (
        select(Student)
        .join(ClassUnit, ClassUnit.id == Student.class_unit_id)
        .where(Student.semester_id == semester_id)
    )
    if class_ids is not None:
        stmt = stmt.where(Student.class_unit_id.in_(class_ids))
    if grade_set is not None:
        stmt = stmt.where(ClassUnit.grade.in_(grade_set))
    if grade is not None:
        stmt = stmt.where(ClassUnit.grade == grade)
    if class_unit_id is not None:
        stmt = stmt.where(Student.class_unit_id == class_unit_id)
    if q:
        stmt = stmt.where(
            (Student.name.contains(q)) | (Student.student_no.contains(q))
        )
    if status_filter:
        stmt = stmt.where(Student.status == status_filter)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(ClassUnit.grade, ClassUnit.name, Student.student_no)
        .limit(limit)
        .offset(offset)
    ).all()
    return list(rows), total


def get_student_visible(db: Session, user: User, student_id: int) -> Student:
    """取一名学生并做可见性拦截;找不到 404,越权 403。"""
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到学生")
    require_student_visible(db, user, student)
    return student


def create_student(
    db: Session,
    semester_id: int,
    class_unit_id: int,
    student_no: str,
    name: str,
    gender: str | None,
    status_value: str,
    exam_no: str | None,
) -> Student:
    _require_semester(db, semester_id)
    _require_class_in_semester(db, semester_id, class_unit_id)
    if gender is not None and gender not in STUDENT_GENDERS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "性别只能是男或女")
    if status_value not in STUDENT_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "状态只能是在读、休学或毕业")
    dup = db.scalar(
        select(Student.id).where(
            Student.semester_id == semester_id, Student.student_no == student_no
        )
    )
    if dup is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"本学期已有学号「{student_no}」的学生"
        )
    student = Student(
        semester_id=semester_id,
        class_unit_id=class_unit_id,
        student_no=student_no,
        name=name,
        gender=gender,
        status=status_value,
        exam_no=exam_no,
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


def _write_status_change(
    db: Session,
    student: Student,
    change_type: str,
    from_class_unit_id: int | None,
    to_class_unit_id: int | None,
    from_status: str | None,
    to_status: str | None,
    note: str | None,
    user: User | None,
) -> StudentStatusChange:
    rec = StudentStatusChange(
        student_id=student.id,
        change_type=change_type,
        from_class_unit_id=from_class_unit_id,
        to_class_unit_id=to_class_unit_id,
        from_status=from_status,
        to_status=to_status,
        note=note,
        changed_by=user.id if user is not None else None,
    )
    db.add(rec)
    db.flush()
    return rec


def update_student(
    db: Session,
    user: User,
    student: Student,
    name: str | None,
    gender: str | None,
    class_unit_id: int | None,
) -> Student:
    """改姓名/性别/班级,不改 status。改班级时同步写一条转班记录。"""
    if gender is not None and gender not in STUDENT_GENDERS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "性别只能是男或女")
    if name is not None:
        student.name = name
    if gender is not None:
        student.gender = gender
    if class_unit_id is not None and class_unit_id != student.class_unit_id:
        _require_class_in_semester(db, student.semester_id, class_unit_id)
        old_class = student.class_unit_id
        student.class_unit_id = class_unit_id
        _write_status_change(
            db, student, "转班", old_class, class_unit_id,
            student.status, student.status, "通过档案修改转班", user,
        )
    db.commit()
    db.refresh(student)
    return student


def change_student_status(
    db: Session,
    user: User,
    student: Student,
    to_status: str,
    note: str | None,
    new_class_unit_id: int | None,
    change_type: str | None,
) -> Student:
    """状态与异动专用接口:状态变更不走普通 PATCH。

    change_type 与 to_status 须一致;转班必须给新班级且不改变状态。
    """
    if to_status not in STUDENT_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "状态只能是在读、休学或毕业")
    if change_type is not None and change_type not in CHANGE_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "异动类型无效")
    if new_class_unit_id is not None:
        _require_class_in_semester(db, student.semester_id, new_class_unit_id)
    if change_type is None:
        if new_class_unit_id is not None:
            change_type = "转班"
        elif to_status == "休学":
            change_type = "休学"
        elif to_status == "毕业":
            change_type = "毕业"
        elif to_status == "在读":
            change_type = "复学" if student.status == "休学" else "入学"
    if change_type == "转班":
        if new_class_unit_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "转班必须指定新班级")
        if new_class_unit_id == student.class_unit_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "转班的新班级与原班级相同")
        if to_status != student.status:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "转班不改变在读状态")
    elif change_type == "休学":
        if to_status != "休学":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "休学异动的目标状态须为休学")
        if new_class_unit_id is not None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "休学异动不需要指定新班级")
    elif change_type == "复学":
        if to_status != "在读":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "复学异动的目标状态须为在读")
        if student.status != "休学":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "只有休学学生可以复学")
    elif change_type == "毕业":
        if to_status != "毕业":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "毕业异动的目标状态须为毕业")
    elif change_type == "入学":
        if to_status != "在读":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "入学异动的目标状态须为在读")
    if (
        change_type != "转班"
        and to_status == student.status
        and new_class_unit_id is None
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "状态没有变化")
    from_class = student.class_unit_id
    from_status = student.status
    to_class = new_class_unit_id if new_class_unit_id is not None else student.class_unit_id
    student.status = to_status
    student.class_unit_id = to_class
    _write_status_change(
        db, student, change_type, from_class, to_class,
        from_status, to_status, note, user,
    )
    db.commit()
    db.refresh(student)
    return student


def list_status_changes(db: Session, student: Student) -> list[StudentStatusChangeOut]:
    classes = _class_map(db, student.semester_id)
    rows = db.scalars(
        select(StudentStatusChange)
        .where(StudentStatusChange.student_id == student.id)
        .order_by(StudentStatusChange.created_at, StudentStatusChange.id)
    ).all()
    out = []
    for r in rows:
        from_cls = classes.get(r.from_class_unit_id) if r.from_class_unit_id else None
        to_cls = classes.get(r.to_class_unit_id) if r.to_class_unit_id else None
        out.append(StudentStatusChangeOut(
            id=r.id,
            student_id=r.student_id,
            change_type=r.change_type,
            from_class_unit_id=r.from_class_unit_id,
            to_class_unit_id=r.to_class_unit_id,
            from_class_name=from_cls.name if from_cls else None,
            to_class_name=to_cls.name if to_cls else None,
            from_status=r.from_status,
            to_status=r.to_status,
            note=r.note,
            changed_by=r.changed_by,
            created_at=r.created_at,
        ))
    return out


# ── 家长 ──────────────────────────────
def create_parent(
    db: Session, student: Student, name: str, relation: str | None, phone: str | None
) -> ParentContact:
    parent = ParentContact(
        student_id=student.id, name=name, relation=relation, phone=phone
    )
    db.add(parent)
    db.commit()
    db.refresh(parent)
    return parent


def get_parent(db: Session, parent_id: int) -> ParentContact:
    parent = db.get(ParentContact, parent_id)
    if parent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到家长联系信息")
    return parent


def update_parent(
    db: Session, parent: ParentContact, name: str, relation: str | None, phone: str | None
) -> ParentContact:
    parent.name = name
    parent.relation = relation
    parent.phone = phone
    db.commit()
    db.refresh(parent)
    return parent


def delete_parent(db: Session, parent: ParentContact) -> None:
    db.delete(parent)
    db.commit()


# ── 导入导出 ──────────────────────────────
def build_student_template() -> bytes:
    """学生导入模板:固定三列表头(栏名/说明/范例),第 4 列起读数据。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "学生"
    ws.append([c[0] for c in STUDENT_TEMPLATE_COLUMNS])
    ws.append([c[1] for c in STUDENT_TEMPLATE_COLUMNS])
    ws.append([c[2] for c in STUDENT_TEMPLATE_COLUMNS])
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


def _data_rows(file_bytes: bytes):
    wb = load_workbook(io.BytesIO(file_bytes), data_only=True)
    ws = wb.active
    for idx, row in enumerate(
        ws.iter_rows(min_row=HEADER_ROWS + 1, values_only=True), start=HEADER_ROWS + 1
    ):
        if row is None or all(c is None or str(c).strip() == "" for c in row):
            continue
        yield idx, row


def import_students(db: Session, semester_id: int, file_bytes: bytes) -> dict:
    """批量导入学生:逐行报错、全对才写入;同一学号重复导入为更新(幂等)。

    有任一错误即返回全部错误且数据库零写入。
    """
    _require_semester(db, semester_id)
    classes_by_name = {
        c.name: c
        for c in db.scalars(
            select(ClassUnit).where(ClassUnit.semester_id == semester_id)
        ).all()
    }
    existing = {
        s.student_no: s
        for s in db.scalars(
            select(Student).where(Student.semester_id == semester_id)
        ).all()
    }
    errors: list[str] = []
    seen: set[str] = set()
    pending: list[dict] = []
    for idx, row in _data_rows(file_bytes):
        student_no = _cell(row, 0)
        name = _cell(row, 1)
        gender = _cell(row, 2)
        class_name = _cell(row, 3)
        status_value = _cell(row, 4) or "在读"
        exam_no = _cell(row, 5)
        parent_name = _cell(row, 6)
        parent_relation = _cell(row, 7)
        parent_phone = _cell(row, 8)
        if not student_no or not name or not class_name:
            errors.append(f"第 {idx} 行:学号、姓名、班级皆必填")
            continue
        if student_no in seen:
            errors.append(f"第 {idx} 行:学号「{student_no}」在文件内重复")
            continue
        seen.add(student_no)
        if gender is not None and gender not in STUDENT_GENDERS:
            errors.append(f"第 {idx} 行:性别「{gender}」无效,只能是男或女")
            continue
        if status_value not in STUDENT_STATUSES:
            errors.append(f"第 {idx} 行:状态「{status_value}」无效,只能是在读、休学或毕业")
            continue
        if class_name not in classes_by_name:
            errors.append(f"第 {idx} 行:班级「{class_name}」不存在")
            continue
        pending.append({
            "student_no": student_no,
            "name": name,
            "gender": gender,
            "class_unit_id": classes_by_name[class_name].id,
            "status": status_value,
            "exam_no": exam_no,
            "parent_name": parent_name,
            "parent_relation": parent_relation,
            "parent_phone": parent_phone,
        })
    if errors:
        return {"created": 0, "updated": 0, "errors": errors}
    created = 0
    updated = 0
    for item in pending:
        student = existing.get(item["student_no"])
        if student is None:
            student = Student(
                semester_id=semester_id,
                class_unit_id=item["class_unit_id"],
                student_no=item["student_no"],
                name=item["name"],
                gender=item["gender"],
                status=item["status"],
                exam_no=item["exam_no"],
            )
            db.add(student)
            db.flush()
            existing[item["student_no"]] = student
            created += 1
        else:
            student.name = item["name"]
            student.gender = item["gender"]
            student.class_unit_id = item["class_unit_id"]
            student.status = item["status"]
            if item["exam_no"] is not None:
                student.exam_no = item["exam_no"]
            updated += 1
        if item["parent_name"]:
            parent = next(
                (p for p in student.parents if p.name == item["parent_name"]), None
            )
            if parent is None:
                db.add(ParentContact(
                    student_id=student.id,
                    name=item["parent_name"],
                    relation=item["parent_relation"],
                    phone=item["parent_phone"],
                ))
            else:
                if item["parent_relation"] is not None:
                    parent.relation = item["parent_relation"]
                if item["parent_phone"] is not None:
                    parent.phone = item["parent_phone"]
    db.commit()
    return {"created": created, "updated": updated, "errors": []}


def build_student_export(
    db: Session, students: list[Student]
) -> bytes:
    """导出学生名单:家长电话默认脱敏导出。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "学生名单"
    ws.append(["学号", "姓名", "性别", "班级", "年级", "状态", "考号", "家长姓名", "家长关系", "家长电话"])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    classes = {}
    for s in students:
        if s.class_unit_id not in classes:
            classes[s.class_unit_id] = db.get(ClassUnit, s.class_unit_id)
        cls = classes[s.class_unit_id]
        parents = sorted(s.parents, key=lambda x: x.id)
        ws.append([
            s.student_no,
            s.name,
            s.gender or "",
            cls.name if cls else "",
            cls.grade if cls else "",
            s.status,
            s.exam_no or "",
            "、".join(p.name for p in parents),
            "、".join(p.relation or "" for p in parents),
            "、".join(mask_phone(p.phone) or "" for p in parents),
        ])
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 16
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── 学科分值 ──────────────────────────────
DEFAULT_SETTING = {
    "full_score": 100.0,
    "pass_line": 60.0,
    "excellent_line": 85.0,
    "counts_toward_total": True,
    "conversion_ratio": 1.0,
}


def list_subject_settings(
    db: Session, user: User, semester_id: int
) -> list[SubjectSettingOut]:
    """该学期全部科目的分值设置;未设置的科目回默认值。"""
    _require_semester(db, semester_id)
    subjects = db.scalars(
        select(Subject).where(Subject.semester_id == semester_id).order_by(Subject.name)
    ).all()
    saved = {
        s.subject_id: s
        for s in db.scalars(
            select(SubjectScoreSetting).where(
                SubjectScoreSetting.semester_id == semester_id
            )
        ).all()
    }
    leader_only = None
    if not can_manage_students(db, user):
        # 教研组长只看本科目;普通教师看全部(只读)。
        teacher_ids = _teacher_ids(db, user)
        if teacher_ids:
            leader_subjects = set(db.scalars(
                select(SubjectLeader.subject_id).where(
                    SubjectLeader.teacher_id.in_(teacher_ids)
                )
            ).all())
            if leader_subjects:
                leader_only = leader_subjects
    out = []
    for subj in subjects:
        if leader_only is not None and subj.id not in leader_only:
            continue
        row = saved.get(subj.id)
        out.append(SubjectSettingOut(
            subject_id=subj.id,
            subject_name=subj.name,
            full_score=row.full_score if row else DEFAULT_SETTING["full_score"],
            pass_line=row.pass_line if row else DEFAULT_SETTING["pass_line"],
            excellent_line=row.excellent_line if row else DEFAULT_SETTING["excellent_line"],
            counts_toward_total=row.counts_toward_total if row else True,
            conversion_ratio=row.conversion_ratio if row else DEFAULT_SETTING["conversion_ratio"],
        ))
    return out


def upsert_subject_settings(
    db: Session, user: User, semester_id: int, settings: list[dict]
) -> list[SubjectSettingOut]:
    """批量 upsert 学科分值;教研组长只能改本科目。"""
    _require_semester(db, semester_id)
    subject_ids = {s["subject_id"] for s in settings}
    subjects = {
        s.id: s
        for s in db.scalars(
            select(Subject).where(
                Subject.semester_id == semester_id, Subject.id.in_(subject_ids)
            )
        ).all()
    }
    if len(subjects) != len(subject_ids):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "科目清单含无效或跨学期的科目")
    for item in settings:
        if not can_manage_subject_settings(db, user, item["subject_id"]):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "无权修改该科目的分值设置")
        if item["pass_line"] > item["full_score"]:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "及格线不可高于满分")
        if item["excellent_line"] > item["full_score"]:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "优秀线不可高于满分")
        if item["pass_line"] > item["excellent_line"]:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "及格线不可高于优秀线")
    saved = {
        s.subject_id: s
        for s in db.scalars(
            select(SubjectScoreSetting).where(
                SubjectScoreSetting.semester_id == semester_id,
                SubjectScoreSetting.subject_id.in_(subject_ids),
            )
        ).all()
    }
    for item in settings:
        row = saved.get(item["subject_id"])
        if row is None:
            row = SubjectScoreSetting(
                semester_id=semester_id, subject_id=item["subject_id"]
            )
            db.add(row)
        row.full_score = item["full_score"]
        row.pass_line = item["pass_line"]
        row.excellent_line = item["excellent_line"]
        row.counts_toward_total = item["counts_toward_total"]
        row.conversion_ratio = item["conversion_ratio"]
    db.commit()
    return list_subject_settings(db, user, semester_id)


# ── 考号规则 ──────────────────────────────
def get_exam_number_rule(
    db: Session, semester_id: int, grade: int | None
) -> ExamNumberRule | None:
    """先找年级规则,没有再找全校通用规则(grade 为空),都没有回 None。"""
    _require_semester(db, semester_id)
    if grade is not None:
        row = db.scalar(
            select(ExamNumberRule).where(
                ExamNumberRule.semester_id == semester_id,
                ExamNumberRule.grade == grade,
            )
        )
        if row is not None:
            return row
    return db.scalar(
        select(ExamNumberRule).where(
            ExamNumberRule.semester_id == semester_id,
            ExamNumberRule.grade.is_(None),
        )
    )


def upsert_exam_number_rule(
    db: Session, semester_id: int, grade: int | None, rule_type: str
) -> ExamNumberRule:
    _require_semester(db, semester_id)
    if rule_type not in RULE_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "考号规则类型无效")
    if grade is not None:
        row = db.scalar(
            select(ExamNumberRule).where(
                ExamNumberRule.semester_id == semester_id,
                ExamNumberRule.grade == grade,
            )
        )
    else:
        row = db.scalar(
            select(ExamNumberRule).where(
                ExamNumberRule.semester_id == semester_id,
                ExamNumberRule.grade.is_(None),
            )
        )
    if row is None:
        row = ExamNumberRule(
            semester_id=semester_id, grade=grade, rule_type=rule_type
        )
        db.add(row)
    else:
        row.rule_type = rule_type
    db.commit()
    db.refresh(row)
    return row


def generate_exam_numbers(
    db: Session, semester_id: int, grade: int
) -> tuple[int, str]:
    """一键生成全年级考号,写到 Student.exam_no;只编在读学生。

    s_shape 第 1 批还没有任何考试成绩,必须返回明确警告,不许假装
    已按成绩 S 型排好;警告口径:暂按学号顺序编排。
    """
    _require_semester(db, semester_id)
    rule = get_exam_number_rule(db, semester_id, grade)
    rule_type = rule.rule_type if rule is not None else "by_student_no"
    students = db.scalars(
        select(Student)
        .join(ClassUnit, ClassUnit.id == Student.class_unit_id)
        .where(
            Student.semester_id == semester_id,
            ClassUnit.grade == grade,
            Student.status == "在读",
        )
        .order_by(ClassUnit.name, Student.student_no)
    ).all()
    warning = ""
    if rule_type == "by_student_no":
        for s in students:
            s.exam_no = s.student_no
    elif rule_type == "sequential":
        for i, s in enumerate(students, start=1):
            s.exam_no = f"{grade:02d}{i:04d}"
    elif rule_type == "s_shape":
        warning = S_SHAPE_NO_SCORE_WARNING
        ordered = sorted(students, key=lambda s: s.student_no)
        for i, s in enumerate(ordered, start=1):
            s.exam_no = f"{grade:02d}{i:04d}"
    db.commit()
    return len(students), warning
