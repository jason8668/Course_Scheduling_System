"""成绩单与查询 schema(KW-52~54/56):班级成绩单、个人成绩单、教师端查询、成绩册。"""

from pydantic import BaseModel, ConfigDict


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
    grade: int | None = None
    students: list[StudentCardOut] = []


class StudentReportCardOut(BaseModel):
    """一名学生的个人成绩单完整版(教师/教务看,含排名)。"""

    student_id: int
    student_no: str = ""
    student_name: str = ""
    class_name: str = ""
    grade: int | None = None
    subjects: list[SubjectScoreOut] = []
    total: float | None = None
    class_rank: int | None = None
    grade_rank: int | None = None


class TeacherScoreOut(BaseModel):
    student_id: int
    student_no: str = ""
    student_name: str = ""
    class_name: str = ""
    grade: int | None = None
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
