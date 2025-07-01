# 阶段六：集成测试和部署优化

## 项目概述

本项目是SQL核验服务系统的最后阶段，主要完成整个系统的测试、部署配置和运维优化。此阶段将确保系统的稳定性、可靠性和可维护性，为生产环境部署做好准备。

在前五个阶段完成后，系统已具备完整的功能：
- FastAPI Web服务提供HTTP接口
- Celery Worker处理后台任务
- 完整的SQL核验业务流程
- 数据库存储和NFS文件管理

## 前置状态（前五阶段已完成）

### 已完成的完整系统
- ✅ 项目基础架构（配置、日志、异常处理、工具类）
- ✅ 数据库层（连接管理、数据模型、迁移系统）
- ✅ 业务逻辑层（Job服务、Task服务、SQLFluff集成、文件处理）
- ✅ FastAPI Web服务（API接口、依赖注入、Consul注册）
- ✅ Celery Worker（ZIP解压、SQL分析、任务管理）
- ✅ 完整的异步处理流程（Web服务 → Redis → Worker → 结果存储）

## 本阶段目标
完成系统的测试验证、部署配置、监控告警和运维文档，确保系统可以稳定运行在生产环境中。

## 本阶段任务清单

### 任务6.1：单元测试和集成测试
**目标**：建立完整的测试体系，确保代码质量和系统稳定性

**具体工作**：
1. 创建测试基础设施：

```python
# tests/conftest.py - 测试配置和fixtures
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from app.core.database import Base, get_db
from app.web_main import app
import tempfile
import os

# 测试数据库
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="session")
def test_db():
    """创建测试数据库"""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def db_session(test_db):
    """数据库会话fixture"""
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()

@pytest.fixture
def client(db_session):
    """测试客户端"""
    def override_get_db():
        try:
            yield db_session
        finally:
            db_session.close()
    
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
```

2. 创建业务逻辑层单元测试：

```python
# tests/services/test_job_service.py
import pytest
from app.services.job_service import JobService
from app.schemas.job import JobCreateRequest

class TestJobService:
    def test_create_single_sql_job(self, db_session):
        """测试创建单SQL工作"""
        job_service = JobService(db_session)
        request = JobCreateRequest(sql_content="SELECT * FROM users;")
        
        job_id = await job_service.create_job(request)
        
        assert job_id is not None
        job = await job_service.get_job_by_id(job_id)
        assert job.submission_type == "SINGLE_FILE"
        assert job.status == "ACCEPTED"
    
    def test_create_zip_job(self, db_session):
        """测试创建ZIP工作"""
        job_service = JobService(db_session)
        request = JobCreateRequest(zip_file_path="test.zip")
        
        job_id = await job_service.create_job(request)
        
        job = await job_service.get_job_by_id(job_id)
        assert job.submission_type == "ZIP_ARCHIVE"
        assert job.status == "ACCEPTED"
```

3. 创建API集成测试：

```python
# tests/api/test_jobs.py
import pytest
from fastapi.testclient import TestClient

class TestJobsAPI:
    def test_create_job_with_sql_content(self, client):
        """测试创建SQL工作API"""
        response = client.post(
            "/api/v1/jobs",
            json={"sql_content": "SELECT * FROM users;"}
        )
        
        assert response.status_code == 202
        data = response.json()
        assert "job_id" in data
        
    def test_get_job_status(self, client):
        """测试查询工作状态API"""
        # 先创建一个工作
        create_response = client.post(
            "/api/v1/jobs",
            json={"sql_content": "SELECT * FROM users;"}
        )
        job_id = create_response.json()["job_id"]
        
        # 查询工作状态
        response = client.get(f"/api/v1/jobs/{job_id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == job_id
        assert "job_status" in data
```

4. 创建Celery任务测试：

```python
# tests/celery_app/test_tasks.py
import pytest
from unittest.mock import patch, MagicMock
from app.celery_app.tasks import process_sql_file

class TestCeleryTasks:
    @patch('app.celery_app.tasks.SQLFluffService')
    @patch('app.celery_app.tasks.FileUtils')
    def test_process_sql_file_success(self, mock_file_utils, mock_sqlfluff):
        """测试SQL文件处理任务成功"""
        # 设置mock
        mock_sqlfluff.return_value.analyze_sql_file.return_value = {
            "violations": [],
            "summary": {"error_count": 0}
        }
        
        # 执行任务
        result = process_sql_file("test-task-id")
        
        # 验证结果
        assert result is not None
        mock_sqlfluff.return_value.analyze_sql_file.assert_called_once()
```

**验收标准**：
- 单元测试覆盖率达到80%以上
- 所有API接口都有对应的集成测试
- Celery任务有完整的单元测试
- 测试可以自动化运行，并生成报告

