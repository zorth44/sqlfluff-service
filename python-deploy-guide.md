# SQLFluff服务部署指南

## 一、项目架构说明

SQLFluff服务是一个基于FastAPI + Celery的分布式SQL检查服务，包含Web API服务和后台Worker服务。

### 服务组件
- **Web服务**: FastAPI应用，提供REST API接口
- **Worker服务**: Celery Worker，处理SQL检查任务
- **数据库**: MySQL，存储任务和作业信息
- **消息队列**: Redis，Celery任务队列
- **文件存储**: NFS共享目录

### 部署架构
```
开发机                     堡垒机/上传工具            服务器
  │                           │                      │
  ├─ 1.打包项目 ─────────────→ ├─ 2.手动上传 ────────→ ├─ 3.接收包
  │                           │                      ├─ 4.备份旧版本
  │                           │                      ├─ 5.解压新版本
  │                           │                      ├─ 6.安装依赖
  │                           │                      ├─ 7.数据库迁移
  │                           │                      ├─ 8.重启Web服务
  │                           │                      └─ 9.重启Worker服务
```

**说明**: 本部署方案适用于有堡垒机限制的环境，不使用SSH/SCP，需要手动上传文件到服务器。

## 二、目录结构规划

### 开发机目录结构
```
sqlfluff-service/
├── app/                   # 应用源代码
│   ├── api/              # API路由
│   ├── celery_app/       # Celery应用
│   ├── core/             # 核心组件
│   ├── models/           # 数据模型
│   ├── services/         # 业务逻辑
│   ├── schemas/          # 数据schemas
│   ├── utils/            # 工具函数
│   ├── web_main.py       # Web服务入口
│   └── worker_main.py    # Worker服务入口
├── scripts/              # 运维脚本
│   ├── start_web.sh      # Web服务启动脚本
│   ├── start_worker.sh   # Worker服务启动脚本
│   ├── init_db.py        # 数据库初始化
│   └── prepare_offline_deployment.sh
├── alembic/              # 数据库迁移
├── local_wheels/         # 本地wheel包
├── requirements.txt      # 依赖列表
├── alembic.ini          # 数据库迁移配置
├── deploy/              # 部署脚本目录
│   ├── package.sh       # 打包脚本
│   └── deploy.sh        # 部署脚本
└── releases/            # 发布包存放目录
```

### 服务器目录结构
```
/home/user/
├── sqlfluff-service/      # 应用运行目录
│   ├── current/          # 当前运行版本
│   │   ├── app/         # 应用代码
│   │   ├── scripts/     # 启动脚本
│   │   ├── alembic/     # 数据库迁移文件（不执行）
│   │   └── requirements.txt # 依赖列表（仅作参考）
│   ├── backups/          # 备份目录
│   ├── releases/         # 发布包目录
│   ├── logs/             # 日志目录
│   │   ├── web.log      # Web服务日志
│   │   └── worker.log   # Worker服务日志
│   ├── scripts/          # 服务器端脚本
│   │   ├── deploy.sh     # 部署脚本
│   │   ├── start_web.sh  # Web服务启动
│   │   ├── start_worker.sh # Worker服务启动
│   │   ├── stop_web.sh   # Web服务停止
│   │   ├── stop_worker.sh # Worker服务停止
│   │   ├── status.sh     # 状态检查
│   │   └── check_env.sh  # 环境变量检查
│   ├── config/           # 配置文件（已弃用，改用~/.bashrc）
│   ├── web.pid           # Web服务进程ID
│   └── worker.pid        # Worker服务进程ID
```

## 三、开发机端脚本

### 3.1 打包脚本 (deploy/package.sh)

```bash
#!/bin/bash
# package.sh - 在开发机上打包项目

# 配置
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC_DIR="$PROJECT_DIR/src"
RELEASE_DIR="$PROJECT_DIR/releases"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
VERSION="${1:-$TIMESTAMP}"  # 可以传入版本号，默认使用时间戳
PACKAGE_NAME="release_${VERSION}.tar.gz"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========== 开始打包 ==========${NC}"
echo "版本号: $VERSION"
echo "包名称: $PACKAGE_NAME"

# 创建发布目录
mkdir -p "$RELEASE_DIR"

# 创建临时打包目录
TEMP_DIR="/tmp/package_${VERSION}"
rm -rf "$TEMP_DIR"
mkdir -p "$TEMP_DIR"

# 复制需要打包的文件
echo -e "${YELLOW}复制文件...${NC}"
cp -r "$PROJECT_DIR/app" "$TEMP_DIR/"
cp -r "$PROJECT_DIR/scripts" "$TEMP_DIR/"
cp -r "$PROJECT_DIR/alembic" "$TEMP_DIR/"
cp -r "$PROJECT_DIR/local_wheels" "$TEMP_DIR/"
cp "$PROJECT_DIR/requirements.txt" "$TEMP_DIR/"
cp "$PROJECT_DIR/alembic.ini" "$TEMP_DIR/"

# 创建版本信息文件
echo "{
  \"version\": \"$VERSION\",
  \"build_time\": \"$(date '+%Y-%m-%d %H:%M:%S')\",
  \"build_user\": \"$(whoami)\",
  \"build_host\": \"$(hostname)\"
}" > "$TEMP_DIR/version.json"

# 清理不需要的文件
echo -e "${YELLOW}清理文件...${NC}"
find "$TEMP_DIR" -type f -name "*.pyc" -delete
find "$TEMP_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$TEMP_DIR" -type f -name ".DS_Store" -delete
find "$TEMP_DIR" -type d -name ".git" -exec rm -rf {} + 2>/dev/null || true
find "$TEMP_DIR" -type d -name "venv" -exec rm -rf {} + 2>/dev/null || true
find "$TEMP_DIR" -type d -name "logs" -exec rm -rf {} + 2>/dev/null || true
find "$TEMP_DIR" -type f -name "*.log" -delete

# 打包
echo -e "${YELLOW}创建压缩包...${NC}"
cd "$TEMP_DIR"
tar czf "$RELEASE_DIR/$PACKAGE_NAME" .
cd - > /dev/null

# 清理临时目录
rm -rf "$TEMP_DIR"

# 显示包信息
PACKAGE_SIZE=$(ls -lh "$RELEASE_DIR/$PACKAGE_NAME" | awk '{print $5}')
echo -e "${GREEN}========== 打包完成 ==========${NC}"
echo "包位置: $RELEASE_DIR/$PACKAGE_NAME"
echo "包大小: $PACKAGE_SIZE"

# 生成部署命令提示
echo -e "\n${YELLOW}下一步: 执行部署命令${NC}"
echo "./deploy/deploy.sh $VERSION"
```

