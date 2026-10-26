"""自动排课的背景任务(RQ)。

**输入输出流**(tasks.md M3-4 补遗):
- 以「来源草稿」为输入:其 `locked` 格位是硬约束(H9),未锁定的格位喂成求解提示,
  让重排时尽量少动已排好的课。
- 结果写成**新草稿**「{来源名} 自排结果」,来源草稿完全不动——排坏了随时可以丢掉。
- 锁定状态随结果一起复制。

**无解时**(M3-5)不只回一句「排不出来」:接著跑冲突定位,告诉教学组长是哪几件事
凑在一起、松开哪一个就好了。定位本身也要送心跳,否则会被误判成 worker 死掉。

求解跑在独立的 worker 容器,不阻塞 Web(architecture.md §3.3)。
"""

import threading
import time
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.timetable import ScheduleEntry, Timetable, TimetableStatus
from app.services.solver_data import load_config, load_problem
from app.solver import conflict_explainer
from app.solver import report as soft_report
from app.solver.model_builder import (
    Relaxation,
    SolveControl,
    SolveOptions,
    SolveProgress,
    SolverInputError,
    UnscheduledCourse,
    solve,
)
from app.solver.problem import Problem, SolvedEntry, SolverConfig
from app.workers.progress import (
    ControlAction,
    JobPhase,
    JobStatus,
    ProgressStore,
    RedisProgressStore,
)

RESULT_SUFFIX = "自排结果"
PARTIAL_SUFFIX = "部分排课结果"
HEARTBEAT_SECONDS = 2.0
# 冲突定位的时间预算。用户已经等过一轮求解,不能再让他等十分钟才知道原因。
EXPLAIN_SECONDS = 60.0


def run_auto_schedule(
    job_id: str,
    timetable_id: int,
    max_seconds: float,
    seed: int,
    user_id: int | None,
    username: str,
    allow_partial: bool = False,
    relax: Sequence[str] = (),
    scope_grades: Sequence[int] | None = None,
) -> None:
    """RQ 进入点。任何例外都必须落到 job 状态上,否则前端只会看到永远的转圈。"""
    from app.core.db import SessionLocal
    from app.workers.queue import redis_conn

    store = RedisProgressStore(redis_conn)
    db = SessionLocal()
    try:
        execute(db, store, job_id, timetable_id, max_seconds, seed, user_id, username,
                allow_partial, relax, scope_grades)
    except Exception as exc:  # noqa: BLE001 - worker 边界:一律转为可见的失败状态
        db.rollback()
        store.update(
            job_id, status=JobStatus.failed.value,
            error=f"排课过程发生错误:{exc}"[:300], heartbeat=time.time(),
        )
    finally:
        db.close()


def execute(
    db: Session,
    store: ProgressStore,
    job_id: str,
    timetable_id: int,
    max_seconds: float,
    seed: int,
    user_id: int | None = None,
    username: str = "system",
    allow_partial: bool = False,
    relax: Sequence[str] = (),
    scope_grades: Sequence[int] | None = None,
) -> None:
    """实际流程。与 RQ 解耦,测试可直接呼叫(记忆体版 store + 测试 session)。

    scope_grades 给定时只排这些年级,范围外已有格位钉住不动(见 solver_data)。
    """
    source = db.get(Timetable, timetable_id)
    if source is None:
        store.update(job_id, status=JobStatus.failed.value, error="找不到来源课表",
                     heartbeat=time.time())
        return

    problem = load_problem(
        db, source.semester_id, source,
        scope_grades=frozenset(scope_grades) if scope_grades else None,
    )
    config = load_config(db, source.semester_id)
    relaxation = Relaxation(soft_codes=frozenset(relax)) if allow_partial else None

    store.update(job_id, status=JobStatus.running.value, partial=allow_partial,
                 phase=JobPhase.solving.value, heartbeat=time.time())

    def on_progress(p: SolveProgress) -> None:
        store.update(job_id, solutions=p.solutions, objective=p.objective,
                     elapsed=p.elapsed, heartbeat=time.time())

    def on_tick(elapsed: float) -> None:
        store.update(job_id, elapsed=elapsed, heartbeat=time.time())

    def should_stop() -> bool:
        return store.requested(job_id) is not None

    try:
        result = solve(
            problem,
            SolveOptions(max_seconds=max_seconds, workers=4, random_seed=seed),
            config=config,
            control=SolveControl(on_progress=on_progress, on_tick=on_tick,
                                 should_stop=should_stop),
            relax=relaxation,
        )
    except SolverInputError as exc:
        # 建模阶段就拦下来(某门课完全没有可排的位置)。这也是一种无解,要说得出原因。
        _fail_with_conflict(store, job_id, problem, config, str(exc), should_stop)
        return

    if store.requested(job_id) == ControlAction.cancel:
        store.update(job_id, status=JobStatus.cancelled.value, heartbeat=time.time(),
                     error=None)
        return

    if not result.solved:
        # 逾时而一个解都没有,往往其实是无解——只是带著软约束目标函数时,CP-SAT 很难
        # 证明这件事(实测:同一份资料纯硬约束 1 秒证完,加上目标函数 60 秒证不完)。
        # 一律跑一次冲突定位:它以纯硬约束求解,能分辨「不可能」与「只是慢」。
        _fail_with_conflict(store, job_id, problem, config,
                            _failure_message(result.status), should_stop)
        return

    new = write_result(db, source, result.entries, user_id, username, result.objective,
                       partial=allow_partial, unplaced=result.unplaced_periods,
                       unscheduled=result.unscheduled)
    rep = soft_report.evaluate(problem, result.entries, config)
    db.commit()

    store.update(
        job_id, status=JobStatus.finished.value, heartbeat=time.time(),
        elapsed=result.wall_time, objective=result.objective,
        result_timetable_id=new.id, result_name=new.name,
        report=_serialize_report(rep),
        unscheduled=[_serialize_unscheduled(u) for u in result.unscheduled],
    )