### 任务6.2：启动脚本和部署配置
**目标**：创建完整的启动脚本和部署配置文件

**具体工作**：
1. 创建Web服务启动脚本：

```bash
#!/bin/bash
# scripts/start_web.sh - Web服务启动脚本

set -e

# 环境变量检查
check_env_vars() {
    local required_vars=(
        "DATABASE_URL"
        "CELERY_BROKER_URL"
        "NFS_SHARE_ROOT_PATH"
        "CONSUL_HOST"
        "CONSUL_PORT"
    )
    
    for var in "${required_vars[@]}"; do
        if [[ -z "${!var}" ]]; then
            echo "Error: Environment variable $var is not set"
            exit 1
        fi
    done
}

# 数据库迁移
run_migrations() {
    echo "Running database migrations..."
    alembic upgrade head
}

# 启动Web服务
start_web_service() {
    echo "Starting FastAPI web service..."
    
    # 生产环境使用gunicorn
    if [[ "${ENVIRONMENT}" == "production" ]]; then
        gunicorn app.web_main:app \
            -w ${GUNICORN_WORKERS:-4} \
            -k uvicorn.workers.UvicornWorker \
            --bind 0.0.0.0:${PORT:-8000} \
            --access-logfile - \
            --error-logfile - \
            --log-level info
    else
        # 开发环境使用uvicorn
        uvicorn app.web_main:app \
            --host 0.0.0.0 \
            --port ${PORT:-8000} \
            --reload
    fi
}

main() {
    echo "Starting SQL Linting Web Service..."
    check_env_vars
    run_migrations
    start_web_service
}

main "$@"
```

2. 创建Worker服务启动脚本：

```bash
#!/bin/bash
# scripts/start_worker.sh - Worker服务启动脚本

set -e

# 环境变量检查
check_env_vars() {
    local required_vars=(
        "DATABASE_URL"
        "CELERY_BROKER_URL"
        "NFS_SHARE_ROOT_PATH"
    )
    
    for var in "${required_vars[@]}"; do
        if [[ -z "${!var}" ]]; then
            echo "Error: Environment variable $var is not set"
            exit 1
        fi
    done
}

# 启动Worker服务
start_worker_service() {
    echo "Starting Celery Worker service..."
    
    celery -A app.celery_app.celery_main worker \
        --loglevel=${CELERY_LOG_LEVEL:-INFO} \
        --concurrency=${CELERY_WORKER_CONCURRENCY:-4} \
        --hostname=worker@%h \
        --max-tasks-per-child=1000 \
        --prefetch-multiplier=1
}

main() {
    echo "Starting SQL Linting Worker Service..."
    check_env_vars
    start_worker_service
}

main "$@"
```

3. 创建Docker配置文件：

```dockerfile
# Dockerfile
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 创建非root用户
RUN useradd --create-home --shell /bin/bash app
RUN chown -R app:app /app
USER app

# 暴露端口
EXPOSE 8000

# 默认命令
CMD ["./scripts/start_web.sh"]
```

4. 创建docker-compose配置：

```yaml
# docker-compose.yml
version: '3.8'

services:
  web:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=mysql+pymysql://user:password@mysql:3306/sqlfluff
      - CELERY_BROKER_URL=redis://redis:6379/0
      - NFS_SHARE_ROOT_PATH=/mnt/nfs_share
    volumes:
      - nfs_share:/mnt/nfs_share
    depends_on:
      - mysql
      - redis
    command: ./scripts/start_web.sh

  worker:
    build: .
    environment:
      - DATABASE_URL=mysql+pymysql://user:password@mysql:3306/sqlfluff
      - CELERY_BROKER_URL=redis://redis:6379/0
      - NFS_SHARE_ROOT_PATH=/mnt/nfs_share
    volumes:
      - nfs_share:/mnt/nfs_share
    depends_on:
      - mysql
      - redis
    command: ./scripts/start_worker.sh

  mysql:
    image: mysql:8.0
    environment:
      - MYSQL_ROOT_PASSWORD=rootpassword
      - MYSQL_DATABASE=sqlfluff
      - MYSQL_USER=user
      - MYSQL_PASSWORD=password
    volumes:
      - mysql_data:/var/lib/mysql

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data

volumes:
  mysql_data:
  redis_data:
  nfs_share:
```

**验收标准**：
- 启动脚本可以正常启动服务
- Docker配置可以成功构建和运行
- docker-compose可以启动完整的服务栈
- 所有配置文件都有详细的注释和说明

### 任务6.3：监控和日志优化
**目标**：完善监控指标和日志聚合系统

**具体工作**：
1. 集成Prometheus监控：

