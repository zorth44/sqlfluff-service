# 阶段五：Celery Worker后台任务处理

## 项目概述

本项目是SQL核验服务系统的后台任务处理部分。Celery Worker负责执行实际的SQL分析工作，包括ZIP文件解压、SQL文件分析、结果文件生成等计算密集型任务。

Celery Worker职责：
- 从Redis队列获取异步任务
- 解压ZIP文件并批量创建子任务
- 使用SQLFluff分析SQL文件
- 更新数据库中的任务状态
- 保存分析结果到NFS共享目录

## 前置状态（前四阶段已完成）

### 已完成组件
- ✅ 项目基础架构（配置、日志、异常处理、工具类）
- ✅ 数据库层（连接管理、数据模型、迁移系统）
- ✅ 业务逻辑层（Job服务、Task服务、SQLFluff集成、文件处理）
- ✅ FastAPI Web服务（API接口、依赖注入、Consul注册）
- ✅ Web服务可以接收请求并派发Celery任务

## 本阶段目标
实现Celery Worker异步任务处理系统，执行实际的SQL分析工作，完成整个核验流程的后台处理部分。

## 本阶段任务清单

### 任务5.1：Celery应用配置
**目标**：创建和配置Celery应用，建立与Redis的连接

**具体工作**：
1. 创建`app/celery_app/celery_main.py`，配置Celery应用：

```python
from celery import Celery
from app.core.config import settings
from app.core.logging import setup_logging

# 创建Celery实例
celery_app = Celery(
    "sql_linting_worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=['app.celery_app.tasks']
)

# 配置Celery
celery_app.conf.update(
    # 任务序列化
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='Asia/Shanghai',
    enable_utc=True,
    
    # 任务确认和重试
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_max_retries=3,
    task_default_retry_delay=60,
    
    # 任务路由
    task_routes={
        'app.celery_app.tasks.expand_zip_and_dispatch_tasks': {'queue': 'zip_processing'},
        'app.celery_app.tasks.process_sql_file': {'queue': 'sql_analysis'},
    },
    
    # Worker配置
    worker_max_tasks_per_child=1000,
    worker_disable_rate_limits=False,
    
    # 结果存储
    result_expires=3600,
)

# 任务自动发现
celery_app.autodiscover_tasks(['app.celery_app'])

@celery_app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    """配置定期任务（如果需要）"""
    pass

if __name__ == '__main__':
    celery_app.start()
```

2. 配置生产环境优化：
   - 连接池配置
   - 任务超时设置
   - 内存使用优化
   - 并发控制

**验收标准**：
- Celery应用可以正常启动并连接Redis
- 配置参数合理，适合生产环境
- 任务队列和路由配置正确
- Worker可以正常接收和处理任务

### 任务5.2：ZIP解压和任务派发
**目标**：实现expand_zip_and_dispatch_tasks任务，处理ZIP文件

**具体工作**：
1. 在`app/celery_app/tasks.py`中实现ZIP处理任务：

```python
from celery import current_task
from sqlalchemy.orm import Session
from app.celery_app.celery_main import celery_app
from app.core.database import SessionLocal
from app.services.job_service import JobService
from app.services.task_service import TaskService
from app.utils.file_utils import FileUtils
from app.core.logging import logger
import os
import tempfile

@celery_app.task(bind=True)
def expand_zip_and_dispatch_tasks(self, job_id: str):
    """
    解压ZIP文件并为每个SQL文件创建处理任务
    Args:
        job_id: 核验工作ID
    """
    db = SessionLocal()
    try:
        # 获取Job信息
        job_service = JobService(db)
        job = await job_service.get_job_by_id(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        
        # 更新Job状态为PROCESSING
        await job_service.update_job_status(job_id, "PROCESSING")
        
        # 构建ZIP文件完整路径
        zip_full_path = FileUtils.get_full_path(job.source_path)
        
        # 创建临时解压目录
        with tempfile.TemporaryDirectory() as temp_dir:
            logger.info(f"Extracting ZIP file: {zip_full_path} to {temp_dir}")
            
            # 解压ZIP文件
            sql_files = FileUtils.extract_zip_file(zip_full_path, temp_dir)
            logger.info(f"Found {len(sql_files)} SQL files in ZIP")
            
            if not sql_files:
                await job_service.update_job_status(
                    job_id, "FAILED", 
                    "No SQL files found in ZIP archive"
                )
                return
            
            # 为每个SQL文件创建Task记录和处理任务
            task_service = TaskService(db)
            task_ids = []
            
            for sql_file_path in sql_files:
                # 生成目标文件路径
                relative_path = FileUtils.generate_job_file_path(job_id, os.path.basename(sql_file_path))
                target_path = FileUtils.get_full_path(relative_path)
                
                # 复制文件到标准位置
                FileUtils.copy_file(sql_file_path, target_path)
                
                # 创建Task记录
                task_id = await task_service.create_task(job_id, relative_path)
                task_ids.append(task_id)
                
                # 派发SQL文件处理任务
                process_sql_file.delay(task_id)
                
            logger.info(f"Dispatched {len(task_ids)} SQL processing tasks for job {job_id}")
            
    except Exception as e:
        logger.error(f"Failed to process ZIP file for job {job_id}: {e}")
        await job_service.update_job_status(job_id, "FAILED", str(e))
        raise
    finally:
        db.close()
```