### 3.2 准备部署脚本 (deploy/prepare_deploy.sh)

```bash
#!/bin/bash
# prepare_deploy.sh - 准备部署包和说明

# 配置
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RELEASE_DIR="$PROJECT_DIR/releases"

# 版本号
VERSION="${1:-$(date +%Y%m%d_%H%M%S)}"
PACKAGE_NAME="release_${VERSION}.tar.gz"
PACKAGE_PATH="$RELEASE_DIR/$PACKAGE_NAME"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 检查包是否存在
if [ ! -f "$PACKAGE_PATH" ]; then
    echo -e "${RED}错误: 包文件不存在: $PACKAGE_PATH${NC}"
    echo "请先运行: ./deploy/package.sh $VERSION"
    exit 1
fi

echo -e "${GREEN}========== 准备部署 ==========${NC}"
echo "版本号: $VERSION"
echo "包文件: $PACKAGE_PATH"

# 生成部署说明文件
DEPLOY_INSTRUCTION="$RELEASE_DIR/deploy_instruction_${VERSION}.md"
cat > "$DEPLOY_INSTRUCTION" << EOF
# SQLFluff服务部署说明 - 版本 ${VERSION}

## 1. 上传文件
请将以下文件上传到服务器：

**包文件**: \`release_${VERSION}.tar.gz\`
**目标路径**: \`~/sqlfluff-service/releases/release_${VERSION}.tar.gz\`

## 2. 在服务器上执行部署

\`\`\`bash
# 登录服务器后执行
cd ~/sqlfluff-service
bash scripts/deploy.sh ${VERSION}
\`\`\`

## 3. 检查部署状态

\`\`\`bash
# 检查服务状态
bash ~/sqlfluff-service/scripts/status.sh

# 查看日志
tail -f ~/sqlfluff-service/logs/web_\$(date +%Y%m%d).log
tail -f ~/sqlfluff-service/logs/worker_\$(date +%Y%m%d).log
\`\`\`

## 4. 如果部署失败

\`\`\`bash
# 回滚到上一版本
bash ~/sqlfluff-service/scripts/rollback.sh

# 查看部署日志
tail -n 50 ~/sqlfluff-service/logs/*.log
\`\`\`

---
生成时间: $(date '+%Y-%m-%d %H:%M:%S')
EOF

echo -e "${BLUE}========== 部署准备完成 ==========${NC}"
echo -e "${YELLOW}包文件位置:${NC} $PACKAGE_PATH"
echo -e "${YELLOW}部署说明:${NC} $DEPLOY_INSTRUCTION"
echo ""
echo -e "${GREEN}下一步操作:${NC}"
echo "1. 将包文件上传到服务器: ~/sqlfluff-service/releases/"
echo "2. 在服务器上运行: bash ~/sqlfluff-service/scripts/deploy.sh $VERSION"
echo "3. 检查部署状态: bash ~/sqlfluff-service/scripts/status.sh"
echo ""
echo -e "${BLUE}快速复制命令:${NC}"
echo "# 服务器上执行部署:"
echo "cd ~/sqlfluff-service && bash scripts/deploy.sh $VERSION"
```

## 四、服务器端脚本

### 4.1 部署脚本 (scripts/deploy.sh)

