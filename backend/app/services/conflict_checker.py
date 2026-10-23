"""手动排课的硬约束单格检查(architecture.md §3.2 H1–H10 的单格版)。

放入/移动一笔配课到某格位时,检查是否违反硬约束并回传人话冲突清单。
跨节次表的教师(H2)/场地(H3)冲突以「同星期 + 墙钟时间区间重叠」判定
(architecture.md D7);同节次表则退化为 period_no 相等(常见情形,零额外成本)。
跑班群组:同群组多笔配课同时排在同一格(H7),批次一起检查;群组成员班级由
多门课共用(不互相视为 H1 冲突),但彼此的教师/场地仍不可重复。
单双周(v1.3.0):单周的课和双周的课永远不会碰在一起——班级、教师、场地的冲突都
先看两堂课是不是同一周会上,再比时段。单双周组的两笔同一格放入,可以是连堂。
"""

from dataclasses import dataclass
from datetime import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.week_parity import PARITIES, PARITY_SHORT, overlaps
from app.models.assignment import (
    AssignmentTeacher,
    CourseAssignment,
    SchedulingUnitMember,
    SchedulingUnitType,
)
from app.models.basedata import ClassUnit, Room, Subject
from app.models.period import Period, PeriodType
from app.models.timetable import ScheduleEntry, Timetable
from app.services import period_tables as pt_service
from app.services.solver_data import load_config

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


@dataclass
class Conflict:
    code: str  # H1..H10
    message: str


@dataclass
class Placement:
    assignment: CourseAssignment
    weekday: int
    period_no: int
    span: int = 1
    # 本格位实际使用的场地(空=沿用配课场地);手动改教室或引擎逐格指派时带入
    room_id: int | None = None

    @property
    def effective_room_id(self) -> int | None:
        return self.room_id if self.room_id is not None else self.assignment.room_id


@dataclass
class _Occ:
    weekday: int
    table_id: int
    period_no: int
    start: time | None
    end: time | None
    desc: str
    parity: str | None = None  # 单双周:这堂课只在单周/双周上(None = 每周)


def _wd(w: int) -> str:
    return WEEKDAY_CN[w - 1] if 1 <= w <= len(WEEKDAY_CN) else f"星期{w}"


