#!/bin/bash
# Web服务停止脚本

APP_DIR="/home/$(whoami)/sqlfluff-service"
WEB_PID_FILE="$APP_DIR/web.pid"

if [ ! -f "$WEB_PID_FILE" ]; then
    echo "Web服务PID文件不存在，服务可能未运行"
    exit 0
fi

WEB_PID=$(cat "$WEB_PID_FILE")

if ps -p "$WEB_PID" > /dev/null 2>&1; then
    echo "停止Web服务 (PID: $WEB_PID)..."
    
    # 先尝试优雅关闭
    kill -TERM "$WEB_PID" 2>/dev/null
    
    # 等待进程结束（最多30秒）
    for i in {1..30}; do
        if ! ps -p "$WEB_PID" > /dev/null 2>&1; then
            echo "Web服务已停止"
            rm -f "$WEB_PID_FILE"
            exit 0
        fi
        sleep 1
    done
    
    # 如果还没停止，强制结束
    echo "强制停止Web服务..."
    kill -9 "$WEB_PID" 2>/dev/null
    sleep 1
fi

rm -f "$WEB_PID_FILE"
echo "Web服务已停止"