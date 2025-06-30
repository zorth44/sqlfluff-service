# 阶段二：数据库层和数据模型

## 项目概述

本项目是一个SQL核验服务系统，提供对SQL文件的自动化质量检查功能。系统采用分布式架构，包含FastAPI Web服务、Celery Worker、Redis消息队列、MySQL数据库、NFS共享存储等组件。

支持两种核验模式：
1. **单SQL提交**：直接提交SQL内容进行分析
2. **ZIP包提交**：提交包含多个SQL文件的压缩包进行批量分析

## 前置状态（阶段一已完成）
- ✅ 完整的项目目录结构已创建
- ✅ 所有依赖库已安装配置
- ✅ 统一的配置管理系统已建立
- ✅ 日志和异常处理系统已搭建
- ✅ 工具类和通用函数已开发
- ✅ 两个服务的入口文件骨架已创建

## 本阶段目标
建立数据持久化层，为FastAPI Web服务和Celery Worker提供统一的数据访问接口。包括数据库连接管理、数据模型定义、数据库迁移管理和API数据模型定义。

## 本阶段任务清单

### 任务2.1：数据库连接和会话管理
**目标**：建立稳定可靠的MySQL数据库连接和会话管理机制

**具体工作**：
1. 创建`app/core/database.py`数据库核心模块：
   - 配置SQLAlchemy引擎，支持连接池
   - 实现数据库会话管理（SessionLocal）
   - 提供依赖注入用的数据库会话获取函数
   - 配置数据库连接参数（编码、时区、超时等）

2. 核心功能实现：
```python
# 关键功能示例
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    """数据库会话依赖注入函数"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

3. 连接池和错误处理配置：
   - 设置合适的连接池大小和超时时间
   - 实现数据库连接健康检查
   - 配置重连机制和异常处理

**验收标准**：
- 数据库连接可以正常建立和关闭
- 会话管理机制工作正常，无内存泄漏
- 连接池配置合理，支持并发访问
- 数据库连接异常可以正确处理和恢复

### 任务2.2：数据模型定义
**目标**：定义linting_jobs和linting_tasks两个核心数据表的SQLAlchemy模型

**具体工作**：
1. 创建`app/models/database.py`，定义数据模型：

**linting_jobs表模型**：
```python
class LintingJob(Base):
    __tablename__ = "linting_jobs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(255), unique=True, nullable=False, index=True)
    status = Column(Enum('ACCEPTED', 'PROCESSING', 'COMPLETED', 'PARTIALLY_COMPLETED', 'FAILED'), nullable=False)
    submission_type = Column(Enum('SINGLE_FILE', 'ZIP_ARCHIVE'), nullable=False)
    source_path = Column(String(1024), nullable=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(6), nullable=False, default=func.now())
    updated_at = Column(DateTime(6), nullable=False, default=func.now(), onupdate=func.now())
    
    # 关系定义
    tasks = relationship("LintingTask", back_populates="job")
```

**linting_tasks表模型**：
```python
class LintingTask(Base):
    __tablename__ = "linting_tasks"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(255), unique=True, nullable=False, index=True)
    job_id = Column(String(255), nullable=False, index=True)
    status = Column(Enum('PENDING', 'IN_PROGRESS', 'SUCCESS', 'FAILURE'), nullable=False)
    source_file_path = Column(String(1024), nullable=False)
    result_file_path = Column(String(1024), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(6), nullable=False, default=func.now())
    updated_at = Column(DateTime(6), nullable=False, default=func.now(), onupdate=func.now())
    
    # 关系定义
    job = relationship("LintingJob", back_populates="tasks")
