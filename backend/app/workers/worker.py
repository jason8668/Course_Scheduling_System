"""RQ worker 进入点。

两个 worker 行程,各守一条伫列(M6-2):

    python -m app.workers.worker           # default:自动排课(可占住数分钟)
    python -m app.workers.worker ops       # ops:导出 / 备份 / 还原 / 寄信 + 定时任务

分开的理由是快慢任务不该互相堵住:合在一条伫列时,排课一开跑,组长按导出就排在后面
等到逾时失败。**排课永远只走 default**,ops worker 因此不会载入求解引擎,记忆体预算低得多。

排程器(`with_scheduler=True`)只挂在 ops worker:定时任务(每日备份、心跳)都排进 ops,
由它自己捞回来执行。排课 worker 不跑排程器——它一忙就是好几分钟,不该负责准时的事。
"""

import sys

from rq import Worker

from app.workers.queue import QUEUES, ops_queue, redis_conn
from app.workers.scheduler import ensure_scheduled


def main(argv: list[str] | None = None) -> None:
    names = list(argv if argv is not None else sys.argv[1:]) or ["default"]
    unknown = [n for n in names if n not in QUEUES]
    if unknown:
        raise SystemExit(f"未知的伫列名称:{', '.join(unknown)}(可用:{', '.join(QUEUES)})")

    queues = [QUEUES[n] for n in names]
    runs_scheduler = ops_queue.name in names
    if runs_scheduler:
        ensure_scheduled()
    Worker(queues, connection=redis_conn).work(with_scheduler=runs_scheduler)


if __name__ == "__main__":
    main()
