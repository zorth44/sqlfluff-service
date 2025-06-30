- **Spring Cloud Gateway**: 系统的统一流量入口，负责请求路由、认证、限流等通用网关功能。它将通过Consul发现并路由到FastAPI服务。
- **FastAPI 服务**: 面向客户端的Web服务。负责接收所有核验工作请求，进行初步处理，向任务队列派发任务，并提供状态和结果的查询接口。
- **Celery Worker**: 后台任务执行引擎。负责从任务队列中获取并执行所有实际的计算密集型任务（解压文件、分析SQL等），并与持久化层交互。
- **Redis**: 作为Celery的消息代理(Broker)，是FastAPI和Celery Worker之间异步通信的桥梁。
- **MySQL**: 作为主持久化存储，存储所有"核验工作(Job)"和其下属"文件任务(Task)"的元数据和状态。
- **NFS共享目录**: 系统的文件存储中心。所有的大块数据，包括用户提交的原始SQL文件、ZIP包，以及系统生成的JSON结果文件，都将以文件的形式存放在此目录中。所有FastAPI和Celery Worker节点都必须挂载此目录到相同的路径。
- **Consul**: 服务注册与发现中心，使得FastAPI服务能被Spring Cloud Gateway动态发现。

---

### 核心工作流

### 工作流一：提交单段SQL

1. 客户端向FastAPI的`POST /jobs`接口提交包含`sql_content`的请求。
2. FastAPI将`sql_content`保存为一个文件，并写入到**NFS共享目录**中，获得该文件的相对路径`source_path`。
3. FastAPI在**MySQL**的`linting_jobs`表中创建一条主工作记录，并在`linting_tasks`表中创建一条关联的子任务记录。
4. FastAPI向**Redis**中派发一个`process_sql_file`任务，并将`job_id`立即返回给客户端。
5. **Celery Worker**获取该任务，根据`task_id`从MySQL查询信息，从NFS读取SQL文件，执行分析，将结果文件写回NFS，并更新MySQL中的任务状态和结果路径。

### 工作流二：提交ZIP包

1. 外部服务（如Spring应用）将用户上传的ZIP包先上传至**NFS共享目录**，获得其相对路径`zip_file_path`。
2. 外部服务向FastAPI的`POST /jobs`接口提交包含`zip_file_path`的请求。
3. FastAPI在**MySQL**中创建一条`linting_jobs`主工作记录，状态为`ACCEPTED`。
4. FastAPI向**Redis**中派发一个`expand_zip_and_dispatch_tasks`任务，并将`job_id`立即返回。
5. **Celery Worker**获取解包任务，从NFS读取ZIP包并解压，遍历所有SQL文件，为每个文件创建`linting_tasks`子任务记录，并为每个文件派发一个`process_sql_file`任务。

### 数据模型设计 (MySQL)

### 表: `linting_jobs` (核验工作主表)

| 字段名 | 类型 | 约束/备注 | 描述 |
| --- | --- | --- | --- |
| `id` | `INT` | `PRIMARY KEY`, `AUTO_INCREMENT` | 自增主键 |
| `job_id` | `VARCHAR(255)` | `UNIQUE`, `NOT NULL` | 对外暴露的UUID工作ID |
| `status` | `ENUM('ACCEPTED', 'PROCESSING', 'COMPLETED', 'PARTIALLY_COMPLETED', 'FAILED')` | `NOT NULL` | 工作总体状态 |
| `submission_type` | `ENUM('SINGLE_FILE', 'ZIP_ARCHIVE')` | `NOT NULL` | 提交类型 |
| `source_path` | `VARCHAR(1024)` | `NOT NULL` | 在NFS共享目录中的源文件相对路径 |
| `error_message` | `TEXT` | `NULL` | 工作级别的错误信息（如解压失败） |
| `created_at` | `DATETIME(6)` | `NOT NULL`, `DEFAULT CURRENT_TIMESTAMP(6)` | 创建时间 |
| `updated_at` | `DATETIME(6)` | `NOT NULL`, `DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)` | 最后更新时间 |

### 表: `linting_tasks` (文件处理任务子表)

