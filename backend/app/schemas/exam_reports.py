"""成绩单与查询 schema(KW-52~56)。

my-scores / my-report-card 的排名键按家长版设置决定是否出现,
不在此用固定 response_model,API 层直接回传字典。
"""

from pydantic import BaseModel, ConfigDict


class ReportSettingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    exam_id: int
    parent_show_grade_rank: bool = False
    parent_show_class_rank: bool = False


class ReportSettingPut(BaseModel):
    parent_show_grade_rank: bool = False
    parent_show_class_rank: bool = False


class SubjectScoreOut(BaseModel):
    subject_id: int
    subject_name: str = ""
    score: float | None = None
    status: str = "未录入"


class StudentCardOut(BaseModel):
    """一名学生的成绩单卡片(班级成绩单内用,不带班级名)。"""

    student_id: int
    student_no: str = ""
    student_name: str = ""
    subjects: list[SubjectScoreOut] = []
    total: float | None = None
    class_rank: int | None = None
    grade_rank: int | None = None


class ClassReportCardOut(BaseModel):
    class_unit_id: int
    class_name: str = ""
    students: list[StudentCardOut] = []


class StudentReportCardOut(BaseModel):
    """一名学生的个人成绩单完整版(教师/教务看,含排名)。"""

    student_id: int
    student_no: str = ""
    student_name: str = ""
    class_name: str = ""
    subjects: list[SubjectScoreOut] = []
    total: float | None = None
    class_rank: int | None = None
    grade_rank: int | None = None


class TeacherScoreOut(BaseModel):
    student_id: int
    student_no: str = ""
    student_name: str = ""
    class_name: str = ""
    subject_id: int
    subject_name: str = ""
    score: float | None = None
    status: str = "未录入"
    total: float | None = None
    class_rank: int | None = None
    grade_rank: int | None = None


class TeacherScoreListOut(BaseModel):
    items: list[TeacherScoreOut] = []
    total: int = 0


class CredentialOut(BaseModel):
    username: str
    role: str
    initial_password: str = ""
    student_name: str = ""


class ProvisionOut(BaseModel):
    students_created: int = 0
    parents_created: int = 0
    credentials: list[CredentialOut] = []


class AccountOut(BaseModel):
    user_id: int
    username: str = ""
    role: str = ""
    student_names: list[str] = []
    must_change_password: bool = False


class AccountListOut(BaseModel):
    items: list[AccountOut] = []
    total: int = 0


class ResetPasswordIn(BaseModel):
    new_password: str = ""
