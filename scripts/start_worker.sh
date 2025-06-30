#!/bin/bash
# scripts/start_worker.sh - Worker服务启动脚本

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

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

# 环境变量检查
check_env_vars() {
    log_info "检查环境变量..."
    
    local required_vars=(
        "DATABASE_URL"
        "REDIS_HOST"
        "REDIS_PORT"
        "NFS_SHARE_ROOT_PATH"
    )
    
    local missing_vars=()
    
    for var in "${required_vars[@]}"; do
        if [[ -z "${!var}" ]]; then
            missing_vars+=("$var")
        fi
    done
    
    if [[ ${#missing_vars[@]} -gt 0 ]]; then
        log_error "缺少必需的环境变量:"
        for var in "${missing_vars[@]}"; do
            echo "  - $var"
        done
        exit 1
    fi
    
    log_success "环境变量检查通过"
}

# 数据库连接检查
check_database() {
    log_info "检查数据库连接..."
    
    # 使用Python检查数据库连接
    python3 -c "
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

try:
    engine = create_engine('$DATABASE_URL')
    with engine.connect() as conn:
        conn.execute(text('SELECT 1'))
    print('Database connection successful')
except SQLAlchemyError as e:
    print(f'Database connection failed: {e}')
    sys.exit(1)
"
    
    if [[ $? -eq 0 ]]; then
        log_success "数据库连接正常"
    else
        log_error "数据库连接失败"
        exit 1
    fi
}

# Redis连接检查
check_redis() {
    log_info "检查Redis连接..."
    
    # 尝试连接Redis
    if command -v redis-cli &> /dev/null; then
        # 构建Redis连接命令
        local redis_cmd="redis-cli -h $REDIS_HOST -p $REDIS_PORT"
        
        # 如果有密码，添加密码参数
        if [[ -n "$REDIS_PASSWORD" ]]; then
            redis_cmd="$redis_cmd -a $REDIS_PASSWORD"
        fi
        
        # 测试连接
        if $redis_cmd ping &> /dev/null; then
            log_success "Redis连接正常: $REDIS_HOST:$REDIS_PORT"
        else
            log_warning "Redis连接失败，但继续启动"
        fi
    else
        log_warning "redis-cli未安装，跳过Redis连接检查"
    fi
}

# NFS目录检查
check_nfs() {
    log_info "检查NFS目录..."
    
    if [[ -d "$NFS_SHARE_ROOT_PATH" ]]; then
        if [[ -w "$NFS_SHARE_ROOT_PATH" ]]; then
            log_success "NFS目录可写: $NFS_SHARE_ROOT_PATH"
        else
            log_error "NFS目录不可写: $NFS_SHARE_ROOT_PATH"
            exit 1
        fi
    else
        log_error "NFS目录不存在: $NFS_SHARE_ROOT_PATH"
        exit 1
    fi
}

# 启动Worker服务
start_worker_service() {
    log_info "启动Celery Worker服务..."
    
    # 设置默认值
    local concurrency=${CELERY_WORKER_CONCURRENCY:-4}
    local log_level=${CELERY_LOG_LEVEL:-INFO}
    local queues=${CELERY_QUEUES:-"default,sql_analysis,zip_processing"}
    
    log_info "Worker配置:"
    log_info "  并发数: $concurrency"
    log_info "  日志级别: $log_level"
    log_info "  队列: $queues"
    
    # 构建Celery命令
    local celery_cmd="celery -A app.celery_app.celery_main worker"
    celery_cmd="$celery_cmd --loglevel=$log_level"
    celery_cmd="$celery_cmd --concurrency=$concurrency"
    celery_cmd="$celery_cmd --hostname=worker@%h"
    celery_cmd="$celery_cmd --max-tasks-per-child=1000"
    celery_cmd="$celery_cmd --prefetch-multiplier=1"
    celery_cmd="$celery_cmd --queues=$queues"
    
    log_info "执行命令: $celery_cmd"
    
    # 启动Worker
    eval $celery_cmd
}

# 信号处理
cleanup() {
    log_info "收到停止信号，正在关闭Worker..."
    # 发送SIGTERM给Celery进程
    pkill -f "celery.*worker" || true
    exit 0
}

# 注册信号处理器
trap cleanup SIGINT SIGTERM

# 主函数
main() {
    log_info "启动SQL核验Worker服务..."
    log_info "版本: 1.0.0"
    log_info "时间: $(date)"
    
    # 检查环境
    check_env_vars
    check_database
    check_redis
    check_nfs
    
    # 启动服务
    start_worker_service
}

# 执行主函数
main "$@" 