| 字段名 | 类型 | 约束/备注 | 描述 |
| --- | --- | --- | --- |
| `id` | `INT` | `PRIMARY KEY`, `AUTO_INCREMENT` | 自增主键 |
| `task_id` | `VARCHAR(255)` | `UNIQUE`, `NOT NULL` | Celery任务的UUID |
| `job_id` | `VARCHAR(255)` | `NOT NULL`, `INDEX` | 关联到`linting_jobs.job_id` |
| `status` | `ENUM('PENDING', 'IN_PROGRESS', 'SUCCESS', 'FAILURE')` | `NOT NULL` | 单个文件的处理状态 |
| `source_file_path` | `VARCHAR(1024)` | `NOT NULL` | 单个SQL文件在NFS共享目录中的相对路径 |
| `result_file_path` | `VARCHAR(1024)` | `NULL` | 结果JSON文件在NFS共享目录中的相对路径 |
| `error_message` | `TEXT` | `NULL` | 文件级别的错误信息 |
| `created_at` | `DATETIME(6)` | `NOT NULL`, `DEFAULT CURRENT_TIMESTAMP(6)` | 创建时间 |
| `updated_at` | `DATETIME(6)` | `NOT NULL`, `DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)` | 最后更新时间 |

### API接口规约 (FastAPI)

### 提交新的核验工作

- **功能**: 创建一个新的核验工作，支持单SQL或ZIP包两种模式。
- **路径**: `/jobs`
- **方法**: `POST`
- **请求体** (`application/json`): 请求体必须包含`sql_content`或`zip_file_path`二者之一。JSON
    
    ```xml
    // 模式一: 提交单段SQL
    {
      "sql_content": "SELECT * FROM my_table;"
    }
    
    // 模式二: 提交已放置在NFS上的ZIP包
    {
      "zip_file_path": "archives/your-uploaded-file-uuid.zip"
    }
    ```
    
- **成功响应** (`202 Accepted`):JSON
    
    ```xml
    {
      "job_id": "job-d8b8a7e0-4f7f-4f7b-8f1e-8e6a1e8e6a1e"
    }
    ```
    
- **错误响应** (`400 Bad Request`):JSON
    
    ```xml
    {
      "detail": "Either 'sql_content' or 'zip_file_path' must be provided."
    }
    ```
    

### 查询核验工作状态与详情

- **功能**: 获取指定核验工作的总体状态及其包含的所有文件任务的列表。
- **路径**: `/jobs/{job_id}`
- **方法**: `GET`
- **路径参数**: `job_id` (string, required): 要查询的工作ID。
- **Query参数**:
    - `page` (int, optional, default: 1): 子任务列表的页码。
    - `size` (int, optional, default: 10): 子任务列表的每页大小。
- **成功响应** (`200 OK`):JSON
    
    ```xml
    {
      "job_id": "job-d8b8a7e0-...",
      "job_status": "PROCESSING",
      "submission_type": "ZIP_ARCHIVE",
      "source_path": "archives/your-uploaded-file-uuid.zip",
      "created_at": "2025-06-27T09:30:00.123456",
      "updated_at": "2025-06-27T09:30:05.654321",
      "sub_tasks": {
        "total": 50,
        "page": 1,
        "size": 10,
        "items": [
          {
            "task_id": "task-e0e1...",
            "file_name": "query_users.sql",
            "status": "SUCCESS",
            "result_file_path": "jobs/job-d8b8.../results/task-e0e1....json"
          },
          {
            "task_id": "task-f1f2...",
            "file_name": "complex_join.sql",
            "status": "FAILURE",
            "error_message": "Syntax error on line 5..."
          }
        ]
      }
    }
    ```
    
- **错误响应** (`404 Not Found`):JSON
    
    ```xml
    {
      "detail": "Job not found"
    }
    ```
    

### 获取单个文件任务的详细结果

- **功能**: 直接获取某个特定文件任务的完整分析结果。
- **路径**: `/tasks/{task_id}/result`
- **方法**: `GET`
- **成功响应** (`200 OK`):
    - 响应体为从NFS读取的JSON文件内容，`Content-Type`为`application/json`。
- **错误响应**:
    - `404 Not Found`: 任务ID不存在或结果文件不存在。
    - `409 Conflict`: 任务尚未成功，无法获取结果。

### 后台任务规约 (Celery)

### 任务一：`expand_zip_and_dispatch_tasks`

