# 阶段三：核心业务逻辑层

## 项目概述

本项目是一个SQL核验服务系统，提供对SQL文件的自动化质量检查功能。系统采用分布式架构，通过FastAPI Web服务接收请求，Celery Worker执行后台任务，使用SQLFluff进行SQL质量分析。

核心工作流程：
1. **单SQL提交**：客户端提交SQL内容，系统直接进行分析
2. **ZIP包提交**：客户端提交ZIP包，系统解压后批量分析所有SQL文件

## 前置状态（前两阶段已完成）

### 阶段一完成项目
- ✅ 完整的项目目录结构
- ✅ 统一的配置管理系统
- ✅ 日志和异常处理框架
- ✅ 工具类库（UUID、文件操作等）

### 阶段二完成项目
- ✅ MySQL数据库连接和会话管理
- ✅ linting_jobs和linting_tasks数据模型
- ✅ Alembic数据库迁移系统
- ✅ Pydantic API数据模型

## 本阶段目标
实现核心业务逻辑层，为FastAPI Web服务和Celery Worker提供统一的业务接口。包括Job管理、Task处理、SQLFluff集成和文件操作等核心功能。

## 本阶段任务清单

### 任务3.1：Job业务服务
**目标**：实现核验工作(Job)的完整业务逻辑

**具体工作**：
1. 创建`app/services/job_service.py`，实现Job核心业务：

```python
class JobService:
    def __init__(self, db: Session):
        self.db = db
    
    async def create_job(self, request: JobCreateRequest) -> str:
        """创建新的核验工作"""
        # 生成job_id
        # 确定submission_type
        # 处理文件保存（单SQL或ZIP）
        # 创建数据库记录
        # 返回job_id
    
    async def get_job_by_id(self, job_id: str) -> Optional[LintingJob]:
        """根据ID获取Job"""
        
    async def get_job_with_tasks(self, job_id: str, page: int, size: int) -> Optional[JobResponse]:
        """获取Job及其关联的Tasks分页列表"""
        
    async def update_job_status(self, job_id: str, status: str, error_message: str = None):
        """更新Job状态"""
        
    async def calculate_job_status(self, job_id: str) -> str:
        """根据子任务状态计算Job总体状态"""
        # ACCEPTED -> PROCESSING -> COMPLETED/PARTIALLY_COMPLETED/FAILED
```

2. Job状态管理逻辑：
   - **ACCEPTED**：刚创建，等待处理
   - **PROCESSING**：正在处理中
   - **COMPLETED**：所有子任务都成功完成
   - **PARTIALLY_COMPLETED**：部分子任务成功，部分失败
   - **FAILED**：Job级别失败（如ZIP解压失败）

3. Job与Task关联管理：
   - 实现Job下Task的批量创建
   - 支持Job状态的自动更新（基于子任务状态）
   - 实现Job的分页查询功能

**验收标准**：
- Job创建功能正常，支持单SQL和ZIP两种模式
- Job状态管理逻辑正确，状态转换符合业务规则
- Job查询功能完整，支持分页和关联查询
- Job与Task的关联关系管理正确

### 任务3.2：Task业务服务
**目标**：实现单个文件处理任务(Task)的业务逻辑

**具体工作**：
1. 创建`app/services/task_service.py`，实现Task核心业务：

```python
class TaskService:
    def __init__(self, db: Session):
        self.db = db
    
    async def create_task(self, job_id: str, source_file_path: str) -> str:
        """创建新的文件处理任务"""
        # 生成task_id
        # 创建数据库记录
        # 返回task_id
    
    async def get_task_by_id(self, task_id: str) -> Optional[LintingTask]:
        """根据ID获取Task"""
        
    async def update_task_status(self, task_id: str, status: str, 
                               result_file_path: str = None, 
                               error_message: str = None):
        """更新Task状态和结果"""
        
    async def get_tasks_by_job_id(self, job_id: str, page: int, size: int) -> List[LintingTask]:
        """获取Job下的Tasks分页列表"""
        
    async def batch_create_tasks(self, job_id: str, file_paths: List[str]) -> List[str]:
        """批量创建Tasks"""
```

2. Task状态流转管理：
   - **PENDING**：刚创建，等待Celery Worker处理
   - **IN_PROGRESS**：Worker正在处理中
   - **SUCCESS**：处理成功，结果已保存
   - **FAILURE**：处理失败，错误信息已记录

3. 批量Task处理：
   - 支持ZIP解压后的批量Task创建
   - 实现Task状态的批量查询和更新
   - 优化数据库操作性能

