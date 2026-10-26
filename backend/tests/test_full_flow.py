"""M5-4 全流程总验收(后端):三套学制 fixtures 走完整条管线——
配课 → 自动排课 → 验证零硬违反 → 发布 → 请假展开 → 指派代课 → 月结统计。

M3 的建模测试已各自证明三套 fixture「解得出且零硬约束违反」;本档的价值在于证明
**下游链路能吃真实求解结果并组合成立**:发布快照、依已发布课表展开受影响节次、
指派代课、月结课时统计,在小学/初中/技高三种学制上一致成立(验收①的后端严谨形式)。

UI 端的连续旅程另见 frontend/e2e/full-journey.spec.ts。
"""

from datetime import date

import pytest

from app.models.leave import LeaveType
from app.models.substitution import SubstitutionType
from app.models.user import Role
from app.services import leaves as leave_svc
from app.services import substitution_stats as stats_svc
from app.services import substitutions as sub_svc
from app.services import timetable_publish as publish_svc
from app.services.availability import Availability
from app.services.solver_data import load_problem
from app.solver.model_builder import SolveOptions, solve
from app.solver.problem import SolverConfig
from app.solver.validator import validate
from app.workers.solve_job import write_result
from tests.conftest import grant_grades, make_user
from tests.dates import MON, SEM_END, SEM_START, on_or_after
from tests.fixtures import (
    build_elementary_small,
    build_junior_high_mid,
    build_vocational_high,
)

# 求解上限只是天花板(fixture 设计为可行,实际远低于此)。用 hard-only 求解(与 M3
# 建模测试同法):只要可行即停,不挂软约束目标函数去逼近最佳解(那会跑到天花板)。
SOLVE = SolveOptions(max_seconds=60.0, workers=4, random_seed=1)
HARD = SolverConfig.hard_only()

CASES = [
    ("elementary_small", build_elementary_small),
    ("junior_high_mid", build_junior_high_mid),
    ("vocational_high", build_vocational_high),
]

# 请假日必须落在「今日之后」:代课处置会拒绝已结束的节次(clock.is_past_slot)。
# 一律由执行当日推算(tests/dates.py),硬编日期会在某天过期并让整套测试无声转红。
_SEM_START = SEM_START
_SEM_END = SEM_END


def _first_date_with_isoweekday(weekday: int) -> date:
    """基准周(必在未来)中 isoweekday 等于 weekday 的那一天(1=周一)。"""
    day = on_or_after(weekday, MON)
    assert _SEM_START <= day <= _SEM_END
    return day


def _pick_teacher_and_weekday(db, published):
    """从已发布课表取一笔格位,回传其主教教师与星期(该教师该星期必有课)。"""
    from app.models.assignment import CourseAssignment

    entry = published.entries[0]
    assignment = db.get(CourseAssignment, entry.course_assignment_id)
    lead = next((t for t in assignment.teachers if t.is_lead), assignment.teachers[0])
    return lead.teacher_id, entry.weekday


@pytest.mark.parametrize("name,builder", CASES, ids=[c[0] for c in CASES])
def test_full_pipeline_per_track(name, builder, db):
    fx = builder(db)
    sid = fx.semester_id
    scheduler = make_user(db, f"sched_{name}", roles=[Role.director])
    grant_grades(db, scheduler)

    # 学期起讫(请假登记需要);fixture 范本未设。
    fx.semester.start_date = _SEM_START
    fx.semester.end_date = _SEM_END
    db.flush()

    # ── 1) 自动排课:建来源草稿 → 求解 → 零硬违反 → 写成结果草稿 ──
    from app.models.timetable import Timetable, TimetableStatus

    source = Timetable(semester_id=sid, name="草稿", status=TimetableStatus.draft.value)
    db.add(source)
    db.flush()

    problem = load_problem(db, sid, source)
    result = solve(problem, SOLVE, config=HARD)
    assert result.solved, f"{name} 应可排出完整解"
    assert not validate(problem, result.entries), f"{name} 解不应有硬约束违反"

    drafted = write_result(db, source, result.entries, scheduler.id, scheduler.username,
                           result.objective)
    db.commit()
    assert len(drafted.entries) == len(result.entries) > 0

    # ── 2) 发布:draft → published(不可变快照)──
    published = publish_svc.publish(db, drafted, scheduler, forced=False)
    db.commit()
    assert published.status == TimetableStatus.published.value

    # ── 3) 请假:挑一位有课的教师请整天假 → 依已发布课表展开受影响节次 ──
    teacher_id, weekday = _pick_teacher_and_weekday(db, published)
    teacher = leave_svc.find_teacher(db, sid, teacher_id)
    assert teacher is not None
    leave_day = _first_date_with_isoweekday(weekday)

    leave = leave_svc.create(
        db, fx.semester, teacher,
        leave_type=LeaveType.personal.value,
        start_date=leave_day, start_time=None, end_date=leave_day, end_time=None,
        reason="全流程测试", created_by_user_id=scheduler.id,
        created_by_name=scheduler.username, notify_teacher=False,
    )
    db.commit()
    affected = list(leave.affected_periods)
    assert affected, f"{name} 请假整天应展开至少一节受影响课"

    # ── 4) 代课:为其中一节找一位当时段有空的教师指派代课 ──
    av = Availability(db, sid)
    assigned = None
    for ap in affected:
        for cand in fx.teachers.values():
            if cand.id in (teacher_id,):
                continue
            try:
                sub = sub_svc.assign(
                    db, ap, sub_type=SubstitutionType.substitute.value,
                    handler_teacher_id=cand.id, counts_toward_hours=None,
                    funding_source="", swap_entry_id=None, swap_date=None,
                    created_by_user_id=scheduler.id, created_by_name=scheduler.username,
                    availability=av,
                )
                assigned = (ap, cand, sub)
                break
            except sub_svc.SubstitutionError:
                continue
        if assigned:
            break
    db.commit()
    assert assigned, f"{name} 应能为受影响节次找到一位可代课教师"
    ap, handler, sub = assigned
    assert sub.handler_teacher_id == handler.id
    assert sub.counts_toward_hours is True  # 代课默认计费

    # ── 5) 月结统计:代课那节所在月份,接手教师应有 1 节代课且计费 ──
    report = stats_svc.monthly_report(db, sid, ap.date.year, ap.date.month)
    summary = next((s for s in report.summaries if s.teacher_id == handler.id), None)
    assert summary is not None, f"{name} 月结应包含接手代课的教师"
    assert summary.handled_count >= 1
    assert summary.billable_count >= 1
    detail = next((d for d in report.details if d.handler_teacher_id == handler.id), None)
    assert detail is not None and detail.sub_type == SubstitutionType.substitute.value
