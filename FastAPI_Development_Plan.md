# SQL核验服务整体开发计划

## 项目概述
基于README.md文档，我们需要开发一个完整的SQL核验系统，包含FastAPI Web服务和Celery Worker后台任务处理。两个服务共享数据库、配置、工具等基础组件，通过Redis进行异步通信。

## 项目架构和目录结构

```
sqlfluff-service/
├── app/
│   ├── __init__.py
│   ├── web_main.py                  # FastAPI Web服务启动入口
│   ├── worker_main.py               # Celery Worker服务启动入口
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py              # 统一配置管理
│   ├── models/
│   │   ├── __init__.py
│   │   └── database.py              # SQLAlchemy数据库模型
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── job.py                   # Job相关的Pydantic模型
│   │   ├── task.py                  # Task相关的Pydantic模型
│   │   └── common.py                # 通用数据模型
│   ├── services/
│   │   ├── __init__.py
│   │   ├── job_service.py           # Job业务逻辑
│   │   ├── task_service.py          # Task业务逻辑
│   │   └── sqlfluff_service.py      # SQLFluff处理逻辑
│   ├── api/
│   │   ├── __init__.py
│   │   ├── deps.py                  # 依赖注入
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── jobs.py              # Job相关路由
│   │       ├── tasks.py             # Task相关路由
│   │       └── health.py            # 健康检查路由
│   ├── core/
│   │   ├── __init__.py
│   │   ├── database.py              # 数据库连接和会话管理
│   │   ├── exceptions.py            # 自定义异常
│   │   ├── logging.py               # 日志配置
│   │   └── consul.py                # Consul服务注册
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── file_utils.py            # 文件操作工具
│   │   └── uuid_utils.py            # UUID工具
│   └── celery_app/
│       ├── __init__.py
│       ├── celery_main.py           # Celery应用配置
│       └── tasks.py                 # Celery任务定义
├── alembic/                         # 数据库版本管理和迁移
│   ├── versions/                    # 存放数据库变更历史
│   ├── alembic.ini                  # Alembic配置文件
│   ├── env.py                       # 迁移环境配置
│   └── script.py.mako               # 迁移脚本模板
├── tests/                           # 测试文件
├── scripts/                         # 启动和部署脚本
│   ├── start_web.py                 # FastAPI服务启动脚本
│   ├── start_worker.py              # Celery Worker启动脚本
│   └── init_db.py                   # 数据库初始化脚本
└── requirements.txt
```

## 关于两个服务入口的说明

### FastAPI Web服务入口 (`app/web_main.py`)
- 负责启动FastAPI应用
- 处理HTTP请求和响应
- 向Celery派发异步任务
- 服务注册到Consul

### Celery Worker服务入口 (`app/worker_main.py`)  
- 负责启动Celery Worker进程
- 从Redis队列获取并执行任务
- 处理SQL文件分析和ZIP解压
- 更新数据库中的任务状态

启动命令将会是：
- **启动Web服务**: `python -m app.web_main` 或 `gunicorn app.web_main:app`
- **启动Worker服务**: `python -m app.worker_main` 或 `celery -A app.celery_app.celery_main worker`

## 部署架构说明

### 服务部署的灵活性

这两个服务**不需要在同一台服务器上**，可以根据业务需要灵活部署：

#### 部署选项一：单机部署（小规模/开发环境）
```
服务器A:
├── FastAPI Web服务 (端口8000)
├── Celery Worker服务
├── Redis (端口6379)
├── MySQL (端口3306)
└── NFS共享目录 (/mnt/nfs_share)
```

**优点**：部署简单，资源集中
**适用场景**：开发环境、测试环境、小规模生产环境

#### 部署选项二：分布式部署（推荐生产环境）
```
Web服务器集群:
服务器A: FastAPI Web服务 (8000) + NFS挂载
服务器B: FastAPI Web服务 (8000) + NFS挂载
└── 通过负载均衡器对外提供服务

Worker服务器集群:
服务器C: Celery Worker × 4进程 + NFS挂载
服务器D: Celery Worker × 4进程 + NFS挂载
└── 自动从Redis获取任务

基础设施服务器:
服务器E: Redis集群
服务器F: MySQL主从
服务器G: NFS存储服务器
服务器H: Consul集群
```

**优点**：高可用、可扩展、性能更好
**适用场景**：生产环境

