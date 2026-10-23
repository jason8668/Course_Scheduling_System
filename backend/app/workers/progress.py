"""自动排课任务的进度与控制状态。

进度不放在 RQ 的 job meta 里:RQ 只知道「执行中/失败」,说不出「已找到 12 个解、
目前目标值 148」。这里用一个独立的 Redis hash 承载,worker 写、API 读。

**心跳**:worker 每 tick 更新 `heartbeat`。若 API 读到 `running` 但心跳超过
`STALE_SECONDS` 没更新,即判定 worker 已死——前端得到明确错误,而不是永远转圈。
"""

import enum
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Protocol

from redis import Redis

KEY_PREFIX = "solve:"
TTL_SECONDS = 24 * 60 * 60
STALE_SECONDS = 30.0  # 心跳逾时;worker 的 tick 为 2 秒
QUEUED_STALE_SECONDS = 15 * 60.0  # 排队等待另一个任务时不算失败


class JobStatus(enum.StrEnum):
    queued = "queued"
    running = "running"
    finished = "finished"
    failed = "failed"
    cancelled = "cancelled"


class ControlAction(enum.StrEnum):
    stop = "stop"      # 提前结束,保留当下最佳解
    cancel = "cancel"  # 取消,丢弃结果


class JobPhase(enum.StrEnum):
    solving = "solving"
    explaining = "explaining"  # 求解证明无解,正在定位是哪几件事凑在一起


@dataclass
class JobState:
    job_id: str
    status: str
    semester_id: int
    source_timetable_id: int
    source_name: str
    max_seconds: float
    created_at: float = field(default_factory=time.time)
    heartbeat: float = field(default_factory=time.time)
    elapsed: float = 0.0
    solutions: int = 0
    objective: float | None = None
    result_timetable_id: int | None = None
    result_name: str | None = None
    error: str | None = None
    report: dict | None = None
    phase: str = JobPhase.solving.value
    partial: bool = False           # 是否为部分排课
    conflict: dict | None = None    # 无解时的冲突定位报告(M3-5)
    unscheduled: list | None = None  # 部分排课下未排入的课务

    @property
    def done(self) -> bool:
        return self.status in (JobStatus.finished, JobStatus.failed, JobStatus.cancelled)


class ProgressStore(Protocol):
    def create(self, state: JobState) -> None: ...
    def get(self, job_id: str) -> JobState | None: ...
    def list(self, semester_id: int | None = None) -> list[JobState]: ...
    def update(self, job_id: str, **fields: object) -> None: ...
    def request(self, job_id: str, action: ControlAction) -> None: ...
    def requested(self, job_id: str) -> ControlAction | None: ...


def _encode(value: object) -> str:
    return json.dumps(value)


def _decode(raw: bytes | str) -> object:
    return json.loads(raw)


class RedisProgressStore:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    def _key(self, job_id: str) -> str:
        return f"{KEY_PREFIX}{job_id}"

    def _control_key(self, job_id: str) -> str:
        return f"{KEY_PREFIX}{job_id}:control"

    def create(self, state: JobState) -> None:
        key = self._key(state.job_id)
        self._redis.hset(key, mapping={k: _encode(v) for k, v in asdict(state).items()})
        self._redis.expire(key, TTL_SECONDS)

    def get(self, job_id: str) -> JobState | None:
        raw = self._redis.hgetall(self._key(job_id))
        if not raw:
            return None
        fields = {
            (k.decode() if isinstance(k, bytes) else k): _decode(v) for k, v in raw.items()
        }
        return JobState(**fields)  # type: ignore[arg-type]

    def list(self, semester_id: int | None = None) -> list[JobState]:
        states: list[JobState] = []
        for key in self._redis.scan_iter(match=f"{KEY_PREFIX}*"):
            name = key.decode() if isinstance(key, bytes) else str(key)
            if name.endswith(":control"):
                continue
            job_id = name[len(KEY_PREFIX):]
            state = self.get(job_id)
            if state is not None and (semester_id is None or state.semester_id == semester_id):
                states.append(state)
        states.sort(key=lambda st: st.created_at, reverse=True)
        return states

    def update(self, job_id: str, **fields: object) -> None:
        key = self._key(job_id)
        if not self._redis.exists(key):
            return
        self._redis.hset(key, mapping={k: _encode(v) for k, v in fields.items()})
        self._redis.expire(key, TTL_SECONDS)

    def request(self, job_id: str, action: ControlAction) -> None:
        self._redis.set(self._control_key(job_id), action.value, ex=TTL_SECONDS)

    def requested(self, job_id: str) -> ControlAction | None:
        raw = self._redis.get(self._control_key(job_id))
        if raw is None:
            return None
        value = raw.decode() if isinstance(raw, bytes) else str(raw)
        return ControlAction(value)


class InMemoryProgressStore:
    """测试用。与 Redis 版行为一致,但不需要外部服务。"""

    def __init__(self) -> None:
        self.states: dict[str, JobState] = {}
        self.controls: dict[str, ControlAction] = {}

    def create(self, state: JobState) -> None:
        self.states[state.job_id] = state

    def get(self, job_id: str) -> JobState | None:
        return self.states.get(job_id)

    def list(self, semester_id: int | None = None) -> list[JobState]:
        states = [
            st for st in self.states.values()
            if semester_id is None or st.semester_id == semester_id
        ]
        states.sort(key=lambda st: st.created_at, reverse=True)
        return states

    def update(self, job_id: str, **fields: object) -> None:
        state = self.states.get(job_id)
        if state is None:
            return
        for key, value in fields.items():
            setattr(state, key, value)

    def request(self, job_id: str, action: ControlAction) -> None:
        self.controls[job_id] = action

    def requested(self, job_id: str) -> ControlAction | None:
        return self.controls.get(job_id)


def is_stale(state: JobState, now: float | None = None) -> bool:
    """worker 是否已失联。排队中的任务可能只是在等前一个排课跑完,给长一点的宽限。"""
    now = now if now is not None else time.time()
    if state.done:
        return False
    limit = QUEUED_STALE_SECONDS if state.status == JobStatus.queued else STALE_SECONDS
    return now - state.heartbeat > limit