@contextmanager
def _heartbeat(store: ProgressStore, job_id: str) -> Generator[None]:
    """在一段没有进度回报的长工作期间持续送心跳。

    冲突定位可能跑上一分钟。少了心跳,API 会在 30 秒后判定 worker 已死,
    用户就永远看不到那份好不容易算出来的原因报告。
    """
    done = threading.Event()

    def beat() -> None:
        while not done.wait(HEARTBEAT_SECONDS):
            store.update(job_id, heartbeat=time.time())

    thread = threading.Thread(target=beat, daemon=True)
    thread.start()
    try:
        yield
    finally:
        done.set()
        thread.join(timeout=HEARTBEAT_SECONDS + 1)


def _fail_with_conflict(
    store: ProgressStore, job_id: str, problem: Problem, config: SolverConfig, message: str,
    should_stop: Callable[[], bool] | None = None,
) -> None:
    store.update(job_id, phase=JobPhase.explaining.value, heartbeat=time.time())
    try:
        with _heartbeat(store, job_id):
            report = conflict_explainer.explain(
                problem, config=config, max_seconds=EXPLAIN_SECONDS, should_stop=should_stop,
            )
    except conflict_explainer.Cancelled:
        # 用户在定位期间按了取消。他已经说不要了,就不该再收到一份 failed 报告(M6-5)
        store.update(job_id, status=JobStatus.cancelled.value, heartbeat=time.time(),
                     phase=JobPhase.solving.value, error=None)
        return

    if report.status == "feasible":
        # 硬约束其实排得出来,是软约束的最佳化太慢。这两件事的处置完全不同。
        error = "排课时间内没找到解,但这份资料确实排得出来。请延长排课时间,或降低软约束权重。"
    else:
        error = report.headline or message

    store.update(
        job_id, status=JobStatus.failed.value, heartbeat=time.time(),
        phase=JobPhase.solving.value,
        error=error,
        conflict=_serialize_conflict(report),
    )


def _failure_message(status: str) -> str:
    if status == "infeasible":
        return "在现有条件下无解。"
    if status == "unknown":
        return "时间内找不到任何可行解。请延长排课时间,或改用部分排课。"
    return f"求解失败({status})"


def _serialize_conflict(rep: conflict_explainer.ConflictReport) -> dict:
    return {
        "status": rep.status,
        "source": rep.source,
        "mode": rep.mode,
        "headline": rep.headline,
        "complete": rep.complete,
        "relaxable_codes": list(rep.relaxable_codes),
        "causes": [asdict(c) for c in rep.causes],
    }


def _serialize_unscheduled(u: UnscheduledCourse) -> dict:
    return {
        **asdict(u),
        "assignment_ids": list(u.assignment_ids),
        "class_names": list(u.class_names),
    }


def _serialize_report(rep: soft_report.SoftReport) -> dict:
    return {
        "total_penalty": rep.total_penalty,
        "items": [
            {**asdict(i), "satisfied": i.satisfied, "rate": i.rate, "penalty": i.penalty,
             "details": list(i.details)}
            for i in rep.items
        ],
    }


def _unique_name(db: Session, semester_id: int, base: str) -> str:
    existing = set(
        db.scalars(select(Timetable.name).where(Timetable.semester_id == semester_id))
    )
    if base not in existing:
        return base
    n = 2
    while f"{base} {n}" in existing:
        n += 1
    return f"{base} {n}"


def write_result(
    db: Session,
    source: Timetable,
    entries: tuple[SolvedEntry, ...],
    user_id: int | None,
    username: str,
    objective: float,
    *,
    partial: bool = False,
    unplaced: int = 0,
    unscheduled: tuple[UnscheduledCourse, ...] = (),
) -> Timetable:
    """把求解结果写成新草稿。来源草稿不动。呼叫端负责 commit。

    未排清单随草稿存进 DB(M6-3):它先前只活在 Redis 24h,草稿一旦被 force 发布,
    solver 讲的「为什么排不下」就永远遗失。
    """
    suffix = PARTIAL_SUFFIX if partial else RESULT_SUFFIX
    name = _unique_name(db, source.semester_id, f"{source.name} {suffix}")
    new = Timetable(
        semester_id=source.semester_id, name=name, status=TimetableStatus.draft.value,
        unscheduled=[_serialize_unscheduled(u) for u in unscheduled] or None,
    )
    db.add(new)
    db.flush()
    for e in entries:
        db.add(ScheduleEntry(
            timetable_id=new.id, course_assignment_id=e.assignment_id,
            weekday=e.weekday, period_no=e.period_no, span=e.span,
            room_id=e.room_id, locked=e.locked,
        ))
    db.add(AuditLog(
        user_id=user_id, username=username, action="auto_schedule",
        target_type="timetable", target_id=new.id,
        detail=(
            f"{'部分排课' if partial else '自动排课'}由「{source.name}」产出「{name}」"
            f",共 {len(entries)} 格,软约束目标值 {objective:.0f}"
            + (f",未排入 {unplaced} 节" if unplaced else "")
        )[:500],
    ))
    db.flush()
    return new