```python
# app/core/metrics.py - 监控指标
from prometheus_client import Counter, Histogram, Gauge, start_http_server
import time

# 定义监控指标
job_counter = Counter('sql_linting_jobs_total', 'Total number of jobs', ['status'])
task_counter = Counter('sql_linting_tasks_total', 'Total number of tasks', ['status'])
request_duration = Histogram('sql_linting_request_duration_seconds', 'Request duration')
active_jobs = Gauge('sql_linting_active_jobs', 'Number of active jobs')

class MetricsMiddleware:
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        start_time = time.time()
        
        # 执行请求
        await self.app(scope, receive, send)
        
        # 记录请求时间
        duration = time.time() - start_time
        request_duration.observe(duration)

def start_metrics_server(port: int = 8001):
    """启动监控指标服务器"""
    start_http_server(port)
```

2. **Celery Worker监控API**：

```python
# app/api/routes/monitoring.py - Worker监控接口
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, Any, List
from datetime import datetime
import redis
import psutil
import os

from app.celery_app.celery_main import celery_app
from app.core.logging import api_logger
from app.config.settings import get_settings

router = APIRouter()
settings = get_settings()

@router.get("/monitoring/workers")
async def get_worker_status():
    """
    获取所有Worker的状态信息
    
    返回活跃Worker列表、状态和性能信息
    """
    try:
        # 使用Celery inspect获取Worker信息
        inspect = celery_app.control.inspect()
        
        # 获取活跃Worker列表
        active_workers = inspect.active()
        registered_tasks = inspect.registered()
        worker_stats = inspect.stats()
        
        # 组装Worker信息
        workers_info = []
        
        if active_workers:
            for worker_name, tasks in active_workers.items():
                worker_info = {
                    "worker_name": worker_name,
                    "status": "online",
                    "active_tasks": len(tasks),
                    "current_tasks": [
                        {
                            "task_id": task["id"],
                            "task_name": task["name"],
                            "args": task.get("args", []),
                            "kwargs": task.get("kwargs", {}),
                            "time_start": task.get("time_start")
                        }
                        for task in tasks
                    ]
                }
                
                # 添加Worker统计信息
                if worker_stats and worker_name in worker_stats:
                    stats = worker_stats[worker_name]
                    worker_info.update({
                        "total_tasks": stats.get("total", 0),
                        "pool_implementation": stats.get("pool", {}).get("implementation"),
                        "pool_processes": stats.get("pool", {}).get("processes"),
                        "rusage": stats.get("rusage", {})
                    })
                
                # 添加注册任务信息
                if registered_tasks and worker_name in registered_tasks:
                    worker_info["registered_tasks"] = registered_tasks[worker_name]
                
                workers_info.append(worker_info)
        
        # 获取队列信息
        queue_info = await get_queue_info()
        
        response = {
            "timestamp": datetime.utcnow().isoformat(),
            "total_workers": len(workers_info),
            "online_workers": len([w for w in workers_info if w["status"] == "online"]),
            "workers": workers_info,
            "queues": queue_info
        }
        
        api_logger.debug(f"Worker状态查询成功: {len(workers_info)}个Worker在线")
        return response
        
    except Exception as e:
        api_logger.error(f"获取Worker状态失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取Worker状态失败: {str(e)}"
        )

@router.get("/monitoring/queues")
async def get_queue_status():
    """
    获取Celery队列状态信息
    
    返回各个队列的任务数量和状态
    """
    try:
        queue_info = await get_queue_info()
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "queues": queue_info
        }
        
    except Exception as e:
        api_logger.error(f"获取队列状态失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取队列状态失败: {str(e)}"
        )

@router.get("/monitoring/workers/{worker_id}")
async def get_worker_detail(worker_id: str):
    """
    获取指定Worker的详细信息
    
    包括当前任务、资源使用情况等
    """
    try:
        inspect = celery_app.control.inspect([worker_id])
        
        # 获取Worker详细信息
        active_tasks = inspect.active()
        scheduled_tasks = inspect.scheduled()
        reserved_tasks = inspect.reserved()
        worker_stats = inspect.stats()
        
        if not active_tasks or worker_id not in active_tasks:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Worker {worker_id} 不存在或不在线"
            )
        
        worker_detail = {
            "worker_id": worker_id,
            "timestamp": datetime.utcnow().isoformat(),
            "status": "online",
            "active_tasks": active_tasks.get(worker_id, []),
            "scheduled_tasks": scheduled_tasks.get(worker_id, []),
            "reserved_tasks": reserved_tasks.get(worker_id, []),
            "stats": worker_stats.get(worker_id, {}) if worker_stats else {}
        }
        
        return worker_detail
        
    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"获取Worker详情失败: {worker_id}, 错误: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取Worker详情失败: {str(e)}"
        )

@router.post("/monitoring/workers/{worker_id}/control")
async def control_worker(worker_id: str, action: str):
    """
    控制Worker操作
    
    支持的操作：shutdown, pool_restart, reset_stats
    """
    try:
        control = celery_app.control
        
        if action == "shutdown":
            # 优雅关闭Worker
            response = control.broadcast('shutdown', destination=[worker_id])
        elif action == "pool_restart":
            # 重启Worker进程池
            response = control.broadcast('pool_restart', destination=[worker_id])
        elif action == "reset_stats":
            # 重置Worker统计信息
            inspect = celery_app.control.inspect([worker_id])
            response = inspect.memdump()
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"不支持的操作: {action}"
            )
        
        return {
            "worker_id": worker_id,
            "action": action,
            "timestamp": datetime.utcnow().isoformat(),
            "result": response
        }
        
    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"控制Worker失败: {worker_id}, 操作: {action}, 错误: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"控制Worker失败: {str(e)}"
        )

async def get_queue_info() -> List[Dict[str, Any]]:
    """获取队列信息"""
    try:
        # 连接Redis获取队列信息
        redis_client = redis.Redis.from_url(settings.CELERY_BROKER_URL)
        
        queues = [
            "celery",           # 默认队列
            "zip_processing",   # ZIP处理队列
            "sql_analysis"      # SQL分析队列
        ]
        
        queue_info = []
        for queue_name in queues:
            # 获取队列长度
            queue_length = redis_client.llen(queue_name)
            
            queue_info.append({
                "name": queue_name,
                "length": queue_length,
                "status": "active" if queue_length >= 0 else "inactive"
            })
        
        return queue_info
        
    except Exception as e:
        api_logger.error(f"获取队列信息失败: {e}")
        return []

@router.get("/monitoring/system")
async def get_system_metrics():
    """
    获取系统资源使用情况
    
    返回CPU、内存、磁盘等资源使用情况
    """
    try:
        # CPU使用率
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()
        
        # 内存使用情况
        memory = psutil.virtual_memory()
        
        # 磁盘使用情况
        disk_usage = psutil.disk_usage('/')
        
        # NFS存储使用情况
        nfs_usage = None
        if os.path.exists(settings.NFS_SHARE_ROOT_PATH):
            nfs_usage = psutil.disk_usage(settings.NFS_SHARE_ROOT_PATH)
        
        # 网络统计
        network_io = psutil.net_io_counters()
        
        # 进程信息
        current_process = psutil.Process()
        process_info = {
            "pid": current_process.pid,
            "cpu_percent": current_process.cpu_percent(),
            "memory_info": current_process.memory_info()._asdict(),
            "create_time": current_process.create_time()
        }
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "cpu": {
                "usage_percent": cpu_percent,
                "core_count": cpu_count
            },
            "memory": {
                "total": memory.total,
                "available": memory.available,
                "used": memory.used,
                "usage_percent": memory.percent
            },
            "disk": {
                "total": disk_usage.total,
                "used": disk_usage.used,
                "free": disk_usage.free,
                "usage_percent": (disk_usage.used / disk_usage.total) * 100
            },
            "nfs_storage": {
                "total": nfs_usage.total if nfs_usage else 0,
                "used": nfs_usage.used if nfs_usage else 0,
                "free": nfs_usage.free if nfs_usage else 0,
                "usage_percent": (nfs_usage.used / nfs_usage.total) * 100 if nfs_usage else 0
            } if nfs_usage else None,
            "network": {
                "bytes_sent": network_io.bytes_sent,
                "bytes_recv": network_io.bytes_recv,
                "packets_sent": network_io.packets_sent,
                "packets_recv": network_io.packets_recv
            },
            "process": process_info
        }
        
    except Exception as e:
        api_logger.error(f"获取系统指标失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取系统指标失败: {str(e)}"
        )
```

