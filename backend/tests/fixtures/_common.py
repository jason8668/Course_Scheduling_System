"""三套学制验证资料集的共用 builder。

测试策略总则(tasks.md)要求全案共用三套 fixtures(小学/初中/技高),作为排课引擎
(M3)与 E2E 总验收(M5-4)的基准资料。

以 Python builder 而非静态 JSON 表达,因为资料之间有数值相依:
教师配课数 ≤ 可排格数、连堂节数 ≤ 每周节数、跑班群组成员须同节次表(D7#4)。
用程序建构才能在改动时一起维护,并直接复用 app.services 既有的验证逻辑。
"""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assignment import (
    AssignmentTeacher,
    BlockRule,
    CourseAssignment,
    SchedulingUnit,
)
from app.models.basedata import (
    ClassUnit,
    Room,
    RoomType,
    Subject,
    Teacher,
    TeacherRuleType,
    TeacherTimeRule,
)
from app.models.period import Period, PeriodTable, PeriodType
from app.models.semester import Semester
from app.services.assignments import create_group, get_or_create_single_unit
from app.services.templates import create_semester_from_template


@dataclass
class Fixture:
    """一套建置完成的学期资料集。以名称索引,测试可直接取用实体。"""

    semester: Semester
    table: PeriodTable
    subjects: dict[str, Subject] = field(default_factory=dict)
    teachers: dict[str, Teacher] = field(default_factory=dict)
    rooms: dict[str, Room] = field(default_factory=dict)
    classes: dict[str, ClassUnit] = field(default_factory=dict)
    groups: dict[str, SchedulingUnit] = field(default_factory=dict)
    assignments: list[CourseAssignment] = field(default_factory=list)

    @property
    def semester_id(self) -> int:
        return self.semester.id


