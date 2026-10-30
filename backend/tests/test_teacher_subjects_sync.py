"""任教科目自动同步:配课一建/一改/一导入,科目自动进教师档案(只加不减);
推荐器档案空时按配课算本科;整学期补同步修旧数据。"""

from app.models.assignment import (
    AssignmentTeacher,
    CourseAssignment,
    SchedulingUnit,
    SchedulingUnitMember,
)
from app.models.basedata import ClassUnit, Subject, Teacher
from app.models.semester import Semester
from app.models.user import Role
from app.services import teacher_subjects as ts
from app.services.substitution_recommender import _subject_teacher_ids
from tests.test_special_days import _login


def _setup(db):
    sem = Semester(academic_year=2026, term=1)
    db.add(sem)
    db.flush()
    cls = ClassUnit(semester_id=sem.id, grade=7, name="七年级1班", track="初中")
    t1 = Teacher(semester_id=sem.id, name="王小明", phone="13800000000")
    t2 = Teacher(semester_id=sem.id, name="李小红", phone="13900000000")
    subj = Subject(semester_id=sem.id, name="数学")
    db.add_all([cls, t1, t2, subj])
    db.flush()
    su = SchedulingUnit(semester_id=sem.id, unit_type="single", name=cls.name)
    db.add(su)
    db.flush()
    db.add(SchedulingUnitMember(scheduling_unit_id=su.id, class_unit_id=cls.id))
    a = CourseAssignment(
        semester_id=sem.id, scheduling_unit_id=su.id, subject_id=subj.id,
        periods_per_week=5,
    )
    db.add(a)
    db.flush()
    db.add(AssignmentTeacher(course_assignment_id=a.id, teacher_id=t1.id))
    db.commit()
    return {"sem": sem, "t1": t1, "t2": t2, "subj": subj, "a": a, "su": su}


def test_sync_adds_and_never_removes(db):
    ctx = _setup(db)
    assert ts.sync_from_assignment(db, ctx["a"]) == 1
    db.commit()
    db.refresh(ctx["t1"])
    assert [s.name for s in ctx["t1"].subjects] == ["数学"]
    # 再同步一次不重复
    assert ts.sync_from_assignment(db, ctx["a"]) == 0
    # 手动填的科目不被同步动:给王小明手动加一个“物理”(无配课),再同步数学仍保留
    subj2 = Subject(semester_id=ctx["sem"].id, name="物理")
    db.add(subj2)
    db.flush()
    ctx["t1"].subjects.append(subj2)
    db.commit()
    ts.sync_from_assignment(db, ctx["a"])
    db.refresh(ctx["t1"])
    assert sorted(s.name for s in ctx["t1"].subjects) == ["数学", "物理"]


def test_recommender_falls_back_to_assignments(db):
    ctx = _setup(db)
    # 档案空,但配课里王小明教数学:推荐器仍应判他是本科教师
    assert ctx["t1"].id in _subject_teacher_ids(db, ctx["sem"].id, "数学")
    assert ctx["t2"].id not in _subject_teacher_ids(db, ctx["sem"].id, "数学")


def test_sync_semester_and_api(env):
    client, db = env
    ctx = _setup(db)
    result = ts.sync_semester(db, ctx["sem"].id)
    db.commit()
    assert result == {"assignments": 1, "added_links": 1}
    db.refresh(ctx["t1"])
    assert [s.name for s in ctx["t1"].subjects] == ["数学"]

    _login(client, db, roles=(Role.admin,), username="a")
    resp = client.post(
        f"/api/assignments/sync-teacher-subjects?semester_id={ctx['sem'].id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["assignments"] == 1
