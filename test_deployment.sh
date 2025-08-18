#!/bin/bash
# test_deployment.sh - 测试部署流程

echo "========== SQLFluff部署测试 =========="

# 检查必要的目录和文件
echo "检查项目结构..."
REQUIRED_DIRS=("deploy" "app" "scripts" "alembic" "local_wheels")
REQUIRED_FILES=("requirements.txt" "alembic.ini" "init_server.sh")

for dir in "${REQUIRED_DIRS[@]}"; do
    if [ -d "$dir" ]; then
        echo "✓ 目录存在: $dir"
    else
        echo "✗ 目录缺失: $dir"
        exit 1
    fi
done

for file in "${REQUIRED_FILES[@]}"; do
    if [ -f "$file" ]; then
        echo "✓ 文件存在: $file"
    else
        echo "✗ 文件缺失: $file"
        exit 1
    fi
done

# 检查部署脚本
echo ""
echo "检查部署脚本..."
DEPLOY_SCRIPTS=("deploy/package.sh" "deploy/prepare_deploy.sh" "deploy/quick_prepare.sh")

for script in "${DEPLOY_SCRIPTS[@]}"; do
    if [ -f "$script" ] && [ -x "$script" ]; then
        echo "✓ 脚本就绪: $script"
    else
        echo "✗ 脚本问题: $script"
        exit 1
    fi
done

# 检查服务器脚本
echo ""
echo "检查服务器脚本..."
SERVER_SCRIPTS=(
    "scripts/check_env.sh"
    "scripts/deploy.sh" 
    "scripts/start_web_new.sh"
    "scripts/start_worker_new.sh"
    "scripts/stop_web.sh"
    "scripts/stop_worker.sh"
    "scripts/status.sh"
    "scripts/rollback.sh"
)

for script in "${SERVER_SCRIPTS[@]}"; do
    if [ -f "$script" ] && [ -x "$script" ]; then
        echo "✓ 脚本就绪: $script"
    else
        echo "✗ 脚本问题: $script"
        exit 1
    fi
done

# 创建releases目录（如果不存在）
mkdir -p releases

echo ""
echo "========== 测试打包流程 =========="

# 测试打包脚本
TEST_VERSION="test_$(date +%Y%m%d_%H%M%S)"
echo "使用测试版本号: $TEST_VERSION"

if ./deploy/package.sh "$TEST_VERSION"; then
    echo "✓ 打包测试成功"
    
    # 检查生成的包
    if [ -f "releases/release_${TEST_VERSION}.tar.gz" ]; then
        echo "✓ 部署包已生成: releases/release_${TEST_VERSION}.tar.gz"
        
        # 显示包的大小
        PACKAGE_SIZE=$(ls -lh "releases/release_${TEST_VERSION}.tar.gz" | awk '{print $5}')
        echo "  包大小: $PACKAGE_SIZE"
        
        # 测试准备部署说明
        if ./deploy/prepare_deploy.sh "$TEST_VERSION"; then
            echo "✓ 部署说明生成成功"
            
            if [ -f "releases/deploy_instruction_${TEST_VERSION}.md" ]; then
                echo "✓ 部署说明文件已生成"
            else
                echo "✗ 部署说明文件缺失"
            fi
        else
            echo "✗ 部署说明生成失败"
        fi
    else
        echo "✗ 部署包生成失败"
        exit 1
    fi
else
    echo "✗ 打包测试失败"
    exit 1
fi

echo ""
echo "========== 部署测试完成 =========="
echo ""
echo "✓ 所有检查通过！"
echo ""
echo "下一步:"
echo "1. 运行 './deploy/quick_prepare.sh' 创建正式部署包"
echo "2. 手动上传包文件到服务器"
echo "3. 在服务器上运行部署脚本"
echo ""
echo "清理测试文件:"
echo "rm releases/release_${TEST_VERSION}.tar.gz"
echo "rm releases/deploy_instruction_${TEST_VERSION}.md"