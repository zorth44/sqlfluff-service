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
        "REDIS_HOST"
        "REDIS_PORT"
        "NFS_SHARE_ROOT_PATH"
        "MYSQL_DATABASE_HOST"
        "MYSQL_DATABASE_PORT"
        "MYSQL_DATABASE_USERNAME"
        "MYSQL_DATABASE_PASSWORD"
        "MYSQL_DATABASE_NAME"
    )
    
    # 可选但重要的变量
    local optional_vars=(
        "REDIS_CLUSTER_ENABLED"
        "REDIS_CLUSTER_NODES"
        "REDIS_PASSWORD"
    )
    
    log_info "检查可选环境变量:"
    for var in "${optional_vars[@]}"; do
        if [[ -n "${!var}" ]]; then
            if [[ "$var" == "REDIS_PASSWORD" ]]; then
                log_info "  $var: ***已设置***"
            else
                log_info "  $var: ${!var}"
            fi
        else
            log_info "  $var: 未设置"
        fi
    done
    
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
    
    # 构建数据库URL
    export DATABASE_URL="mysql+pymysql://${MYSQL_DATABASE_USERNAME}:${MYSQL_DATABASE_PASSWORD}@${MYSQL_DATABASE_HOST}:${MYSQL_DATABASE_PORT}/${MYSQL_DATABASE_NAME}"
    log_info "数据库URL已构建: mysql+pymysql://${MYSQL_DATABASE_USERNAME}:***@${MYSQL_DATABASE_HOST}:${MYSQL_DATABASE_PORT}/${MYSQL_DATABASE_NAME}"
    
    # 设置Consul配置
    if [[ -n "$CONSUL_URL" ]]; then
        export CONSUL_HOST="$CONSUL_URL"
        log_info "Consul配置: $CONSUL_HOST:${CONSUL_PORT:-8500}"
    fi
    
    log_success "环境变量检查通过"
}

# 数据库连接检查
check_database() {
    log_info "检查数据库连接..."
    
    # 使用Python检查数据库连接
    python3 -c "
import sys
import os
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

try:
    # 从环境变量获取数据库URL
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        print('DATABASE_URL environment variable is not set')
        sys.exit(1)
    
    print(f'Testing connection to database...')
    engine = create_engine(database_url)
    with engine.connect() as conn:
        conn.execute(text('SELECT 1'))
    print('Database connection successful')
except SQLAlchemyError as e:
    print(f'Database connection failed: {e}')
    sys.exit(1)
except Exception as e:
    print(f'Unexpected error: {e}')
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
        # 测试连接 - 使用环境变量传递密码避免shell特殊字符问题
        if [[ -n "$REDIS_PASSWORD" ]]; then
            # 使用REDISCLI_AUTH环境变量传递密码，避免命令行特殊字符问题
            if REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ping &> /dev/null; then
                log_success "Redis连接正常: $REDIS_HOST:$REDIS_PORT"
            else
                log_warning "Redis连接失败，但继续启动"
            fi
        else
            # 没有密码的情况
            if redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ping &> /dev/null; then
                log_success "Redis连接正常: $REDIS_HOST:$REDIS_PORT"
            else
                log_warning "Redis连接失败，但继续启动"
            fi
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
    
    # 设置 Python 路径确保能找到模块
    export PYTHONPATH="${PYTHONPATH:+${PYTHONPATH}:}."
    
    # Redis集群模式的环境变量
    local redis_cluster_enabled=$(echo "${REDIS_CLUSTER_ENABLED:-false}" | tr '[:upper:]' '[:lower:]')
    if [[ "$redis_cluster_enabled" == "true" ]]; then
        log_info "启用Redis集群兼容模式"
        # 注意：这些环境变量将通过Celery配置文件设置，而不是环境变量
        # 因为Celery 5.x不允许混用新旧格式
    fi
    
    # 构建Celery命令 - 正确的应用路径
    local celery_cmd="celery -A app.celery_app.celery_main:celery_app worker"
    celery_cmd="$celery_cmd --loglevel=$log_level"
    celery_cmd="$celery_cmd --concurrency=$concurrency"
    celery_cmd="$celery_cmd --hostname=worker@%h"
    celery_cmd="$celery_cmd --max-tasks-per-child=1000"
    celery_cmd="$celery_cmd --prefetch-multiplier=1"
    celery_cmd="$celery_cmd --queues=$queues"
    
    # Redis集群模式添加额外参数
    if [[ "$redis_cluster_enabled" == "true" ]]; then
        celery_cmd="$celery_cmd --without-mingle --without-gossip --without-heartbeat"
        log_info "Redis集群模式：已添加 --without-mingle --without-gossip --without-heartbeat 参数"
    fi
    
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