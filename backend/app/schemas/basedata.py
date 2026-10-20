"""基础资料(教师/科目/场地/班级)schema。"""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.validators import is_valid_email
from app.models.basedata import ClassTrack, RoomType, TeacherRuleType


def _normalize_optional_email(value: str | None) -> str | None:
    """空字串转 None;非空则验证 Email 格式。"""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if not is_valid_email(value):
        raise ValueError("Email 格式不正确")
    return value


# ── 科目 ──────────────────────────────
class SubjectBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class SubjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    domain: str | None = Field(default=None, max_length=64)
    required_room_type: RoomType | None = None
    default_block_size: int = Field(default=1, ge=1, le=8)
    is_major: bool = False  # 主科(排课引擎 S5:尽量排上午)


class SubjectOut(SubjectIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    semester_id: int


# ── 教师 ──────────────────────────────
class TeacherIn(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    id_last4: str | None = Field(default=None, max_length=4)
    base_periods: int = Field(default=0, ge=0)
    admin_title: str | None = Field(default=None, max_length=32)
    admin_reduction: int = Field(default=0, ge=0)
    is_external: bool = False
    is_active: bool = True
    subject_ids: list[int] = []
    email: str | None = Field(default=None, max_length=128)
    phone: str | None = Field(default=None, max_length=32)
    line_id: str | None = Field(default=None, max_length=64)
    user_id: int | None = None  # 绑定的登录帐号(空=不绑定)

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str | None) -> str | None:
        return _normalize_optional_email(v)


class TeacherOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    semester_id: int
    name: str
    id_last4: str | None
    base_periods: int
    admin_title: str | None
    admin_reduction: int
    is_external: bool
    is_active: bool
    subjects: list[SubjectBrief] = []
    email: str | None = None
    phone: str | None = None
    line_id: str | None = None
    user_id: int | None = None


class BindableAccount(BaseModel):
    """可供教师绑定的帐号(teacher 角色、于本学期尚未被绑定者)。"""

    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    display_name: str


class TeacherAccountIn(BaseModel):
    """为既有教师补开登录帐号(导入时没勾、或后来才需要用系统的老师)。"""

    username: str = Field(min_length=3, max_length=64)
    password: str = Field(default="", max_length=128)  # 空=用部署设置的默认密码


class ResetPasswordIn(BaseModel):
    password: str = Field(default="", max_length=128)  # 空=用部署设置的默认密码


class TeacherAccountOut(BaseModel):
    """教师的登录帐号状态(给界面显示;不含密码)。"""

    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    display_name: str
    must_change_password: bool
    is_active: bool = True  # 停用后无法登录,帐号与历史资料仍保留


class AccountActiveIn(BaseModel):
    is_active: bool


class TeacherDeleteImpact(BaseModel):
    """删除教师会连带消失的东西(删除前先让用户看清楚)。"""

    teacher_id: int
    teacher_name: str
    leave_requests: int        # 请假单数
    substitutions: int         # 调代课处置数(含代课、调课、并班…)
    assignments: int           # 会失去这位教师的配课数
    homeroom_classes: int      # 担任班主任的班级数(有的话根本不能删)
    account_username: str = ""  # 绑定的登录帐号(删除教师时会一并停用)


class TeacherTimeRuleIn(BaseModel):
    weekday: int = Field(ge=1, le=6)
    period_no: int = Field(ge=1)
    rule_type: TeacherRuleType


class TeacherTimeRuleOut(TeacherTimeRuleIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ── 场地 ──────────────────────────────
class RoomIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    room_type: RoomType = RoomType.normal
    capacity: int | None = Field(default=None, ge=0)
    subject_ids: list[int] = []


class RoomOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    semester_id: int
    name: str
    room_type: RoomType
    capacity: int | None
    subjects: list[SubjectBrief] = []


# ── 班级 ──────────────────────────────
class ClassUnitIn(BaseModel):
    grade: int = Field(ge=1, le=12)
    name: str = Field(min_length=1, max_length=32)
    track: ClassTrack
    department: str | None = Field(default=None, max_length=32)
    student_count: int | None = Field(default=None, ge=0)
    homeroom_teacher_id: int | None = None
    period_table_id: int | None = None  # 空=用学期默认节次表


class ClassUnitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    semester_id: int
    grade: int
    name: str
    track: ClassTrack
    department: str | None
    student_count: int | None
    homeroom_teacher_id: int | None
    homeroom_teacher: SubjectBrief | None = None  # 借用 {id,name} 结构显示班主任
    period_table_id: int | None = None
