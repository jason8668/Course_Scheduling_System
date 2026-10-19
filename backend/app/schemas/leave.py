"""请假与受影响节次 schema(M4-1)。"""

from datetime import date, datetime, time

from pydantic import BaseModel, Field

# 栏位名 date 会遮蔽同名型别(mypy 判为变数),其后的栏位以别名标注
_Date = date


class AffectedPeriodOut(BaseModel):
    id: int
    date: date
    weekday: int
    period_no: int
    period_name: str  # 「第三节」——一律用节次表的名称,不用内部 period_no
    start_time: time | None = None
    end_time: time | None = None
    subject_name: str
    class_names: str
    room_name: str
    status: str  # pending / resolved / completed / cancelled
    handler_teacher_id: int | None = None
    handler_name: str | None = None
    sub_type: str | None = None  # 已处置时的处置方式(substitute/swap/…),未处置为空
    # 调课才有:请假教师回来补课的那一节(让清单直接写出「王师 10/8 第二节补课」)
    swap_date: _Date | None = None
    swap_period_name: str = ""

    model_config = {"from_attributes": True}


class LeaveRequestIn(BaseModel):
    """时间为空 = 该端点整天。单日 + 起讫时间 = 半天假。"""

    teacher_id: int | None = None  # 组长代登时指定;教师自登留空
    leave_type: str
    start_date: date
    start_time: time | None = None
    end_date: date
    end_time: time | None = None
    reason: str = Field(default="", max_length=200)


class LeaveRequestOut(BaseModel):
    id: int
    semester_id: int
    teacher_id: int
    teacher_name: str
    leave_type: str
    leave_type_label: str
    start_date: date
    start_time: time | None = None
    end_date: date
    end_time: time | None = None
    reason: str
    status: str
    created_by_name: str
    created_at: datetime
    affected_count: int = 0
    pending_count: int = 0
    affected_periods: list[AffectedPeriodOut] = []


class LeaveCancelled(BaseModel):
    id: int
    status: str
    revoked_count: int  # 原本已指派、现在被取消的节次数
    notified_teachers: list[str] = []

