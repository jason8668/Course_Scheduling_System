"""考务角色与数据范围测试(KW-62/KW-63)。

用 db fixture 直接建数据,不走 API。学生用 SimpleNamespace 模拟,
只依赖 require_student_visible 读取的 class_unit_id / grade 字段。
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.assignment import (
    AssignmentTeacher,
    CourseAssignment,
    SchedulingUnit,
    SchedulingUnitMember,
)
from app.models.basedata import ClassUnit, Subject, Teacher
from app.models.exam_scopes import SubjectLeader
from app.models.semester import Semester
from app.models.user import Role, UserGradeScope
from app.services import exam_scopes
from tests.conftest import make_user

PW = "password123"


@pytest.fixture
def seed(db):
    """一学期 + 701(7 年级)、801(8 年级)两个班 + 数学、语文两科。

    t1:任教 701 数学,且为数学教研组长。
    t2:801 班主任,不任教。
    t3:有教师档案但无任教班、无班主任班、无组长任命。
    """
    sem = Semester(academic_year=2026, term=1)
    db.add(sem)
    db.flush()
    math = Subject(semester_id=sem.id, name="数学")
    chinese = Subject(semester_id=sem.id, name="语文")
    cls7 = ClassUnit(semester_id=sem.id, grade=7, name="701", track="junior_high")
    cls8 = ClassUnit(semester_id=sem.id, grade=8, name="801", track="junior_high")
    db.add_all([math, chinese, cls7, cls8])
    db.flush()

    admin = make_user(db, "adm", PW, roles=[Role.admin])
    academic = make_user(db, "jiao", PW, roles=[Role.director])
    leader = make_user(db, "nzb", PW, roles=[Role.director])
    db.add(UserGradeScope(user_id=leader.id, grade=7))
    t1user = make_user(db, "t1", PW, roles=[Role.teacher])
    t2user = make_user(db, "t2", PW, roles=[Role.teacher])
    t3user = make_user(db, "t3", PW, roles=[Role.teacher])
    plain = make_user(db, "plain", PW, roles=[Role.teacher])

    t1 = Teacher(semester_id=sem.id, name="王老师", user_id=t1user.id)
    t2 = Teacher(semester_id=sem.id, name="李老师", user_id=t2user.id)
    t3 = Teacher(semester_id=sem.id, name="张老师", user_id=t3user.id)
    db.add_all([t1, t2, t3])
    db.flush()
    cls8.homeroom_teacher_id = t2.id
    db.flush()

    su = SchedulingUnit(semester_id=sem.id, unit_type="single", name="701")
    db.add(su)
    db.flush()
    db.add(SchedulingUnitMember(scheduling_unit_id=su.id, class_unit_id=cls7.id))
    a = CourseAssignment(
        semester_id=sem.id, scheduling_unit_id=su.id,
        subject_id=math.id, periods_per_week=5,
    )
    db.add(a)
    db.flush()
    db.add(AssignmentTeacher(course_assignment_id=a.id, teacher_id=t1.id))
    db.add(SubjectLeader(semester_id=sem.id, teacher_id=t1.id, subject_id=math.id))
    db.commit()
    return {
        "sem": sem, "math": math, "chinese": chinese,
        "cls7": cls7, "cls8": cls8,
        "admin": admin, "academic": academic, "leader": leader,
        "t1": t1user, "t2": t2user, "t3": t3user, "plain": plain,
    }


def test_admin_all_visible(db, seed):
    assert exam_scopes.exam_roles(db, seed["admin"]) == {"admin"}
    assert exam_scopes.visible_class_ids(db, seed["admin"]) is None
    assert exam_scopes.visible_grade_set(db, seed["admin"]) is None
    assert exam_scopes.can_manage_students(db, seed["admin"]) is True
    assert exam_scopes.can_manage_subject_settings(db, seed["admin"]) is True
    assert exam_scopes.can_manage_subject_settings(
        db, seed["admin"], seed["math"].id
    ) is True
    exam_scopes.require_student_visible(
        db, seed["admin"], SimpleNamespace(class_unit_id=seed["cls8"].id)
    )


def test_director_without_scopes_is_academic_all_visible(db, seed):
    assert exam_scopes.exam_roles(db, seed["academic"]) == {"academic"}
    assert exam_scopes.visible_class_ids(db, seed["academic"]) is None
    assert exam_scopes.visible_grade_set(db, seed["academic"]) is None
    assert exam_scopes.can_manage_students(db, seed["academic"]) is True
    assert exam_scopes.can_manage_subject_settings(db, seed["academic"]) is True


def test_director_with_scopes_is_grade_leader(db, seed):
    assert exam_scopes.exam_roles(db, seed["leader"]) == {"grade_leader"}
    assert exam_scopes.visible_class_ids(db, seed["leader"]) is None
    assert exam_scopes.visible_grade_set(db, seed["leader"]) == {7}
    exam_scopes.require_student_visible(
        db, seed["leader"], SimpleNamespace(class_unit_id=seed["cls7"].id)
    )
    with pytest.raises(HTTPException) as exc:
        exam_scopes.require_student_visible(
            db, seed["leader"], SimpleNamespace(class_unit_id=seed["cls8"].id)
        )
    assert exc.value.status_code == 403


def test_teacher_sees_taught_and_homeroom_classes(db, seed):
    assert exam_scopes.exam_roles(db, seed["t1"]) == {"teacher", "subject_leader"}
    assert exam_scopes.visible_class_ids(db, seed["t1"]) == {seed["cls7"].id}
    assert exam_scopes.visible_grade_set(db, seed["t1"]) == {7}
    assert exam_scopes.exam_roles(db, seed["t2"]) == {"teacher", "homeroom"}
    assert exam_scopes.visible_class_ids(db, seed["t2"]) == {seed["cls8"].id}
    assert exam_scopes.visible_grade_set(db, seed["t2"]) == {8}


def test_teacher_without_classes_sees_nothing(db, seed):
    assert exam_scopes.exam_roles(db, seed["t3"]) == {"teacher"}
    assert exam_scopes.visible_class_ids(db, seed["t3"]) == set()
    assert exam_scopes.visible_grade_set(db, seed["t3"]) == set()
    assert exam_scopes.visible_class_ids(db, seed["plain"]) == set()
    with pytest.raises(HTTPException) as exc:
        exam_scopes.require_student_visible(
            db, seed["t3"], SimpleNamespace(class_unit_id=seed["cls7"].id)
        )
    assert exc.value.status_code == 403


def test_require_student_visible_cross_class_forbidden(db, seed):
    with pytest.raises(HTTPException) as exc:
        exam_scopes.require_student_visible(
            db, seed["t1"], SimpleNamespace(class_unit_id=seed["cls8"].id)
        )
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        exam_scopes.require_student_visible(
            db, seed["t2"], SimpleNamespace(class_unit_id=seed["cls7"].id)
        )
    assert exc.value.status_code == 403
    exam_scopes.require_student_visible(
        db, seed["t2"], SimpleNamespace(class_unit_id=seed["cls8"].id)
    )


def test_require_student_visible_grade_fallback(db, seed):
    exam_scopes.require_student_visible(
        db, seed["leader"], SimpleNamespace(grade=7)
    )
    with pytest.raises(HTTPException) as exc:
        exam_scopes.require_student_visible(
            db, seed["leader"], SimpleNamespace(grade=8)
        )
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        exam_scopes.require_student_visible(db, seed["leader"], SimpleNamespace())
    assert exc.value.status_code == 403


def test_can_manage_subject_settings_subject_leader_only_own_subject(db, seed):
    math_id = seed["math"].id
    chinese_id = seed["chinese"].id
    assert exam_scopes.can_manage_subject_settings(db, seed["t1"], math_id) is True
    assert exam_scopes.can_manage_subject_settings(db, seed["t1"], chinese_id) is False
    assert exam_scopes.can_manage_subject_settings(db, seed["t1"]) is True
    assert exam_scopes.can_manage_subject_settings(db, seed["t2"], math_id) is False
    assert exam_scopes.can_manage_subject_settings(db, seed["t2"]) is False
    assert exam_scopes.can_manage_students(db, seed["t1"]) is False
    assert exam_scopes.can_manage_students(db, seed["leader"]) is True