```

2. 模型关系和索引优化：
   - 定义Job和Task之间的一对多关系
   - 创建必要的数据库索引以优化查询性能
   - 配置级联删除和更新规则

**验收标准**：
- 数据模型定义准确，字段类型和约束正确
- 表关系定义清晰，支持关联查询
- 索引配置合理，查询性能良好
- 模型可以正确映射到数据库表结构

### 任务2.3：数据库迁移设置
**目标**：使用Alembic管理数据库版本和结构变更

**具体工作**：
1. 初始化Alembic配置：
   - 创建`alembic/`目录结构
   - 配置`alembic.ini`文件，连接到项目数据库
   - 设置`alembic/env.py`，集成项目的数据库模型

2. 创建初始数据库迁移：
   - 生成包含linting_jobs和linting_tasks表的初始迁移文件
   - 迁移文件应包含完整的CREATE TABLE语句
   - 包含所有索引、约束和关系的创建

3. 数据库初始化脚本：
   - 创建`scripts/init_db.py`数据库初始化脚本
   - 支持从零开始创建数据库结构
   - 支持数据库升级和降级操作

示例迁移文件结构：
```python
# alembic/versions/001_create_initial_tables.py
def upgrade():
    # 创建linting_jobs表
    op.create_table('linting_jobs', ...)
    # 创建linting_tasks表  
    op.create_table('linting_tasks', ...)
    # 创建索引
    op.create_index(...)

def downgrade():
    # 删除表和索引的逆向操作
    op.drop_table('linting_tasks')
    op.drop_table('linting_jobs')
```

**验收标准**：
- Alembic配置正确，可以连接到数据库
- 初始迁移文件可以成功执行，创建正确的表结构
- 数据库初始化脚本工作正常
- 支持迁移的升级和回滚操作

### 任务2.4：API数据模型定义
**目标**：定义Pydantic数据模型，用于API请求和响应的数据验证

**具体工作**：
1. 创建`app/schemas/common.py`通用数据模型：
```python
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class PaginationResponse(BaseModel):
    total: int
    page: int
    size: int
    items: List[Any]

class BaseResponse(BaseModel):
    success: bool = True
    message: Optional[str] = None
```

2. 创建`app/schemas/job.py`Job相关数据模型：
```python
class JobCreateRequest(BaseModel):
    sql_content: Optional[str] = None
    zip_file_path: Optional[str] = None

class JobResponse(BaseModel):
    job_id: str
    job_status: str
    submission_type: str
    source_path: str
    created_at: datetime
    updated_at: datetime
    sub_tasks: Optional[PaginationResponse] = None

class JobCreateResponse(BaseModel):
    job_id: str
```

3. 创建`app/schemas/task.py`Task相关数据模型：
```python
class TaskResponse(BaseModel):
    task_id: str
    file_name: str
    status: str
    result_file_path: Optional[str] = None
    error_message: Optional[str] = None

class TaskDetailResponse(BaseModel):
    task_id: str
    job_id: str
    status: str
    source_file_path: str
    result_file_path: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
```

4. 配置数据验证规则：
   - 实现字段验证器和约束
   - 配置序列化和反序列化规则
   - 处理数据类型转换和格式化

**验收标准**：
- Pydantic模型定义完整，覆盖所有API数据交换场景
- 数据验证规则正确，可以有效防止无效数据
- 模型之间的关联关系清晰
- 序列化和反序列化工作正常

## 本阶段完成标志
- [ ] 数据库连接管理系统工作正常
- [ ] SQLAlchemy数据模型定义完整且正确
- [ ] Alembic迁移系统配置完成
- [ ] 初始数据库迁移可以成功执行
- [ ] 数据库初始化脚本可以正常工作
- [ ] Pydantic API数据模型定义完整
- [ ] 数据验证和序列化功能正常
- [ ] 可以通过ORM进行基本的数据库CRUD操作

## 下一阶段预告
**阶段三：核心业务逻辑层**
- 实现Job业务服务（创建、查询、状态管理）
- 实现Task业务服务（任务处理、状态流转）
- 集成SQLFluff核心分析功能
- 开发文件处理和NFS操作服务

完成本阶段后，我们将拥有完整的数据持久化层，包括数据库连接、数据模型、迁移管理和API数据结构，为后续的业务逻辑开发提供坚实的数据基础。 