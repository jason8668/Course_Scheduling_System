"""教师相关共用逻辑。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.basedata import Teacher
from app.models.user import User


def current_teacher(db: Session, user: User, semester_id: int) -> Teacher | None:
    """解析登录者在指定学期绑定的教师主档(无绑定则回 None)。

    M2-5「教师查本人课表」、M4 请假自登/代课确认皆以此定位当前教师。
    绑定唯一性由 uq(semester_id, user_id) 保证,故至多一笔。
    """
    return db.scalar(
        select(Teacher).where(
            Teacher.semester_id == semester_id, Teacher.user_id == user.id
        )
    )