2. 实现ZIP文件处理的错误处理：
   - ZIP文件损坏处理
   - 文件编码问题处理
   - 磁盘空间不足处理
   - 临时文件清理

**验收标准**：
- 可以正确解压ZIP文件
- 能够识别和提取所有SQL文件
- 为每个SQL文件正确创建任务记录
- 任务派发成功，状态更新正确
- 错误处理完善，临时文件清理正常

### 任务5.3：SQL文件分析任务
**目标**：实现process_sql_file任务，执行SQL质量分析

**具体工作**：
1. 实现SQL文件处理的核心任务：

```python
@celery_app.task(bind=True)
def process_sql_file(self, task_id: str):
    """
    处理单个SQL文件
    Args:
        task_id: 任务ID
    """
    db = SessionLocal()
    try:
        # 获取任务信息
        task_service = TaskService(db)
        task = await task_service.get_task_by_id(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")
        
        # 更新任务状态为IN_PROGRESS
        await task_service.update_task_status(task_id, "IN_PROGRESS")
        
        logger.info(f"Processing SQL file for task {task_id}: {task.source_file_path}")
        
        # 获取SQL文件完整路径
        sql_file_path = FileUtils.get_full_path(task.source_file_path)
        
        if not os.path.exists(sql_file_path):
            raise FileNotFoundError(f"SQL file not found: {sql_file_path}")
        
        # 使用SQLFluff分析SQL文件
        from app.services.sqlfluff_service import SQLFluffService
        sqlfluff_service = SQLFluffService()
        
        analysis_result = sqlfluff_service.analyze_sql_file(sql_file_path)
        
        # 生成结果文件路径
        result_file_path = FileUtils.generate_result_file_path(task.job_id, task_id)
        result_full_path = FileUtils.get_full_path(result_file_path)
        
        # 保存分析结果
        FileUtils.save_analysis_result(analysis_result, result_full_path)
        
        # 更新任务状态为SUCCESS
        await task_service.update_task_status(
            task_id, "SUCCESS", 
            result_file_path=result_file_path
        )
        
        logger.info(f"Successfully processed SQL file for task {task_id}")
        
        # 检查并更新父Job状态
        await update_job_status_based_on_tasks(task.job_id, db)
        
    except Exception as e:
        logger.error(f"Failed to process SQL file for task {task_id}: {e}")
        
        # 更新任务状态为FAILURE
        await task_service.update_task_status(
            task_id, "FAILURE", 
            error_message=str(e)
        )
        
        # 检查并更新父Job状态
        await update_job_status_based_on_tasks(task.job_id, db)
        
        raise
    finally:
        db.close()

async def update_job_status_based_on_tasks(job_id: str, db: Session):
    """根据子任务状态更新Job状态"""
    job_service = JobService(db)
    new_status = await job_service.calculate_job_status(job_id)
    await job_service.update_job_status(job_id, new_status)
```

2. 实现任务监控和进度追踪：
   - 任务进度更新
   - 性能指标收集
   - 资源使用监控

**验收标准**：
- 可以正确读取和分析SQL文件
- SQLFluff集成正常，分析结果准确
- 结果文件正确保存到NFS
- 任务状态更新及时准确
- 父Job状态自动更新逻辑正确

### 任务5.4：任务状态管理和错误处理
**目标**：完善任务的状态管理和错误处理机制

**具体工作**：
1. 实现分布式锁防止任务重复执行：

