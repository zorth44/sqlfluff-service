# 阶段四：FastAPI Web服务开发

## 项目概述

本项目是SQL核验服务系统，通过FastAPI提供HTTP接口，接收SQL核验请求并返回分析结果。系统支持单SQL文件和ZIP包两种提交模式，通过Celery进行异步任务处理。

FastAPI服务职责：
- 接收和验证客户端请求
- 调用业务逻辑层处理请求
- 向Celery派发异步任务
- 提供查询接口返回处理结果
- 注册到Consul进行服务发现

## 前置状态（前三阶段已完成）

### 阶段一、二、三完成项目
- ✅ 项目基础架构（配置、日志、异常处理）
- ✅ 数据库层（连接管理、数据模型、迁移系统）
- ✅ 业务逻辑层（Job服务、Task服务、SQLFluff集成、文件处理）
- ✅ 核心业务功能可以独立使用和测试

## 本阶段目标
实现面向客户端的FastAPI Web服务，包括API路由、依赖注入、错误处理、服务注册等功能，将业务逻辑层封装为HTTP接口。

## 本阶段任务清单

### 任务4.1：API路由实现
**目标**：实现完整的HTTP API接口

**具体工作**：
1. 创建`app/api/routes/jobs.py`，实现Job相关接口：

```python
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.services.job_service import JobService
from app.schemas.job import JobCreateRequest, JobCreateResponse, JobResponse

router = APIRouter()

@router.post("/jobs", response_model=JobCreateResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_job(
    request: JobCreateRequest,
    db: Session = Depends(get_db)
):
    """创建新的核验工作"""
    # 验证请求参数
    # 调用JobService创建工作
    # 派发Celery任务
    # 返回job_id

@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    page: int = 1,
    size: int = 10,
    db: Session = Depends(get_db)
):
    """查询核验工作状态与详情"""
    # 验证job_id格式
    # 调用JobService查询
    # 返回Job信息及Tasks分页列表
```

2. 创建`app/api/routes/tasks.py`，实现Task相关接口：

```python
@router.get("/tasks/{task_id}/result")
async def get_task_result(
    task_id: str,
    db: Session = Depends(get_db)
):
    """获取单个文件任务的详细结果"""
    # 验证task_id
    # 检查任务状态
    # 从NFS读取结果文件
    # 返回JSON结果
```

3. 创建`app/api/routes/health.py`，实现健康检查：

```python
@router.get("/health")
async def health_check():
    """健康检查接口"""
    # 检查数据库连接
    # 检查Redis连接
    # 检查NFS挂载
    # 返回系统状态
```

**验收标准**：
- 所有API接口按照规约正确实现
- 请求参数验证完整，错误处理规范
- 接口响应格式符合API规约
- 状态码使用正确

### 任务4.2：依赖注入和中间件
**目标**：实现依赖注入系统和请求处理中间件

**具体工作**：
1. 创建`app/api/deps.py`，实现依赖注入：

```python
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.services.job_service import JobService
from app.services.task_service import TaskService

def get_job_service(db: Session = Depends(get_db)) -> JobService:
    """获取Job服务实例"""
    return JobService(db)

def get_task_service(db: Session = Depends(get_db)) -> TaskService:
    """获取Task服务实例"""
    return TaskService(db)

def validate_job_id(job_id: str) -> str:
    """验证job_id格式"""
    # UUID格式验证
    # 返回验证后的job_id

def validate_task_id(task_id: str) -> str:
    """验证task_id格式"""
    # UUID格式验证
    # 返回验证后的task_id
```

2. 实现请求处理中间件：
   - 请求ID生成和追踪
   - 请求响应时间记录
   - 统一错误处理
   - 请求日志记录

3. 配置CORS和安全中间件：
   - 跨域请求支持
   - 请求大小限制
   - 超时设置

**验收标准**：
- 依赖注入系统工作正常
- 中间件功能完整，请求处理流程顺畅
- 错误处理统一，日志记录详细
- 安全配置合理

### 任务4.3：FastAPI应用配置
**目标**：创建和配置FastAPI主应用

**具体工作**：
1. 完善`app/web_main.py`，创建FastAPI应用：

