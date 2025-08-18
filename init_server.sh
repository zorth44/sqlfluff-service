#!/bin/bash
# init_server.sh - 初始化SQLFluff服务器环境

APP_DIR="/home/$(whoami)/sqlfluff-service"
BASHRC_FILE="$HOME/.bashrc"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "创建应用目录结构..."
mkdir -p "$APP_DIR"/{current,backups,releases,logs,scripts,config}

echo "设置目录权限..."
chmod 755 "$APP_DIR"/{scripts,releases,backups,config}
chmod 755 "$APP_DIR/scripts"/*.sh 2>/dev/null || true

echo "配置环境变量到 .bashrc ..."
# 备份原始 .bashrc
cp "$BASHRC_FILE" "$BASHRC_FILE.backup.$(date +%Y%m%d_%H%M%S)"

# 添加SQLFluff服务环境变量到 .bashrc
cat >> "$BASHRC_FILE" << 'EOF'

# ========== SQLFluff服务环境变量 ==========
# 数据库配置
export MYSQL_DATABASE_HOST=localhost
export MYSQL_DATABASE_PORT=3306
export MYSQL_DATABASE_USERNAME=sqlfluff
export MYSQL_DATABASE_PASSWORD=your_password
export MYSQL_DATABASE_NAME=sqlfluff_db

# Redis配置
export REDIS_HOST=localhost
export REDIS_PORT=6379
export REDIS_DB_BROKER=0
export REDIS_DB_RESULT=1
export REDIS_PASSWORD=your_redis_password
export REDIS_CLUSTER_MODE=false
export REDIS_CLUSTER_ENABLED=false
# export REDIS_CLUSTER_NODES=node1:7000,node2:7000,node3:7000

# NFS配置
export NFS_SHARE_ROOT_PATH=/data/bddf/resource

# 服务配置
export ENVIRONMENT=production
export PORT=8000
export GUNICORN_WORKERS=4

# Celery配置
export CELERY_WORKER_CONCURRENCY=4
export CELERY_LOG_LEVEL=INFO
export CELERY_QUEUES=default,sql_analysis,zip_processing

# Consul配置
export CONSUL_URL=localhost
export CONSUL_PORT=8500

# 构建数据库URL
export DATABASE_URL="mysql+pymysql://${MYSQL_DATABASE_USERNAME}:${MYSQL_DATABASE_PASSWORD}@${MYSQL_DATABASE_HOST}:${MYSQL_DATABASE_PORT}/${MYSQL_DATABASE_NAME}"
# ========== SQLFluff服务环境变量结束 ==========
EOF

echo "创建环境变量检查脚本..."
cat > "$APP_DIR/scripts/check_env.sh" << 'EOF'
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
    "REDIS_HOST"
    "REDIS_PORT"
    "NFS_SHARE_ROOT_PATH"
    "DATABASE_URL"
)

# 可选但重要的环境变量
OPTIONAL_VARS=(
    "ENVIRONMENT"
    "PORT"
    "GUNICORN_WORKERS"
    "CELERY_WORKER_CONCURRENCY"
    "CELERY_LOG_LEVEL"
    "CELERY_QUEUES"
    "REDIS_PASSWORD"
    "REDIS_CLUSTER_MODE"
    "REDIS_CLUSTER_ENABLED"
    "CONSUL_URL"
)

missing_vars=()

echo -e "${YELLOW}检查必需环境变量:${NC}"
for var in "${REQUIRED_VARS[@]}"; do
    if [[ -n "${!var}" ]]; then
        if [[ "$var" == *"PASSWORD"* ]]; then
            echo -e "  ✓ $var: ***已设置***"
        elif [[ "$var" == "DATABASE_URL" ]]; then
            echo -e "  ✓ $var: mysql+pymysql://***:***@${MYSQL_DATABASE_HOST}:${MYSQL_DATABASE_PORT}/${MYSQL_DATABASE_NAME}"
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
EOF

chmod +x "$APP_DIR/scripts/check_env.sh"

echo "初始化完成！"
echo "应用目录: $APP_DIR"
echo ""
echo -e "${YELLOW}重要提示:${NC}"
echo "1. 环境变量已添加到 ~/.bashrc 文件"
echo "2. 请编辑 ~/.bashrc 文件，修改配置为你的实际值"
echo "3. 运行 'source ~/.bashrc' 重新加载环境变量"
echo "4. 运行 '$APP_DIR/scripts/check_env.sh' 检查配置是否正确"
echo ""
echo "目录结构:"
tree "$APP_DIR" -L 2 2>/dev/null || ls -la "$APP_DIR"