3. **Worker健康检查增强**：

```python
# app/api/routes/health.py - 增强Worker健康检查
@router.get("/health/workers")
async def workers_health_check():
    """
    Worker服务健康检查
    
    检查Worker服务的可用性和健康状态
    """
    try:
        health_status = {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "service": "celery-workers",
            "checks": {}
        }
        
        # 检查Celery连接
        try:
            inspect = celery_app.control.inspect()
            active_workers = inspect.active()
            
            if active_workers:
                worker_count = len(active_workers)
                health_status["checks"]["celery_workers"] = {
                    "status": "healthy",
                    "message": f"{worker_count}个Worker在线",
                    "worker_count": worker_count,
                    "workers": list(active_workers.keys())
                }
            else:
                health_status["checks"]["celery_workers"] = {
                    "status": "unhealthy",
                    "message": "没有可用的Worker",
                    "worker_count": 0
                }
                health_status["status"] = "unhealthy"
                
        except Exception as e:
            health_status["checks"]["celery_workers"] = {
                "status": "unhealthy",
                "message": f"Celery连接失败: {str(e)}"
            }
            health_status["status"] = "unhealthy"
        
        # 检查消息队列
        try:
            redis_client = redis.Redis.from_url(settings.CELERY_BROKER_URL)
            redis_client.ping()
            
            # 检查队列长度
            queue_lengths = {}
            for queue_name in ["celery", "zip_processing", "sql_analysis"]:
                queue_lengths[queue_name] = redis_client.llen(queue_name)
            
            health_status["checks"]["message_queues"] = {
                "status": "healthy",
                "message": "消息队列正常",
                "queue_lengths": queue_lengths
            }
            
        except Exception as e:
            health_status["checks"]["message_queues"] = {
                "status": "unhealthy",
                "message": f"消息队列连接失败: {str(e)}"
            }
            health_status["status"] = "unhealthy"
        
        # 检查任务处理能力
        try:
            # 可以发送一个测试任务来验证处理能力
            from app.celery_app.tasks import celery_app
            
            # 获取任务统计
            inspect = celery_app.control.inspect()
            stats = inspect.stats()
            
            total_processed = 0
            if stats:
                for worker_stats in stats.values():
                    total_processed += worker_stats.get('total', 0)
            
            health_status["checks"]["task_processing"] = {
                "status": "healthy",
                "message": "任务处理能力正常",
                "total_tasks_processed": total_processed
            }
            
        except Exception as e:
            health_status["checks"]["task_processing"] = {
                "status": "warning",
                "message": f"任务处理能力检查失败: {str(e)}"
            }
        
        return health_status
        
    except Exception as e:
        return {
            "status": "unhealthy",
            "timestamp": datetime.utcnow().isoformat(),
            "service": "celery-workers",
            "error": str(e)
        }
```

