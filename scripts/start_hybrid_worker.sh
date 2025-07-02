#!/bin/bash

# SQLFluff事件驱动 + Celery混合架构Worker启动脚本
# 
# 用法:
#   ./start_hybrid_worker.sh [mode]
#
# 模式:
#   hybrid         - 同时运行事件监听器和Celery Worker (默认，推荐)
#   event_listener - 只运行事件监听器
#   celery_worker  - 只运行Celery Worker
#   flower         - 启动Flower监控面板

set -e

# 脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# 默认模式
MODE="${1:-hybrid}"

echo "🚀 SQLFluff Event-Driven + Celery Hybrid Worker"
echo "📁 Project Directory: $PROJECT_DIR"
echo "🔧 Mode: $MODE"
echo "=" $(printf '=%.0s' {1..50})

# 切换到项目目录
cd "$PROJECT_DIR"

# 检查Python环境
if [ ! -f "venv/bin/python" ]; then
    echo "❌ Virtual environment not found at venv/bin/python"
    echo "💡 Please create virtual environment first:"
    echo "   python -m venv venv"
    echo "   source venv/bin/activate"
    echo "   pip install -r requirements.txt"
    exit 1
fi

# 激活虚拟环境
source venv/bin/activate

# 检查依赖
echo "🔍 Checking dependencies..."
python -c "import celery, redis, sqlfluff" 2>/dev/null || {
    echo "❌ Missing core dependencies. Installing..."
    pip install -r requirements.txt
}

# 检查Flower依赖（仅在flower模式时）
if [ "$MODE" = "flower" ]; then
    python -c "import flower" 2>/dev/null || {
        echo "❌ Flower not installed. Installing..."
        pip install flower==2.0.1
    }
fi

# 设置环境变量（如果.env文件存在）
if [ -f ".env" ]; then
    echo "📄 Loading environment variables from .env"
    export $(grep -v '^#' .env | xargs)
fi

# 根据模式启动相应服务
case "$MODE" in
    "hybrid")
        echo "🎯 Starting Hybrid Mode (Event Listener + Celery Worker)"
        python -m app.worker_main --mode hybrid
        ;;
    
    "event_listener")
        echo "📡 Starting Event Listener Mode"
        python -m app.worker_main --mode event_listener
        ;;
    
    "celery_worker")
        echo "⚙️  Starting Celery Worker Mode"
        python -m app.worker_main --mode celery_worker
        ;;
    
    "flower")
        echo "🌸 Starting Flower Monitoring Dashboard"
        echo "📊 Access at: http://localhost:5555"
        echo ""
        echo "💡 部署说明："
        echo "   - Flower是集中式监控，只需在一台服务器启动"
        echo "   - 可以监控所有连接到相同Redis的Worker"
        echo "   - 横向扩展时，其他服务器只需启动Worker："
        echo "     ./start_hybrid_worker.sh hybrid"
        echo ""
        echo "🚀 Starting Flower..."
        
        # 构建Redis连接URL
        if [ -n "$REDIS_PASSWORD" ]; then
            REDIS_URL="redis://:${REDIS_PASSWORD}@${REDIS_HOST:-localhost}:${REDIS_PORT:-6379}/${REDIS_DB_BROKER:-0}"
        else
            REDIS_URL="redis://${REDIS_HOST:-localhost}:${REDIS_PORT:-6379}/${REDIS_DB_BROKER:-0}"
        fi
        
        # 使用CELERY_BROKER_URL环境变量，如果没有则使用构建的Redis URL
        BROKER_URL="${CELERY_BROKER_URL:-$REDIS_URL}"
        
        echo "📡 Broker URL: $BROKER_URL"
        echo "🚀 Starting Flower on port 5555..."
        FLOWER_PORT=5555 celery -A app.celery_app.celery_main flower
        ;;
    
    "celery_beat")
        echo "⏰ Starting Celery Beat Scheduler (if needed)"
        celery -A app.celery_app.celery_main beat --loglevel=info
        ;;
    
    "monitor")
        echo "📊 Starting Celery Events Monitor"
        celery -A app.celery_app.celery_main events --loglevel=info
        ;;
    
    "inspect")
        echo "🔍 Inspecting Celery Workers"
        celery -A app.celery_app.celery_main inspect active
        celery -A app.celery_app.celery_main inspect stats
        ;;
    
    "purge")
        echo "🗑️  Purging Celery Queue"
        read -p "Are you sure you want to purge all tasks? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            celery -A app.celery_app.celery_main purge -f
            echo "✅ Queue purged"
        else
            echo "❌ Cancelled"
        fi
        ;;
    
    "help")
        echo "📚 Available modes:"
        echo ""
        echo "🔥 生产环境模式："
        echo "  hybrid         - 事件监听器 + Celery Worker (默认，推荐)"
        echo "                   在一个进程中同时运行完整功能"
        echo ""
        echo "🔧 调试开发模式："
        echo "  event_listener - 只运行事件监听器"
        echo "                   用于调试Redis事件处理"
        echo "  celery_worker  - 只运行Celery Worker"
        echo "                   用于调试任务执行"
        echo ""
        echo "🌸 监控管理模式："
        echo "  flower         - Flower Web监控面板 (集中式，只需一个)"
        echo "                   访问: http://localhost:5555"
        echo "  monitor        - Celery事件命令行监控"
        echo "  inspect        - 检查Worker状态"
        echo ""
        echo "🛠️ 维护模式："
        echo "  purge          - 清空任务队列"
        echo "  celery_beat    - 定时任务调度器 (如需要)"
        echo "  help           - 显示帮助信息"
        echo ""
        echo "🌐 横向扩展部署："
        echo "  服务器1: ./start_hybrid_worker.sh hybrid + flower"
        echo "  服务器2+: ./start_hybrid_worker.sh hybrid"
        ;;
    
    *)
        echo "❌ Unknown mode: $MODE"
        echo "💡 Use 'help' mode to see available options"
        echo "   ./start_hybrid_worker.sh help"
        exit 1
        ;;
esac 