- **目的**: 处理ZIP包提交的工作，将其分解为多个单个文件的处理任务。
- **参数**: `job_id` (string)
- **核心逻辑**:
    1. 使用`job_id`从`linting_jobs`表查询`source_path`。
    2. 更新`linting_jobs`表状态为`PROCESSING`。
    3. 根据`source_path`和配置的NFS根目录，定位并解压ZIP包到NFS上的临时子目录。
    4. 遍历解压目录中所有`.sql`文件：
    a. 为每个文件生成唯一的`task_id` (UUID)。
    b. 将该文件的相对路径记录为`source_file_path`。
    c. 在`linting_tasks`表中创建一条子任务记录，关联`job_id`，保存`source_file_path`，状态为`PENDING`。
    d. 派发一个`process_sql_file`任务，参数为新生成的`task_id`。
    5. 所有文件派发完毕后，清理临时解压目录。
    6. 若解压过程失败，则捕获异常，更新`linting_jobs`表状态为`FAILED`并记录错误信息。

### 任务二：`process_sql_file`

- **目的**: 对单个SQL文件执行SQLFluff分析。
- **参数**: `task_id` (string)
- **核心逻辑**:
    1. 使用`task_id`从`linting_tasks`表获取任务详情（特别是`source_file_path`和`job_id`）。
    2. 更新该任务状态为`IN_PROGRESS`。
    3. 根据`source_file_path`和配置的NFS根目录，读取SQL文件内容。
    4. 在`try/except`块中执行`sqlfluff.lint()`。
    5. **成功时**:
    a. 定义结果文件的相对路径，如`jobs/{job_id}/results/{task_id}.json`。
    b. 将SQLFluff返回的JSON结果写入到NFS的对应路径中。
    c. 更新`linting_tasks`表，状态为`SUCCESS`，并保存结果文件的相对路径`result_file_path`。
    6. **失败时**:
    a. 捕获异常信息。
    b. 更新`linting_tasks`表，状态为`FAILURE`，并保存错误信息`error_message`。
    7. (可选)任务结束后，可以检查并更新父`linting_jobs`的总体状态。

### 环境与依赖

### 核心依赖库

- **Web框架**: `fastapi`, `uvicorn`
- **应用服务器**: `gunicorn`
- **任务队列**: `celery`, `redis`
- **数据库**: `sqlalchemy`, `pymysql`
- **服务发现**: `python-consul`
- **数据校验**: `pydantic`
- **核心逻辑**: `sqlfluff`

### 环境变量配置

| 变量名 | 示例值 | 描述 |
| --- | --- | --- |
| `DATABASE_URL` | `mysql+pymysql://user:pass@host:port/dbname` | MySQL数据库连接字符串 |
| `CELERY_BROKER_URL` | `redis://host:port/0` | Redis连接字符串 |
| `NFS_SHARE_ROOT_PATH` | `/mnt/nfs_share/sql_linting` | NFS共享目录在服务器上的挂载点 |
| `CONSUL_HOST` | `127.0.0.1` | Consul Agent的主机地址 |
| `CONSUL_PORT` | `8500` | Consul Agent的端口 |

### 部署与运维

### 前置条件

- **NFS挂载**: 所有运行FastAPI服务或Celery Worker服务的服务器节点，都**必须**将同一个NFS共享目录挂载到**完全相同的路径**上。该路径必须与`NFS_SHARE_ROOT_PATH`环境变量的值一致。
- **目录权限**: 运行服务的操作系统用户（或容器内的用户）**必须**拥有对该NFS挂载目录的**读写权限**。

### 启动命令

- **启动FastAPI Web服务**:
`gunicorn -w [NUM_WORKERS] -k uvicorn.workers.UvicornWorker main:app`
- **启动Celery Worker**:
`celery -A tasks.celery_app worker --loglevel=INFO -c [NUM_CONCURRENCY]`

### 未来展望：监控与告警

为保证生产环境的稳定性，后续应考虑引入监控告警体系：

- **Flower**: 用于实时观察Celery集群状态。
- **Prometheus + Grafana**: 用于系统核心指标（如任务队列长度、任务处理速率、API响应时间）的聚合与可视化。
- **Alertmanager**: 用于实现自动化告警，如Worker进程异常、任务队列积压、任务失败率过高等。