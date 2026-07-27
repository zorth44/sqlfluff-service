#!/bin/bash
# scripts/start_db_worker.sh
# DB-as-Queue Worker 启动脚本
#
# 环境变量:
#   WORKER_CONCURRENCY      并发线程数（默认 4）
#   WORKER_POLL_INTERVAL    轮询间隔秒数（默认 2.0）
#   WORKER_HEARTBEAT_INTERVAL 心跳间隔秒数（默认 30）
#   WORKER_ZOMBIE_TIMEOUT   Worker 心跳超时秒数（默认 600）
#   WORKER_TASK_TIMEOUT     单任务超时秒数（默认 1800）
#   WORKER_MAX_RETRIES      最大重试次数（默认 3）
#   SKIP_DB_MIGRATION       设为 1 跳过 Alembic（Worker 默认 1；Web 负责迁移）
#
# 必需环境变量:
#   DATABASE_URL 或 MYSQL_DATABASE_* 系列
#   NFS_SHARE_ROOT_PATH

set -e

echo "Starting DB-as-Queue Worker..."

# 检查必需环境变量
if [ -z "$DATABASE_URL" ]; then
    if [ -z "$MYSQL_DATABASE_HOST" ] || [ -z "$MYSQL_DATABASE_USERNAME" ] || [ -z "$MYSQL_DATABASE_PASSWORD" ] || [ -z "$MYSQL_DATABASE_NAME" ]; then
        echo "ERROR: DATABASE_URL or MYSQL_DATABASE_* environment variables must be set"
        exit 1
    fi
    # 构建 DATABASE_URL
    export DATABASE_URL="mysql+pymysql://${MYSQL_DATABASE_USERNAME}:${MYSQL_DATABASE_PASSWORD}@${MYSQL_DATABASE_HOST}:${MYSQL_DATABASE_PORT:-3306}/${MYSQL_DATABASE_NAME}"
fi

if [ -z "$NFS_SHARE_ROOT_PATH" ]; then
    echo "ERROR: NFS_SHARE_ROOT_PATH must be set"
    exit 1
fi

export PROCESS_ROLE="${PROCESS_ROLE:-worker}"

# Worker 默认跳过迁移（Web 或 migrate 服务负责 schema）
if [ "${SKIP_DB_MIGRATION:-1}" != "1" ]; then
    echo "Running database migrations..."
    cd /app
    python -m alembic upgrade head
else
    echo "Skipping database migrations (SKIP_DB_MIGRATION=${SKIP_DB_MIGRATION:-1})"
fi

# 启动 Worker
echo "Starting worker process (PROCESS_ROLE=$PROCESS_ROLE)..."
cd /app
exec python -m app.worker.run_worker