```bash
#!/bin/bash
# 服务器端部署脚本

# 配置
APP_DIR="/home/$(whoami)/sqlfluff-service"
CURRENT_DIR="$APP_DIR/current"
BACKUP_DIR="$APP_DIR/backups"
RELEASE_DIR="$APP_DIR/releases"
LOG_DIR="$APP_DIR/logs"
CONFIG_DIR="$APP_DIR/config"
WEB_PID_FILE="$APP_DIR/web.pid"
WORKER_PID_FILE="$APP_DIR/worker.pid"

# 版本号
VERSION="${1}"
if [ -z "$VERSION" ]; then
    echo "错误: 请提供版本号"
    exit 1
fi

PACKAGE_NAME="release_${VERSION}.tar.gz"
PACKAGE_PATH="$RELEASE_DIR/$PACKAGE_NAME"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}========== 服务器部署开始 ==========${NC}"
echo "版本: $VERSION"
echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"

# 检查包文件
if [ ! -f "$PACKAGE_PATH" ]; then
    echo -e "${RED}错误: 包文件不存在: $PACKAGE_PATH${NC}"
    exit 1
fi

# 1. 停止当前服务
echo -e "${YELLOW}[1/6] 停止当前服务...${NC}"
bash "$APP_DIR/scripts/stop.sh"

# 2. 备份当前版本
if [ -d "$CURRENT_DIR" ]; then
    echo -e "${YELLOW}[2/6] 备份当前版本...${NC}"
    BACKUP_NAME="backup_$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$BACKUP_DIR"
    cp -r "$CURRENT_DIR" "$BACKUP_DIR/$BACKUP_NAME"
    
    # 只保留最近5个备份
    cd "$BACKUP_DIR"
    ls -t | tail -n +6 | xargs -r rm -rf
    cd - > /dev/null
else
    echo -e "${YELLOW}[2/6] 跳过备份（首次部署）${NC}"
fi

# 3. 解压新版本
echo -e "${YELLOW}[3/6] 解压新版本...${NC}"
rm -rf "$CURRENT_DIR"
mkdir -p "$CURRENT_DIR"
tar xzf "$PACKAGE_PATH" -C "$CURRENT_DIR"

# 4. 检查环境变量
echo -e "${YELLOW}[4/5] 检查环境变量...${NC}"
bash "$APP_DIR/scripts/check_env.sh"
if [ $? -ne 0 ]; then
    echo -e "${RED}环境变量检查失败，请检查 ~/.bashrc 配置${NC}"
    exit 1
fi

# 5. 启动服务
echo -e "${YELLOW}[5/5] 启动服务...${NC}"
# 启动Web服务
bash "$APP_DIR/scripts/start_web.sh"
# 启动Worker服务  
bash "$APP_DIR/scripts/start_worker.sh"

# 检查启动状态
sleep 5

# 检查Web服务
WEB_SUCCESS=false
if [ -f "$WEB_PID_FILE" ]; then
    WEB_PID=$(cat "$WEB_PID_FILE")
    if ps -p "$WEB_PID" > /dev/null; then
        echo -e "${GREEN}Web服务启动成功 - PID: $WEB_PID${NC}"
        WEB_SUCCESS=true
    else
        echo -e "${RED}Web服务启动失败${NC}"
    fi
else
    echo -e "${RED}Web服务PID文件不存在${NC}"
fi

# 检查Worker服务
WORKER_SUCCESS=false
if [ -f "$WORKER_PID_FILE" ]; then
    WORKER_PID=$(cat "$WORKER_PID_FILE")
    if ps -p "$WORKER_PID" > /dev/null; then
        echo -e "${GREEN}Worker服务启动成功 - PID: $WORKER_PID${NC}"
        WORKER_SUCCESS=true
    else
        echo -e "${RED}Worker服务启动失败${NC}"
    fi
else
    echo -e "${RED}Worker服务PID文件不存在${NC}"
fi

# 综合结果
if [ "$WEB_SUCCESS" = true ] && [ "$WORKER_SUCCESS" = true ]; then
    echo -e "${GREEN}========== 部署成功 ==========${NC}"
    echo "版本信息:"
    cat "$CURRENT_DIR/version.json" 2>/dev/null || echo "无版本信息文件"
elif [ "$WEB_SUCCESS" = true ]; then
    echo -e "${YELLOW}========== 部分成功（仅Web服务） ==========${NC}"
    exit 1
elif [ "$WORKER_SUCCESS" = true ]; then
    echo -e "${YELLOW}========== 部分成功（仅Worker服务） ==========${NC}"
    exit 1
else
    echo -e "${RED}========== 部署失败 ==========${NC}"
    exit 1
fi
```

### 4.2 Web服务启动脚本 (scripts/start_web.sh)

```bash
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
LOG_FILE="$LOG_DIR/web_$(date +%Y%m%d).log"

echo "启动Web服务..."
echo "日志文件: $LOG_FILE"

# 设置Python路径
export PYTHONPATH="${PYTHONPATH:+${PYTHONPATH}:}."

# 启动Web服务
if [ "${ENVIRONMENT:-development}" = "production" ]; then
    # 生产环境使用Gunicorn
    nohup gunicorn app.web_main:app \
        -w "${GUNICORN_WORKERS:-4}" \
        -k uvicorn.workers.UvicornWorker \
        --bind "0.0.0.0:${PORT:-8000}" \
        --access-logfile - \
        --error-logfile - \
        --timeout 120 \
        >> "$LOG_FILE" 2>&1 &
else
    # 开发环境使用Uvicorn
    nohup uvicorn app.web_main:app \
        --host "0.0.0.0" \
        --port "${PORT:-8000}" \
        >> "$LOG_FILE" 2>&1 &
fi

WEB_PID=$!
echo $WEB_PID > "$WEB_PID_FILE"

# 等待确认启动
sleep 3
if ps -p "$WEB_PID" > /dev/null; then
    echo "Web服务启动成功，PID: $WEB_PID"
else
    echo "Web服务启动失败"
    rm -f "$WEB_PID_FILE"
    exit 1
fi
```

