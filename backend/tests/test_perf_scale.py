"""M5-4 效能验收(60 班规模):check-conflict 单格检查 p95 < 100ms。

以 build_large_school(60) 建 60 班初中(660 配课、约 55 位教师),在课表塞入
接近整周满排的格位量,量测冲突检查的 p95。这是验收②里最硬性的一条数字。

「页面载入 p95 < 2s」为前端量测(见 frontend/e2e 的 page-load 量测);「自动排课
< 10 分钟」由 M3 的 junior_high < 60s 建模测试与 docker 实测共同保证(60 班求解耗时
于实机记录,不放进 CI 单元测试以免每次跑十分钟)。
"""

import time as _time

import pytest
from sqlalchemy import select

from app.models.period import Period, PeriodType
from app.models.timetable import ScheduleEntry, Timetable, TimetableStatus
from app.services.conflict_checker import check_conflict
from tests.fixtures import build_large_school


def _regular_slots(db, table_id):
    return list(db.scalars(
        select(Period).where(
            Period.period_table_id == table_id,
            Period.type == PeriodType.regular.value,
        ).order_by(Period.weekday, Period.period_no)
    ))


@pytest.mark.perf
def test_check_conflict_p95_under_100ms_at_60_classes(db):
    fx = build_large_school(db, num_classes=60)
    sid = fx.semester_id

    tt = Timetable(semester_id=sid, name="效能草稿", status=TimetableStatus.draft.value)
    db.add(tt)
    db.flush()

    # 以合法节次格位轮替塞满:量测的是占用索引的建立与比对速度,不要求教学合理。
    slots = _regular_slots(db, fx.table.id)
    assert slots, "节次表应有一般课格位"
    placed = 0
    for i, a in enumerate(fx.assignments):
        for k in range(a.periods_per_week):
            slot = slots[(i + k) % len(slots)]
            db.add(ScheduleEntry(
                timetable_id=tt.id, course_assignment_id=a.id,
                weekday=slot.weekday, period_no=slot.period_no, span=1,
                room_id=a.room_id, locked=False,
            ))
            placed += 1
    db.flush()
    assert placed > 1500, f"应塞入具规模的格位(实际 {placed})"

    probe = fx.assignments[0]
    slot = slots[len(slots) // 2]

    samples = []
    for _ in range(30):
        t0 = _time.perf_counter()
        check_conflict(db, tt, probe, slot.weekday, slot.period_no, span=1)
        samples.append((_time.perf_counter() - t0) * 1000)
    samples.sort()
    p95 = samples[int(0.95 * (len(samples) - 1))]
    median = samples[len(samples) // 2]
    assert p95 < 100, (
        f"60 班 {placed} 格下 check-conflict p95 {p95:.1f}ms"
        f"(中位数 {median:.1f}ms、最慢 {samples[-1]:.1f}ms),超过 100ms 目标"
    )
