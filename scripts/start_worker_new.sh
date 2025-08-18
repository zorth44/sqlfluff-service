#!/bin/bash
# Worker服务启动脚本

APP_DIR="/home/$(whoami)/sqlfluff-service"
CURRENT_DIR="$APP_DIR/current"
LOG_DIR="$APP_DIR/logs"
CONFIG_DIR="$APP_DIR/config"
WORKER_PID_FILE="$APP_DIR/worker.pid"

# 创建目录
mkdir -p "$LOG_DIR"

# 环境变量在 ~/.bashrc 中已配置，这里确保加载
source ~/.bashrc

# 检查环境变量
bash "$APP_DIR/scripts/check_env.sh" >/dev/null
if [ $? -ne 0 ]; then
    echo "环境变量未正确配置，请检查 ~/.bashrc"
    exit 1
fi

# 检查是否已经在运行
if [ -f "$WORKER_PID_FILE" ]; then
    OLD_PID=$(cat "$WORKER_PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo "Worker服务已经在运行，PID: $OLD_PID"
        exit 1
    fi
fi

# 启动Worker服务
cd "$CURRENT_DIR"
LOG_FILE="$LOG_DIR/worker_$(date +%Y%m%d).log"

echo "启动Worker服务..."
echo "日志文件: $LOG_FILE"

# 设置Python路径
export PYTHONPATH="${PYTHONPATH:+${PYTHONPATH}:}."

# 启动Celery Worker
nohup celery -A app.celery_app.celery_main:celery_app worker \
    --loglevel="${CELERY_LOG_LEVEL:-INFO}" \
    --concurrency="${CELERY_WORKER_CONCURRENCY:-4}" \
    --hostname="worker@%h" \
    --max-tasks-per-child=1000 \
    --prefetch-multiplier=1 \
    --queues="${CELERY_QUEUES:-default,sql_analysis,zip_processing}" \
    >> "$LOG_FILE" 2>&1 &

WORKER_PID=$!
echo $WORKER_PID > "$WORKER_PID_FILE"

# 等待确认启动
sleep 3
if ps -p "$WORKER_PID" > /dev/null; then
    echo "Worker服务启动成功，PID: $WORKER_PID"
else
    echo "Worker服务启动失败"
    rm -f "$WORKER_PID_FILE"
    exit 1
fi