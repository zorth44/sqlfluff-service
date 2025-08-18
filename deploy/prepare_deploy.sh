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