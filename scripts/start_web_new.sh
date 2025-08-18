#!/bin/bash
# Web服务启动脚本

APP_DIR="/home/$(whoami)/sqlfluff-service"
CURRENT_DIR="$APP_DIR/current"
LOG_DIR="$APP_DIR/logs"
CONFIG_DIR="$APP_DIR/config"
WEB_PID_FILE="$APP_DIR/web.pid"

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
if [ -f "$WEB_PID_FILE" ]; then
    OLD_PID=$(cat "$WEB_PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo "Web服务已经在运行，PID: $OLD_PID"
        exit 1
    fi
fi

# 启动Web服务
cd "$CURRENT_DIR"
LOG_FILE="$LOG_DIR/web_$(date +%Y%m%d).log"

echo "启动Web服务..."
echo "日志文件: $LOG_FILE"

# 设置Python路径
export PYTHONPATH="${PYTHONPATH:+${PYTHONPATH}:}."

# 启动Web服务
if [ "${ENVIRONMENT:-development}" = "production" ]; then
    # 生产环境使用Gunicorn
    nohup gunicorn app.web_main:app \
        -w "${GUNICORN_WORKERS:-4}" \
        -k uvicorn.workers.UvicornWorker \
        --bind "0.0.0.0:${PORT:-8000}" \
        --access-logfile - \
        --error-logfile - \
        --timeout 120 \
        >> "$LOG_FILE" 2>&1 &
else
    # 开发环境使用Uvicorn
    nohup uvicorn app.web_main:app \
        --host "0.0.0.0" \
        --port "${PORT:-8000}" \
        >> "$LOG_FILE" 2>&1 &
fi

WEB_PID=$!
echo $WEB_PID > "$WEB_PID_FILE"

# 等待确认启动
sleep 3
if ps -p "$WEB_PID" > /dev/null; then
    echo "Web服务启动成功，PID: $WEB_PID"
else
    echo "Web服务启动失败"
    rm -f "$WEB_PID_FILE"
    exit 1
fi