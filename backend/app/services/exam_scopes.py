"""考务角色与数据范围(KW-62/KW-63)。

派生角色映射(角色与现有排课系统账号体系共用):

- 系统管理员 = admin
- 教务 = director,且未配 UserGradeScope 年级
- 年级组长 = director,且配有 UserGradeScope 年级
- 教研组长 = teacher,且在 subject_leaders 表中有本科目记录
- 班主任 = teacher,且其 Teacher 记录是某班的 homeroom_teacher
- 任课教师 = teacher
- 学生与家长不设账号、不进本系统角色体系,只有教师看成绩。
注意:主任配了年级即视为年级组长,不再同时视为教务(两者按映射互斥);
年级组长管学生档案的能力仍由 can_manage_students 另行规定,不受此影响。

数据范围口径:

- visible_class_ids 回传 None 表示全校班级都可见(admin、director);
  普通教师回传本人任教班级 + 本人任班主任的班级。
- visible_grade_set 回传 None 表示全年级可见(admin、无年级配置的
  director);年级组长回传其 UserGradeScope 年级;普通教师回传其可见
  班级的年级。
- 任教班级溯源用现有口径:CourseAssignment -> AssignmentTeacher ->
  SchedulingUnitMember -> ClassUnit,与 grade_scopes.py 同一口径。
- 教研组长的科目范围不在班级集合里体现:其可见班级与普通教师相同,
  科目限制由 can_manage_subject_settings 以及后续批次的成绩查询
  按 subject_id 过滤来执行。
- 教师身份按 Teacher.user_id 绑定判定,跨学期并集;教研组长任命、
  年级配置同样不按学期切分(与 UserGradeScope 年级不绑定学期同一口径)。
"""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assignment import (
    AssignmentTeacher,
    CourseAssignment,
    SchedulingUnitMember,
)
from app.models.basedata import ClassUnit, Teacher
from app.models.exam_scopes import SubjectLeader
from app.models.user import Role, User, UserGradeScope


def _teacher_ids(db: Session, user: User) -> set[int]:
    """该账号绑定的全部 Teacher 记录 id(跨学期并集)。"""
    rows = db.scalars(
        select(Teacher.id).where(Teacher.user_id == user.id)
    ).all()
    return set(rows)


def _subject_leader_subject_ids(db: Session, user: User) -> set[int]:
    """该账号担任教研组长的科目 id 集合(跨学期并集)。"""
    teacher_ids = _teacher_ids(db, user)
    if not teacher_ids:
        return set()
    rows = db.scalars(
        select(SubjectLeader.subject_id).where(
            SubjectLeader.teacher_id.in_(teacher_ids)
        )
    ).all()
    return set(rows)


def _teaching_class_ids(db: Session, teacher_ids: set[int]) -> set[int]:
    """任教班级:CourseAssignment -> SchedulingUnitMember -> ClassUnit。"""
    if not teacher_ids:
        return set()
    rows = db.execute(
        select(SchedulingUnitMember.class_unit_id)
        .join(
            CourseAssignment,
            CourseAssignment.scheduling_unit_id
            == SchedulingUnitMember.scheduling_unit_id,
        )
        .join(
            AssignmentTeacher,
            AssignmentTeacher.course_assignment_id == CourseAssignment.id,
        )
        .where(AssignmentTeacher.teacher_id.in_(teacher_ids))
    ).all()
    return {class_id for (class_id,) in rows}


def _homeroom_class_ids(db: Session, teacher_ids: set[int]) -> set[int]:
    """班主任班级:ClassUnit.homeroom_teacher_id 指向本人 Teacher 记录。"""
    if not teacher_ids:
        return set()
    rows = db.scalars(
        select(ClassUnit.id).where(
            ClassUnit.homeroom_teacher_id.in_(teacher_ids)
        )
    ).all()
    return set(rows)