class _Checker:
    def __init__(self, db: Session, timetable: Timetable, daily_subject_cap: int) -> None:
        self.db = db
        self.timetable = timetable
        self.cap = daily_subject_cap
        self._pmap_cache: dict[int, dict[tuple[int, int], Period]] = {}
        self._table_cache: dict[int, int | None] = {}
        self._class_table_cache: dict[int, int | None] = {}
        self._default_table_cache: dict[int, int | None] = {}
        self._room_name_cache: dict[int, str] = {}

    def _room_name(self, room_id: int) -> str:
        if room_id not in self._room_name_cache:
            room = self.db.get(Room, room_id)
            self._room_name_cache[room_id] = room.name if room else str(room_id)
        return self._room_name_cache[room_id]

    def _period_map(self, table_id: int) -> dict[tuple[int, int], Period]:
        if table_id not in self._pmap_cache:
            rows = self.db.scalars(select(Period).where(Period.period_table_id == table_id))
            self._pmap_cache[table_id] = {(p.weekday, p.period_no): p for p in rows}
        return self._pmap_cache[table_id]

    def _default_table_id(self, semester_id: int) -> int | None:
        if semester_id not in self._default_table_cache:
            t = pt_service.semester_default_table(self.db, semester_id)
            self._default_table_cache[semester_id] = t.id if t else None
        return self._default_table_cache[semester_id]

    def _table_for_class(self, class_id: int, semester_id: int, table_id: int | None) -> int | None:
        """等同 resolve_period_table(指定表 → 回退学期默认表),但于单次检查内快取,
        避免每笔配课都重查一次学期默认表(check-conflict 需 <100ms)。"""
        if class_id not in self._class_table_cache:
            self._class_table_cache[class_id] = (
                table_id if table_id is not None else self._default_table_id(semester_id)
            )
        return self._class_table_cache[class_id]

    def _class_table_id(self, cls: ClassUnit) -> int | None:
        return self._table_for_class(cls.id, cls.semester_id, cls.period_table_id)

    def _table_id(self, a: CourseAssignment) -> int | None:
        if a.id not in self._table_cache:
            members = a.scheduling_unit.members
            cls = members[0].class_unit if members else None
            self._table_cache[a.id] = self._class_table_id(cls) if cls else None
        return self._table_cache[a.id]

    def _classes(self, a: CourseAssignment):
        return [m.class_unit for m in a.scheduling_unit.members]

    def _desc(self, a: CourseAssignment) -> str:
        names = "、".join(m.class_unit.name for m in a.scheduling_unit.members)
        week = f"({PARITY_SHORT[a.week_parity]}周)" if a.week_parity else ""
        return f"{names} 班{a.subject.name}{week}"

    def _slot(self, pmap: dict[tuple[int, int], Period], weekday: int, pno: int) -> str:
        """人话时段标签:用节次表里的名称(早自习/午休/第一节),而非内部 period_no。

        period_no 是含早自习/午休的内部索引(初中范本第一节的 period_no 是 2),
        直接显示会与教学组长的认知不符。
        """
        p = pmap.get((weekday, pno))
        return f"{_wd(weekday)}{p.name}" if p else f"{_wd(weekday)}第{pno}节"

    @staticmethod
    def _occ_desc(occ: _Occ, table_id: int) -> str:
        """对方那一节的说明;跨节次表时补上它实际的时间。

        跨表是以墙钟重叠判定的,两边的节次名称对不起来(小学第五节 13:30 会撞到
        初中第六节 14:05)——只写「第五节已有课」用户会找不到那堂课在哪里。
        """
        if occ.table_id != table_id and occ.start and occ.end:
            return f"{occ.desc}({occ.start:%H:%M}–{occ.end:%H:%M})"
        return occ.desc

    def _overlap(
        self, occ: _Occ, weekday: int, table_id: int, pno: int,
        start: time | None, end: time | None, parity: str | None = None,
    ) -> bool:
        if occ.weekday != weekday or not overlaps(occ.parity, parity):
            return False
        if occ.table_id == table_id:
            return occ.period_no == pno  # 同表:节次号相等
        # 跨节次表:墙钟时间区间重叠(D7)
        if occ.start and occ.end and start and end:
            return start < occ.end and occ.start < end
        # 任一方没填起讫时间(学校自己新增的节次列,时间默认是空的):无从比较时间,
        # 保守地退回节次号相等。先前这里回 False,老师会被排到同一时段的两堂课。
        return occ.period_no == pno

    def _build_occupancy(self, ignore_entry_ids: set[int]):
        """以栏位查询(非 ORM 实体)建立既有格位的占用索引。

        check-conflict 是拖曳时的热路径(目标 p95 <100ms),逐格 hydrate ORM 物件
        在 60 班规模下代价过高,故此处只取需要的栏位并在 Python 端组装。
        """
        # 班级:(班, 星期, 节) → 已有的课(说明, 周别);单双周组那一格会有单周、双周两堂
        class_occ: dict[tuple[int, int, int], list[tuple[str, str | None]]] = {}
        teacher_occ: dict[int, list[_Occ]] = {}
        room_occ: dict[int, list[_Occ]] = {}
        # 每日上限:单周、双周各算一次(每周的课两周都算)
        subj_count: dict[tuple[int, int, int, str], int] = {}

        rows = self.db.execute(
            select(
                ScheduleEntry.id, ScheduleEntry.weekday, ScheduleEntry.period_no,
                ScheduleEntry.span, CourseAssignment.id, CourseAssignment.subject_id,
                # 格位场地优先,未指定才沿用配课场地
                func.coalesce(ScheduleEntry.room_id, CourseAssignment.room_id),
                CourseAssignment.scheduling_unit_id, Subject.name,
                CourseAssignment.week_parity,
            )
            .join(CourseAssignment, ScheduleEntry.course_assignment_id == CourseAssignment.id)
            .join(Subject, Subject.id == CourseAssignment.subject_id)
            .where(ScheduleEntry.timetable_id == self.timetable.id)
        ).all()
        rows = [r for r in rows if r[0] not in ignore_entry_ids]
        if not rows:
            return class_occ, teacher_occ, room_occ, subj_count

        unit_ids = {r[7] for r in rows}
        a_ids = {r[4] for r in rows}

        # 排课单位 → 成员班级(id, 班名, 节次表)
        classes_by_unit: dict[int, list[tuple[int, str, int | None]]] = {}
        for uid, cid, cname, c_sem, c_table in self.db.execute(
            select(
                SchedulingUnitMember.scheduling_unit_id, ClassUnit.id, ClassUnit.name,
                ClassUnit.semester_id, ClassUnit.period_table_id,
            )
            .join(ClassUnit, ClassUnit.id == SchedulingUnitMember.class_unit_id)
            .where(SchedulingUnitMember.scheduling_unit_id.in_(unit_ids))
        ).all():
            classes_by_unit.setdefault(uid, []).append(
                (cid, cname, self._table_for_class(cid, c_sem, c_table))
            )

        # 配课 → 教师
        teachers_by_a: dict[int, list[int]] = {}
        for aid, tid in self.db.execute(
            select(AssignmentTeacher.course_assignment_id, AssignmentTeacher.teacher_id)
            .where(AssignmentTeacher.course_assignment_id.in_(a_ids))
        ).all():
            teachers_by_a.setdefault(aid, []).append(tid)

        subj_slots: set[tuple[int, int, int, int, str]] = set()
        for row in rows:
            _e_id, wd, pno0, span, a_id, subject_id, room_id, unit_id, subj_name, parity = (
                tuple(row))
            classes = classes_by_unit.get(unit_id, [])
            if not classes:
                continue
            table_id = classes[0][2]
            if table_id is None:
                continue
            pmap = self._period_map(table_id)
            week = f"({PARITY_SHORT[parity]}周)" if parity else ""
            desc = f"{'、'.join(c[1] for c in classes)} 班{subj_name}{week}"
            t_ids = teachers_by_a.get(a_id, [])
            for k in range(span):
                pno = pno0 + k
                p = pmap.get((wd, pno))
                start = p.start_time if p else None
                end = p.end_time if p else None
                occ = _Occ(wd, table_id, pno, start, end, desc, parity)
                for cid, _cname, _ct in classes:
                    class_occ.setdefault((cid, wd, pno), []).append((desc, parity))
                for t_id in t_ids:
                    teacher_occ.setdefault(t_id, []).append(occ)
                if room_id:
                    room_occ.setdefault(room_id, []).append(occ)
            # H10 只计单节:连堂是一次上完的整块,本来就不受每日上限限制。
            # 以「格位」计而不是以配课计:跑班群组同一格可以有好几笔同科目的课(英语分组、
            # 两班对开的两笔国语),对学生来说那是一节课——自动排课本来就这样算(用户回报)。
            if span == 1:
                for cid, _cname, _ct in classes:
                    for w in (parity,) if parity else PARITIES:
                        if (cid, wd, subject_id, pno0, w) in subj_slots:
                            continue
                        subj_slots.add((cid, wd, subject_id, pno0, w))
                        key = (cid, wd, subject_id, w)
                        subj_count[key] = subj_count.get(key, 0) + 1
        return class_occ, teacher_occ, room_occ, subj_count

    def check(self, placements: list[Placement], ignore_entry_ids: set[int]) -> list[Conflict]:
        class_occ, teacher_occ, room_occ, subj_count = self._build_occupancy(ignore_entry_ids)
        conflicts: list[Conflict] = []
        batch_teacher: dict[int, list[_Occ]] = {}
        batch_room: dict[int, list[_Occ]] = {}

        for pl in placements:
            a = pl.assignment
            wd = pl.weekday
            parity = a.week_parity
            table_id = self._table_id(a)
            if table_id is None:
                conflicts.append(Conflict("H5", f"{self._desc(a)} 尚无可用节次表"))
                continue
            pmap = self._period_map(table_id)

            # H5/H6:区块涵盖的节次须存在且皆为一般课
            covered: list[tuple[int, time | None, time | None]] = []
            block_ok = True
            for k in range(pl.span):
                pno = pl.period_no + k
                p = pmap.get((wd, pno))
                if p is None or p.type != PeriodType.regular.value:
                    block_ok = False
                    break
                covered.append((pno, p.start_time, p.end_time))
            if not block_ok:
                if pl.span > 1:
                    conflicts.append(Conflict(
                        "H6",
                        f"连堂课排在 {self._slot(pmap, wd, pl.period_no)} 会跨越午休或非上课时段"
                        f"(需连续 {pl.span} 节一般课)",
                    ))
                else:
                    conflicts.append(Conflict(
                        "H5",
                        f"{self._slot(pmap, wd, pl.period_no)} 非一般上课节次,不可排课"))
                continue

            # H1:班级不冲堂(仅比对既有格位;同群组成员班级共用不算冲突)
            for c in self._classes(a):
                for pno, _s, _e in covered:
                    for d, d_parity in class_occ.get((c.id, wd, pno), []):
                        if overlaps(d_parity, parity):
                            conflicts.append(Conflict(
                                "H1", f"班级 {c.name} {self._slot(pmap, wd, pno)} 已有 {d}"))

            # H4 教师不可排时段 + H2 教师不冲堂(含跨表时间重叠、同群组其他门课)
            for at in a.teachers:
                t = at.teacher
                for pno, s, e in covered:
                    label = self._slot(pmap, wd, pno)
                    for rule in t.time_rules:
                        if (rule.rule_type == "unavailable"
                                and rule.weekday == wd and rule.period_no == pno):
                            conflicts.append(Conflict(
                                "H4", f"教师{t.name} {label} 为不可排时段"))
                    for occ in teacher_occ.get(at.teacher_id, []):
                        if self._overlap(occ, wd, table_id, pno, s, e, parity):
                            conflicts.append(Conflict(
                                "H2",
                                f"教师{t.name} {label} 已有 {self._occ_desc(occ, table_id)}"))
                    for occ in batch_teacher.get(at.teacher_id, []):
                        if self._overlap(occ, wd, table_id, pno, s, e, parity):
                            conflicts.append(Conflict(
                                "H2", f"教师{t.name} {label} 与同群组另一门课撞课"))

            # H3 场地不冲堂(以格位实际场地判定,非配课上的默认场地)
            room_id = pl.effective_room_id
            if room_id:
                for pno, s, e in covered:
                    for occ in room_occ.get(room_id, []) + batch_room.get(room_id, []):
                        if self._overlap(occ, wd, table_id, pno, s, e, parity):
                            conflicts.append(Conflict(
                                "H3",
                                f"场地 {self._room_name(room_id)} "
                                f"{self._slot(pmap, wd, pno)} "
                                f"已有 {self._occ_desc(occ, table_id)}"))

            # H10 同班同科目每日上限。连堂(span>1)是一次上完的整块,不计亦不受限;
            # 但连堂课剩下的单节仍受限——定义以 solver/validator.py 为准。
            if pl.span == 1:
                for c in self._classes(a):
                    existing = max(
                        subj_count.get((c.id, wd, a.subject_id, w), 0)
                        for w in ((parity,) if parity else PARITIES)
                    )
                    if existing + 1 > self.cap:
                        conflicts.append(Conflict(
                            "H10",
                            f"班级 {c.name} {_wd(wd)} 已排「{a.subject.name}」{existing} 节,"
                            f"达每日上限 {self.cap} 节",
                        ))

            # 累积批次教师/场地占用(同群组其他门课据此互检)
            desc = self._desc(a)
            for at in a.teachers:
                for pno, s, e in covered:
                    batch_teacher.setdefault(at.teacher_id, []).append(
                        _Occ(wd, table_id, pno, s, e, desc, parity))
            if room_id:
                for pno, s, e in covered:
                    batch_room.setdefault(room_id, []).append(
                        _Occ(wd, table_id, pno, s, e, desc, parity))

        return conflicts


