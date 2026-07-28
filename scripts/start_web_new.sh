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

# 默认使用 Python 3；可在 ~/.bashrc 中通过 PYTHON_BIN 指向虚拟环境或 Python 3.11。
PYTHON_BIN="${PYTHON_BIN:-python3}"
PYTHON_VERSION=$("$PYTHON_BIN" --version 2>&1)
if [ $? -ne 0 ] || ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
    echo "错误: 服务要求 Python 3.11+，当前解释器为: ${PYTHON_VERSION:-$PYTHON_BIN 不可用}"
    echo "请在 ~/.bashrc 配置，例如：export PYTHON_BIN=/path/to/python3.11"
    exit 1
fi

# 使用应用内日志轮转：固定文件名 + 按日轮转
export LOG_FILE_PATH="$LOG_DIR/web.log"
export LOG_FILE_BACKUP_COUNT=14
STARTUP_LOG="$LOG_DIR/web.startup.log"

echo "启动Web服务..."
echo "Python解释器: $PYTHON_BIN ($PYTHON_VERSION)"
echo "日志文件: $LOG_FILE_PATH"
echo "启动诊断日志: $STARTUP_LOG"

# 应用在日志系统初始化前退出时，正式日志文件尚未创建。保留标准输出和错误，
# 以便启动失败时能在部署终端看到实际异常。
: > "$STARTUP_LOG"

# 设置Python路径
export PYTHONPATH="${PYTHONPATH:+${PYTHONPATH}:}."

# 启动Web服务（settings 仅认 dev/test/prod；兼容旧值 production）
if [[ "${ENVIRONMENT:-dev}" == "prod" || "${ENVIRONMENT:-dev}" == "production" ]]; then
    # 生产环境使用Gunicorn
    nohup "$PYTHON_BIN" -m gunicorn app.web_main:app \
        -w "${GUNICORN_WORKERS:-4}" \
        -k uvicorn.workers.UvicornWorker \
        --bind "0.0.0.0:${PORT:-8000}" \
        --access-logfile - \
        --error-logfile - \
        --timeout 120 \
        >> "$STARTUP_LOG" 2>&1 &
else
    # 开发环境使用Uvicorn
    nohup "$PYTHON_BIN" -m uvicorn app.web_main:app \
        --host "0.0.0.0" \
        --port "${PORT:-8000}" \
        >> "$STARTUP_LOG" 2>&1 &
fi

WEB_PID=$!
echo $WEB_PID > "$WEB_PID_FILE"

# 等待确认启动
sleep 3
if ps -p "$WEB_PID" > /dev/null; then
    echo "Web服务启动成功，PID: $WEB_PID"
else
    echo "Web服务启动失败"
    echo "--- Web启动错误（最后100行）---"
    tail -n 100 "$STARTUP_LOG" 2>/dev/null || true
    echo "--- 完整启动诊断日志: $STARTUP_LOG ---"
    rm -f "$WEB_PID_FILE"
    exit 1
fi
