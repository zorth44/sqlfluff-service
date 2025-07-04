#!/bin/bash
#
# 这是一个用于准备离线部署的脚本。
# 它会读取 requirements.txt 文件，并将所有依赖项下载到一个指定的目录中。

set -e

# 定义离线包存放的目录
OFFLINE_PACKAGES_DIR="./offline_packages"

# 创建存放离线包的目录
rm -rf "${OFFLINE_PACKAGES_DIR}"
mkdir -p "${OFFLINE_PACKAGES_DIR}"

# 定义目标平台信息 (请根据您的目标服务器修改)
TARGET_PLATFORM="manylinux2014_x86_64"
TARGET_PYTHON_VERSION="3.9"
TARGET_ABI="cp39"

# 1. 使用 pip-tools 解析完整的依赖树并生成 requirements-full.txt
#    这需要在有网络连接的环境中执行。如果未安装 pip-tools，请先运行: pip install pip-tools
echo "正在解析完整的依赖树并生成 requirements-full.txt..."
FULL_REQUIREMENTS_FILE="${OFFLINE_PACKAGES_DIR}/requirements-full.txt"
pip-compile --resolver=backtracking \
    --output-file "${FULL_REQUIREMENTS_FILE}" \
    requirements.txt

# 2. 根据完整的依赖列表下载所有依赖包
echo "正在为平台 ${TARGET_PLATFORM} 和 Python ${TARGET_PYTHON_VERSION} 下载所有依赖包..."
pip download \
    -r "${FULL_REQUIREMENTS_FILE}" \
    -d "${OFFLINE_PACKAGES_DIR}" \
    --platform "${TARGET_PLATFORM}" \
    --python-version "${TARGET_PYTHON_VERSION}" \
    --implementation cp \
    --abi "${TARGET_ABI}" \
    --only-binary=:all:

# 复制本地的 wheel 文件到离线包目录
echo "正在复制本地的 wheel 文件..."
cp ./local_wheels/*.whl "${OFFLINE_PACKAGES_DIR}/"

echo "离线依赖包准备完成！"
echo "请将整个项目目录（包括 'offline_packages' 文件夹）复制到您的目标服务器。"
echo "在目标服务器上，您可以使用以下命令进行安装："
echo "pip install --no-index --find-links=./offline_packages -r requirements.txt"