def exam_roles(db: Session, user: User) -> set[str]:
    """该账号的考务派生角色集合。

    取值范围是 {"admin", "academic", "grade_leader", "subject_leader",
    "homeroom", "teacher"} 的子集。
    """
    names = user.role_names
    roles: set[str] = set()
    if Role.admin.value in names:
        roles.add("admin")
    if Role.director.value in names:
        scopes = db.scalars(
            select(UserGradeScope.grade).where(
                UserGradeScope.user_id == user.id
            )
        ).all()
        if scopes:
            roles.add("grade_leader")
        else:
            roles.add("academic")
    if Role.teacher.value in names:
        roles.add("teacher")
        teacher_ids = _teacher_ids(db, user)
        if _homeroom_class_ids(db, teacher_ids):
            roles.add("homeroom")
        if _subject_leader_subject_ids(db, user):
            roles.add("subject_leader")
    return roles


def visible_class_ids(db: Session, user: User) -> set[int] | None:
    """该账号可见的班级 id 集合;None 表示全校班级都可见(admin、director)。"""
    names = user.role_names
    if Role.admin.value in names or Role.director.value in names:
        return None
    teacher_ids = _teacher_ids(db, user)
    return _teaching_class_ids(db, teacher_ids) | _homeroom_class_ids(
        db, teacher_ids
    )


def visible_grade_set(db: Session, user: User) -> set[int] | None:
    """该账号可见的年级集合;None 表示全年级可见。

    admin 与未配年级的 director 回传 None;年级组长回传其配置年级;
    普通教师回传其可见班级的年级。
    """
    names = user.role_names
    if Role.admin.value in names:
        return None
    if Role.director.value in names:
        scopes = set(
            db.scalars(
                select(UserGradeScope.grade).where(
                    UserGradeScope.user_id == user.id
                )
            ).all()
        )
        if scopes:
            return scopes
        return None
    class_ids = visible_class_ids(db, user)
    if not class_ids:
        return set()
    rows = db.scalars(
        select(ClassUnit.grade).where(ClassUnit.id.in_(class_ids))
    ).all()
    return set(rows)


def _student_class_unit_id(student) -> int | None:
    """取学生的所属班级 id;兼容对象属性与字典两种形态。"""
    if isinstance(student, dict):
        value = student.get("class_unit_id")
    else:
        value = getattr(student, "class_unit_id", None)
    return value if isinstance(value, int) else None


def _student_grade(student) -> int | None:
    """取学生的年级;兼容对象属性与字典两种形态。"""
    if isinstance(student, dict):
        value = student.get("grade")
    else:
        value = getattr(student, "grade", None)
    return value if isinstance(value, int) else None


def require_student_visible(db: Session, user: User, student) -> None:
    """学生可见性拦截:看不到就抛 403。

    判定依据是学生的 class_unit_id(学生档案模型须提供该字段)。
    班级与年级两层都要过:班级不在可见集合、或所属年级不在可见
    年级集合,都拒绝。class_unit_id 缺失时退回用学生自带的 grade
    字段判定;两者都没有则拒绝(无法确认归属时不放行)。
    """
    class_ids = visible_class_ids(db, user)
    grade_set = visible_grade_set(db, user)
    class_unit_id = _student_class_unit_id(student)
    if class_unit_id is not None:
        if class_ids is not None and class_unit_id not in class_ids:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "无权查看该学生(不在你的可见班级范围内)"
            )
        if grade_set is not None:
            cls = db.get(ClassUnit, class_unit_id)
            grade = cls.grade if cls is not None else None
            if grade is None or grade not in grade_set:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN, "无权查看该学生(不在你的可见年级范围内)"
                )
        return
    grade = _student_grade(student)
    if grade is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "无权查看该学生(无法确认该学生所属班级)"
        )
    if grade_set is not None and grade not in grade_set:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "无权查看该学生(不在你的可见年级范围内)"
        )


def can_manage_students(db: Session, user: User) -> bool:
    """是否可管理学生档案:只有 admin、director 为 True。"""
    names = user.role_names
    return Role.admin.value in names or Role.director.value in names


def can_manage_subject_settings(
    db: Session, user: User, subject_id: int | None = None
) -> bool:
    """是否可管理科目设置:科目满分、及格线、等级划分等。

    admin、director 全可;教研组长只可管本科目;其他教师不可。
    subject_id 为空时表示“是否可管任意科目设置”:教研组长只要
    担任至少一科组长即回传 True。
    """
    names = user.role_names
    if Role.admin.value in names or Role.director.value in names:
        return True
    leader_subjects = _subject_leader_subject_ids(db, user)
    if subject_id is None:
        return bool(leader_subjects)
    return subject_id in leader_subjects