4. 配置结构化日志：

```python
# app/core/logging.py - 增强日志配置
import logging
import sys
from datetime import datetime
import json
from app.core.config import settings

class JSONFormatter(logging.Formatter):
    """JSON格式化器"""
    
    def format(self, record):
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # 添加额外字段
        if hasattr(record, 'job_id'):
            log_entry['job_id'] = record.job_id
        if hasattr(record, 'task_id'):
            log_entry['task_id'] = record.task_id
        if hasattr(record, 'user_id'):
            log_entry['user_id'] = record.user_id
            
        # 添加异常信息
        if record.exc_info:
            log_entry['exception'] = self.formatException(record.exc_info)
            
        return json.dumps(log_entry)

def setup_logging():
    """设置日志配置"""
    
    # 根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper()))
    
    # 清除现有处理器
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(JSONFormatter())
    root_logger.addHandler(console_handler)
    
    # 文件处理器（如果配置了）
    if settings.LOG_FILE:
        file_handler = logging.FileHandler(settings.LOG_FILE)
        file_handler.setFormatter(JSONFormatter())
        root_logger.addHandler(file_handler)
```

5. **在FastAPI主应用中注册监控路由**：

```python
# app/web_main.py - 注册监控路由
from app.api.routes import jobs, tasks, health, monitoring

app.include_router(jobs.router, prefix="/api/v1", tags=["jobs"])
app.include_router(tasks.router, prefix="/api/v1", tags=["tasks"])
app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(monitoring.router, prefix="/api/v1", tags=["monitoring"])
```

**验收标准**：
- Prometheus监控指标正常收集
- Worker监控API可以获取实时Worker状态
- 队列监控API可以查看任务队列情况
- Worker健康检查覆盖所有关键功能
- 日志格式统一，便于聚合和分析
- 监控指标可以用于告警和可视化

### 6. **监控仪表板配置**：