def placements_for(
    db: Session,
    assignment: CourseAssignment,
    weekday: int,
    period_no: int,
    span: int,
    room_id: int | None = None,
) -> list[Placement]:
    """展开实际要放入的配课:跑班群组 → 群组内全部配课同格(span=1);
    单双周组 → 单周、双周两笔同格(可以是连堂,两笔的连堂结构相同);单班 → 该配课。

    room_id 为「本次放入的场地」,只套用在被拖曳的那一笔配课上;
    群组内的其他门课各自使用自己的场地(跑班的每组本来就在不同教室)。
    """
    su = assignment.scheduling_unit
    if su.unit_type == SchedulingUnitType.alternate.value:
        sibs = list(
            db.scalars(
                select(CourseAssignment).where(CourseAssignment.scheduling_unit_id == su.id)
                .order_by(CourseAssignment.id)
            )
        )
        return [
            Placement(s, weekday, period_no, span, room_id if s.id == assignment.id else None)
            for s in sibs
        ]
    if su.unit_type == SchedulingUnitType.group.value:
        sibs = list(
            db.scalars(
                select(CourseAssignment).where(CourseAssignment.scheduling_unit_id == su.id)
                .order_by(CourseAssignment.id)   # 顺序固定:格位依配课建立的先后写入
            )
        )
        return [
            Placement(s, weekday, period_no, 1, room_id if s.id == assignment.id else None)
            for s in sibs
        ]
    return [Placement(assignment, weekday, period_no, span, room_id)]


def check_conflict(
    db: Session,
    timetable: Timetable,
    assignment: CourseAssignment,
    weekday: int,
    period_no: int,
    span: int = 1,
    ignore_entry_ids: set[int] | None = None,
    room_id: int | None = None,
    daily_subject_cap: int | None = None,
) -> list[Conflict]:
    """检查将 assignment 放到 (weekday, period_no) 是否违反硬约束。

    移动既有格位时传 ignore_entry_ids(被搬动的那几格),使其不与自己相冲。
    room_id 为格位指定场地(空=沿用配课场地)。回传空清单表示可放。

    H10 的每日上限**必须与自动排课用同一个值**(学期的 constraint_config),
    否则同一张草稿会出现「自动排课排得出来、手动拖曳却报违规」的双轨判定。
    未指定时自动读取该学期设置。
    """
    if daily_subject_cap is None:
        daily_subject_cap = load_config(db, timetable.semester_id).daily_subject_cap
    checker = _Checker(db, timetable, daily_subject_cap)
    placements = placements_for(db, assignment, weekday, period_no, span, room_id)
    return checker.check(placements, ignore_entry_ids or set())
