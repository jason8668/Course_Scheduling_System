from pydantic import BaseModel


class TeacherHoursOut(BaseModel):
    teacher_id: int
    teacher_name: str
    total: int
    by_grade: dict[str, int] = {}


class TeachingHoursOut(BaseModel):
    semester_id: int
    date_from: str
    date_to: str
    effective_from: str
    effective_to: str
    teachers: list[TeacherHoursOut] = []
    total_periods: int = 0
