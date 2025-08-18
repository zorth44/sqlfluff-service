#!/bin/bash
# package.sh - 在开发机上打包项目

# 配置
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC_DIR="$PROJECT_DIR"
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
echo -e "\n${YELLOW}下一步: 执行部署准备命令${NC}"
echo "./deploy/prepare_deploy.sh $VERSION"