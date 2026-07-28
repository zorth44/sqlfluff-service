# 环境变量配置说明

本文档说明了SQL核验服务所需的环境变量配置。

## 必需的环境变量

### 数据库配置
```bash
# MySQL数据库连接字符串
DATABASE_URL=mysql+pymysql://username:password@host:port/database_name

# 示例
DATABASE_URL=mysql+pymysql://zorth:password@gz-cdb-5k5lx4bt.sql.tencentcdb.com:23728/sql_linting
```

### Redis配置
```bash
# 单节点Redis配置
REDIS_HOST=your-redis-host
REDIS_PORT=6379
REDIS_USERNAME=your-redis-username  # 可选，如果Redis需要用户名认证
REDIS_PASSWORD=your-redis-password  # Redis密码
REDIS_DB_BROKER=0                   # Celery消息代理使用的数据库
REDIS_DB_RESULT=1                   # Celery结果后端使用的数据库

# 示例（单节点）
REDIS_HOST=47.116.196.61
REDIS_PORT=27493
REDIS_PASSWORD=your_redis_password
REDIS_DB_BROKER=0
REDIS_DB_RESULT=1

# Redis集群配置（解决cross-slot问题）
REDIS_CLUSTER_ENABLED=true                                    # 启用Redis集群模式
REDIS_CLUSTER_NODES=node1:6379,node2:6379,node3:6379         # 集群节点列表
REDIS_CLUSTER_KEY_PREFIX={celery}:                            # 键前缀，解决cross-slot问题

# 示例（集群）
REDIS_CLUSTER_ENABLED=true
REDIS_CLUSTER_NODES=redis-cluster-node1:6379,redis-cluster-node2:6379,redis-cluster-node3:6379
REDIS_CLUSTER_KEY_PREFIX={celery}:
```

### NFS共享目录配置
```bash
# NFS共享目录路径
NFS_SHARE_ROOT_PATH=/Users/zorth/Code/ai/python/temp

# 示例
NFS_SHARE_ROOT_PATH=/Users/zorth/Code/ai/python/temp
```

## 可选的环境变量

### 基础配置
```bash
ENVIRONMENT=dev                     # 运行环境: dev/test/prod
DEBUG=true                         # 调试模式
```

### Consul服务发现
```bash
CONSUL_HOST=127.0.0.1
CONSUL_PORT=8500
CONSUL_SERVICE_NAME=sql-linting-service
CONSUL_SERVICE_PORT=8000
CONSUL_HEALTH_CHECK_INTERVAL=10s
```

### 日志配置
```bash
LOG_LEVEL=INFO                     # 日志级别
LOG_FORMAT=json                    # 日志格式: json/text
LOG_FILE_PATH=/var/log/sql-linting.log
LOG_FILE_BACKUP_COUNT=14           # 按日轮转后保留天数（进程内 gzip 压缩历史日志）
```

日志由服务进程内管理：每天午夜轮转当前文件为 `*.YYYY-MM-DD.gz`，并自动删除超过 `LOG_FILE_BACKUP_COUNT` 的历史文件。无需外挂 cron / cleanup 脚本。

### Web服务配置
```bash
WEB_HOST=0.0.0.0
WEB_PORT=8000
WEB_WORKERS=1
WEB_MAX_REQUEST_SIZE=16777216      # 16MB
```

### Celery Worker配置
```bash
CELERY_WORKER_CONCURRENCY=4
CELERY_WORKER_PREFETCH_MULTIPLIER=1
CELERY_TASK_ACKS_LATE=true
CELERY_TASK_REJECT_ON_WORKER_LOST=true
CELERY_TASK_MAX_RETRIES=3
CELERY_TASK_DEFAULT_RETRY_DELAY=60
```

### SQLFluff配置
```bash
SQLFLUFF_DIALECT=mysql
SQLFLUFF_CONFIG_PATH=/path/to/sqlfluff/config

# 实时 SQL 检查（单个 Web 进程）
REALTIME_SQL_MAX_CONCURRENCY=2
REALTIME_SQL_QUEUE_TIMEOUT=5
REALTIME_SQL_SOFT_TIMEOUT=30
REALTIME_SQL_HARD_TIMEOUT=35
```

### 文件处理配置
```bash
MAX_FILE_SIZE=52428800             # 50MB
MAX_ZIP_FILES=1000
TEMP_DIR_CLEANUP_INTERVAL=3600
```

## 设置环境变量

### 方法一：使用.env文件
创建项目根目录下的`.env`文件：
```bash
cp .env.example .env
# 编辑.env文件，填入实际配置值
```

### 方法二：系统环境变量
```bash
export DATABASE_URL="mysql+pymysql://username:password@host:port/database"
export REDIS_HOST="your-redis-host"
export REDIS_PASSWORD="your-redis-password"
export NFS_SHARE_ROOT_PATH="/mnt/nfs_share/sql_linting"
```

## 配置验证

使用以下命令验证配置：
```bash
# 检查数据库连接
python scripts/init_db.py --check

# 测试完整配置
python -c "from app.config.settings import get_settings; print('配置加载成功')"
```

## 环境特定配置

### 开发环境
```bash
ENVIRONMENT=dev
DEBUG=true
LOG_LEVEL=DEBUG
```

### 测试环境
```bash
ENVIRONMENT=test
DEBUG=false
LOG_LEVEL=INFO
```

### 生产环境
```bash
ENVIRONMENT=prod
DEBUG=false
LOG_LEVEL=WARNING
```

## 安全注意事项

1. **不要将敏感信息提交到版本控制系统**
2. **使用强密码和加密连接**
3. **定期轮换密码和密钥**
4. **限制数据库和Redis的网络访问**
5. **使用环境变量或安全的密钥管理系统**
