"""通知单(调课单、代课单)共用的版面组装。

纸本一律是一张周课表,只在「有异动的格子」写上日期、科目与一行说明;
格线、节次列、下午粗线、跨周分页都一样。调课单(v1.2.2)与代课单(v1.2.5)
差在表头栏位与格子里那一行字,故把相同的部分抽在这里共用。

本模组只读,不写资料库;资料全部来自处置的快照栏位与节次表。
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assignment import CourseAssignment
from app.models.period import Period, PeriodType
from app.models.semester import Semester
from app.services import period_tables as pt_service
from app.services import settings as app_settings

# dataclass 栏位名 date 会遮蔽同名型别(mypy 判为变数),故型别一律用别名
_Date = date

_TERM_CN = {1: "一", 2: "二", 3: "三"}
_AFTERNOON = time(12, 0)


@dataclass(frozen=True, slots=True)
class SlipRow:
    ordinal: int              # 第几节(只数一般课,早自习/午休不算)
    start_time: time | None
    end_time: time | None
    afternoon_starts: bool    # 这一列是下午的第一节(纸本在这里画粗线)


@dataclass(frozen=True, slots=True)
class SlipCell:
    date: _Date
    weekday: int
    ordinal: int
    subject_name: str
    actor: str                # 第三行:调课单写实际上课的老师;代课单写「班级[代]」或「老师[代]」
    code: str                 # 调课单的「调09-15_25」(与 9/15 星期二第 5 节对调);代课单没有
    time_note: str = ""       # 这一格属于另一套节次表、时间与所在列不同时,写实际时间


@dataclass
class SlipWeek:
    monday: _Date
    days: list[_Date] = field(default_factory=list)
    cells: list[SlipCell] = field(default_factory=list)


@dataclass
class Slip:
    kind: str                 # teacher / class
    teacher_name: str         # 教师单的主角:调课教师 / 代课教师
    class_names: str
    date_from: _Date
    date_to: _Date
    absent_teacher_name: str = ""   # 代课单才有:请假教师
    leave_type_name: str = ""       # 代课单才有:假别
    funding_label: str = ""         # 代课单才有:计费方式
    rows: list[SlipRow] = field(default_factory=list)
    weeks: list[SlipWeek] = field(default_factory=list)


@dataclass
class Slips:
    title: str                # 调课单「示范初中115学年第一学期」;代课单只有校名
    kind: str = "swap"        # swap / substitute:决定纸本抬头
    slips: list[Slip] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Move:
    """一个异动格:某天某节,某班改由某老师上某科。"""

    date: _Date
    period_no: int
    class_names: str
    subject_name: str
    teacher_id: int
    teacher_name: str
    table_id: int | None
    code: str = ""            # 调课单的对调代码
    mark: str = ""            # 接在人名/班级后的标记,如「[代]」「[并]」


class SlipError(Exception):
    """要印的不是有效的处置(呼叫端转 404/409)。"""


class Tables:
    """节次表快取:算「第几节」与列出一般课的列。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self._cache: dict[int, list[Period]] = {}

    def of_assignment(self, assignment_id: int | None) -> int | None:
        a = self.db.get(CourseAssignment, assignment_id) if assignment_id else None
        if a is None or not a.scheduling_unit.members:
            return None
        table = pt_service.resolve_period_table(self.db, a.scheduling_unit.members[0].class_unit)
        return table.id if table else None

    def regular(self, table_id: int | None, weekday: int) -> list[Period]:
        if table_id is None:
            return []
        if table_id not in self._cache:
            self._cache[table_id] = list(self.db.scalars(
                select(Period).where(Period.period_table_id == table_id)
                .order_by(Period.weekday, Period.period_no)))
        return [p for p in self._cache[table_id]
                if p.weekday == weekday and p.type == PeriodType.regular.value]

    def ordinal(self, table_id: int | None, weekday: int, period_no: int) -> int:
        for i, p in enumerate(self.regular(table_id, weekday), start=1):
            if p.period_no == period_no:
                return i
        return period_no  # 节次表查不到:退回内部节次号,至少不会印空白

    def time_note(self, shown: int | None, own: int | None, weekday: int, period_no: int) -> str:
        """`own` 节次表的这一节,若与 `shown`(纸本格线用的那套)同一列的时间不同,回实际时间。

        初中小、完全中学的老师可能同一张单子上有两部的课;格线只能照一套画,
        另一部的课不标时间的话,老师会照格线上的时间去上课。
        """
        if shown is None or own is None or shown == own:
            return ""
        mine = next((p for p in self.regular(own, weekday) if p.period_no == period_no), None)
        if mine is None or mine.start_time is None or mine.end_time is None:
            return ""
        ordinal = self.ordinal(own, weekday, period_no)
        rows = self.regular(shown, weekday)
        row = rows[ordinal - 1] if 0 < ordinal <= len(rows) else None
        if row and (row.start_time, row.end_time) == (mine.start_time, mine.end_time):
            return ""
        return f"{mine.start_time:%H:%M}–{mine.end_time:%H:%M}"

    def weekdays(self, table_id: int | None) -> int:
        if table_id is None:
            return 5
        self.regular(table_id, 1)
        return max((p.weekday for p in self._cache[table_id]), default=5)

    def rows(self, table_id: int | None) -> list[SlipRow]:
        periods = self.regular(table_id, 1)
        out: list[SlipRow] = []
        for i, p in enumerate(periods, start=1):
            prev = periods[i - 2] if i > 1 else None
            afternoon = bool(
                prev and prev.start_time and p.start_time
                and prev.start_time < _AFTERNOON <= p.start_time
            )
            out.append(SlipRow(i, p.start_time, p.end_time, afternoon))
        return out


