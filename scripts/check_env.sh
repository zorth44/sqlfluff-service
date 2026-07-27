#!/bin/bash
# check_env.sh - 检查环境变量是否正确配置

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "========== 环境变量检查 =========="

# 必需的环境变量
REQUIRED_VARS=(
    "MYSQL_DATABASE_HOST"
    "MYSQL_DATABASE_PORT"
    "MYSQL_DATABASE_USERNAME"
    "MYSQL_DATABASE_PASSWORD"
    "MYSQL_DATABASE_NAME"
    "NFS_SHARE_ROOT_PATH"
)

# 可选但重要的环境变量
OPTIONAL_VARS=(
    "ENVIRONMENT"
    "PORT"
    "WEB_PORT"
    "GUNICORN_WORKERS"
    "WORKER_CONCURRENCY"
    "WORKER_POLL_INTERVAL"
    "WORKER_HEARTBEAT_INTERVAL"
    "WORKER_ZOMBIE_TIMEOUT"
    "WORKER_TASK_TIMEOUT"
    "WORKER_ZOMBIE_SWEEP_INTERVAL"
    "WORKER_MAX_RETRIES"
    "DATABASE_URL"
    "CONSUL_URL"
    "CONSUL_HOST"
    "CONSUL_SERVICE_IP"
    "LOG_FILE_BACKUP_COUNT"
)

missing_vars=()

echo -e "${YELLOW}检查必需环境变量:${NC}"
for var in "${REQUIRED_VARS[@]}"; do
    if [[ -n "${!var}" ]]; then
        if [[ "$var" == *"PASSWORD"* ]]; then
            echo -e "  ✓ $var: ***已设置***"
        else
            echo -e "  ✓ $var: ${!var}"
        fi
    else
        echo -e "  ${RED}✗ $var: 未设置${NC}"
        missing_vars+=("$var")
    fi
done

echo -e "\n${YELLOW}检查可选环境变量:${NC}"
for var in "${OPTIONAL_VARS[@]}"; do
    if [[ -n "${!var}" ]]; then
        if [[ "$var" == *"PASSWORD"* ]]; then
            echo -e "  ✓ $var: ***已设置***"
        elif [[ "$var" == "DATABASE_URL" ]]; then
            echo -e "  ✓ $var: mysql+pymysql://***:***@${MYSQL_DATABASE_HOST}:${MYSQL_DATABASE_PORT}/${MYSQL_DATABASE_NAME}"
        else
            echo -e "  ✓ $var: ${!var}"
        fi
    else
        echo -e "  - $var: 未设置"
    fi
done

if [[ ${#missing_vars[@]} -gt 0 ]]; then
    echo -e "\n${RED}错误: 以下必需环境变量未设置:${NC}"
    for var in "${missing_vars[@]}"; do
        echo "  - $var"
    done
    echo -e "\n${YELLOW}请编辑 ~/.bashrc 文件设置这些环境变量，然后运行:${NC}"
    echo "source ~/.bashrc"
    exit 1
else
    echo -e "\n${GREEN}✓ 所有必需环境变量已正确设置${NC}"
fi

echo "================================="