### 4.3 Worker服务启动脚本 (scripts/start_worker.sh)

```bash
#!/bin/bash
# Worker服务启动脚本

APP_DIR="/home/$(whoami)/sqlfluff-service"
CURRENT_DIR="$APP_DIR/current"
LOG_DIR="$APP_DIR/logs"
CONFIG_DIR="$APP_DIR/config"
WORKER_PID_FILE="$APP_DIR/worker.pid"

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
if [ -f "$WORKER_PID_FILE" ]; then
    OLD_PID=$(cat "$WORKER_PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo "Worker服务已经在运行，PID: $OLD_PID"
        exit 1
    fi
fi

# 启动Worker服务
cd "$CURRENT_DIR"
LOG_FILE="$LOG_DIR/worker_$(date +%Y%m%d).log"

echo "启动Worker服务..."
echo "日志文件: $LOG_FILE"

# 设置Python路径
export PYTHONPATH="${PYTHONPATH:+${PYTHONPATH}:}."

# 启动Celery Worker
nohup celery -A app.celery_app.celery_main:celery_app worker \
    --loglevel="${CELERY_LOG_LEVEL:-INFO}" \
    --concurrency="${CELERY_WORKER_CONCURRENCY:-4}" \
    --hostname="worker@%h" \
    --max-tasks-per-child=1000 \
    --prefetch-multiplier=1 \
    --queues="${CELERY_QUEUES:-default,sql_analysis,zip_processing}" \
    >> "$LOG_FILE" 2>&1 &

WORKER_PID=$!
echo $WORKER_PID > "$WORKER_PID_FILE"

# 等待确认启动
sleep 3
if ps -p "$WORKER_PID" > /dev/null; then
    echo "Worker服务启动成功，PID: $WORKER_PID"
else
    echo "Worker服务启动失败"
    rm -f "$WORKER_PID_FILE"
    exit 1
fi
```

### 4.4 Web服务停止脚本 (scripts/stop_web.sh)

```bash
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
```

### 4.5 Worker服务停止脚本 (scripts/stop_worker.sh)

```bash
#!/bin/bash
# 停止Python应用

APP_DIR="/home/$(whoami)/sqlfluff-service"
WORKER_PID_FILE="$APP_DIR/worker.pid"

if [ ! -f "$WORKER_PID_FILE" ]; then
    echo "Worker服务PID文件不存在，服务可能未运行"
    # 强制杀死所有Celery进程（防止僵尸进程）
    pkill -f "celery.*worker" 2>/dev/null || true
    exit 0
fi

WORKER_PID=$(cat "$WORKER_PID_FILE")

if ps -p "$WORKER_PID" > /dev/null 2>&1; then
    echo "停止Worker服务 (PID: $WORKER_PID)..."
    
    # 先尝试优雅关闭
    kill -TERM "$WORKER_PID" 2>/dev/null
    
    # 等待进程结束（最多30秒）
    for i in {1..30}; do
        if ! ps -p "$WORKER_PID" > /dev/null 2>&1; then
            echo "Worker服务已停止"
            rm -f "$WORKER_PID_FILE"
            exit 0
        fi
        sleep 1
    done
    
    # 如果还没停止，强制结束
    echo "强制停止Worker服务..."
    kill -9 "$WORKER_PID" 2>/dev/null
    sleep 1
fi

# 清理所有Celery进程
pkill -f "celery.*worker" 2>/dev/null || true
rm -f "$WORKER_PID_FILE"
echo "Worker服务已停止"
```

### 4.6 状态检查脚本 (scripts/status.sh)

