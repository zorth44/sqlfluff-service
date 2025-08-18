#!/bin/bash
# rollback.sh - 回滚脚本

APP_DIR="/home/$(whoami)/sqlfluff-service"
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
bash "$APP_DIR/scripts/stop_web.sh"
bash "$APP_DIR/scripts/stop_worker.sh"

# 恢复备份
rm -rf "$CURRENT_DIR"
cp -r "$BACKUP_DIR/$LATEST_BACKUP" "$CURRENT_DIR"

# 启动服务
bash "$APP_DIR/scripts/start_web_new.sh"
bash "$APP_DIR/scripts/start_worker_new.sh"

echo "回滚完成"