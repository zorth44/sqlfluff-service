#!/bin/bash

# SQLFluff 事件驱动Worker启动脚本
# 
# 新架构特性:
# - 完全事件驱动，无数据库依赖
# - 统一的单文件处理模式
# - 支持动态规则配置
# - 自动批量处理聚合

set -e

echo "========================================"
echo "SQLFluff Event-Driven Worker"
echo "========================================"
echo "Architecture: Event-Driven (No Database)"
echo "Processing: Unified Single-File Mode"
echo "Features: Dynamic Rules Configuration"
echo "========================================"

# 设置环境变量
export PYTHONPATH="${PYTHONPATH:-}:$(pwd)"

# Redis连接检查
echo "🔍 Checking Redis connection..."
if command -v redis-cli >/dev/null 2>&1; then
    if redis-cli ping >/dev/null 2>&1; then
        echo "✅ Redis connection successful"
    else
        echo "❌ Redis connection failed - please start Redis server"
        echo "   Start Redis: redis-server"
        exit 1
    fi
else
    echo "⚠️  redis-cli not found - assuming Redis is running"
fi

# Python环境检查
echo "🐍 Checking Python environment..."
if [ -d "venv" ]; then
    echo "🔄 Activating virtual environment..."
    source venv/bin/activate
    echo "✅ Virtual environment activated"
else
    echo "⚠️  No virtual environment found - using system Python"
fi

# 依赖检查
echo "📦 Checking dependencies..."
python -c "import redis, sqlfluff; print('✅ Core dependencies available')" || {
    echo "❌ Missing dependencies - please install requirements"
    echo "   Run: pip install -r requirements.txt"
    exit 1
}

# 信号处理
cleanup() {
    echo "🛑 Shutting down Event-Driven Worker..."
    pkill -f "python.*worker_main" || true
    exit 0
}

trap cleanup SIGINT SIGTERM

# 启动Worker
echo "🚀 Starting Event-Driven Worker..."
echo "📍 Working directory: $(pwd)"
echo "🔧 Python path: $PYTHONPATH"
echo "📡 Listening on: sql_check_requests (Redis channel)"
echo "📊 Publishing to: sql_check_events, worker_monitoring"
echo "========================================"

# 启动Python Worker
exec python -m app.worker_main 