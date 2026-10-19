"""节次表解析与可排时段共用逻辑。

M2 起所有「某班/某节次表的合法时段」查询一律经 resolve_period_table + regular_slots,
排课引擎不需关心学校是单一或多套节次表(混合学制封装于此)。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.basedata import ClassUnit
from app.models.period import Period, PeriodTable, PeriodType


def semester_default_table(db: Session, semester_id: int) -> PeriodTable | None:
    tables = db.scalars(
        select(PeriodTable).where(PeriodTable.semester_id == semester_id).order_by(PeriodTable.id)
    ).all()
    if not tables:
        return None
    return next((t for t in tables if t.is_default), tables[0])


def resolve_period_table(db: Session, class_unit: ClassUnit) -> PeriodTable | None:
    """班级所属节次表:有指定则用之,否则回退学期默认表。"""
    if class_unit.period_table_id is not None:
        pt = db.get(PeriodTable, class_unit.period_table_id)
        if pt is not None:
            return pt
    return semester_default_table(db, class_unit.semester_id)


def regular_slots(db: Session, period_table_id: int) -> list[Period]:
    """节次表中可排课(type=regular)的格位,依星期、节次排序。"""
    return list(
        db.scalars(
            select(Period)
            .where(
                Period.period_table_id == period_table_id,
                Period.type == PeriodType.regular.value,
            )
            .order_by(Period.weekday, Period.period_no)
        ).all()
    )
