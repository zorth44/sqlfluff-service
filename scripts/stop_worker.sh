#!/bin/bash
# Worker服务停止脚本

APP_DIR="/home/$(whoami)/sqlfluff-service"
WORKER_PID_FILE="$APP_DIR/worker.pid"

if [ ! -f "$WORKER_PID_FILE" ]; then
    echo "Worker服务PID文件不存在，服务可能未运行"
    # 强制杀死所有Celery进程（防止僵尸进程）
    pkill -f "celery.*worker" 2>/dev/null || true
    exit 0
fi

WORKER_PID=$(cat "$WORKER_PID_FILE")

if ps -p "$WORKER_PID" > /dev/null 2>&1; then
    echo "停止Worker服务 (PID: $WORKER_PID)..."
    
    # 先尝试优雅关闭
    kill -TERM "$WORKER_PID" 2>/dev/null
    
    # 等待进程结束（最多30秒）
    for i in {1..30}; do
        if ! ps -p "$WORKER_PID" > /dev/null 2>&1; then
            echo "Worker服务已停止"
            rm -f "$WORKER_PID_FILE"
            exit 0
        fi
        sleep 1
    done
    
    # 如果还没停止，强制结束
    echo "强制停止Worker服务..."
    kill -9 "$WORKER_PID" 2>/dev/null
    sleep 1
fi

# 清理所有Celery进程
pkill -f "celery.*worker" 2>/dev/null || true
rm -f "$WORKER_PID_FILE"
echo "Worker服务已停止"