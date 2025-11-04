# 日志清理脚本使用指南

## 快速开始

### 1. 查看当前日志状态
```bash
bash scripts/cleanup_logs.sh --status
```

### 2. 预览清理效果（不实际执行）
```bash
bash scripts/cleanup_logs.sh --dry-run
```

### 3. 执行清理
```bash
bash scripts/cleanup_logs.sh
```

---

## 脚本功能

✅ **自动压缩旧日志** - 将2天前的日志文件压缩为 .gz 格式，节省80-90%磁盘空间
✅ **自动删除过期日志** - 删除14天前的压缩日志
✅ **超大文件检测** - 检测并警告超过500MB的日志文件
✅ **安全预览模式** - 可以先预览不执行，确保安全
✅ **详细清理报告** - 显示清理前后的日志状态对比

---

## 使用示例

### 基础使用

```bash
# 查看帮助
bash scripts/cleanup_logs.sh --help

# 查看当前日志状态（不执行清理）
bash scripts/cleanup_logs.sh --status

# 预览清理（安全，不实际执行）
bash scripts/cleanup_logs.sh --dry-run

# 执行清理（使用默认配置：保留14天，压缩2天前）
bash scripts/cleanup_logs.sh
```

### 自定义配置

```bash
# 保留30天的日志
bash scripts/cleanup_logs.sh --keep 30

# 1天前的日志就压缩
bash scripts/cleanup_logs.sh --compress 1

# 保留7天，1天前压缩
bash scripts/cleanup_logs.sh --keep 7 --compress 1
```

---

## 设置自动清理（推荐）

### 方式1: 使用 cron（推荐）

每天凌晨2点自动执行清理：

```bash
# 编辑 crontab
crontab -e

# 添加以下行（替换 <username> 为你的用户名）
0 2 * * * /home/<username>/sqlfluff-service/scripts/cleanup_logs.sh >> /home/<username>/sqlfluff-service/logs/cleanup.log 2>&1
```

**cron 时间说明：**
```
0 2 * * *  = 每天凌晨2点
0 4 * * 0  = 每周日凌晨4点
0 3 1 * *  = 每月1号凌晨3点
```

### 方式2: 使用 systemd timer（适合 systemd 系统）

创建 timer 文件：`/etc/systemd/system/sqlfluff-log-cleanup.timer`

```ini
[Unit]
Description=SQLFluff Service Log Cleanup Timer

[Timer]
OnCalendar=daily
OnCalendar=02:00
Persistent=true

[Install]
WantedBy=timers.target
```

创建 service 文件：`/etc/systemd/system/sqlfluff-log-cleanup.service`

```ini
[Unit]
Description=SQLFluff Service Log Cleanup

[Service]
Type=oneshot
User=<username>
ExecStart=/home/<username>/sqlfluff-service/scripts/cleanup_logs.sh
StandardOutput=append:/home/<username>/sqlfluff-service/logs/cleanup.log
StandardError=append:/home/<username>/sqlfluff-service/logs/cleanup.log
```

启用 timer：
```bash
sudo systemctl enable sqlfluff-log-cleanup.timer
sudo systemctl start sqlfluff-log-cleanup.timer
sudo systemctl status sqlfluff-log-cleanup.timer
```

---

## 配置说明

脚本顶部有配置区域，可以根据需要修改：

```bash
# 日志保留策略
KEEP_DAYS=14              # 保留14天的日志
COMPRESS_DAYS=2           # 2天前的日志进行压缩

# 最大日志文件大小检查 (单位: MB)
MAX_SINGLE_FILE_SIZE=500  # 单个文件超过500MB时警告
```

### 配置建议

**开发环境：**
```bash
KEEP_DAYS=7
COMPRESS_DAYS=1
```

**生产环境（低流量）：**
```bash
KEEP_DAYS=30
COMPRESS_DAYS=2
```

**生产环境（高流量）：**
```bash
KEEP_DAYS=14
COMPRESS_DAYS=1
```

---

## 清理效果示例

### 清理前
```
logs/
├── web_20250101.log     (500 MB)
├── web_20250102.log     (600 MB)
├── web_20250103.log     (550 MB)
├── web_20250104.log     (700 MB)
├── worker_20250101.log  (800 MB)
├── worker_20250102.log  (900 MB)
├── worker_20250103.log  (850 MB)
└── worker_20250104.log  (1000 MB)

总大小: 5.9 GB
```