class Builder:
    """以学制范本开一个学期,再逐步叠上教师/班级/场地/配课。"""

    def __init__(self, db: Session, academic_year: int, term: int, template_key: str) -> None:
        self.db = db
        self.semester = create_semester_from_template(db, academic_year, term, template_key)
        self.table = self.semester.period_tables[0]
        self.subjects: dict[str, Subject] = {
            s.name: s
            for s in db.scalars(select(Subject).where(Subject.semester_id == self.semester.id))
        }
        self.teachers: dict[str, Teacher] = {}
        self.rooms: dict[str, Room] = {}
        self.classes: dict[str, ClassUnit] = {}
        self.groups: dict[str, SchedulingUnit] = {}
        self.assignments: list[CourseAssignment] = []

    # ── 节次表 ────────────────────────
    def set_period(self, weekday: int, period_no: int, ptype: PeriodType, name: str) -> None:
        p = self.db.scalar(
            select(Period).where(
                Period.period_table_id == self.table.id,
                Period.weekday == weekday,
                Period.period_no == period_no,
            )
        )
        assert p is not None, f"节次表无此格位:周{weekday} 第{period_no}格"
        p.type = ptype.value
        p.name = name
        self.db.flush()

    def regular_slots(self) -> list[Period]:
        return list(
            self.db.scalars(
                select(Period)
                .where(
                    Period.period_table_id == self.table.id,
                    Period.type == PeriodType.regular.value,
                )
                .order_by(Period.weekday, Period.period_no)
            )
        )

    # ── 实体 ──────────────────────────
    def subject(
        self,
        name: str,
        *,
        domain: str | None = None,
        required_room_type: RoomType | None = None,
        default_block_size: int = 1,
        is_major: bool = False,
    ) -> Subject:
        s = self.subjects.get(name)
        if s is None:
            s = Subject(semester_id=self.semester.id, name=name)
            self.db.add(s)
            self.subjects[name] = s
        if domain:
            s.domain = domain
        if required_room_type:
            s.required_room_type = required_room_type.value
        s.default_block_size = default_block_size
        s.is_major = is_major
        self.db.flush()
        return s

    def teacher(
        self,
        name: str,
        *,
        base_periods: int = 20,
        admin_title: str | None = None,
        admin_reduction: int = 0,
        is_external: bool = False,
        subjects: list[str] | None = None,
    ) -> Teacher:
        t = Teacher(
            semester_id=self.semester.id,
            name=name,
            base_periods=base_periods,
            admin_title=admin_title,
            admin_reduction=admin_reduction,
            is_external=is_external,
        )
        for sn in subjects or []:
            t.subjects.append(self.subjects[sn])
        self.db.add(t)
        self.db.flush()
        self.teachers[name] = t
        return t

    def unavailable_days(self, teacher_name: str, weekdays: list[int]) -> None:
        """该教师在指定星期的所有一般课节次皆不可排(业界师资只有特定到校日)。"""
        t = self.teachers[teacher_name]
        for p in self.regular_slots():
            if p.weekday in weekdays:
                self.db.add(
                    TeacherTimeRule(
                        teacher_id=t.id,
                        weekday=p.weekday,
                        period_no=p.period_no,
                        rule_type=TeacherRuleType.unavailable.value,
                    )
                )
        self.db.flush()

    def room(
        self,
        name: str,
        *,
        room_type: RoomType = RoomType.normal,
        capacity: int | None = None,
        subjects: list[str] | None = None,
    ) -> Room:
        r = Room(
            semester_id=self.semester.id,
            name=name,
            room_type=room_type.value,
            capacity=capacity,
        )
        for sn in subjects or []:
            r.subjects.append(self.subjects[sn])
        self.db.add(r)
        self.db.flush()
        self.rooms[name] = r
        return r

    def klass(
        self,
        name: str,
        *,
        grade: int,
        track: str,
        department: str | None = None,
        student_count: int = 30,
        homeroom: str | None = None,
    ) -> ClassUnit:
        c = ClassUnit(
            semester_id=self.semester.id,
            grade=grade,
            name=name,
            track=track,
            department=department,
            student_count=student_count,
            homeroom_teacher_id=self.teachers[homeroom].id if homeroom else None,
        )
        self.db.add(c)
        self.db.flush()
        self.classes[name] = c
        return c

    def group(self, name: str, class_names: list[str]) -> SchedulingUnit:
        """跑班群组。create_group 会验证成员班级同节次表(D7#4)。"""
        g = create_group(
            self.db,
            self.semester.id,
            name,
            [self.classes[n].id for n in class_names],
        )
        self.groups[name] = g
        return g

    # ── 配课 ──────────────────────────
    def assign(
        self,
        *,
        subject: str,
        teachers: list[str],
        periods: int,
        classes: list[str] | None = None,
        group: str | None = None,
        room: str | None = None,
        required_room_type: RoomType | None = None,
        blocks: tuple[int, int] | None = None,
        lock_room: bool = False,
    ) -> list[CourseAssignment]:
        """建立配课。classes → 每班一笔(single unit);group → 群组一笔。

        teachers 第一位为主教,其余为协同。blocks=(连堂长度, 每周次数)。
        """
        if (classes is None) == (group is None):
            raise ValueError("classes 与 group 择一")
        units = (
            [get_or_create_single_unit(self.db, self.classes[n]) for n in classes]
            if classes
            else [self.groups[group]]  # type: ignore[index]
        )
        out = []
        for unit in units:
            a = CourseAssignment(
                semester_id=self.semester.id,
                scheduling_unit_id=unit.id,
                subject_id=self.subjects[subject].id,
                periods_per_week=periods,
                required_room_type=required_room_type.value if required_room_type else None,
                room_id=self.rooms[room].id if room else None,
                lock_room=lock_room,
            )
            for i, tn in enumerate(teachers):
                a.teachers.append(
                    AssignmentTeacher(teacher_id=self.teachers[tn].id, is_lead=(i == 0))
                )
            if blocks:
                size, count = blocks
                a.block_rules.append(BlockRule(block_size=size, count_per_week=count))
            self.db.add(a)
            self.db.flush()
            self.assignments.append(a)
            out.append(a)
        return out

    def build(self) -> Fixture:
        self.db.commit()
        return Fixture(
            semester=self.semester,
            table=self.table,
            subjects=self.subjects,
            teachers=self.teachers,
            rooms=self.rooms,
            classes=self.classes,
            groups=self.groups,
            assignments=self.assignments,
        )


# ── 分析 helper(供烟雾测试与日后 pre-flight 对照)────────────────
def teacher_available_slots(db: Session, fx: Fixture, teacher: Teacher) -> int:
    """教师可排格数 = 一般课格数 − 其 unavailable 规则落在一般课格位的数量。

    单一节次表(绝大多数学校)的定义;跨表任教的教师以墙钟区间联集去重,
    留待 M3-1 pre-flight 实作。
    """
    regular = {
        (p.weekday, p.period_no)
        for p in db.scalars(
            select(Period).where(
                Period.period_table_id == fx.table.id,
                Period.type == PeriodType.regular.value,
            )
        )
    }
    blocked = {
        (r.weekday, r.period_no)
        for r in teacher.time_rules
        if r.rule_type == TeacherRuleType.unavailable.value
    }
    return len(regular - blocked)


def room_demand(fx: Fixture) -> dict[int, int]:
    """每个「已指定场地」的配课节数需求(room_id → 节数)。"""
    demand: dict[int, int] = {}
    for a in fx.assignments:
        if a.room_id:
            demand[a.room_id] = demand.get(a.room_id, 0) + a.periods_per_week
    return demand