#### 部署选项三：混合部署
```
服务器A: FastAPI Web服务 + Celery Worker (少量)
服务器B: FastAPI Web服务 + Celery Worker (少量)  
服务器C: 专门的Celery Worker集群
服务器D: 专门的Celery Worker集群
```

### 服务间通信架构

两个服务通过以下方式通信，支持分布式部署：

1. **异步任务通信**：
   - FastAPI通过**Redis**向Celery派发任务
   - 支持跨服务器通信

2. **数据共享**：
   - 通过**MySQL数据库**共享任务状态和元数据
   - 支持远程数据库连接

3. **文件共享**：
   - 通过**NFS共享目录**共享文件
   - 所有服务器必须挂载同一个NFS目录

4. **服务发现**：
   - FastAPI服务通过**Consul**注册，支持多实例
   - Worker服务无需注册（后台服务）

### 部署要求和约束

#### 必须满足的约束：
1. **NFS挂载路径一致**：所有运行FastAPI或Worker的服务器都必须将NFS挂载到相同路径
2. **环境变量一致**：数据库连接、Redis连接、NFS路径等配置必须一致
3. **网络连通性**：所有服务器能访问MySQL、Redis、NFS、Consul

#### 推荐的部署配置：
1. **FastAPI服务**：
   - 可部署多个实例（负载均衡）
   - 每个实例注册到Consul
   - 建议CPU密集型服务器

2. **Celery Worker服务**：
   - 可部署多个Worker进程
   - 根据任务量动态扩缩容
   - 建议内存和IO密集型的服务器

### 扩容策略

#### Web服务扩容：
```bash
# 新增Web服务器时
1. 部署代码到新服务器
2. 挂载NFS到相同路径  
3. 配置相同的环境变量
4. 启动FastAPI服务
5. 服务自动注册到Consul
6. 负载均衡器自动发现新实例
```

#### Worker服务扩容：
```bash
# 新增Worker服务器时
1. 部署代码到新服务器
2. 挂载NFS到相同路径
3. 配置相同的环境变量  
4. 启动多个Celery Worker进程
5. Worker自动连接Redis获取任务
```

### 启动脚本示例

考虑到分布式部署，我们会提供不同场景的启动脚本：

```bash
# scripts/start_web_cluster.sh - Web服务集群启动
#!/bin/bash
gunicorn app.web_main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000

# scripts/start_worker_cluster.sh - Worker集群启动  
#!/bin/bash
celery -A app.celery_app.celery_main worker --loglevel=INFO -c 4 --hostname=worker@%h
```

这样的架构设计使得系统既可以简单部署（单机），也可以灵活扩展（分布式），满足不同规模和场景的需求。

## 分布式并发问题分析与解决方案

### 潜在的并发问题

在分布式部署环境下，确实会遇到并发问题

### 行业标准解决方案

#### 1. 任务唯一执行：Redis分布式锁
```python
@celery_app.task(bind=True)
def process_sql_file(self, task_id: str):
    # 使用Redis分布式锁确保任务唯一执行
    lock_key = f"task_lock:{task_id}"
    
    with redis_client.lock(lock_key, timeout=300):
        # 检查任务状态，确保幂等性
        task = get_task_by_id(task_id)
        if task.status in ['SUCCESS', 'IN_PROGRESS']:
            logger.info(f"Task {task_id} already processed")
            return task.result_file_path
            
        # 执行任务处理逻辑
        try:
            task.status = 'IN_PROGRESS'
            result = process_sql_content(task.source_file_path)
            task.status = 'SUCCESS'
            task.result_file_path = result
        except Exception as e:
            task.status = 'FAILURE'
            task.error_message = str(e)
            raise
```

#### 2. Celery配置优化
```python
# celery_main.py - 标准生产配置
celery_app.conf.update(
    task_acks_late=True,           # 任务完成后才确认
    worker_prefetch_multiplier=1,  # 限制预取，避免任务堆积
    task_max_retries=3,           # 失败重试次数
    task_default_retry_delay=60,   # 重试间隔
)
```


## 开发阶段划分

### 阶段一：基础设施和共享组件搭建
**目标**: 建立两个服务共享的基础设施和通用组件
**开发重点**: 为FastAPI和Celery Worker提供统一的基础支撑

#### 步骤1.1：项目结构和依赖管理
**包含内容**:
- 创建完整的目录结构
- 更新requirements.txt，添加所有依赖
- 设置基本的__init__.py文件
- 创建两个服务的启动入口文件

