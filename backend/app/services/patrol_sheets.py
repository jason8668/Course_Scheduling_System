"""课堂巡视情况记录表(课堂巡视情况记录表)的资料组装(v1.2.12)。

巡视人员拿著这张纸逐班走:每一节、每一班「现在应该是谁在上什么课、在哪里」。
周课表答不了这个问题——调代课之后,那一天的老师、科目可能都换了。这里把
「已发布的周课表」与「那一天的调代课处置」叠起来,印出当天真正的样子。

版面照使用学校的纸本:

- **课堂巡视情况记录表**:班级为栏、节次为列,一天分上午/下午各一张(以午休为界;早自习、
  午休等非一般课的时段不列)。每格印科目、教师、教室与备注(代课/调课/…);
  授课情形、学生学习、巡视签名留白手写。班级多的学校自动分页。
- **分组巡视单**:社团、多元选修这类「一个时段全校拆成很多组」的跑班群组,
  十几组塞不进一个格子,另外列成清单(一列一组:名称、教师、地点)。
  主表那一格只写群组名称与组数。

**巡视人员不在表上。** 纸本是签名栏,由巡视的人自己签;系统不管巡视轮值。

本模组只读,不写资料库。
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.week_parity import runs_in_week, week_parity
from app.models.basedata import ClassUnit
from app.models.leave import AffectedPeriod, AffectedStatus, LeaveRequest, LeaveStatus
from app.models.period import Period, PeriodTable, PeriodType
from app.models.semester import Semester
from app.models.substitution import Substitution, SubstitutionType
from app.models.timetable import ScheduleEntry
from app.services import period_tables as pt_service
from app.services import settings as app_settings
from app.services.availability import published_timetable
from app.services.slip_layout import school_title

# dataclass 栏位名 date 会遮蔽同名型别(mypy 判为变数),故型别一律用别名
_Date = date

CLASSES_PER_PAGE = 12       # A4 横式一页放得下的班级栏数(照使用学校的纸本)
GROUP_LIST_MIN = 4          # 群组在同一节有几门课以上,就改列成分组巡视单
MAX_DAYS = 14               # 一次最多印几天
_NOON = time(12, 0)

_NOTE = {
    SubstitutionType.substitute.value: "代课",
    SubstitutionType.swap.value: "调课",
    SubstitutionType.merge.value: "并班",
    SubstitutionType.self_study.value: "自习",
    SubstitutionType.cancel.value: "停课",
}
_PENDING = "请假待处理"


@dataclass(frozen=True, slots=True)
class PatrolCell:
    subject: str = ""
    teacher: str = ""
    room: str = ""
    note: str = ""


@dataclass
class PatrolRow:
    ordinal: int              # 第几节(只数一般课)
    name: str                 # 节次名称「第一节」
    cells: list[PatrolCell] = field(default_factory=list)   # 与 PatrolPage.classes 一一对应


@dataclass
class PatrolPage:
    date: _Date
    table_name: str           # 全校只有一套节次表时为空字串
    first_ordinal: int        # 抬头的「第 1~4 节」
    last_ordinal: int
    classes: list[str] = field(default_factory=list)
    rows: list[PatrolRow] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class GroupItem:
    no: int
    subject: str
    teacher: str
    room: str
    note: str


@dataclass
class GroupList:
    date: _Date
    group_name: str
    period_name: str
    items: list[GroupItem] = field(default_factory=list)


@dataclass
class PatrolSheets:
    title: str                # 「示范学校2026-2027学年第一学期」
    legend: str               # 纸本下方的记录说明(各校代码不同,可在系统管理修改)
    pages: list[PatrolPage] = field(default_factory=list)
    group_lists: list[GroupList] = field(default_factory=list)


class PatrolError(Exception):
    """印不出课堂巡视情况记录表(呼叫端转 404/400)。"""


@dataclass(frozen=True, slots=True)
class _Lesson:
    """某一班某一节实际上的一门课(已套用当天的调代课)。"""

    unit_id: int
    unit_name: str
    is_group: bool
    subject: str
    teacher: str
    room: str
    note: str


def _days(date_from: date, date_to: date) -> Iterator[date]:
    d = date_from
    while d <= date_to:
        yield d
        d += timedelta(days=1)


def _halves(periods: list[Period]) -> list[list[tuple[int, Period]]]:
    """把一天的一般课切成上午/下午,并编上「第几节」。

    以午休为界;节次表没有午休时改以 12:00 为界;两者都判断不出来就整天一张。
    """
    ordered = sorted(periods, key=lambda p: p.period_no)
    lunch = next((p.period_no for p in ordered if p.type == PeriodType.lunch.value), None)
    regular = [p for p in ordered if p.type == PeriodType.regular.value]
    numbered = list(enumerate(regular, start=1))

    def is_morning(p: Period) -> bool:
        if lunch is not None:
            return p.period_no < lunch
        return p.start_time is None or p.start_time < _NOON

    morning = [x for x in numbered if is_morning(x[1])]
    afternoon = [x for x in numbered if not is_morning(x[1])]
    return [half for half in (morning, afternoon) if half]


def _same_class(ap: AffectedPeriod, sub: Substitution) -> bool:
    return ap.class_names == sub.swap_class_names


class _Day:
    """某一天的实际课表:周课表格位 + 当天的请假与调代课。"""

    def __init__(self, db: Session, semester_id: int, timetable_id: int, on: date) -> None:
        self.db = db
        self.on = on
        weekday = on.isoweekday()
        semester = db.get(Semester, semester_id)
        week = week_parity(semester.start_date if semester else None, on)
        self.entries = [
            e for e in db.scalars(
                select(ScheduleEntry).where(
                    ScheduleEntry.timetable_id == timetable_id, ScheduleEntry.weekday == weekday)
            )
            # 单双周的课只在对应的那一周出现在课堂巡视情况记录表上(v1.3.0)
            if runs_in_week(e.assignment.week_parity, week)
        ]
        live = (
            LeaveRequest.status == LeaveStatus.registered.value,
            AffectedPeriod.status != AffectedStatus.cancelled.value,
            AffectedPeriod.semester_id == semester_id,
        )
        # 当天请假的节次:(配课, 节次) → (受影响节次, 处置或 None)
        absent = db.scalars(
            select(AffectedPeriod)
            .join(LeaveRequest, AffectedPeriod.leave_request_id == LeaveRequest.id)
            .where(AffectedPeriod.date == on, *live)
        ).unique().all()
        subs = {
            s.affected_period_id: s for s in db.scalars(
                select(Substitution).where(
                    Substitution.affected_period_id.in_([a.id for a in absent] or [0])))
        }
        self.absent: dict[tuple[int | None, int], tuple[AffectedPeriod, Substitution | None]] = {
            (a.course_assignment_id, a.period_no): (a, subs.get(a.id)) for a in absent
        }
        # 当天因调课回来补课的节次:(格位, 节次) → (请假那一节, 调课处置)
        self.makeup: dict[tuple[int | None, int | None], tuple[AffectedPeriod, Substitution]] = {}
        for sub in db.scalars(
            select(Substitution)
            .join(AffectedPeriod, Substitution.affected_period_id == AffectedPeriod.id)
            .join(LeaveRequest, AffectedPeriod.leave_request_id == LeaveRequest.id)
            .where(
                Substitution.type == SubstitutionType.swap.value,
                Substitution.swap_date == on, *live)
        ):
            ap = db.get(AffectedPeriod, sub.affected_period_id)
            if ap is not None:
                self.makeup[(sub.swap_entry_id, sub.swap_period_no)] = (ap, sub)

    def _lesson(self, entry: ScheduleEntry, period_no: int) -> _Lesson:
        a = entry.assignment
        unit = a.scheduling_unit
        room = entry.room if entry.room is not None else a.room
        names = [at.teacher.name for at in a.teachers]
        subject, note = a.subject.name, ""

        def replace(absent_name: str, by: str) -> None:
            """只换掉请假的那一位;协同教学的另一位老师照常上课。"""
            if absent_name in names:
                names[names.index(absent_name)] = by
            else:
                names[:] = [by]

        if (a.id, period_no) in self.absent:
            ap, sub = self.absent[(a.id, period_no)]
            absent_name = ap.leave_request.teacher.name if ap.leave_request.teacher else ""
            if sub is None:
                note = _PENDING
            else:
                note = _NOTE.get(sub.type, "")
                if sub.handler is not None:
                    replace(absent_name, sub.handler.name)
                elif absent_name in names:      # 自习、停课:没有人接手,请假的那位不会来
                    names.remove(absent_name)
                if sub.type == SubstitutionType.swap.value and _same_class(ap, sub):
                    subject = sub.swap_subject_name or subject   # 同班互调:科目跟著老师走
        elif (entry.id, period_no) in self.makeup:
            ap, sub = self.makeup[(entry.id, period_no)]
            note = _NOTE[SubstitutionType.swap.value]
            partner = sub.handler.name if sub.handler else ""
            back = ap.leave_request.teacher.name if ap.leave_request.teacher else ""
            replace(partner, back)
            if _same_class(ap, sub):
                subject = ap.subject_name or subject

        return _Lesson(
            unit_id=unit.id, unit_name=unit.name, is_group=unit.unit_type == "group",
            subject=subject, teacher="、".join(names), room=room.name if room else "", note=note,
        )

    def lessons(self, class_id: int, period_no: int) -> list[_Lesson]:
        """这一班这一节的课;跑班时会有好几门(每一组一门),依配课建立的顺序排列。

        顺序不能看格位:群组的格位是一次整批写入的,写入顺序取决于资料库怎么回传配课,
        PostgreSQL 并不保证。分组巡视单的编号要每次都对到同一个社团,故以配课 id 为准。
        """
        out = []
        for e in self.entries:
            if not (e.period_no <= period_no < e.period_no + e.span):
                continue
            if any(m.class_unit_id == class_id for m in e.assignment.scheduling_unit.members):
                out.append((e.course_assignment_id, self._lesson(e, period_no)))
        return [lesson for _, lesson in sorted(out, key=lambda x: x[0])]


def _join(values: list[str], sep: str = "／") -> str:
    return sep.join(dict.fromkeys(v for v in values if v))


def _cell(lessons: list[_Lesson]) -> PatrolCell:
    if not lessons:
        return PatrolCell()
    if lessons[0].is_group and len(lessons) >= GROUP_LIST_MIN:
        return PatrolCell(
            subject=lessons[0].unit_name, teacher=f"共 {len(lessons)} 组", note="见分组巡视单")
    return PatrolCell(
        subject=_join([x.subject for x in lessons]),
        teacher=_join([x.teacher for x in lessons]),
        room=_join([x.room for x in lessons]),
        note=_join([x.note for x in lessons], "、"),
    )


def legend(db: Session) -> str:
    return app_settings.patrol_legend(db)


def build(db: Session, semester_id: int, date_from: date, date_to: date) -> PatrolSheets:
    """把一段期间的每一天组成课堂巡视情况记录表;没有课的日子(假日)自动略过。"""
    if date_to < date_from:
        raise PatrolError("结束日期不可早于开始日期")
    if (date_to - date_from).days >= MAX_DAYS:
        raise PatrolError(f"一次最多打印 {MAX_DAYS} 天")
    timetable = published_timetable(db, semester_id)
    if timetable is None:
        raise PatrolError("此学期尚无已发布的课表")

    classes = list(db.scalars(
        select(ClassUnit).where(ClassUnit.semester_id == semester_id)
        .order_by(ClassUnit.grade, ClassUnit.name)
    ))
    by_table: dict[int, tuple[PeriodTable, list[ClassUnit]]] = {}
    for c in classes:
        table = pt_service.resolve_period_table(db, c)
        if table is not None:
            by_table.setdefault(table.id, (table, []))[1].append(c)
    multi = len(by_table) > 1

    result = PatrolSheets(title=school_title(db, semester_id), legend=legend(db))
    for on in _days(date_from, date_to):
        day = _Day(db, semester_id, timetable.id, on)
        if not day.entries:
            continue
        listed: set[tuple[int, int]] = set()      # 已出过分组单的 (群组, 节次)
        for table, members in by_table.values():
            periods = [p for p in table.periods if p.weekday == on.isoweekday()]
            for half in _halves(periods):
                for i in range(0, len(members), CLASSES_PER_PAGE):
                    chunk = members[i:i + CLASSES_PER_PAGE]
                    page = PatrolPage(
                        date=on, table_name=table.name if multi else "",
                        first_ordinal=half[0][0], last_ordinal=half[-1][0],
                        classes=[c.name for c in chunk],
                    )
                    for ordinal, period in half:
                        row = PatrolRow(ordinal=ordinal, name=period.name)
                        for c in chunk:
                            lessons = day.lessons(c.id, period.period_no)
                            row.cells.append(_cell(lessons))
                            big = lessons and lessons[0].is_group and len(lessons) >= GROUP_LIST_MIN
                            key = (lessons[0].unit_id, period.period_no) if big else None
                            if key and key not in listed:
                                listed.add(key)
                                result.group_lists.append(GroupList(
                                    date=on, group_name=lessons[0].unit_name,
                                    period_name=period.name,
                                    items=[GroupItem(n, x.subject, x.teacher, x.room, x.note)
                                           for n, x in enumerate(lessons, start=1)],
                                ))
                        page.rows.append(row)
                    result.pages.append(page)
    if not result.pages:
        raise PatrolError("这段期间没有任何课(可能是假日,或课表尚未排入)")
    return result
