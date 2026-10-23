"""课表检查:对一份既有课表重跑硬约束(v1.2.18,用户回报 #40、#41)。

手动排入每一步都有 `conflict_checker` 把关、自动排课的结果也合规,所以正常操作排出来的
课表不会有冲堂。会出问题的是「课表排好之后,规则或资料又改了」——事后把某节设成教师
不可排、改了配课的老师或场地、调低每日上限——这时课表与规则已经矛盾,界面上却没有任何
地方看得出来,发布也只检查有没有排完。

这里直接沿用求解器的 `validator`(与自动排课同一套定义),再做三件事让它适合给人看:

- **「还没排完」不算违规**:那是 `timetable_publish.completeness` 的事,发布时本来就会列。
  节数已经排满、但连堂的切法与设置不同,才会留下来。
- **不检查锁定(H9)**:那是「自动排课不可移动锁定格位」,对一份静态的课表没有意义。
- **「需要场地却未指派」不算违规**:手动排课不会替「需要某类型场地」的课挑教室,
  那只是还没指定,不是冲突。排进了类型不符的教室才列出。
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assignment import AssignmentTeacher, CourseAssignment
from app.models.basedata import Teacher, TeacherRuleType
from app.models.timetable import ScheduleEntry, Timetable, TimetableStatus
from app.services.solver_data import load_config, load_problem
from app.solver.problem import AssignmentSpec, Problem, SolvedEntry
from app.solver.validator import Violation, validate

# 给界面分组用的标题;顺序即显示顺序
CODE_LABELS: dict[str, str] = {
    "H1": "班级冲堂",
    "H2": "教师冲堂",
    "H3": "场地冲堂",
    "H4": "教师不可排时段",
    "H5": "排在非上课节次",
    "H6": "连堂跨越午休",
    "H7": "跑班群组未同时段",
    "H8": "节数或连堂与配课不符",
    "H10": "超过每日上限",
    "room_type": "场地类型不符",
    "input": "资料不一致",
}

_WEEKDAYS = "一二三四五六日"


@dataclass(frozen=True, slots=True)
class CheckIssue:
    code: str
    label: str
    message: str


def _keep(v: Violation) -> bool:
    if v.code == "H9":
        return False
    if v.code == "H8":
        # 排入节数少于应排 = 还没排完,交给完整性检查;排满或排超过才是这里要讲的
        placed = sum(v.detail.get("placed", []))
        expected = sum(v.detail.get("expected", []))
        return placed >= expected
    if v.code == "room_type":
        return "room_id" in v.detail  # 没指派教室不算;排错类型才算
    return True


def _shape(lengths: list[int]) -> str:
    """[3, 3, 1] → 「3 连堂 2 次、单节 1 节」。"""
    parts = []
    for size in sorted({n for n in lengths if n > 1}, reverse=True):
        parts.append(f"{size} 连堂 {lengths.count(size)} 次")
    singles = lengths.count(1)
    if singles:
        parts.append(f"单节 {singles} 节")
    return "、".join(parts) or "无"


def _message(problem: Problem, spec: AssignmentSpec | None, v: Violation) -> str:
    """validator 的讯息是写给开发者看的(只有科目、节长用串列);这里补上班级、改成人话。"""
    if spec is None:
        return v.message
    classes = "、".join(c.name for c in problem.classes_of(spec))
    who = f"{classes}「{spec.subject_name}」" if classes else f"「{spec.subject_name}」"
    if v.code == "H8":
        placed, expected = v.detail.get("placed", []), v.detail.get("expected", [])
        if sum(placed) > sum(expected):
            return f"{who}排了 {sum(placed)} 节,超过配课的每周 {sum(expected)} 节"
        return f"{who}的连堂排法与配课不同:配课是{_shape(expected)},课表是{_shape(placed)}"
    head = f"「{spec.subject_name}」"
    return who + v.message[len(head):] if v.message.startswith(head) else v.message


def check(db: Session, timetable: Timetable) -> list[CheckIssue]:
    """这份课表目前违反的硬约束;空清单表示没有问题。未排完不在此列。"""
    problem = load_problem(db, timetable.semester_id)
    cap = load_config(db, timetable.semester_id).daily_subject_cap
    rows = db.scalars(
        select(ScheduleEntry)
        .where(ScheduleEntry.timetable_id == timetable.id)
        .order_by(ScheduleEntry.weekday, ScheduleEntry.period_no, ScheduleEntry.id)
    ).all()
    entries = [
        SolvedEntry(e.course_assignment_id, e.weekday, e.period_no, e.span, e.room_id)
        for e in rows
    ]
    order = {code: i for i, code in enumerate(CODE_LABELS)}
    issues: list[CheckIssue] = []
    seen: set[tuple[str, str]] = set()
    spec_by_id = {a.id: a for a in problem.assignments}
    for v in validate(problem, entries, daily_subject_cap=cap):
        if not _keep(v):
            continue
        message = _message(problem, spec_by_id.get(v.detail.get("assignment_id", 0)), v)
        if (v.code, message) in seen:
            continue
        seen.add((v.code, message))
        issues.append(CheckIssue(v.code, CODE_LABELS.get(v.code, v.code), message))
    issues.sort(key=lambda i: order.get(i.code, len(order)))
    return issues


@dataclass(frozen=True, slots=True)
class UnavailableHit:
    """某位教师的一节课落在他的不可排时段。"""

    timetable_id: int
    timetable_name: str
    timetable_status: str
    weekday: int
    period_no: int
    period_name: str
    subject: str
    classes: str

    @property
    def text(self) -> str:
        day = _WEEKDAYS[self.weekday - 1] if 1 <= self.weekday <= 7 else str(self.weekday)
        return f"周{day}{self.period_name} {self.classes} {self.subject}"


def unavailable_hits(db: Session, teacher: Teacher) -> list[UnavailableHit]:
    """这位教师在草稿与已发布课表中,落在「不可排」时段的课(#41)。

    储存时段规则之后呼叫:规则常是学期初凭印象设的,课表排好后再改,两边就可能矛盾。
    封存的课表是历史快照,不看。
    """
    blocked = {
        (r.weekday, r.period_no)
        for r in teacher.time_rules
        if r.rule_type == TeacherRuleType.unavailable.value
    }
    if not blocked:
        return []

    rows = db.execute(
        select(ScheduleEntry, Timetable, CourseAssignment)
        .join(Timetable, Timetable.id == ScheduleEntry.timetable_id)
        .join(CourseAssignment, CourseAssignment.id == ScheduleEntry.course_assignment_id)
        .join(AssignmentTeacher, AssignmentTeacher.course_assignment_id == CourseAssignment.id)
        .where(
            AssignmentTeacher.teacher_id == teacher.id,
            Timetable.semester_id == teacher.semester_id,
            Timetable.status.in_(
                [TimetableStatus.draft.value, TimetableStatus.published.value]
            ),
        )
        .order_by(
            # 已发布的排前面:那是老师们正在照著上课的那一份
            Timetable.status.desc(), Timetable.id,
            ScheduleEntry.weekday, ScheduleEntry.period_no, ScheduleEntry.id,
        )
    ).all()
    if not rows:
        return []

    problem = load_problem(db, teacher.semester_id)
    spec_by_id = {a.id: a for a in problem.assignments}
    hits: list[UnavailableHit] = []
    for entry, tt, assignment in rows:
        spec = spec_by_id.get(assignment.id)
        table = problem.table_of(spec) if spec else None
        classes = "、".join(c.name for c in problem.classes_of(spec)) if spec else ""
        for k in range(entry.span):
            pno = entry.period_no + k
            if (entry.weekday, pno) not in blocked:
                continue
            slot = table.slot(entry.weekday, pno) if table else None
            hits.append(UnavailableHit(
                timetable_id=tt.id, timetable_name=tt.name, timetable_status=tt.status,
                weekday=entry.weekday, period_no=pno,
                period_name=slot.name if slot else f"第 {pno} 格",
                subject=assignment.subject.name, classes=classes,
            ))
    return hits