```python
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.api.routes import jobs, tasks, health
from app.core.config import settings
from app.core.logging import setup_logging
from app.core.exceptions import BusinessException

def create_app() -> FastAPI:
    """创建FastAPI应用"""
    app = FastAPI(
        title="SQL核验服务",
        description="提供SQL文件质量检查服务",
        version="1.0.0",
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None
    )
    
    # 配置中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_HOSTS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # 注册路由
    app.include_router(jobs.router, prefix="/api/v1", tags=["jobs"])
    app.include_router(tasks.router, prefix="/api/v1", tags=["tasks"])
    app.include_router(health.router, prefix="/api/v1", tags=["health"])
    
    # 全局异常处理器
    @app.exception_handler(BusinessException)
    async def business_exception_handler(request: Request, exc: BusinessException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail}
        )
    
    # 启动和关闭事件
    @app.on_event("startup")
    async def startup_event():
        # 初始化日志
        setup_logging()
        # 注册到Consul
        await register_to_consul()
    
    @app.on_event("shutdown")
    async def shutdown_event():
        # 从Consul注销
        await deregister_from_consul()
    
    return app

app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

2. 集成Celery任务派发：
   - 在路由中调用Celery任务
   - 处理任务派发失败的情况
   - 任务ID的生成和管理

**验收标准**：
- FastAPI应用可以正常启动
- 所有路由正确注册，接口可以访问
- 全局异常处理工作正常
- 应用配置合理，支持开发和生产环境

### 任务4.4：服务注册和发现
**目标**：集成Consul服务注册和发现

**具体工作**：
1. 创建`app/core/consul.py`，实现Consul集成：

```python
import consul
from app.core.config import settings
from app.core.logging import logger

class ConsulClient:
    def __init__(self):
        self.consul = consul.Consul(
            host=settings.CONSUL_HOST,
            port=settings.CONSUL_PORT
        )
        self.service_id = f"sql-linting-service-{settings.SERVICE_ID}"
        
    async def register_service(self):
        """注册服务到Consul"""
        try:
            self.consul.agent.service.register(
                name="sql-linting-service",
                service_id=self.service_id,
                address=settings.SERVICE_HOST,
                port=settings.SERVICE_PORT,
                check=consul.Check.http(
                    url=f"http://{settings.SERVICE_HOST}:{settings.SERVICE_PORT}/api/v1/health",
                    interval="10s",
                    timeout="5s"
                )
            )
            logger.info(f"Service registered to Consul: {self.service_id}")
        except Exception as e:
            logger.error(f"Failed to register service to Consul: {e}")
            
    async def deregister_service(self):
        """从Consul注销服务"""
        try:
            self.consul.agent.service.deregister(self.service_id)
            logger.info(f"Service deregistered from Consul: {self.service_id}")
        except Exception as e:
            logger.error(f"Failed to deregister service from Consul: {e}")

consul_client = ConsulClient()

async def register_to_consul():
    """注册到Consul"""
    await consul_client.register_service()

async def deregister_from_consul():
    """从Consul注销"""
    await consul_client.deregister_service()
```

2. 配置健康检查端点：
   - 实现详细的健康检查逻辑
   - 检查依赖服务状态（数据库、Redis、NFS）
   - 返回服务健康状态信息

3. 支持服务发现配置：
   - 支持多实例部署
   - 服务元数据配置
   - 负载均衡兼容性

**验收标准**：
- 服务可以正确注册到Consul
- 健康检查端点正常工作
- 服务注销功能正常
- 支持多实例部署和负载均衡

### 任务4.5：Celery任务派发集成
**目标**：在FastAPI中集成Celery任务派发

**具体工作**：
1. 在路由中集成Celery任务调用：

```python
from app.celery_app.tasks import expand_zip_and_dispatch_tasks, process_sql_file

@router.post("/jobs", response_model=JobCreateResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_job(
    request: JobCreateRequest,
    db: Session = Depends(get_db)
):
    # 创建Job记录
    job_service = JobService(db)
    job_id = await job_service.create_job(request)
    
    # 根据提交类型派发不同的任务
    if request.sql_content:
        # 单SQL文件：直接派发process_sql_file任务
        task_id = await job_service.create_single_task(job_id, "single_sql.sql")
        process_sql_file.delay(task_id)
    elif request.zip_file_path:
        # ZIP包：派发expand_zip_and_dispatch_tasks任务
        expand_zip_and_dispatch_tasks.delay(job_id)
    
    return JobCreateResponse(job_id=job_id)
```

2. 任务状态追踪：
   - 实现任务状态的实时查询
   - 处理任务失败的情况
   - 提供任务重试机制

**验收标准**：
- Celery任务可以正确派发
- 任务状态追踪正常
- 错误处理机制完善

## 本阶段完成标志
- [ ] 所有API接口实现完整，符合规约要求
- [ ] 依赖注入和中间件系统工作正常
- [ ] FastAPI应用可以正常启动和运行
- [ ] 服务注册到Consul成功，健康检查正常
- [ ] Celery任务派发集成完成
- [ ] 接口文档自动生成，可通过/docs访问
- [ ] 错误处理统一，日志记录完整
- [ ] 支持并发请求处理

## 下一阶段预告
**阶段五：Celery Worker后台任务处理**
- 实现Celery应用配置和初始化
- 开发expand_zip_and_dispatch_tasks任务（ZIP解压）
- 开发process_sql_file任务（SQL文件分析）
- 实现任务状态更新和错误处理
- 配置Worker启动和管理

完成本阶段后，我们将拥有完整的FastAPI Web服务，可以接收客户端请求，调用业务逻辑，派发异步任务，并提供查询接口。Web服务将能够独立运行并提供HTTP API。 