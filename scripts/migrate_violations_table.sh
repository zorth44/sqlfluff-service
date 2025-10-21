#!/bin/bash
################################################################################
# Violations 表迁移脚本
################################################################################
# 用途: 通过执行SQL文件创建 linting_violations 表
# 使用: ./scripts/migrate_violations_table.sh
################################################################################

set -e  # 遇到错误立即退出

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 脚本目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SQL_FILE="$PROJECT_DIR/alembic/versions/abc123456789_create_linting_violations_table.sql"
SIMPLE_SQL_FILE="$PROJECT_DIR/alembic/versions/abc123456789_create_linting_violations_table_simple.sql"

echo -e "${BLUE}================================${NC}"
echo -e "${BLUE}  Violations 表迁移工具${NC}"
echo -e "${BLUE}================================${NC}\n"

# 检查SQL文件是否存在
if [ ! -f "$SQL_FILE" ]; then
    echo -e "${RED}❌ 错误: SQL文件不存在${NC}"
    echo "   路径: $SQL_FILE"
    exit 1
fi

# 获取数据库配置
echo -e "${YELLOW}请输入数据库配置:${NC}"

# 从环境变量或用户输入获取配置
if [ -z "$DB_HOST" ]; then
    read -p "数据库主机 (默认: localhost): " DB_HOST
    DB_HOST=${DB_HOST:-localhost}
fi

if [ -z "$DB_PORT" ]; then
    read -p "数据库端口 (默认: 3306): " DB_PORT
    DB_PORT=${DB_PORT:-3306}
fi

if [ -z "$DB_USER" ]; then
    read -p "数据库用户名: " DB_USER
fi

if [ -z "$DB_NAME" ]; then
    read -p "数据库名称: " DB_NAME
fi

# 数据库密码（不回显）
if [ -z "$DB_PASSWORD" ]; then
    read -s -p "数据库密码: " DB_PASSWORD
    echo
fi

# 确认信息
echo -e "\n${YELLOW}数据库配置:${NC}"
echo "  主机: $DB_HOST:$DB_PORT"
echo "  数据库: $DB_NAME"
echo "  用户: $DB_USER"

# 选择SQL文件版本
echo -e "\n${YELLOW}选择要执行的SQL文件:${NC}"
echo "  1) 完整版 (包含详细注释)"
echo "  2) 精简版 (纯SQL语句)"
read -p "请选择 [1/2] (默认: 2): " SQL_CHOICE
SQL_CHOICE=${SQL_CHOICE:-2}

if [ "$SQL_CHOICE" = "1" ]; then
    SELECTED_SQL_FILE="$SQL_FILE"
else
    SELECTED_SQL_FILE="$SIMPLE_SQL_FILE"
fi

echo -e "\n${BLUE}将执行: $(basename "$SELECTED_SQL_FILE")${NC}"

# 确认执行
read -p "确认执行？[y/N]: " CONFIRM
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}❌ 已取消${NC}"
    exit 0
fi

# 执行SQL
echo -e "\n${BLUE}正在执行SQL...${NC}"

# 构建mysql命令
MYSQL_CMD="mysql -h $DB_HOST -P $DB_PORT -u $DB_USER -p$DB_PASSWORD $DB_NAME"

# 执行SQL文件
if $MYSQL_CMD < "$SELECTED_SQL_FILE" 2>&1; then
    echo -e "\n${GREEN}✅ SQL执行成功！${NC}"
    
    # 验证表是否创建成功
    echo -e "\n${BLUE}验证表结构...${NC}"
    
    # 检查表是否存在
    TABLE_EXISTS=$($MYSQL_CMD -e "SHOW TABLES LIKE 'linting_violations';" -s -N 2>/dev/null | wc -l)
    
    if [ "$TABLE_EXISTS" -eq 1 ]; then
        echo -e "${GREEN}✅ 表 linting_violations 已创建${NC}"
        
        # 显示表结构
        echo -e "\n${BLUE}表结构:${NC}"
        $MYSQL_CMD -e "DESC linting_violations;" 2>/dev/null
        
        # 显示索引
        echo -e "\n${BLUE}索引信息:${NC}"
        $MYSQL_CMD -e "SHOW INDEX FROM linting_violations;" 2>/dev/null
        
        # 统计记录数
        RECORD_COUNT=$($MYSQL_CMD -e "SELECT COUNT(*) FROM linting_violations;" -s -N 2>/dev/null)
        echo -e "\n${BLUE}当前记录数: ${RECORD_COUNT}${NC}"
        
    else
        echo -e "${RED}❌ 表创建验证失败${NC}"
        exit 1
    fi
    
    # 更新 Alembic 版本（可选）
    echo -e "\n${YELLOW}是否更新 Alembic 版本记录？${NC}"
    echo "  (如果您使用 Alembic 管理迁移，建议更新)"
    read -p "更新？[y/N]: " UPDATE_ALEMBIC
    
    if [[ "$UPDATE_ALEMBIC" =~ ^[Yy]$ ]]; then
        echo "正在更新 Alembic 版本记录..."
        $MYSQL_CMD -e "INSERT IGNORE INTO alembic_version (version_num) VALUES ('abc123456789');" 2>/dev/null
        echo -e "${GREEN}✅ Alembic 版本已更新${NC}"
    fi
    
    # 完成
    echo -e "\n${GREEN}================================${NC}"
    echo -e "${GREEN}  ✅ 迁移完成！${NC}"
    echo -e "${GREEN}================================${NC}\n"
    
    echo -e "${YELLOW}下一步:${NC}"
    echo "  1. 重启应用服务"
    echo "  2. 测试API端点:"
    echo "     - GET /api/v1/jobs/{job_id}/violations"
    echo "     - GET /api/v1/jobs/{job_id}/statistics"
    echo "     - GET /api/v1/jobs/{job_id}/export/csv"
    echo ""
    
else
    echo -e "\n${RED}❌ SQL执行失败${NC}"
    echo "请检查:"
    echo "  1. 数据库连接信息是否正确"
    echo "  2. 用户是否有足够的权限"
    echo "  3. 数据库是否存在"
    exit 1
fi