### 清理后（KEEP_DAYS=14, COMPRESS_DAYS=2）
```
logs/
├── web_20250103.log        (550 MB) ← 今天
├── web_20250104.log        (700 MB) ← 昨天
├── web_20250102.log.gz     (60 MB)  ← 压缩
├── web_20250101.log.gz     (50 MB)  ← 压缩
├── worker_20250103.log     (850 MB) ← 今天
├── worker_20250104.log     (1000 MB) ← 昨天
├── worker_20250102.log.gz  (90 MB)  ← 压缩
└── worker_20250101.log.gz  (80 MB)  ← 压缩

总大小: 3.4 GB (节省 42%)
[14天前的压缩文件已删除]
```

---

## 故障排查

### 问题1: 脚本没有执行权限
```bash
chmod +x scripts/cleanup_logs.sh
```

### 问题2: 找不到日志目录
检查脚本中的 `APP_DIR` 和 `LOG_DIR` 配置是否正确。

### 问题3: cron 没有执行
```bash
# 查看 cron 日志
tail -f /var/log/cron
# 或
tail -f /var/log/syslog | grep CRON

# 检查 crontab 是否正确添加
crontab -l
```

### 问题4: 压缩失败
确保系统安装了 gzip：
```bash
which gzip
# 如果没有安装
sudo apt-get install gzip  # Debian/Ubuntu
sudo yum install gzip      # CentOS/RHEL
```

---

## 监控建议

### 1. 监控磁盘使用
```bash
# 检查日志目录大小
du -sh ~/sqlfluff-service/logs/

# 检查具体文件
du -h ~/sqlfluff-service/logs/*.log | sort -h | tail -10
```

### 2. 检查清理日志
```bash
# 查看自动清理的执行记录
tail -f ~/sqlfluff-service/logs/cleanup.log
```

### 3. 设置磁盘空间告警
```bash
# 在 cron 中添加磁盘检查
0 */6 * * * df -h | awk '$NF=="/"{if($5+0>80) print "Disk usage alert: " $5}'
```

---

## 配合 LOG_LEVEL 使用

**重要：日志清理只是治标，LOG_LEVEL 才是治本！**

### 推荐配置

在 `.env` 文件中：

```bash
# 开发环境
LOG_LEVEL=DEBUG
# 配合使用：KEEP_DAYS=3, COMPRESS_DAYS=1

# 测试环境
LOG_LEVEL=INFO
# 配合使用：KEEP_DAYS=7, COMPRESS_DAYS=2

# 生产环境
LOG_LEVEL=WARNING
# 配合使用：KEEP_DAYS=14, COMPRESS_DAYS=2
```

### 效果对比

| LOG_LEVEL | 每日日志大小（估算） | 14天总大小 |
|-----------|----------------------|-----------|
| DEBUG     | 500-1000 MB          | 7-14 GB   |
| INFO      | 100-300 MB           | 1.4-4.2 GB |
| WARNING   | 20-50 MB             | 280-700 MB |

---

## 完整的日志管理方案

### 1. 立即执行（现在）
```bash
# 修改 .env
LOG_LEVEL=INFO  # 或 WARNING

# 重启服务
bash scripts/deploy.sh <version>

# 手动清理一次旧日志
bash scripts/cleanup_logs.sh
```

### 2. 设置自动化（今天）
```bash
# 添加 cron 任务
crontab -e
# 添加: 0 2 * * * /home/<username>/sqlfluff-service/scripts/cleanup_logs.sh >> /home/<username>/sqlfluff-service/logs/cleanup.log 2>&1
```

### 3. 定期检查（每周）
```bash
# 每周一查看日志使用情况
bash scripts/cleanup_logs.sh --status

# 查看清理日志
tail -50 ~/sqlfluff-service/logs/cleanup.log
```

---

## 参考资源

- [Python logging 文档](https://docs.python.org/3/library/logging.html)
- [Cron 表达式生成器](https://crontab.guru/)
- [gzip 压缩工具](https://www.gnu.org/software/gzip/)

---

**最后提醒：先用 `--dry-run` 预览，确认无误后再执行实际清理！**