```python
# monitoring_dashboard.py - 简单的监控仪表板
import asyncio
import aiohttp
import json
from datetime import datetime
import time

class WorkerMonitoringDashboard:
    def __init__(self, base_url="http://localhost:8000"):
        self.base_url = base_url
    
    async def get_worker_status(self):
        """获取Worker状态"""
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.base_url}/api/v1/monitoring/workers") as response:
                return await response.json()
    
    async def get_system_metrics(self):
        """获取系统指标"""
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.base_url}/api/v1/monitoring/system") as response:
                return await response.json()
    
    async def get_health_status(self):
        """获取健康状态"""
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.base_url}/api/v1/health/workers") as response:
                return await response.json()
    
    def print_dashboard(self, worker_status, system_metrics, health_status):
        """打印仪表板"""
        print("\n" + "="*60)
        print(f"SQL Linting Service - Worker Dashboard")
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*60)
        
        # Worker状态
        print(f"\n📊 Worker Status:")
        print(f"  Total Workers: {worker_status.get('total_workers', 0)}")
        print(f"  Online Workers: {worker_status.get('online_workers', 0)}")
        
        for worker in worker_status.get('workers', []):
            print(f"  • {worker['worker_name']}: {worker['active_tasks']} active tasks")
        
        # 队列状态
        print(f"\n📦 Queue Status:")
        for queue in worker_status.get('queues', []):
            print(f"  • {queue['name']}: {queue['length']} tasks ({queue['status']})")
        
        # 系统资源
        print(f"\n💻 System Resources:")
        cpu = system_metrics.get('cpu', {})
        memory = system_metrics.get('memory', {})
        print(f"  CPU: {cpu.get('usage_percent', 0):.1f}% ({cpu.get('core_count', 0)} cores)")
        print(f"  Memory: {memory.get('usage_percent', 0):.1f}% ({memory.get('used', 0)//1048576}MB used)")
        
        # 健康状态
        print(f"\n🏥 Health Status:")
        overall_status = health_status.get('status', 'unknown')
        print(f"  Overall: {overall_status.upper()}")
        
        for check_name, check_info in health_status.get('checks', {}).items():
            status = check_info.get('status', 'unknown')
            message = check_info.get('message', '')
            print(f"  • {check_name}: {status.upper()} - {message}")
        
        print("="*60)
    
    async def run_dashboard(self, refresh_interval=30):
        """运行仪表板"""
        while True:
            try:
                # 获取所有监控数据
                worker_status = await self.get_worker_status()
                system_metrics = await self.get_system_metrics()
                health_status = await self.get_health_status()
                
                # 清屏并打印仪表板
                import os
                os.system('clear' if os.name == 'posix' else 'cls')
                self.print_dashboard(worker_status, system_metrics, health_status)
                
                # 等待刷新间隔
                await asyncio.sleep(refresh_interval)
                
            except Exception as e:
                print(f"Error updating dashboard: {e}")
                await asyncio.sleep(refresh_interval)

# 使用示例
async def main():
    dashboard = WorkerMonitoringDashboard()
    await dashboard.run_dashboard(refresh_interval=10)

if __name__ == "__main__":
    asyncio.run(main())
```

使用方法：
```bash
# 启动监控仪表板
python monitoring_dashboard.py
```

### 7. **Grafana集成配置**：

```yaml
# grafana-dashboard.json - Grafana仪表板配置
{
  "dashboard": {
    "title": "SQL Linting Service - Worker Monitoring",
    "panels": [
      {
        "title": "Worker Status",
        "type": "stat",
        "targets": [
          {
            "url": "http://localhost:8000/api/v1/monitoring/workers",
            "jsonPath": "$.online_workers"
          }
        ]
      },
      {
        "title": "Queue Length",
        "type": "graph",
        "targets": [
          {
            "url": "http://localhost:8000/api/v1/monitoring/queues",
            "jsonPath": "$.queues[*].length"
          }
        ]
      },
      {
        "title": "System Resources",
        "type": "graph",
        "targets": [
          {
            "url": "http://localhost:8000/api/v1/monitoring/system",
            "jsonPath": "$.cpu.usage_percent"
          }
        ]
      }
    ]
  }
}
```

### 任务6.4：部署文档和运维指南
**目标**：编写完整的部署文档和运维指南

**具体工作**：
1. 创建部署指南：

```markdown
# 部署指南

## 环境要求

### 硬件要求
- **Web服务器**: CPU 2核+, 内存 4GB+, 磁盘 20GB+
- **Worker服务器**: CPU 4核+, 内存 8GB+, 磁盘 50GB+
- **数据库服务器**: CPU 2核+, 内存 4GB+, 磁盘 100GB+

### 软件要求
- Python 3.11+
- MySQL 8.0+
- Redis 6.0+
- NFS服务器
- Consul 1.15+

## 部署步骤

### 1. 准备环境
```bash
# 安装Python依赖
pip install -r requirements.txt

# 配置环境变量
export DATABASE_URL="mysql+pymysql://user:password@host:port/database"
export CELERY_BROKER_URL="redis://host:port/0"
export NFS_SHARE_ROOT_PATH="/mnt/nfs_share"
```

### 2. 数据库初始化
```bash
# 运行数据库迁移
alembic upgrade head
```

### 3. 启动服务
```bash
# 启动Web服务
./scripts/start_web.sh