```bash
#!/bin/bash
# 检查服务状态

APP_DIR="/home/$(whoami)/sqlfluff-service"
WEB_PID_FILE="$APP_DIR/web.pid"
WORKER_PID_FILE="$APP_DIR/worker.pid"
CURRENT_DIR="$APP_DIR/current"
LOG_DIR="$APP_DIR/logs"

echo "========== SQLFluff服务状态 =========="

# 检查Web服务
echo "Web服务:"
if [ -f "$WEB_PID_FILE" ]; then
    WEB_PID=$(cat "$WEB_PID_FILE")
    if ps -p "$WEB_PID" > /dev/null 2>&1; then
        echo "  状态: 运行中 ✓"
        echo "  PID: $WEB_PID"
        echo "  端口: ${PORT:-8000}"
        
        # 显示内存使用
        echo "  内存使用:"
        ps -o pid,vsz,rss,comm -p "$WEB_PID" | tail -n 1 | sed 's/^/    /'
    else
        echo "  状态: 已停止 ✗"
        echo "  PID文件存在但进程未运行"
    fi
else
    echo "  状态: 未运行 ✗"
fi

echo ""
# 检查Worker服务
echo "Worker服务:"
if [ -f "$WORKER_PID_FILE" ]; then
    WORKER_PID=$(cat "$WORKER_PID_FILE")
    if ps -p "$WORKER_PID" > /dev/null 2>&1; then
        echo "  状态: 运行中 ✓"
        echo "  PID: $WORKER_PID"
        echo "  队列: ${CELERY_QUEUES:-default,sql_analysis,zip_processing}"
        echo "  并发数: ${CELERY_WORKER_CONCURRENCY:-4}"
        
        # 显示内存使用
        echo "  内存使用:"
        ps -o pid,vsz,rss,comm -p "$WORKER_PID" | tail -n 1 | sed 's/^/    /'
    else
        echo "  状态: 已停止 ✗"
        echo "  PID文件存在但进程未运行"
    fi
else
    echo "  状态: 未运行 ✗"
fi

# 显示版本信息
if [ -f "$CURRENT_DIR/version.json" ]; then
    echo ""
    echo "版本信息:"
    cat "$CURRENT_DIR/version.json"
fi

# 显示最新日志
echo ""
echo "最新日志:"
WEB_LOG_FILE="$LOG_DIR/web_$(date +%Y%m%d).log"
if [ -f "$WEB_LOG_FILE" ]; then
    echo "Web服务日志 (最后5行):"
    tail -n 5 "$WEB_LOG_FILE" | sed 's/^/  /'
fi

WORKER_LOG_FILE="$LOG_DIR/worker_$(date +%Y%m%d).log"
if [ -f "$WORKER_LOG_FILE" ]; then
    echo "Worker服务日志 (最后5行):"
    tail -n 5 "$WORKER_LOG_FILE" | sed 's/^/  /'
fi

# 检查环境配置
echo ""
echo "环境配置:"
echo "  环境: ${ENVIRONMENT:-development}"
echo "  Redis: ${REDIS_HOST:-localhost}:${REDIS_PORT:-6379}"
echo "  数据库: ${MYSQL_DATABASE_HOST:-localhost}:${MYSQL_DATABASE_PORT:-3306}/${MYSQL_DATABASE_NAME:-sqlfluff}"
echo "  NFS目录: ${NFS_SHARE_ROOT_PATH:-/data/nfs}"

echo "=========================================="
```

## 五、初始化设置

### 5.1 服务器初始化脚本

首次使用时，在服务器上运行此脚本创建目录结构：

```bash
#!/bin/bash
# init_server.sh - 初始化SQLFluff服务器环境

APP_DIR="/home/$(whoami)/sqlfluff-service"
BASHRC_FILE="$HOME/.bashrc"

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
```

### 5.2 环境配置说明

环境变量已通过 `init_server.sh` 脚本添加到 `~/.bashrc` 文件中。请编辑 `~/.bashrc` 文件，修改以下配置为你的实际值：

#### 必需配置
- `MYSQL_DATABASE_*`: MySQL数据库连接信息
- `REDIS_HOST/PORT`: Redis服务器地址  
- `NFS_SHARE_ROOT_PATH`: 文件存储目录

#### 可选配置
- `REDIS_PASSWORD`: Redis密码（如果有）
- `REDIS_CLUSTER_*`: Redis集群配置
- `CONSUL_*`: 服务发现配置
- `CELERY_*`: Celery Worker配置
- `GUNICORN_WORKERS`: Gunicorn Worker数量

#### 配置完成后
```bash
# 重新加载环境变量
source ~/.bashrc

# 检查配置是否正确
~/sqlfluff-service/scripts/check_env.sh
```

## 六、使用流程

### 6.1 首次部署

#### 步骤1: 在服务器上初始化环境
```bash
# 通过堡垒机登录服务器后执行
bash init_server.sh

# 编辑环境变量配置
vim ~/.bashrc
# 修改SQLFluff服务相关的export配置为实际值

# 重新加载配置
source ~/.bashrc

# 检查配置是否正确
~/sqlfluff-service/scripts/check_env.sh
```

#### 步骤2: 手动部署数据库（根据需要）
```bash
# 注意：数据库部署由DBA或运维人员手动完成
# 本部署流程不包含数据库迁移，alembic文件仅作参考
# 请根据 alembic/versions/ 中的SQL脚本手动执行数据库变更
```

#### 步骤3: 在开发机上准备部署包
```bash
# 开发机上执行
cd /path/to/sqlfluff-service
./deploy/package.sh v1.0.0
./deploy/prepare_deploy.sh v1.0.0
```

#### 步骤4: 手动上传文件到服务器
```bash
# 使用你的上传工具将以下文件上传到服务器：
# 源文件: releases/release_v1.0.0.tar.gz
# 目标路径: ~/sqlfluff-service/releases/release_v1.0.0.tar.gz
# 
# 上传方式示例（根据你的环境选择）：
# - WinSCP, FileZilla 等FTP工具
# - 堡垒机的文件传输功能
# - 其他企业内部文件传输工具
```

#### 步骤5: 在服务器上执行部署
```bash
# 通过堡垒机登录服务器后执行
cd ~/sqlfluff-service
bash scripts/deploy.sh v1.0.0
```

#### 步骤6: 检查服务状态
```bash
# 在服务器上执行
bash ~/sqlfluff-service/scripts/status.sh
```

### 6.2 日常更新部署

#### 方式1: 指定版本号部署
```bash
# 开发机上执行
cd /path/to/sqlfluff-service
./deploy/package.sh v1.0.1
./deploy/prepare_deploy.sh v1.0.1

# 手动上传包文件到服务器:
# 源文件: releases/release_v1.0.1.tar.gz  
# 目标路径: ~/sqlfluff-service/releases/release_v1.0.1.tar.gz

# 服务器上执行部署:
cd ~/sqlfluff-service && bash scripts/deploy.sh v1.0.1
```

