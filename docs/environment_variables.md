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
# Redis服务器配置
REDIS_HOST=your-redis-host
REDIS_PORT=6379
REDIS_USERNAME=your-redis-username  # 可选，如果Redis需要用户名认证
REDIS_PASSWORD=your-redis-password  # Redis密码
REDIS_DB_BROKER=0                   # Celery消息代理使用的数据库
REDIS_DB_RESULT=1                   # Celery结果后端使用的数据库

# 示例
REDIS_HOST=47.116.196.61
REDIS_PORT=27493
REDIS_PASSWORD=your_redis_password
REDIS_DB_BROKER=0
REDIS_DB_RESULT=1
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
LOG_FILE_MAX_SIZE=100MB
LOG_FILE_BACKUP_COUNT=5
```

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

### 方法三：Docker环境变量
```yaml
# docker-compose.yml
environment:
  - DATABASE_URL=mysql+pymysql://username:password@host:port/database
  - REDIS_HOST=your-redis-host
  - REDIS_PASSWORD=your-redis-password
  - NFS_SHARE_ROOT_PATH=/mnt/nfs_share/sql_linting
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