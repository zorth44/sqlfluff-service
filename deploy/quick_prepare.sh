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