**关键文件**:
- `requirements.txt` - 完整依赖列表
- `app/web_main.py` - FastAPI服务入口
- `app/worker_main.py` - Celery Worker入口
- 各级目录的`__init__.py`

#### 步骤1.2：统一配置管理
**包含内容**:
- 创建基于环境变量的配置系统
- 支持不同环境(dev/test/prod)的配置
- 数据库、Redis、NFS、Consul等配置项
- 配置验证和默认值设置

**关键文件**:
- `app/config/settings.py` - 配置管理核心

#### 步骤1.3：日志和异常处理系统
**包含内容**:
- 结构化日志配置，支持JSON格式输出
- 统一的异常处理类
- 日志级别和格式配置
- 错误码定义和管理

**关键文件**:
- `app/core/logging.py` - 日志配置
- `app/core/exceptions.py` - 异常定义

#### 步骤1.4：工具类和通用函数
**包含内容**:
- UUID生成和管理工具
- 文件操作工具类
- 时间处理工具
- 通用验证函数

**关键文件**:
- `app/utils/uuid_utils.py` - UUID工具
- `app/utils/file_utils.py` - 文件工具

### 阶段二：数据库层和数据模型
**目标**: 建立数据持久化层，为两个服务提供统一的数据访问
**开发重点**: 数据库连接、模型定义、迁移管理

#### 步骤2.1：数据库连接和会话管理
**包含内容**:
- SQLAlchemy引擎配置
- 数据库会话管理
- 连接池配置
- 事务管理封装

**关键文件**:
- `app/core/database.py` - 数据库核心

#### 步骤2.2：数据模型定义
**包含内容**:
- `linting_jobs`表模型定义
- `linting_tasks`表模型定义
- 模型关系定义
- 索引和约束设置

**关键文件**:
- `app/models/database.py` - SQLAlchemy模型

#### 步骤2.3：数据库迁移设置
**包含内容**:
- Alembic配置和初始化
- 创建初始迁移文件（包含linting_jobs和linting_tasks表的CREATE语句）
- 迁移脚本编写
- 数据库初始化脚本

**关键文件**:
- `alembic/` - 迁移相关文件
- `scripts/init_db.py` - 数据库初始化
- 初始迁移文件：`alembic/versions/001_create_initial_tables.py`

#### 步骤2.4：API数据模型定义
**包含内容**:
- Pydantic模型定义
- 请求和响应模型
- 数据验证规则
- 分页和通用响应模型

**关键文件**:
- `app/schemas/job.py` - Job数据模型
- `app/schemas/task.py` - Task数据模型
- `app/schemas/common.py` - 通用模型

### 阶段三：核心业务逻辑层
**目标**: 实现核心业务逻辑，为Web服务和Worker提供统一的业务接口
**开发重点**: 业务服务层、SQLFluff集成、文件处理

#### 步骤3.1：Job业务服务
**包含内容**:
- Job创建、查询、更新逻辑
- Job状态管理
- Job与Task的关联管理
- 分页查询实现

**关键文件**:
- `app/services/job_service.py` - Job业务逻辑

#### 步骤3.2：Task业务服务
**包含内容**:
- Task创建、查询、更新逻辑
- Task状态流转管理
- 批量Task处理
- 结果文件管理

**关键文件**:
- `app/services/task_service.py` - Task业务逻辑

#### 步骤3.3：SQLFluff集成服务
**包含内容**:
- SQLFluff配置和初始化
- SQL文件分析处理
- 结果格式化和存储
- 错误处理和日志记录

**关键文件**:
- `app/services/sqlfluff_service.py` - SQLFluff处理

#### 步骤3.4：文件处理服务
**包含内容**:
- NFS文件操作封装
- ZIP包解压和处理
- 临时文件管理
- 文件路径生成和管理

**关键文件**:
- `app/utils/file_utils.py` - 文件操作工具（扩展）

### 阶段四：FastAPI Web服务开发
**目标**: 实现面向客户端的Web API服务
**开发重点**: API路由、依赖注入、错误处理

#### 步骤4.1：API路由实现
**包含内容**:
- `POST /jobs` - 创建核验工作
- `GET /jobs/{job_id}` - 查询工作状态
- `GET /tasks/{task_id}/result` - 获取任务结果
- `GET /health` - 健康检查

