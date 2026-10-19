"""设置精灵 schema。"""

from pydantic import BaseModel


class WizardStateOut(BaseModel):
    current_step: int
    completed: bool
    semester_id: int | None
    total_steps: int
    has_semesters: bool  # 系统是否已有任何学期(辅助前端判断是否需引导)


class WizardStateUpdate(BaseModel):
    current_step: int | None = None
    completed: bool | None = None
    semester_id: int | None = None


class SemesterSummary(BaseModel):
    subjects: int
    teachers: int
    classes: int
    rooms: int