def school_title(db: Session, semester_id: int | None = None) -> str:
    """校名;给了学期就再接「115学年第一学期」(调课单纸本有,代课单没有)。"""
    school = app_settings.school_name(db)
    sem = db.get(Semester, semester_id) if semester_id else None
    if sem is None:
        return school
    return f"{school}{sem.academic_year}学年第{_TERM_CN.get(sem.term, str(sem.term))}学期"


def assemble(
    tables: Tables, kind: str, teacher_name: str, moves: list[Move],
    actor_of: Callable[[Move], str],
) -> Slip:
    """把异动格排进周课表:跨周会产生多个 `SlipWeek`(打印页一周一页)。"""
    # 格线照「节数最多」的那套节次表画:初中七节、高中八节的完全中学,
    # 跨部老师的单子若照初中画,高中第八节那一格会没有列可以放、印不出来。
    table_id = max(
        dict.fromkeys(m.table_id for m in moves), key=lambda t: len(tables.rows(t)))
    n_days = tables.weekdays(table_id)
    classes = list(dict.fromkeys(m.class_names for m in moves))
    slip = Slip(
        kind=kind, teacher_name=teacher_name, class_names="、".join(classes),
        date_from=min(m.date for m in moves), date_to=max(m.date for m in moves),
        rows=tables.rows(table_id),
    )
    weeks: dict[_Date, SlipWeek] = {}
    for m in sorted(moves, key=lambda m: (m.date, m.period_no)):
        monday = m.date - timedelta(days=m.date.isoweekday() - 1)
        week = weeks.setdefault(monday, SlipWeek(
            monday=monday, days=[monday + timedelta(days=i) for i in range(n_days)]))
        week.cells.append(SlipCell(
            date=m.date, weekday=m.date.isoweekday(),
            ordinal=tables.ordinal(m.table_id, m.date.isoweekday(), m.period_no),
            subject_name=m.subject_name, actor=actor_of(m), code=m.code,
            time_note=tables.time_note(table_id, m.table_id, m.date.isoweekday(), m.period_no),
        ))
    slip.weeks = [weeks[k] for k in sorted(weeks)]
    return slip