#### 方式2: 时间戳版本号部署
```bash
# 开发机上执行
cd /path/to/sqlfluff-service
./deploy/package.sh
./deploy/prepare_deploy.sh
# 记下生成的版本号，例如: 20241230_143022

# 手动上传包文件到服务器:
# 源文件: releases/release_20241230_143022.tar.gz
# 目标路径: ~/sqlfluff-service/releases/release_20241230_143022.tar.gz

# 服务器上执行部署:
cd ~/sqlfluff-service && bash scripts/deploy.sh 20241230_143022
```

#### 方式3: 一键准备
```bash
# 开发机上执行
cd /path/to/sqlfluff-service
./deploy/quick_prepare.sh
# 脚本会自动生成版本号、打包，并生成详细的部署说明文件

# 按照生成的部署说明文件操作即可
```

#### 方式4: 离线部署（无网络环境）
```bash
# 开发机上执行
cd /path/to/sqlfluff-service
scripts/prepare_offline_deployment.sh
# 然后将整个项目目录打包上传到目标服务器

# 在目标服务器上使用离线安装:
pip install --no-index --find-links=./offline_packages -r requirements.txt
```

### 6.3 一键准备脚本 (deploy/quick_prepare.sh)

```bash
#!/bin/bash
# quick_prepare.sh - 一键打包准备

VERSION=$(date +%Y%m%d_%H%M%S)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "开始一键准备部署，版本: $VERSION"

# 打包
"$SCRIPT_DIR/package.sh" "$VERSION"
if [ $? -ne 0 ]; then
    echo "打包失败！"
    exit 1
fi

# 准备部署说明
"$SCRIPT_DIR/prepare_deploy.sh" "$VERSION"
if [ $? -ne 0 ]; then
    echo "准备部署说明失败！"
    exit 1
fi

echo "一键准备完成！请查看部署说明文件并手动上传包文件。"
```

### 6.4 文件上传方法说明

由于堡垒机环境限制，需要手动上传部署包到服务器。以下是常见的上传方法：

#### 方法1: 图形化FTP工具
```bash
# 使用 WinSCP (Windows) 或 FileZilla (跨平台)
# 1. 连接到堡垒机或跳板机
# 2. 导航到源文件: releases/release_<version>.tar.gz
# 3. 上传到目标路径: ~/sqlfluff-service/releases/
```

#### 方法2: 堡垒机内置文件传输
```bash
# 使用堡垒机提供的文件传输功能
# 1. 登录堡垒机Web界面
# 2. 找到文件传输或上传功能
# 3. 选择本地文件并指定远程路径
```

#### 方法3: 通过中转服务器
```bash
# 如果有中转服务器或共享存储
# 1. 先上传到中转位置
# 2. 在目标服务器上下载:
wget http://transfer-server/releases/release_<version>.tar.gz
# 或
scp transfer-server:/path/to/release_<version>.tar.gz ~/sqlfluff-service/releases/
```

#### 方法4: 企业内部工具
```bash
# 使用企业内部的文件传输工具
# 如: 企业云盘、内部文件共享系统等
# 具体操作请咨询你的系统管理员
```

#### 上传完成后验证
```bash
# 在服务器上验证文件是否上传成功
ls -la ~/sqlfluff-service/releases/
# 检查文件大小和MD5（可选）
md5sum ~/sqlfluff-service/releases/release_<version>.tar.gz
```

## 七、故障处理

### 7.1 回滚到上一版本

```bash
#!/bin/bash
# rollback.sh - 回滚脚本

APP_DIR="/home/$(whoami)/app"
BACKUP_DIR="$APP_DIR/backups"
CURRENT_DIR="$APP_DIR/current"

# 获取最新的备份
LATEST_BACKUP=$(ls -t "$BACKUP_DIR" | head -n 1)

if [ -z "$LATEST_BACKUP" ]; then
    echo "错误: 没有可用的备份"
    exit 1
fi

echo "回滚到: $LATEST_BACKUP"

# 停止服务
bash "$APP_DIR/scripts/stop.sh"

# 恢复备份
rm -rf "$CURRENT_DIR"
cp -r "$BACKUP_DIR/$LATEST_BACKUP" "$CURRENT_DIR"

# 启动服务
bash "$APP_DIR/scripts/start.sh"

echo "回滚完成"
```

### 7.2 查看日志

```bash
# 查看实时日志
tail -f ~/app/logs/app_$(date +%Y%m%d).log

# 查看所有日志文件
ls -lh ~/app/logs/

# 搜索错误
grep -i error ~/app/logs/app_*.log
```

### 7.3 手动操作

```bash
# 手动停止服务
bash ~/sqlfluff-service/scripts/stop_web.sh
bash ~/sqlfluff-service/scripts/stop_worker.sh

# 手动启动服务
bash ~/sqlfluff-service/scripts/start_web.sh
bash ~/sqlfluff-service/scripts/start_worker.sh

# 查看状态
bash ~/sqlfluff-service/scripts/status.sh

# 强制杀死所有进程（紧急情况）
pkill -f "gunicorn.*app.web_main:app"
pkill -f "uvicorn.*app.web_main:app"
pkill -f "celery.*worker"

# 重启所有服务
bash ~/sqlfluff-service/scripts/stop_web.sh
bash ~/sqlfluff-service/scripts/stop_worker.sh
sleep 2
bash ~/sqlfluff-service/scripts/start_web.sh
bash ~/sqlfluff-service/scripts/start_worker.sh
```

