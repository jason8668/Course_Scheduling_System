"""配课领域服务:排课单位解析、跑班群组验证、课时/负载统计、序列化。"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.week_parity import PARITY_CN, fmt_periods, weekly_load
from app.models.assignment import (
    BUNDLE_UNIT_TYPES,
    AssignmentTeacher,
    CourseAssignment,
    SchedulingUnit,
    SchedulingUnitMember,
    SchedulingUnitType,
)
from app.models.basedata import ClassUnit, Teacher
from app.services import period_tables as pt_service
from app.services import settings as settings_service


class DomainError(Exception):
    """商业规则违反(由 API 层转为对应 HTTP 状态)。"""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def get_or_create_single_unit(db: Session, class_unit: ClassUnit) -> SchedulingUnit:
    """取得(或建立)某班级的单班排课单位。单班的所有配课共用同一 single unit。"""
    existing = db.scalar(
        select(SchedulingUnit)
        .join(SchedulingUnitMember, SchedulingUnitMember.scheduling_unit_id == SchedulingUnit.id)
        .where(
            SchedulingUnit.semester_id == class_unit.semester_id,
            SchedulingUnit.unit_type == SchedulingUnitType.single.value,
            SchedulingUnitMember.class_unit_id == class_unit.id,
        )
    )
    if existing is not None:
        return existing
    unit = SchedulingUnit(
        semester_id=class_unit.semester_id,
        unit_type=SchedulingUnitType.single.value,
        name=class_unit.name,
    )
    unit.members.append(SchedulingUnitMember(class_unit_id=class_unit.id))
    db.add(unit)
    db.flush()
    return unit


def create_group(
    db: Session, semester_id: int, name: str, class_ids: list[int]
) -> SchedulingUnit:
    """建立跑班群组。验证班级同属本学期,且成员节次表一致(architecture.md D7 #4)。"""
    classes = list(
        db.scalars(
            select(ClassUnit).where(
                ClassUnit.id.in_(class_ids), ClassUnit.semester_id == semester_id
            )
        )
    )
    if len(classes) != len(set(class_ids)):
        raise DomainError("班级清单含无效或跨学期的班级")
    _require_same_period_table(db, classes)
    unit = SchedulingUnit(
        semester_id=semester_id, unit_type=SchedulingUnitType.group.value, name=name
    )
    for cid in class_ids:
        unit.members.append(SchedulingUnitMember(class_unit_id=cid))
    db.add(unit)
    db.flush()
    return unit


def create_alternate(
    db: Session, semester_id: int, class_id: int, name: str | None = None
) -> SchedulingUnit:
    """建立单双周组(v1.3.0):一个班,之后在组里配单周、双周各一笔课。

    一个班可以有好几组(周一三四节生科/资科、周三第五节音乐/美术…)。
    没给名称时用「701 单双周」,同班第二组起加上编号。
    """
    cls = db.get(ClassUnit, class_id)
    if cls is None or cls.semester_id != semester_id:
        raise DomainError("班级无效或不属于本学期")
    if not name:
        taken = set(db.scalars(
            select(SchedulingUnit.name).where(
                SchedulingUnit.semester_id == semester_id,
                SchedulingUnit.unit_type == SchedulingUnitType.alternate.value,
            )
        ))
        base = f"{cls.name} 单双周"
        name, n = base, 2
        while name in taken:
            name = f"{base} {n}"
            n += 1
    unit = SchedulingUnit(
        semester_id=semester_id, unit_type=SchedulingUnitType.alternate.value, name=name
    )
    unit.members.append(SchedulingUnitMember(class_unit_id=class_id))
    db.add(unit)
    db.flush()
    return unit


def check_week_parity(
    db: Session, unit: SchedulingUnit, week_parity: str | None, assignment_id: int | None
) -> None:
    """单双周组的配课一定要标单周或双周,而且同一组单周、双周各只能一笔;
    其他配课不可以标(跑班群组＋单双周这次不支援)。"""
    if unit.unit_type != SchedulingUnitType.alternate.value:
        if week_parity:
            raise DomainError("只有单双周组里的配课可以设置单周或双周")
        return
    if not week_parity:
        raise DomainError("单双周组的配课要选择单周或双周")
    clash = db.scalar(
        select(CourseAssignment).where(
            CourseAssignment.scheduling_unit_id == unit.id,
            CourseAssignment.week_parity == week_parity,
            CourseAssignment.id != (assignment_id or -1),
        )
    )
    if clash is not None:
        raise DomainError(
            f"单双周组「{unit.name}」已经有{PARITY_CN[week_parity]}的课"
            f"({clash.subject.name}),每组单周、双周各一笔",
            status_code=409,
        )


def _require_same_period_table(db: Session, classes: list[ClassUnit]) -> None:
    table_ids = set()
    for c in classes:
        table = pt_service.resolve_period_table(db, c)
        table_ids.add(table.id if table is not None else None)
    if len(table_ids) > 1:
        raise DomainError(
            "跑班群组的成员班级必须使用同一套节次表(否则无法同时段开课)", status_code=409
        )


def teacher_loads(db: Session, semester_id: int) -> list[dict]:
    """每位教师的课时统计:应授(base-减课)vs 已配课,delta 正为超课时。

    单双周的课按实际上课量算一半(v1.3.0,用户定案):单周在 701、双周在 702 的老师
    每周都上,合计是完整的节数;只有单周那笔的老师平均每周只有一半。
    """
    rows = db.execute(
        select(
            AssignmentTeacher.teacher_id,
            CourseAssignment.periods_per_week,
            CourseAssignment.week_parity,
        )
        .join(CourseAssignment, AssignmentTeacher.course_assignment_id == CourseAssignment.id)
        .where(CourseAssignment.semester_id == semester_id)
    ).all()
    assigned_by: dict[int, float] = {}
    for tid, periods, parity in rows:
        assigned_by[tid] = assigned_by.get(tid, 0.0) + weekly_load(periods, parity)
    teachers = db.scalars(
        select(Teacher).where(Teacher.semester_id == semester_id).order_by(Teacher.name)
    )
    limit = settings_service.max_overtime(db)
    out: list[dict] = []
    for t in teachers:
        target = max(t.base_periods - t.admin_reduction, 0)
        assigned = assigned_by.get(t.id, 0.0)
        delta = assigned - target
        out.append({
            "teacher_id": t.id, "name": t.name,
            "base_periods": t.base_periods, "admin_reduction": t.admin_reduction,
            "target": target, "assigned": assigned, "delta": delta,
            "max_overtime": limit,
            # 两种情况不算违规:
            #   limit=0  → 学校未设上限
            #   base=0   → 这位教师没填基本课时。「应授 0 节」不是真的不用上课,
            #              而是资料还没建;此时谈超课时没有意义,硬挡会让没有
            #              维护基钟的学校连一般配课都做不了。
            "over_limit": limit > 0 and t.base_periods > 0 and delta > limit,
        })
    return out


def assert_within_overtime_limit(
    db: Session, semester_id: int, teacher_ids: set[int]
) -> None:
    """配课异动后,检查受影响的教师有没有超出超课时上限。

    只检查这次动到的教师:既有资料可能是在上限调低之前建立的,
    全面检查会让用户连「把某人的课调少」都做不到。
    """
    if not teacher_ids:
        return
    limit = settings_service.max_overtime(db)
    if limit <= 0:
        return
    for row in teacher_loads(db, semester_id):
        if row["teacher_id"] not in teacher_ids or not row["over_limit"]:
            continue
        raise DomainError(
            f"{row['name']} 应授 {row['target']} 节,配课后为 {fmt_periods(row['assigned'])} 节,"
            f"超出 {fmt_periods(row['delta'])} 节,已超过上限 {limit} 节。"
            "请调整配课,或于「系统管理」修改超课时上限。",
            status_code=409,
        )


def _unit_slot_consumption(db: Session, semester_id: int) -> dict[int, int]:
    """每个排课单位占用成员班级的节数。

    single:单位内各笔配课的节数总和(同一班的不同科目依序上课)。
    group(跑班):群组内的配课「同时段开课」(H7),学生分流到不同教室,
    班级实际被占用的是最长的那一笔,而非全部相加——5 门 3 节的选修同时开,
    班级只被占掉 3 节。
    """
    rows = db.execute(
        select(
            SchedulingUnit.id,
            SchedulingUnit.unit_type,
            func.sum(CourseAssignment.periods_per_week),
            func.max(CourseAssignment.periods_per_week),
        )
        .join(CourseAssignment, CourseAssignment.scheduling_unit_id == SchedulingUnit.id)
        .where(SchedulingUnit.semester_id == semester_id)
        .group_by(SchedulingUnit.id, SchedulingUnit.unit_type)
    ).all()
    return {
        uid: int((longest if utype in BUNDLE_UNIT_TYPES else total) or 0)
        for uid, utype, total, longest in rows
    }


def class_loads(db: Session, semester_id: int) -> list[dict]:
    """每班每周配课总节数 vs 可排节次数(超出即警告,对应验收④)。"""
    consumption = _unit_slot_consumption(db, semester_id)
    assigned_by: dict[int, int] = {}
    if consumption:
        members = db.execute(
            select(
                SchedulingUnitMember.scheduling_unit_id,
                SchedulingUnitMember.class_unit_id,
            ).where(SchedulingUnitMember.scheduling_unit_id.in_(consumption))
        ).all()
        for uid, cid in members:
            assigned_by[cid] = assigned_by.get(cid, 0) + consumption[uid]
    classes = db.scalars(
        select(ClassUnit).where(ClassUnit.semester_id == semester_id)
        .order_by(ClassUnit.grade, ClassUnit.name)
    )
    out: list[dict] = []
    for c in classes:
        table = pt_service.resolve_period_table(db, c)
        capacity = len(pt_service.regular_slots(db, table.id)) if table is not None else 0
        assigned = assigned_by.get(c.id, 0)
        out.append({
            "class_id": c.id, "name": c.name, "grade": c.grade,
            "assigned": assigned, "capacity": capacity,
            "over_capacity": assigned > capacity,
        })
    return out


# ── 序列化 ────────────────────────────
def serialize_unit(u: SchedulingUnit) -> dict:
    return {
        "id": u.id, "semester_id": u.semester_id,
        "unit_type": u.unit_type, "name": u.name,
        "classes": [
            {"id": m.class_unit.id, "name": m.class_unit.name, "grade": m.class_unit.grade}
            for m in u.members
        ],
    }


def serialize_assignment(a: CourseAssignment) -> dict:
    return {
        "id": a.id, "semester_id": a.semester_id,
        "scheduling_unit": serialize_unit(a.scheduling_unit),
        "subject": {"id": a.subject.id, "name": a.subject.name},
        "periods_per_week": a.periods_per_week,
        "required_room_type": a.required_room_type,
        "room_id": a.room_id, "lock_room": a.lock_room,
        "week_parity": a.week_parity,
        "teachers": [
            {"teacher_id": t.teacher_id, "is_lead": t.is_lead, "name": t.teacher.name}
            for t in sorted(a.teachers, key=lambda x: (not x.is_lead, x.teacher_id))
        ],
        "block_rules": [
            {"id": b.id, "block_size": b.block_size, "count_per_week": b.count_per_week}
            for b in a.block_rules
        ],
    }
