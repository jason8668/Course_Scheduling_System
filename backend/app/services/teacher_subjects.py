"""任教科目自动同步(Jason 2026-10-30 定:能自动实现的都自动实现)。

背景:教师档案的 subjects 与配课是两张表,配课不自动写档案,导致
档案空、调课推荐“同科目”全判非本科(2026-10-27 已修示范回填,但正式
手动流程仍会空)。从此配课一建/一改,任教科目自动跟上。

语义——只加不减,绝不删手动填的科目:
  配课新增/修改/导入时,把该科加进任课教师的档案(已有的不动);
  配课删除、或某位教师被从配课里移除时,不删档案科目——同步分不清
  “手动填的”与“自动加的”,删了会把管理员手动填的资质也抹掉。
  停教的科目请在教师档案里手动去掉,同步不会替你删。

推荐器另有兜底:档案为空的教师,按配课算本科(见 substitution_recommender
的 _subject_teacher_ids),所以即使旧数据档案还没补同步,推荐也不会全错。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assignment import AssignmentTeacher, CourseAssignment
from app.models.basedata import Subject, Teacher


def sync_from_assignment(db: Session, assignment: CourseAssignment) -> int:
    """把一笔配课的科目加进其任课教师的档案。回新增的档案科目链接数。"""
    subject = db.get(Subject, assignment.subject_id)
    if subject is None:
        return 0
    added = 0
    for link in assignment.teachers:
        teacher = db.get(Teacher, link.teacher_id)
        if teacher is None:
            continue
        if all(s.id != subject.id for s in teacher.subjects):
            teacher.subjects.append(subject)
            added += 1
    return added


def sync_semester(db: Session, semester_id: int) -> dict:
    """给整学期补同步(旧数据档案空时的一键修复):逐笔配课只加不减。"""
    assignments = db.scalars(
        select(CourseAssignment).where(CourseAssignment.semester_id == semester_id)
    ).all()
    added = sum(sync_from_assignment(db, a) for a in assignments)
    return {"assignments": len(assignments), "added_links": added}


def assignment_subject_teacher_ids(db: Session, semester_id: int, subject_name: str) -> set[int]:
    """按配课教这个科目的教师 id(以科目名称比对,与推荐器快照名称一致)。"""
    if not subject_name:
        return set()
    rows = db.execute(
        select(AssignmentTeacher.teacher_id)
        .join(CourseAssignment, CourseAssignment.id == AssignmentTeacher.course_assignment_id)
        .join(Subject, Subject.id == CourseAssignment.subject_id)
        .join(Teacher, Teacher.id == AssignmentTeacher.teacher_id)
        .where(CourseAssignment.semester_id == semester_id, Subject.name == subject_name)
    ).all()
    return {r[0] for r in rows}
