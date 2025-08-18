#!/bin/bash
# 检查服务状态

APP_DIR="/home/$(whoami)/sqlfluff-service"
WEB_PID_FILE="$APP_DIR/web.pid"
WORKER_PID_FILE="$APP_DIR/worker.pid"
CURRENT_DIR="$APP_DIR/current"
LOG_DIR="$APP_DIR/logs"

echo "========== SQLFluff服务状态 =========="

# 检查Web服务
echo "Web服务:"
if [ -f "$WEB_PID_FILE" ]; then
    WEB_PID=$(cat "$WEB_PID_FILE")
    if ps -p "$WEB_PID" > /dev/null 2>&1; then
        echo "  状态: 运行中 ✓"
        echo "  PID: $WEB_PID"
        echo "  端口: ${PORT:-8000}"
        
        # 显示内存使用
        echo "  内存使用:"
        ps -o pid,vsz,rss,comm -p "$WEB_PID" | tail -n 1 | sed 's/^/    /'
    else
        echo "  状态: 已停止 ✗"
        echo "  PID文件存在但进程未运行"
    fi
else
    echo "  状态: 未运行 ✗"
fi

echo ""
# 检查Worker服务
echo "Worker服务:"
if [ -f "$WORKER_PID_FILE" ]; then
    WORKER_PID=$(cat "$WORKER_PID_FILE")
    if ps -p "$WORKER_PID" > /dev/null 2>&1; then
        echo "  状态: 运行中 ✓"
        echo "  PID: $WORKER_PID"
        echo "  队列: ${CELERY_QUEUES:-default,sql_analysis,zip_processing}"
        echo "  并发数: ${CELERY_WORKER_CONCURRENCY:-4}"
        
        # 显示内存使用
        echo "  内存使用:"
        ps -o pid,vsz,rss,comm -p "$WORKER_PID" | tail -n 1 | sed 's/^/    /'
    else
        echo "  状态: 已停止 ✗"
        echo "  PID文件存在但进程未运行"
    fi
else
    echo "  状态: 未运行 ✗"
fi

# 显示版本信息
if [ -f "$CURRENT_DIR/version.json" ]; then
    echo ""
    echo "版本信息:"
    cat "$CURRENT_DIR/version.json"
fi

# 显示最新日志
echo ""
echo "最新日志:"
WEB_LOG_FILE="$LOG_DIR/web_$(date +%Y%m%d).log"
if [ -f "$WEB_LOG_FILE" ]; then
    echo "Web服务日志 (最后5行):"
    tail -n 5 "$WEB_LOG_FILE" | sed 's/^/  /'
fi

WORKER_LOG_FILE="$LOG_DIR/worker_$(date +%Y%m%d).log"
if [ -f "$WORKER_LOG_FILE" ]; then
    echo "Worker服务日志 (最后5行):"
    tail -n 5 "$WORKER_LOG_FILE" | sed 's/^/  /'
fi

# 检查环境配置
echo ""
echo "环境配置:"
echo "  环境: ${ENVIRONMENT:-development}"
echo "  Redis: ${REDIS_HOST:-localhost}:${REDIS_PORT:-6379}"
echo "  数据库: ${MYSQL_DATABASE_HOST:-localhost}:${MYSQL_DATABASE_PORT:-3306}/${MYSQL_DATABASE_NAME:-sqlfluff}"
echo "  NFS目录: ${NFS_SHARE_ROOT_PATH:-/data/nfs}"

echo "=========================================="