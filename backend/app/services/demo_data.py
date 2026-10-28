"""示范资料产生器:一键建出一所完整的示范初中。

为什么需要这个:装好系统之后,用户面对的是一个空系统——要看到「自动排课」
做了什么,得先手 key 十几个班级、四十几位教师、几百笔配课。连本专案作者
自己想完整走一遍都卡在「手边没有资料」,遑论素未谋面的评估者。

规格在 app/data/demo_school.json,这里只负责把规格算成实际资料:
教师名册、应授节数、以及「哪位老师教哪一班的哪一科」都是推算出来的,
改 JSON 里的人数,配课会自动重新平衡。

只在空学期上执行(呼叫端负责挡)。
"""

import json
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.assignment import AssignmentTeacher, CourseAssignment
from app.models.basedata import ClassTrack, ClassUnit, Room, Subject, Teacher
from app.models.semester import Semester
from app.models.wizard import SINGLETON_ID, TOTAL_STEPS, WizardState
from app.services import settings as settings_service
from app.services import teacher_grades as teacher_grades_service
from app.services import templates as template_service
from app.services.assignments import get_or_create_single_unit

_SPEC_PATH = Path(__file__).resolve().parent.parent / "data" / "demo_school.json"

# 教师身分。顺序即配课的优先序:班主任要先拿到自己班的课(软约束 S7 才有东西可排),
# 行政人员应授少、最后才补,免得把他们塞爆。
ROLE_HOMEROOM = "班主任"
ROLE_FULLTIME = "专任"
ROLE_EXTERNAL = "外聘"
ROLE_ORDER = [ROLE_HOMEROOM, ROLE_FULLTIME, "组长", "主任", "心理教师", ROLE_EXTERNAL]


@lru_cache
def load_spec() -> dict:
    with open(_SPEC_PATH, encoding="utf-8") as fh:
        return json.load(fh)


@dataclass
class _TeacherPlan:
    """建表前的教师规划:先算好应授节数,再决定配课。"""

    name: str
    dept: str
    role: str
    base_periods: int
    admin_reduction: int = 0
    admin_title: str | None = None
    is_external: bool = False
    homeroom_of: str | None = None          # 班主任带的班名
    assigned: int = 0                        # 累计配课节数
    model: Teacher | None = field(default=None, repr=False)

    @property
    def target(self) -> int:
        return max(self.base_periods - self.admin_reduction, 0)

    @property
    def headroom(self) -> int:
        """离应授还差几节。负数代表已超课时。"""
        return self.target - self.assigned


@dataclass
class DemoSummary:
    """产生结果,供 API 回报与测试断言。"""

    semester_id: int
    school_name: str
    classes: int
    teachers: int
    subjects: int
    rooms: int
    assignments: int
    total_periods: int
    max_overtime_used: int   # 全校最大超课时节数
    under_target: int        # 未达应授的教师数


def _base_for(spec: dict, dept: str, role: str) -> int:
    """该科该身分的基本课时。行政职以『专任』为基准,再靠减课降到规定的应授。"""
    table = spec["base_periods"].get(dept, spec["base_periods"]["_default"])
    if role == ROLE_HOMEROOM:
        return table[ROLE_HOMEROOM]
    return table[ROLE_FULLTIME]


def _plan_teachers(spec: dict, class_names: list[str]) -> list[_TeacherPlan]:
    """依编制表产生教师名册(含应授节数),班主任依序绑定班级。"""
    surnames, givens = spec["surnames"], spec["given_names"]
    titles = {k: list(v) for k, v in spec["admin_titles"].items()}
    homeroom_queue = list(class_names)
    plans: list[_TeacherPlan] = []

    for dept in spec["departments"]:
        dept_name = dept["name"]
        for role in ROLE_ORDER:
            for _ in range(dept.get(role, 0)):
                idx = len(plans)
                # 姓名以索引错开组合,49 个姓 × 49 个名足以避免重复
                name = surnames[idx % len(surnames)] + givens[(idx * 7 + 3) % len(givens)]
                plan = _TeacherPlan(
                    name=name,
                    dept=dept_name,
                    role=role,
                    base_periods=_base_for(spec, dept_name, role),
                    is_external=(role == ROLE_EXTERNAL),
                )
                if role in titles and titles[role]:
                    plan.admin_title = titles[role].pop(0)
                if role in spec["admin_targets"]:
                    # 主任/组长/专辅:规定写的是「应授几节」,换算成减课存进资料库
                    plan.admin_reduction = max(
                        plan.base_periods - spec["admin_targets"][role], 0
                    )
                if role == ROLE_HOMEROOM and homeroom_queue:
                    plan.homeroom_of = homeroom_queue.pop(0)
                if role == ROLE_EXTERNAL:
                    # 外聘兼任:没有专任基钟,以实际需求节数为应授
                    plan.base_periods = 0
                plans.append(plan)
    return plans


