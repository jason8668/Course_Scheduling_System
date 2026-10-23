#!/usr/bin/env bash
# 后端容器进入点。第一个参数决定角色:api(默认)或 worker。
#
#   worker        → 守 default 伫列(自动排课)
#   worker ops    → 守 ops 伫列(导出/备份/还原/寄信 + 定时任务)
# 两者同一个映像,只差在守哪条伫列(M6-2)。
set -e

ROLE="${1:-api}"

if [ "$ROLE" = "api" ]; then
    # 结构要升级时先自动备份(v1.3.0;备份失败照常升级并提示系统管理员)
    echo "[entrypoint] 执行资料库迁移(结构有变更时先自动备份)..."
    python -m app.scripts.migrate
    echo "[entrypoint] 启动 API (uvicorn) ..."
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000
elif [ "$ROLE" = "worker" ]; then
    shift
    echo "[entrypoint] 启动 RQ worker(伫列:${*:-default})..."
    exec python -m app.workers.worker "$@"
else
    echo "[entrypoint] 未知角色: $ROLE(可用:api、worker [伫列])" >&2
    exit 1
fi
