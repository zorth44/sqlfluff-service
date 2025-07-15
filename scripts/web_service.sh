#!/bin/bash
# scripts/web_service.sh - Web服务启停脚本

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 配置
SERVICE_NAME="sqlfluff-web"
PID_FILE="/tmp/${SERVICE_NAME}.pid"
LOG_FILE="/tmp/${SERVICE_NAME}.log"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
START_SCRIPT="${SCRIPT_DIR}/start_web.sh"

# 日志函数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查服务是否运行
is_running() {
    if [[ -f "$PID_FILE" ]]; then
        local pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            return 0  # 运行中
        else
            # PID文件存在但进程不存在，清理PID文件
            rm -f "$PID_FILE"
        fi
    fi
    return 1  # 未运行
}

# 获取服务状态
get_status() {
    if is_running; then
        local pid=$(cat "$PID_FILE")
        echo "running (PID: $pid)"
        return 0
    else
        echo "stopped"
        return 1
    fi
}

# 启动服务
start_service() {
    log_info "启动 $SERVICE_NAME 服务..."
    
    if is_running; then
        log_warning "$SERVICE_NAME 已经在运行中 (PID: $(cat "$PID_FILE"))"
        return 0
    fi
    
    # 检查启动脚本是否存在
    if [[ ! -f "$START_SCRIPT" ]]; then
        log_error "启动脚本不存在: $START_SCRIPT"
        return 1
    fi
    
    # 检查启动脚本是否可执行
    if [[ ! -x "$START_SCRIPT" ]]; then
        log_error "启动脚本不可执行: $START_SCRIPT"
        return 1
    fi
    
    # 启动服务并记录PID
    nohup "$START_SCRIPT" > "$LOG_FILE" 2>&1 &
    local pid=$!
    echo "$pid" > "$PID_FILE"
    
    # 等待一下检查是否启动成功
    sleep 2
    if kill -0 "$pid" 2>/dev/null; then
        log_success "$SERVICE_NAME 启动成功 (PID: $pid)"
        log_info "日志文件: $LOG_FILE"
        return 0
    else
        log_error "$SERVICE_NAME 启动失败"
        rm -f "$PID_FILE"
        return 1
    fi
}

# 停止服务
stop_service() {
    log_info "停止 $SERVICE_NAME 服务..."
    
    if ! is_running; then
        log_warning "$SERVICE_NAME 未在运行"
        return 0
    fi
    
    local pid=$(cat "$PID_FILE")
    
    # 发送SIGTERM信号
    log_info "发送停止信号到进程 $pid..."
    kill -TERM "$pid" 2>/dev/null || true
    
    # 等待进程结束
    local count=0
    while kill -0 "$pid" 2>/dev/null && [[ $count -lt 30 ]]; do
        sleep 1
        ((count++))
    done
    
    # 如果进程仍然存在，强制杀死
    if kill -0 "$pid" 2>/dev/null; then
        log_warning "进程 $pid 未响应SIGTERM，发送SIGKILL..."
        kill -KILL "$pid" 2>/dev/null || true
        sleep 1
    fi
    
    # 清理PID文件
    rm -f "$PID_FILE"
    
    if ! kill -0 "$pid" 2>/dev/null; then
        log_success "$SERVICE_NAME 已停止"
        return 0
    else
        log_error "无法停止 $SERVICE_NAME (PID: $pid)"
        return 1
    fi
}

# 重启服务
restart_service() {
    log_info "重启 $SERVICE_NAME 服务..."
    stop_service
    sleep 2
    start_service
}

# 查看状态
status_service() {
    local status=$(get_status)
    if [[ $? -eq 0 ]]; then
        log_success "$SERVICE_NAME 状态: $status"
        return 0
    else
        log_warning "$SERVICE_NAME 状态: $status"
        return 1
    fi
}

# 查看日志
show_logs() {
    if [[ -f "$LOG_FILE" ]]; then
        log_info "显示 $SERVICE_NAME 日志 (最后50行):"
        echo "----------------------------------------"
        tail -n 50 "$LOG_FILE"
        echo "----------------------------------------"
    else
        log_warning "日志文件不存在: $LOG_FILE"
    fi
}

# 显示帮助信息
show_help() {
    echo "用法: $0 {start|stop|restart|status|logs|help}"
    echo ""
    echo "命令:"
    echo "  start   - 启动 $SERVICE_NAME 服务"
    echo "  stop    - 停止 $SERVICE_NAME 服务"
    echo "  restart - 重启 $SERVICE_NAME 服务"
    echo "  status  - 查看 $SERVICE_NAME 服务状态"
    echo "  logs    - 查看 $SERVICE_NAME 服务日志"
    echo "  help    - 显示此帮助信息"
    echo ""
    echo "文件:"
    echo "  PID文件: $PID_FILE"
    echo "  日志文件: $LOG_FILE"
    echo "  启动脚本: $START_SCRIPT"
}

# 主函数
main() {
    case "${1:-}" in
        start)
            start_service
            ;;
        stop)
            stop_service
            ;;
        restart)
            restart_service
            ;;
        status)
            status_service
            ;;
        logs)
            show_logs
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            log_error "未知命令: ${1:-}"
            echo ""
            show_help
            exit 1
            ;;
    esac
}

# 执行主函数
main "$@" 