# 阶段一：基础设施和共享组件搭建

## 项目概述

本项目是一个SQL核验服务系统，提供对SQL文件的自动化质量检查功能。系统采用分布式架构设计：

### 核心组件
- **FastAPI Web服务**：面向客户端的HTTP API服务，负责接收核验请求
- **Celery Worker**：后台任务处理引擎，执行实际的SQL分析工作
- **Redis**：消息队列，FastAPI与Celery之间的异步通信桥梁
- **MySQL**：持久化存储，保存核验工作和任务的元数据
- **NFS共享目录**：文件存储中心，存放SQL文件和分析结果
- **SQLFluff**：核心分析引擎，执行SQL质量检查

### 支持的工作流
1. **单SQL提交**：客户端直接提交SQL内容进行分析
2. **ZIP包提交**：客户端提交包含多个SQL文件的压缩包进行批量分析

## 前置状态
- 项目刚开始，仅有基本的项目文件（main.py, requirements.txt等）
- 需要从零开始构建完整的项目架构

## 本阶段目标
建立两个服务（FastAPI Web服务和Celery Worker）共享的基础设施和通用组件，为后续开发提供统一的基础支撑。

## 本阶段任务清单

### 任务1.1：项目结构和依赖管理
**目标**：建立完整的项目目录结构和依赖管理

**具体工作**：
1. 创建完整的目录结构：
```
sqlfluff-service/
├── app/
│   ├── __init__.py
│   ├── web_main.py                  # FastAPI服务启动入口
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
├── tests/                           # 测试文件
├── scripts/                         # 启动和部署脚本
└── requirements.txt
```

2. 更新requirements.txt，添加所有必需依赖：
```txt
# Web框架
fastapi==0.104.1
uvicorn[standard]==0.24.0
gunicorn==21.2.0

# 任务队列
celery==5.3.4
redis==5.0.1

# 数据库
sqlalchemy==2.0.23
mysqlclient==2.2.0
alembic==1.12.1

# 数据验证
pydantic==2.5.0
pydantic-settings==2.1.0

# 服务发现
python-consul==1.1.0

# 核心逻辑
sqlfluff==2.3.5

# 工具库
python-multipart==0.0.6
python-dotenv==1.0.0
```

3. 创建服务启动入口文件骨架：
   - `app/web_main.py`：FastAPI应用入口
   - `app/worker_main.py`：Celery Worker入口

**验收标准**：
- 目录结构完整创建，所有__init__.py文件就位
- requirements.txt包含所有必需依赖
- 可以成功执行`pip install -r requirements.txt`

### 任务1.2：统一配置管理
**目标**：建立基于环境变量的统一配置系统

**具体工作**：
1. 创建`app/config/settings.py`配置管理核心
2. 支持不同环境(dev/test/prod)的配置
3. 包含所有系统配置项：
   - 数据库连接配置
   - Redis连接配置
   - NFS共享目录配置
   - Consul服务发现配置
   - 日志配置
   - 应用运行配置

4. 实现配置验证和默认值设置
5. 支持从环境变量和.env文件加载配置

**验收标准**：
- 配置系统可以正确加载所有环境变量
- 支持配置验证，缺失必要配置时报错明确
- 支持不同环境的配置切换

### 任务1.3：日志和异常处理系统
**目标**：建立统一的日志记录和异常处理机制

**具体工作**：
1. 创建`app/core/logging.py`日志配置模块：
   - 支持结构化日志输出（JSON格式）
   - 支持不同日志级别配置
   - 支持日志文件轮转
   - 为FastAPI和Celery提供统一的日志格式

2. 创建`app/core/exceptions.py`异常处理模块：
   - 定义业务异常类层次结构
   - 定义标准错误码和错误消息
   - 提供异常转HTTP响应的工具函数

**验收标准**：
- 日志系统可以正常输出结构化日志
- 异常处理系统定义清晰，覆盖主要业务场景
- 日志和异常信息便于调试和监控

### 任务1.4：工具类和通用函数
**目标**：开发系统通用的工具函数库

**具体工作**：
1. 创建`app/utils/uuid_utils.py`：
   - UUID生成函数（job_id, task_id）
   - UUID格式验证函数
   - UUID转换工具函数

2. 创建`app/utils/file_utils.py`：
   - NFS路径操作工具函数
   - 文件读写封装函数
   - 目录创建和清理函数
   - 文件扩展名检查函数

**验收标准**：
- 工具函数功能完整，包含错误处理
- 所有工具函数有明确的docstring说明
- 工具函数便于后续阶段调用

## 本阶段完成标志
- [ ] 完整的项目目录结构已创建
- [ ] 所有依赖库已安装并可正常导入
- [ ] 配置管理系统工作正常
- [ ] 日志系统可以输出格式化日志
- [ ] 异常处理框架已建立
- [ ] 工具函数库可正常使用
- [ ] 两个服务入口文件已创建（虽然还是空骨架）

## 下一阶段预告
**阶段二：数据库层和数据模型**
- 建立MySQL数据库连接
- 定义SQLAlchemy数据模型
- 设置Alembic数据库迁移
- 创建API数据模型（Pydantic schemas）

完成本阶段后，我们将拥有一个结构完整、配置统一、日志完善的项目基础架构，为后续的数据库和业务逻辑开发奠定坚实基础。 