### 7.4 数据库操作

```bash
# 手动运行数据库迁移
cd ~/sqlfluff-service/current
source ~/sqlfluff-service/venv/bin/activate
alembic upgrade head

# 查看迁移历史
alembic history

# 回滚数据库到指定版本
alembic downgrade <revision_id>

# 初始化数据库（首次部署）
python scripts/init_db.py
```

## 八、优化建议

### 8.1 添加健康检查

SQLFluff服务已经在FastAPI中内置了健康棄查端点：

```bash
# 检查Web服务健康状态
curl http://localhost:8000/health

# 检查API文档
curl http://localhost:8000/docs

# 检查具体API端点
curl http://localhost:8000/api/health
```

如果需要自定义健康检查，可以在 `app/api/routes/health.py` 中添加更多检查项。

### 8.2 环境变量管理

配置文件已在 `~/sqlfluff-service/config/production.env` 中统一管理，包含：

- 数据库连接信息
- Redis配置
- NFS目录配置
- Celery Worker配置
- 服务端口和环境设置

启动脚本会自动加载这些配置。新增配置项时，只需编辑此文件。

### 8.3 添加监控告警

创建简单的监控脚本：

```bash
#!/bin/bash
# monitor.sh - 监控脚本（可通过crontab定期执行）

APP_DIR="/home/$(whoami)/sqlfluff-service"
WEB_PID_FILE="$APP_DIR/web.pid"
WORKER_PID_FILE="$APP_DIR/worker.pid"
ALERT_EMAIL="admin@example.com"
LOG_FILE="$APP_DIR/logs/monitor.log"

# 检查Web服务
if [ -f "$WEB_PID_FILE" ]; then
    WEB_PID=$(cat "$WEB_PID_FILE")
    if ! ps -p "$WEB_PID" > /dev/null 2>&1; then
        echo "$(date): Web服务崩溃，尝试重启" >> "$LOG_FILE"
        bash "$APP_DIR/scripts/start_web.sh"
        echo "Web服务已崩溃并自动重启" | mail -s "SQLFluff Web服务告警" "$ALERT_EMAIL" 2>/dev/null
    fi
fi

# 检查Worker服务
if [ -f "$WORKER_PID_FILE" ]; then
    WORKER_PID=$(cat "$WORKER_PID_FILE")
    if ! ps -p "$WORKER_PID" > /dev/null 2>&1; then
        echo "$(date): Worker服务崩溃，尝试重启" >> "$LOG_FILE"
        bash "$APP_DIR/scripts/start_worker.sh"
        echo "Worker服务已崩溃并自动重启" | mail -s "SQLFluff Worker服务告警" "$ALERT_EMAIL" 2>/dev/null
    fi
fi

# 检查磁盘空间
DISK_USAGE=$(df "$APP_DIR" | awk 'NR==2 {print $5}' | sed 's/%//')
if [ "$DISK_USAGE" -gt 85 ]; then
    echo "$(date): 磁盘使用率过高: ${DISK_USAGE}%" >> "$LOG_FILE"
    echo "警告: SQLFluff服务器磁盘使用率已达 ${DISK_USAGE}%" | mail -s "SQLFluff磁盘空间告警" "$ALERT_EMAIL" 2>/dev/null
fi

# 清理旧日志（保留最近7天）
find "$APP_DIR/logs" -name "*.log" -mtime +7 -delete
```

设置定时任务：
```bash
# 编辑crontab
crontab -e

# 添加以下内容（每5分钟检查一次）
*/5 * * * * /home/$(whoami)/sqlfluff-service/scripts/monitor.sh
```

## 九、安全建议

1. **使用SSH密钥认证**而不是密码
2. **限制部署脚本的执行权限**
3. **对上传的包进行校验**（MD5/SHA256）
4. **定期清理旧的备份和日志**
5. **敏感配置使用环境变量**，不要打包到代码中

## 十、常见问题

**Q: 如何查看服务占用的端口？**
```bash
# 查看Web服务端口
lsof -i -P -n | grep gunicorn
lsof -i -P -n | grep uvicorn

# 查看所有Python进程端口
lsof -i -P -n | grep python

# 查看特定端口
lsof -i :8000
```

**Q: 如何查看Celery任务队列状态？**
```bash
# 进入项目目录
cd ~/sqlfluff-service/current
source ~/sqlfluff-service/venv/bin/activate

# 查看活跃Worker
celery -A app.celery_app.celery_main:celery_app inspect active

# 查看队列任务数量
celery -A app.celery_app.celery_main:celery_app inspect active_queues

# 查看Worker统计信息
celery -A app.celery_app.celery_main:celery_app inspect stats
```

**Q: 如何限制服务的资源使用？**
```bash
# 在启动脚本中使用 ulimit
ulimit -m 2097152  # 限制内存 2GB
ulimit -t 7200     # CPU时间限制
ulimit -n 4096     # 文件描述符限制

# 或者使用systemd服务限制资源
```

