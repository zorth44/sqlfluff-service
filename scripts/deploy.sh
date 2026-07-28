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
echo -e "${YELLOW}[1/5] 停止当前服务...${NC}"
bash "$APP_DIR/scripts/stop_web.sh"
bash "$APP_DIR/scripts/stop_worker.sh"

# 2. 备份当前版本
if [ -d "$CURRENT_DIR" ]; then
    echo -e "${YELLOW}[2/5] 备份当前版本...${NC}"
    BACKUP_NAME="backup_$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$BACKUP_DIR"
    cp -r "$CURRENT_DIR" "$BACKUP_DIR/$BACKUP_NAME"
    
    # 只保留最近5个备份
    cd "$BACKUP_DIR"
    ls -t | tail -n +6 | xargs -r rm -rf
    cd - > /dev/null
else
    echo -e "${YELLOW}[2/5] 跳过备份（首次部署）${NC}"
fi

# 3. 解压新版本
echo -e "${YELLOW}[3/5] 解压新版本...${NC}"
rm -rf "$CURRENT_DIR"
mkdir -p "$CURRENT_DIR"
tar xzf "$PACKAGE_PATH" -C "$CURRENT_DIR"

# 4. 检查环境变量
echo -e "${YELLOW}[4/5] 检查环境变量...${NC}"
# 新版本已解压到 current，使用包内脚本以确保启动逻辑与应用版本同步。
bash "$CURRENT_DIR/scripts/check_env.sh"
if [ $? -ne 0 ]; then
    echo -e "${RED}环境变量检查失败，请检查 ~/.bashrc 配置${NC}"
    exit 1
fi

# 5. 启动服务
echo -e "${YELLOW}[5/5] 启动服务...${NC}"
# 启动Web服务
bash "$CURRENT_DIR/scripts/start_web_new.sh"
# 启动Worker服务  
bash "$CURRENT_DIR/scripts/start_worker_new.sh"

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
