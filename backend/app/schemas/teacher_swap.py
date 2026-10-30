"""老师自主调课的请求/回传结构。"""

from datetime import date

from pydantic import BaseModel, model_validator


class TeacherSwapCreate(BaseModel):
    class_date: date
    period_no: int
    class_unit_id: int
    course_assignment_id: int
    original_teacher_id: int
    handler_teacher_id: int
    # 补课四项要么全填,要么全不填
    makeup_date: date | None = None
    makeup_period_no: int | None = None
    makeup_class_unit_id: int | None = None
    makeup_assignment_id: int | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _check_makeup_all_or_none(self):
        parts = [
            self.makeup_date, self.makeup_period_no,
            self.makeup_class_unit_id, self.makeup_assignment_id,
        ]
        if any(p is not None for p in parts) and not all(p is not None for p in parts):
            raise ValueError("补课四项要么全填,要么全不填")
        if self.original_teacher_id == self.handler_teacher_id:
            raise ValueError("原任教师与换课教师不能是同一人")
        return self


class TeacherSwapOut(BaseModel):
    id: int
    semester_id: int
    requester_id: int
    status: str
    note: str | None
    class_date: date
    period_no: int
    class_unit_id: int
    course_assignment_id: int
    original_teacher_id: int
    handler_teacher_id: int
    makeup_date: date | None
    makeup_period_no: int | None
    makeup_class_unit_id: int | None
    makeup_assignment_id: int | None
    # 展示用:对方(非发起人)的教师 id,前端据此判断当前用户能否同意
    approver_teacher_id: int
    # 展示用:换课节是否为事后补登(日期在今天之前)
    is_retroactive: bool