# 启动Worker服务
./scripts/start_worker.sh
```

## 运维监控

### 监控指标
- 请求响应时间
- 任务处理速度
- 错误率
- 资源使用情况

### Worker监控API
系统提供了完整的Worker监控API，用于实时监控Celery Worker的状态和性能：

#### 1. 获取所有Worker状态
```bash
curl http://localhost:8000/api/v1/monitoring/workers
```

响应示例：
```json
{
  "timestamp": "2025-01-27T10:30:00.123456",
  "total_workers": 2,
  "online_workers": 2,
  "workers": [
    {
      "worker_name": "worker@server1",
      "status": "online",
      "active_tasks": 3,
      "total_tasks": 150,
      "pool_processes": 4,
      "current_tasks": [
        {
          "task_id": "abc123",
          "task_name": "app.celery_app.tasks.process_sql_file",
          "time_start": 1640000000.0
        }
      ]
    }
  ],
  "queues": [
    {
      "name": "sql_analysis",
      "length": 5,
      "status": "active"
    }
  ]
}
```

#### 2. 获取特定Worker详情
```bash
curl http://localhost:8000/api/v1/monitoring/workers/worker@server1
```

#### 3. 获取队列状态
```bash
curl http://localhost:8000/api/v1/monitoring/queues
```

#### 4. 获取系统资源使用情况
```bash
curl http://localhost:8000/api/v1/monitoring/system
```

响应示例：
```json
{
  "timestamp": "2025-01-27T10:30:00.123456",
  "cpu": {
    "usage_percent": 45.2,
    "core_count": 8
  },
  "memory": {
    "total": 8589934592,
    "available": 4294967296,
    "used": 4294967296,
    "usage_percent": 50.0
  },
  "nfs_storage": {
    "total": 1073741824000,
    "used": 536870912000,
    "free": 536870912000,
    "usage_percent": 50.0
  }
}
```

#### 5. Worker健康检查
```bash
curl http://localhost:8000/api/v1/health/workers
```

### 告警设置建议
基于监控API数据，建议设置以下告警规则：

1. **Worker离线告警**：
   - 条件：online_workers < 1
   - 严重程度：Critical

2. **队列积压告警**：
   - 条件：队列长度 > 100
   - 严重程度：Warning

3. **系统资源告警**：
   - CPU使用率 > 80%：Warning
   - 内存使用率 > 85%：Warning
   - 磁盘使用率 > 90%：Critical

4. **任务处理异常告警**：
   - 任务失败率 > 10%：Warning
   - 任务平均处理时间 > 5分钟：Warning

### 日志位置
- Web服务日志: `/var/log/sqlfluff/web.log`
- Worker日志: `/var/log/sqlfluff/worker.log`
```

2. 创建故障排查文档：

```markdown
# 故障排查指南

## 常见问题

### 1. 服务启动失败
**症状**: 服务无法启动或立即退出
**排查步骤**:
1. 检查环境变量配置
2. 检查依赖服务状态（MySQL、Redis、NFS）
3. 检查日志文件
4. 验证网络连通性

### 2. 任务处理失败
**症状**: 任务状态一直为PENDING或FAILURE
**排查步骤**:
1. 检查Worker服务状态
2. 检查Redis连接
3. 检查SQL文件是否存在
4. 检查SQLFluff配置

### 3. Worker监控相关问题
**症状**: Worker监控API返回异常或Worker状态不正确
**排查步骤**:
1. 使用监控API检查Worker状态：
   ```bash
   curl http://localhost:8000/api/v1/monitoring/workers
   ```
2. 检查Worker进程是否正在运行：
   ```bash
   ps aux | grep celery
   ```
3. 检查Worker日志：
   ```bash
   tail -f /var/log/sqlfluff/worker.log
   ```
4. 检查消息队列状态：
   ```bash
   curl http://localhost:8000/api/v1/monitoring/queues
   ```
5. 验证Redis连接：
   ```bash
   redis-cli -u $CELERY_BROKER_URL ping
   ```

### 4. 队列积压问题
**症状**: 任务长时间排队，处理缓慢
**排查步骤**:
1. 检查队列长度：
   ```bash
   curl http://localhost:8000/api/v1/monitoring/queues
   ```
2. 检查Worker并发设置：
   ```bash
   # 调整Worker并发数
   export CELERY_WORKER_CONCURRENCY=8
   ```
3. 增加Worker实例：
   ```bash
   # 启动额外的Worker
   ./scripts/start_worker.sh &
   ```
4. 检查系统资源使用：
   ```bash
   curl http://localhost:8000/api/v1/monitoring/system
   ```

### 5. Worker性能问题
**症状**: Worker CPU或内存使用率过高
**排查步骤**:
1. 监控系统资源：
   ```bash
   curl http://localhost:8000/api/v1/monitoring/system
   ```
2. 检查单个Worker的任务负载：
   ```bash
   curl http://localhost:8000/api/v1/monitoring/workers/worker@hostname
   ```
3. 调整Worker配置：
   ```bash
   # 降低并发数
   export CELERY_WORKER_CONCURRENCY=2
   # 增加任务重启频率
   export CELERY_WORKER_MAX_TASKS_PER_CHILD=500
   ```
4. 检查是否有长时间运行的任务：
   - 查看active_tasks中的time_start时间戳
   - 考虑设置任务超时时间

### 6. Worker健康检查失败
**症状**: Worker健康检查接口返回unhealthy状态
**排查步骤**:
1. 检查Worker健康状态：
   ```bash
   curl http://localhost:8000/api/v1/health/workers
   ```
2. 根据返回的checks信息定位具体问题：
   - `celery_workers`: Worker连接问题
   - `message_queues`: Redis队列问题
   - `task_processing`: 任务处理能力问题
3. 重启相应的服务或组件

### 7. 性能问题
**症状**: 请求响应慢或任务处理缓慢
**排查步骤**:
1. 检查系统资源使用情况
2. 检查数据库性能
3. 调整Worker并发数
4. 检查NFS性能
5. 使用监控API持续观察性能指标
```

