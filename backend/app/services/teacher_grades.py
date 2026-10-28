"""教师所属年级:档案多选年级的读写。

年级范围 1~12 由 API 层 schema 校验;这里只做整批覆盖与按学期读取。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.basedata import Teacher, TeacherGrade
from app.models.user import Role, User
from app.services import grade_scopes

# 老师跟着学生升年级:七年级→八年级、八年级→九年级、九年级毕业班循环回七年级带新生。
# 其他年级不动(本校只用 7/8/9;与复制学期的班级进位规则不同:学生毕业班级消失,老师不消失)。
PROMOTION_MAP = {7: 8, 8: 9, 9: 7}


def set_teacher_grades(db: Session, teacher_id: int, grades: list[int]) -> list[int]:
    """整批覆盖某教师的所属年级(去重升序);呼叫端负责 commit。"""
    wanted = sorted(set(grades))
    db.query(TeacherGrade).filter(TeacherGrade.teacher_id == teacher_id).delete()
    for g in wanted:
        db.add(TeacherGrade(teacher_id=teacher_id, grade=g))
    db.flush()
    return wanted


def teacher_grade_map(db: Session, semester_id: int) -> dict[int, set[int]]:
    """本学期有填所属年级的教师 -> 年级集合(没填的不在 map 里)。"""
    rows = db.execute(
        select(TeacherGrade.teacher_id, TeacherGrade.grade)
        .join(Teacher, Teacher.id == TeacherGrade.teacher_id)
        .where(Teacher.semester_id == semester_id)
    ).all()
    out: dict[int, set[int]] = {}
    for teacher_id, grade in rows:
        out.setdefault(teacher_id, set()).add(grade)
    return out


def promote_grades(grades: list[int]) -> list[int]:
    """升一年级后的所属年级(7→8、8→9、9→7;其他年级不动)。"""
    return sorted({PROMOTION_MAP.get(g, g) for g in grades})


def sync_director_scopes(db: Session, teacher: Teacher, grades: list[int]) -> None:
    """主任的年级范围跟着所属年级走(主任管的年级 = 所属年级)。
    只动已是主任的绑定帐号;管理员帐号与未绑定帐号不受影响。"""
    if teacher.user_id is None:
        return
    user = db.get(User, teacher.user_id)
    if user is None or Role.admin.value in user.role_names:
        return
    if Role.director.value in user.role_names:
        grade_scopes.set_user_grades(db, user.id, grades)


def promote_semester_grades(db: Session, semester_id: int) -> dict:
    """本学期全部教师升一年级(整批);呼叫端负责 commit。没填年级的不动。"""
    updated = 0
    for teacher in db.scalars(
        select(Teacher).where(Teacher.semester_id == semester_id)
    ).all():
        new_grades = promote_grades(teacher.grade_ids)
        if new_grades == teacher.grade_ids:
            continue
        set_teacher_grades(db, teacher.id, new_grades)
        sync_director_scopes(db, teacher, new_grades)
        updated += 1
    return {"teachers_updated": updated}