def _class_names(spec: dict) -> list[tuple[int, str]]:
    """班名。班级以「年级+序号」命名(7年级1班~9年级6班)。"""
    cfg = spec["classes"]
    fmt = cfg.get("name_format", "{grade}{index:02d}")
    return [
        (grade, fmt.format(grade=grade, index=i))
        for grade in cfg["grades"]
        for i in range(1, cfg["per_grade"] + 1)
    ]


def _demand(spec: dict, classes: list[tuple[int, str]]) -> list[tuple[str, str, int]]:
    """展开成 (班名, 科目名, 每周节数);没有该年级节数的科目自动跳过。"""
    rows: list[tuple[str, str, int]] = []
    for grade, cname in classes:
        for subj in spec["subjects"]:
            periods = subj["periods"].get(str(grade))
            if periods:
                rows.append((cname, subj["name"], periods))
    return rows


def _pick_teacher(pool: list[_TeacherPlan]) -> _TeacherPlan:
    """挑「剩余容量最多」的老师。

    这样自然会把课平均分散,而不是把前几位塞满、后几位没课。
    全科都满了就给最不满的那位,超出的部分成为超课时——真实学校也是这样。
    """
    return max(pool, key=lambda p: (p.headroom, -p.assigned))


def generate(db: Session, spec: dict | None = None) -> DemoSummary:
    """建立整所示范学校。呼叫端负责确认学期是空的,并负责 commit。"""
    spec = spec or load_spec()
    classes = _class_names(spec)
    class_names = [name for _, name in classes]

    # 校名一并设好。先前只能改 .env 再重启,示范资料的校名对不上很突兀。
    settings_service.save_school_name(db, spec["school_name"])

    # ── 学期与节次表(沿用既有的学制范本,示范资料不另造一套)──
    # 学期起止必须带上:本周课表、校历、课时统计都靠它算第几周,不填就没有第几周。
    semester = template_service.create_semester_from_template(
        db,
        academic_year=spec["academic_year"],
        term=spec["term"],
        template_key=spec["template_key"],
        start_date=date.fromisoformat(spec["start_date"]) if spec.get("start_date") else None,
        end_date=date.fromisoformat(spec["end_date"]) if spec.get("end_date") else None,
    )
    sid = semester.id

    # 范本会带入领域层级的科目名称;示范资料要分科,先清掉再建自己的
    for row in db.query(Subject).filter(Subject.semester_id == sid).all():
        db.delete(row)
    db.flush()

    subjects: dict[str, Subject] = {}
    for item in spec["subjects"]:
        s = Subject(
            semester_id=sid,
            name=item["name"],
            domain=item["domain"],
            is_major=item.get("major", False),
            required_room_type=item.get("room"),
        )
        db.add(s)
        subjects[item["name"]] = s

    # ── 场地 ──
    rooms: dict[str, list[Room]] = {}
    room_count = 0
    for spec_room in spec["rooms"]:
        for i in range(spec_room["count"]):
            suffix = f"{i + 1}" if spec_room["count"] > 1 else ""
            r = Room(
                semester_id=sid,
                name=f"{spec_room['name']}{suffix}",
                room_type=spec_room["type"],
            )
            db.add(r)
            for sub_name in spec_room["subjects"]:
                rooms.setdefault(sub_name, []).append(r)
            room_count += 1
    # 每班一间普通教室
    for _, cname in classes:
        db.add(Room(semester_id=sid, name=cname, room_type="normal"))
        room_count += 1
    db.flush()

    # ── 教师 ──
    plans = _plan_teachers(spec, class_names)
    by_name: dict[str, _TeacherPlan] = {}
    for plan in plans:
        t = Teacher(
            semester_id=sid,
            name=plan.name,
            base_periods=plan.base_periods,
            admin_reduction=plan.admin_reduction,
            admin_title=plan.admin_title,
            is_external=plan.is_external,
        )
        db.add(t)
        plan.model = t
        by_name[plan.name] = plan
    db.flush()

    # 外聘教师的应授 = 他实际要教的节数(如外聘的校本课程教师),避免显示成「超课时 12 节」
    demand = _demand(spec, classes)
    dept_of = {s["name"]: s["dept"] for s in spec["subjects"]}
    for plan in plans:
        if plan.role != ROLE_EXTERNAL:
            continue
        total = sum(p for _, sname, p in demand if dept_of[sname] == plan.dept)
        plan.base_periods = total
        assert plan.model is not None
        plan.model.base_periods = total

    # ── 班级(绑班主任)──
    homeroom_by_class = {p.homeroom_of: p for p in plans if p.homeroom_of}
    class_models: dict[str, ClassUnit] = {}
    for grade, cname in classes:
        hr = homeroom_by_class.get(cname)
        assert hr is None or hr.model is not None
        cu = ClassUnit(
            semester_id=sid,
            grade=grade,
            name=cname,
            track=ClassTrack.junior_high.value,
            student_count=spec["classes"]["student_count"],
            homeroom_teacher_id=hr.model.id if hr and hr.model else None,
        )
        db.add(cu)
        class_models[cname] = cu
    db.flush()

    # ── 配课 ──
    pools: dict[str, list[_TeacherPlan]] = {}
    for plan in plans:
        pools.setdefault(plan.dept, []).append(plan)

    # 班主任优先拿自己班、自己科的课:S7(班主任的课优先排自己班第一节)才示范得出来
    def sort_key(row: tuple[str, str, int]) -> tuple[int, str, str]:
        cname, sname, _ = row
        hr = homeroom_by_class.get(cname)
        own = 0 if hr and dept_of[sname] == hr.dept else 1
        return (own, cname, sname)

    assignment_count = 0
    total_periods = 0
    taught_subjects: dict[str, set[str]] = {}
    taught_grades: dict[str, set[int]] = {}
    for cname, sname, periods in sorted(demand, key=sort_key):
        pool = pools[dept_of[sname]]
        hr = homeroom_by_class.get(cname)
        if hr is not None and hr.dept == dept_of[sname] and hr.headroom >= periods:
            teacher = hr
        else:
            teacher = _pick_teacher(pool)

        assert teacher.model is not None
        unit = get_or_create_single_unit(db, class_models[cname])
        assignment = CourseAssignment(
            semester_id=sid,
            scheduling_unit_id=unit.id,
            subject_id=subjects[sname].id,
            periods_per_week=periods,
            required_room_type=subjects[sname].required_room_type,
        )
        db.add(assignment)
        db.flush()
        assignment.teachers.append(
            AssignmentTeacher(teacher_id=teacher.model.id, is_lead=True)
        )
        teacher.assigned += periods
        taught_subjects.setdefault(teacher.name, set()).add(sname)
        taught_grades.setdefault(teacher.name, set()).add(class_models[cname].grade)
        assignment_count += 1
        total_periods += periods
    db.flush()

    # 任教科目:教师档案的 subjects 是独立的一张表,配课不会自动写它,
    # 不填的话基础资料里任教科目全空,调课推荐也分不出本科教师。
    # 按实际配课回填:只填该教师真正教的科目,不按教研组整组带。
    for plan in plans:
        assert plan.model is not None
        plan.model.subjects = [
            subjects[sname] for sname in sorted(taught_subjects.get(plan.name, set()))
        ]
    # 所属年级:与任教科目同理,按实际配课回填(只填真正教的年级)。
    for plan in plans:
        assert plan.model is not None
        teacher_grades_service.set_teacher_grades(
            db, plan.model.id, sorted(taught_grades.get(plan.name, set()))
        )
    db.flush()

    # 标记设置精灵已完成。否则载完示范资料回到首页,路由守卫会因为
    # 「精灵未完成」把用户弹回设置精灵——资料明明都建好了,却被要求重建一次。
    wizard = db.get(WizardState, SINGLETON_ID)
    if wizard is None:
        wizard = WizardState(id=SINGLETON_ID)
        db.add(wizard)
    wizard.completed = True
    wizard.current_step = TOTAL_STEPS - 1
    wizard.semester_id = sid
    db.flush()

    overs = [-p.headroom for p in plans if p.headroom < 0]
    return DemoSummary(
        semester_id=sid,
        school_name=spec["school_name"],
        classes=len(classes),
        teachers=len(plans),
        subjects=len(subjects),
        rooms=room_count,
        assignments=assignment_count,
        total_periods=total_periods,
        max_overtime_used=max(overs, default=0),
        under_target=sum(1 for p in plans if p.headroom > 0),
    )


def semester_is_empty(db: Session, semester_id: int) -> bool:
    """学期是否还没有任何班级或教师——示范资料只能建在空学期上。"""
    has_class = db.query(ClassUnit).filter(ClassUnit.semester_id == semester_id).first()
    has_teacher = db.query(Teacher).filter(Teacher.semester_id == semester_id).first()
    return has_class is None and has_teacher is None


def any_semester_exists(db: Session) -> bool:
    return db.query(Semester).first() is not None