**验收标准**：
- 部署文档详细完整，可以按步骤成功部署
- 运维指南涵盖监控、日志、故障排查等关键内容
- 文档结构清晰，便于查阅和维护

### 任务6.5：性能测试和优化
**目标**：进行性能测试并优化系统性能

**具体工作**：
1. 创建性能测试脚本：

```python
# tests/performance/load_test.py
import asyncio
import aiohttp
import time
from concurrent.futures import ThreadPoolExecutor

async def create_job(session, sql_content):
    """创建一个核验工作"""
    async with session.post(
        "http://localhost:8000/api/v1/jobs",
        json={"sql_content": sql_content}
    ) as response:
        return await response.json()

async def load_test(concurrent_requests=10, total_requests=100):
    """负载测试"""
    async with aiohttp.ClientSession() as session:
        sql_content = "SELECT * FROM users WHERE id = 1;"
        
        start_time = time.time()
        
        # 创建任务
        tasks = []
        for i in range(total_requests):
            task = create_job(session, sql_content)
            tasks.append(task)
            
            # 控制并发数
            if len(tasks) >= concurrent_requests:
                await asyncio.gather(*tasks)
                tasks = []
        
        # 处理剩余任务
        if tasks:
            await asyncio.gather(*tasks)
        
        end_time = time.time()
        
        print(f"总请求数: {total_requests}")
        print(f"并发数: {concurrent_requests}")
        print(f"总耗时: {end_time - start_time:.2f}秒")
        print(f"QPS: {total_requests / (end_time - start_time):.2f}")

if __name__ == "__main__":
    asyncio.run(load_test())
```

2. 性能优化配置：

```python
# 数据库连接池优化
engine = create_engine(
    DATABASE_URL,
    pool_size=20,
    max_overflow=30,
    pool_pre_ping=True,
    pool_recycle=3600
)

# Redis连接池优化
redis_pool = redis.ConnectionPool.from_url(
    CELERY_BROKER_URL,
    max_connections=50
)

# Celery Worker优化
celery_app.conf.update(
    worker_prefetch_multiplier=1,
    task_max_retries=3,
    worker_max_tasks_per_child=1000,
    worker_concurrency=8  # 根据CPU核数调整
)
```

**验收标准**：
- 性能测试脚本可以正常运行
- 系统可以承受预期的并发负载
- 关键性能指标满足业务要求
- 优化配置已应用到生产环境

## 本阶段完成标志
- [ ] 单元测试和集成测试完整，覆盖率达标
- [ ] 启动脚本和部署配置完成并验证
- [ ] 监控和日志系统正常工作
- [ ] 部署文档和运维指南编写完成
- [ ] 性能测试通过，系统性能满足要求
- [ ] 完整的CI/CD流程配置（可选）
- [ ] 生产环境部署验证通过

## 项目总结
完成第六阶段后，SQL核验服务系统将完全满足生产环境的要求：

### 功能完整性
- ✅ 支持单SQL文件和ZIP包两种提交方式
- ✅ 完整的异步处理流程
- ✅ 基于SQLFluff的质量分析
- ✅ 结果文件管理和查询

### 系统可靠性
- ✅ 完善的错误处理和重试机制
- ✅ 分布式部署支持
- ✅ 数据库事务一致性
- ✅ 资源清理和内存管理

### 运维友好性
- ✅ 结构化日志和监控指标
- ✅ 健康检查和服务发现
- ✅ 完整的部署文档
- ✅ 故障排查指南

### 性能可扩展性
- ✅ 水平扩展支持
- ✅ 连接池和缓存优化
- ✅ 负载均衡兼容性
- ✅ 性能监控和调优

整个项目已经可以部署到生产环境，为客户提供稳定可靠的SQL核验服务。 