**关键文件**:
- `app/api/routes/jobs.py` - Job路由
- `app/api/routes/tasks.py` - Task路由
- `app/api/routes/health.py` - 健康检查

#### 步骤4.2：依赖注入和中间件
**包含内容**:
- 数据库会话依赖注入
- 请求响应中间件
- CORS配置
- 请求日志记录

**关键文件**:
- `app/api/deps.py` - 依赖注入

#### 步骤4.3：FastAPI应用配置
**包含内容**:
- FastAPI应用创建和配置
- 路由注册
- 全局异常处理器
- 启动和关闭事件处理

**关键文件**:
- `app/web_main.py` - FastAPI主应用入口

#### 步骤4.4：服务注册和发现
**包含内容**:
- Consul客户端集成
- 服务自动注册
- 健康检查端点
- 服务发现配置

**关键文件**:
- `app/core/consul.py` - Consul集成

### 阶段五：Celery Worker后台任务处理
**目标**: 实现异步任务处理系统
**开发重点**: Celery配置、任务定义、任务执行逻辑

#### 步骤5.1：Celery应用配置
**包含内容**:
- Celery应用初始化
- Redis broker配置
- 任务路由配置
- 错误处理和重试策略

**关键文件**:
- `app/celery_app/celery_main.py` - Celery配置

#### 步骤5.2：核心任务实现
**包含内容**:
- `expand_zip_and_dispatch_tasks` - ZIP解压任务
- `process_sql_file` - SQL文件处理任务
- 任务状态更新和错误处理
- 任务结果存储

**关键文件**:
- `app/celery_app/tasks.py` - 任务定义

#### 步骤5.3：Worker启动和管理
**包含内容**:
- Worker启动脚本
- Worker监控和健康检查
- 资源清理和优雅关闭
- 并发控制

**关键文件**:
- `app/worker_main.py` - Worker启动入口
- `scripts/start_worker.py` - Worker启动脚本

#### 步骤5.4：FastAPI与Celery集成
**包含内容**:
- 任务派发接口
- 任务状态查询
- 异步结果处理
- 错误传播机制

**关键文件**:
- 在相关服务中集成Celery调用

### 阶段六：集成测试和部署优化
**目标**: 确保系统整体稳定运行，优化部署和运维
**开发重点**: 测试、监控、部署脚本

#### 步骤6.1：单元测试和集成测试
**包含内容**:
- 服务层单元测试
- API集成测试
- Celery任务测试
- 数据库操作测试

**关键文件**:
- `tests/` - 测试文件目录

#### 步骤6.2：启动脚本和部署配置
**包含内容**:
- FastAPI启动脚本
- Celery Worker启动脚本
- 环境部署脚本
- 数据库迁移脚本

**关键文件**:
- `scripts/start_web.py` - Web服务启动脚本
- `scripts/start_worker.py` - Worker启动脚本

#### 步骤6.3：监控和日志优化
**包含内容**:
- 性能监控集成
- 日志聚合配置
- 错误告警设置
- 健康检查完善

#### 步骤6.4：文档和部署指南
**包含内容**:
- API文档生成
- 部署指南编写
- 配置说明文档
- 故障排查指南

## 开发里程碑

- **里程碑1**（阶段一、二完成）：基础设施就绪，数据库可用
- **里程碑2**（阶段三完成）：核心业务逻辑完成，可进行单元测试
- **里程碑3**（阶段四完成）：FastAPI服务可独立运行和测试
- **里程碑4**（阶段五完成）：完整系统集成，可进行端到端测试
- **里程碑5**（阶段六完成）：生产就绪，可部署上线

## 开发注意事项

1. **共享组件优先**：优先开发两个服务共用的组件，避免重复开发
2. **依赖关系清晰**：严格按阶段顺序开发，确保依赖关系正确
3. **配置统一管理**：所有配置通过环境变量统一管理
4. **错误处理完善**：每个层次都要有完善的错误处理机制
5. **日志记录详细**：关键操作都要有详细的日志记录
6. **测试驱动开发**：关键功能要有对应的测试用例
7. **性能考虑**：注意数据库查询优化和文件操作效率
8. **数据库迁移管理**：所有数据库结构变更都通过Alembic管理

## 下一步行动
请确认这个整合后的开发计划是否符合你的预期。如果确认无误，我们将从阶段一开始，逐步进行开发。 