**Q: 如何实现零停机部署？**
对于SQLFluff服务，可以：
1. 部署多个Web实例，使用Nginx做负载均衡
2. Worker服务可以滚动更新（逐台重启）
3. 使用蓝绿部署策略

**Q: 数据库连接失败怎么办？**
```bash
# 检查数据库连接
mysql -h $MYSQL_DATABASE_HOST -P $MYSQL_DATABASE_PORT -u $MYSQL_DATABASE_USERNAME -p

# 检查网络连通性
telnet $MYSQL_DATABASE_HOST $MYSQL_DATABASE_PORT

# 查看数据库相关日志
grep -i mysql ~/sqlfluff-service/logs/*.log
```

**Q: Redis连接失败怎么办？**
```bash
# 测试Redis连接
redis-cli -h $REDIS_HOST -p $REDIS_PORT ping

# 如果有密码
REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli -h $REDIS_HOST -p $REDIS_PORT ping

# 查看Redis相关日志
grep -i redis ~/sqlfluff-service/logs/*.log
```

**Q: 环境变量未正确加载怎么办？**
```bash
# 检查环境变量是否在.bashrc中
grep -A 30 "SQLFluff服务环境变量" ~/.bashrc

# 手动重新加载
source ~/.bashrc

# 运行环境变量检查脚本
~/sqlfluff-service/scripts/check_env.sh

# 如果还有问题，检查shell类型
echo $SHELL
# 如果不是bash，可能需要编辑相应的配置文件如 ~/.zshrc
```

**Q: Python模块找不到怎么办？**
```bash
# 检查Python路径
echo $PYTHONPATH
which python
which gunicorn
which celery

# 检查当前目录
pwd
ls -la

# 确保在正确目录启动服务
cd ~/sqlfluff-service/current
```

---

## 附录：完整的项目结构示例

最终，你的SQLFluff服务项目结构应该是这样的：

```
开发机:
sqlfluff-service/
├── app/                   # 应用代码
│   ├── api/              # FastAPI路由
│   ├── celery_app/       # Celery配置和任务
│   ├── core/             # 核心组件
│   ├── models/           # 数据模型
│   ├── services/         # 业务服务
│   ├── web_main.py       # Web入口
│   └── worker_main.py    # Worker入口
├── scripts/              # 运维脚本
│   ├── start_web.sh
│   ├── start_worker.sh
│   └── prepare_offline_deployment.sh
├── alembic/              # 数据库迁移
├── local_wheels/         # 本地wheel包
├── requirements.txt
├── deploy/              # 部署脚本
│   ├── package.sh       # 打包脚本
│   ├── deploy.sh        # 部署脚本
│   └── quick_deploy.sh  # 一键部署
└── releases/            # 发布包
    └── release_20241230_143022.tar.gz

服务器:
~/sqlfluff-service/
├── current/            # 当前运行的代码
│   ├── app/             # 应用代码
│   ├── scripts/         # 运维脚本
│   ├── alembic/         # 数据库迁移
│   ├── requirements.txt
│   └── version.json     # 版本信息
├── backups/           # 历史版本备份
│   └── backup_20241230_142000/
├── releases/          # 上传的发布包
│   └── release_20241230_143022.tar.gz
├── logs/              # 应用日志
│   ├── web_20241230.log
│   ├── worker_20241230.log
│   └── monitor.log
├── config/            # 配置文件（已弃用）
├── scripts/           # 管理脚本
│   ├── deploy.sh
│   ├── start_web.sh
│   ├── start_worker.sh
│   ├── stop_web.sh
│   ├── stop_worker.sh
│   ├── status.sh
│   └── monitor.sh
├── web.pid            # Web服务PID
└── worker.pid         # Worker服务PID
```

这样就可以实现SQLFluff分布式服务的优雅部署了！

## 总结

本部署指南针对SQLFluff服务的实际架构以及堡垒机环境限制进行了优化，包括：

1. **双服务架构**: Web服务和Worker服务分离部署
2. **环境配置管理**: 基于~/.bashrc的环境变量配置
3. **简化部署**: 无venv、无pip install、无数据库迁移
4. **堡垒机适配**: 无SSH/SCP依赖，支持手动文件上传
5. **服务监控**: 完整的服务状态检查和监控
6. **故障恢复**: 支持版本回滚和服务重启
7. **部署说明**: 自动生成详细的部署指导文档
8. **环境检查**: 自动化的环境变量验证

### 核心优势

- **适用堡垒机环境**: 不依赖SSH/SCP，支持多种文件传输方式
- **简化依赖管理**: 无需venv和pip install，使用预配置Python环境
- **配置统一管理**: 环境变量集中在~/.bashrc，便于维护
- **流程标准化**: 从打包到部署的完整流程规范
- **操作简化**: 一键准备脚本，自动生成部署说明
- **错误处理**: 完善的环境检查和回滚机制
- **企业友好**: 符合企业内网安全要求

### 适用场景

- **堡垒机环境**: 无法直接SSH/SCP的受限网络环境
- **预配置环境**: Python环境已由运维团队统一配置
- **手动数据库管理**: 数据库变更由DBA团队负责
- **简化运维**: 减少部署过程中的依赖安装步骤

遵循本指南可以在受限环境下实现稳定、可靠的SQLFluff分布式服务部署。