```python
import redis
from contextlib import contextmanager

redis_client = redis.Redis.from_url(settings.CELERY_BROKER_URL)

@contextmanager
def task_lock(task_id: str, timeout: int = 300):
    """任务执行锁"""
    lock_key = f"task_lock:{task_id}"
    lock = redis_client.lock(lock_key, timeout=timeout)
    
    try:
        if lock.acquire(blocking=False):
            yield
        else:
            raise Exception(f"Task {task_id} is already being processed")
    finally:
        try:
            lock.release()
        except:
            pass

# 在任务中使用锁
@celery_app.task(bind=True)
def process_sql_file(self, task_id: str):
    with task_lock(task_id):
        # 任务处理逻辑
        pass
```

2. 实现任务重试机制：
   - 自动重试失败任务
   - 指数退避重试策略
   - 最大重试次数限制

3. 任务超时处理：
   - 设置任务执行超时时间
   - 超时任务的状态更新
   - 资源清理机制

**验收标准**：
- 分布式锁正常工作，避免任务重复执行
- 重试机制配置合理，失败任务可以自动重试
- 超时处理机制完善
- 错误日志记录详细，便于问题排查

### 任务5.5：Worker启动和管理
**目标**：配置Worker启动脚本和进程管理

**具体工作**：
1. 完善`app/worker_main.py` Worker启动入口：

```python
import os
import sys
from app.celery_app.celery_main import celery_app
from app.core.config import settings
from app.core.logging import setup_logging

def main():
    """Worker主启动函数"""
    # 设置日志
    setup_logging()
    
    # 设置Worker参数
    worker_args = [
        'worker',
        '--loglevel=INFO',
        f'--concurrency={settings.CELERY_WORKER_CONCURRENCY}',
        '--prefetch-multiplier=1',
        '--max-tasks-per-child=1000',
        f'--hostname=worker@{settings.SERVICE_ID}',
    ]
    
    # 如果指定了队列，则只处理特定队列
    if settings.CELERY_WORKER_QUEUES:
        worker_args.extend(['--queues', settings.CELERY_WORKER_QUEUES])
    
    # 启动Worker
    celery_app.worker_main(worker_args)

if __name__ == '__main__':
    main()
```

2. 创建启动脚本`scripts/start_worker.py`：

```python
#!/usr/bin/env python3
import subprocess
import sys
import os

def start_worker():
    """启动Celery Worker"""
    
    # 环境变量检查
    required_vars = [
        'DATABASE_URL',
        'CELERY_BROKER_URL',
        'NFS_SHARE_ROOT_PATH'
    ]
    
    for var in required_vars:
        if not os.getenv(var):
            print(f"Error: Environment variable {var} is not set")
            sys.exit(1)
    
    # 启动Worker
    cmd = [
        'celery',
        '-A', 'app.celery_app.celery_main',
        'worker',
        '--loglevel=INFO',
        '--concurrency=4',
        '--hostname=worker@%h'
    ]
    
    print(f"Starting Celery Worker with command: {' '.join(cmd)}")
    subprocess.run(cmd)

if __name__ == '__main__':
    start_worker()
```

3. 实现Worker监控：
   - Worker健康状态检查
   - 任务处理统计
   - 性能指标监控

**验收标准**：
- Worker可以正常启动并连接到Redis
- 可以从队列中正确获取和处理任务
- Worker可以优雅关闭，正在处理的任务不会丢失
- 启动脚本工作正常，支持参数配置

## 本阶段完成标志
- [ ] Celery应用配置完成，可以正常启动
- [ ] expand_zip_and_dispatch_tasks任务实现完整
- [ ] process_sql_file任务实现完整
- [ ] 任务状态管理和错误处理机制完善
- [ ] Worker启动脚本和管理功能正常
- [ ] 分布式锁和重试机制工作正常
- [ ] 任务执行日志记录完整
- [ ] 与FastAPI Web服务的集成测试通过

## 下一阶段预告
**阶段六：集成测试和部署优化**
- 编写完整的单元测试和集成测试
- 创建启动脚本和部署配置
- 完善监控和日志聚合
- 编写部署文档和运维指南
- 性能测试和优化

完成本阶段后，我们将拥有完整的Celery Worker系统，可以处理ZIP解压、SQL分析等后台任务，与FastAPI Web服务配合形成完整的异步处理流程。整个SQL核验服务的核心功能将全部完成。 