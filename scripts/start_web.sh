#!/bin/bash
# scripts/start_web.sh - Web服务启动脚本

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
    
    # 构建Redis URL
    local redis_url="redis://${REDIS_HOST}:${REDIS_PORT}/${REDIS_DB_BROKER:-0}"
    
    # 简单检查Redis配置
    if [[ -n "$REDIS_HOST" && -n "$REDIS_PORT" ]]; then
        log_success "Redis配置正确: $redis_url"
    else
        log_warning "Redis配置可能有问题: HOST=$REDIS_HOST, PORT=$REDIS_PORT"
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

# 数据库迁移
run_migrations() {
    log_info "运行数据库迁移..."
    
    if command -v alembic &> /dev/null; then
        alembic upgrade head
        log_success "数据库迁移完成"
    else
        log_warning "Alembic未安装，跳过数据库迁移"
    fi
}

# 启动Web服务
start_web_service() {
    log_info "启动FastAPI Web服务..."
    
    # 设置默认值
    local port=${PORT:-8000}
    local workers=${GUNICORN_WORKERS:-4}
    local environment=${ENVIRONMENT:-development}
    
    log_info "服务配置:"
    log_info "  端口: $port"
    log_info "  环境: $environment"
    
    if [[ "$environment" == "production" ]]; then
        log_info "使用Gunicorn启动生产环境服务..."
        log_info "  Worker数量: $workers"
        
        gunicorn app.web_main:app \
            -w $workers \
            -k uvicorn.workers.UvicornWorker \
            --bind 0.0.0.0:$port \
            --access-logfile - \
            --error-logfile - \
            --log-level info \
            --timeout 120 \
            --keep-alive 5 \
            --max-requests 1000 \
            --max-requests-jitter 100
    else
        log_info "使用Uvicorn启动开发环境服务..."
        
        uvicorn app.web_main:app \
            --host 0.0.0.0 \
            --port $port \
            --reload \
            --log-level info
    fi
}

# 信号处理
cleanup() {
    log_info "收到停止信号，正在关闭服务..."
    exit 0
}

# 注册信号处理器
trap cleanup SIGINT SIGTERM

# 主函数
main() {
    log_info "启动SQL核验Web服务..."
    log_info "版本: 1.0.0"
    log_info "时间: $(date)"
    
    # 检查环境
    check_env_vars
    check_database
    check_redis
    check_nfs
    
    # 运行迁移
    run_migrations
    
    # 启动服务
    start_web_service
}

# 执行主函数
main "$@" 