**验收标准**：
- Task创建和状态更新功能正常
- Task状态流转逻辑正确
- 批量Task操作性能良好
- Task查询功能支持分页和过滤

### 任务3.3：SQLFluff集成服务
**目标**：集成SQLFluff引擎，实现SQL文件的质量分析

**具体工作**：
1. 创建`app/services/sqlfluff_service.py`，实现SQLFluff集成：

```python
class SQLFluffService:
    def __init__(self):
        self.config = self._load_sqlfluff_config()
    
    def analyze_sql_file(self, file_path: str) -> Dict:
        """分析单个SQL文件"""
        # 读取SQL文件内容
        # 调用sqlfluff.lint()
        # 格式化分析结果
        # 返回结构化结果
    
    def analyze_sql_content(self, sql_content: str) -> Dict:
        """分析SQL内容字符串"""
        # 直接分析SQL内容
        # 返回结构化结果
    
    def _load_sqlfluff_config(self) -> Dict:
        """加载SQLFluff配置"""
        # 支持自定义规则配置
        # 支持不同SQL方言
    
    def _format_lint_result(self, lint_result) -> Dict:
        """格式化分析结果为标准JSON格式"""
        # 转换为统一的结果格式
        # 包含错误、警告、建议等信息
```

2. SQLFluff配置管理：
   - 支持多种SQL方言（MySQL、PostgreSQL、SQLite等）
   - 可配置的规则集合
   - 自定义规则严重程度

3. 结果格式化：
   - 统一的JSON输出格式
   - 包含文件名、行号、列号、错误类型、错误描述
   - 支持错误统计和汇总

**验收标准**：
- SQLFluff集成正常，可以分析SQL文件
- 支持多种SQL方言和规则配置
- 分析结果格式统一，信息完整
- 错误处理机制完善，分析失败时有明确提示

### 任务3.4：文件处理服务扩展
**目标**：扩展文件操作工具，支持SQL文件和ZIP包的处理

**具体工作**：
1. 扩展`app/utils/file_utils.py`，添加SQL文件处理功能：

```python
class FileUtils:
    @staticmethod
    def save_sql_content(content: str, relative_path: str) -> str:
        """保存SQL内容到NFS文件"""
        
    @staticmethod
    def extract_zip_file(zip_path: str, extract_to: str) -> List[str]:
        """解压ZIP文件，返回SQL文件列表"""
        
    @staticmethod
    def find_sql_files(directory: str) -> List[str]:
        """递归查找目录下的所有SQL文件"""
        
    @staticmethod
    def generate_result_file_path(job_id: str, task_id: str) -> str:
        """生成结果文件路径"""
        
    @staticmethod
    def save_analysis_result(result: Dict, file_path: str):
        """保存分析结果到JSON文件"""
        
    @staticmethod
    def load_analysis_result(file_path: str) -> Dict:
        """从JSON文件加载分析结果"""
        
    @staticmethod
    def cleanup_temp_directory(directory: str):
        """清理临时目录"""
```

2. NFS文件路径管理：
   - 实现标准的文件路径生成规则
   - 支持相对路径和绝对路径转换
   - 实现文件夹的自动创建和清理

3. ZIP文件处理：
   - 支持ZIP文件的解压和文件枚举
   - 过滤非SQL文件
   - 处理文件名编码问题

**验收标准**：
- 文件操作功能完整，支持SQL和ZIP文件处理
- NFS路径管理规范，文件组织有序
- ZIP解压功能正常，可以正确提取SQL文件
- 文件读写操作稳定，包含完善的错误处理

## 本阶段完成标志
- [ ] Job业务服务实现完整，支持创建、查询、状态管理
- [ ] Task业务服务实现完整，支持单个和批量操作
- [ ] SQLFluff集成服务正常工作，可以分析SQL文件
- [ ] 文件处理服务扩展完成，支持SQL和ZIP文件操作
- [ ] 所有业务服务都有完善的错误处理和日志记录
- [ ] 业务逻辑层可以独立进行单元测试
- [ ] 服务间的依赖关系清晰，接口定义明确

## 下一阶段预告
**阶段四：FastAPI Web服务开发**
- 实现POST /jobs接口（创建核验工作）
- 实现GET /jobs/{job_id}接口（查询工作状态）
- 实现GET /tasks/{task_id}/result接口（获取任务结果）
- 实现健康检查和依赖注入
- 集成Consul服务注册

完成本阶段后，我们将拥有完整的核心业务逻辑层，包括Job管理、Task处理、SQLFluff分析和文件操作等功能，为FastAPI Web服务和Celery Worker的实现提供统一的业务接口。 