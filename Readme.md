# SQL 核验服务 (sqlfluff-service)

基于 SQLFluff 的 SQL 代码质量核验服务。支持单段 SQL、ZIP 批量文件异步分析，以及同步实时检查；结果可查询、统计，并导出 CSV / HTML 报告。

## 架构概览

当前版本采用 **DB-as-Queue** 异步模型，不再依赖 Celery / Redis。

| 组件 | 说明 |
| --- | --- |
| **FastAPI Web** | HTTP API 入口：创建 Job、查询状态/结果、违规统计、报告导出、健康检查；可选注册到 Consul |
| **DB Worker** | 后台消费进程：通过 MySQL `FOR UPDATE SKIP LOCKED` 原子领取 `PENDING` 任务并执行 SQLFluff 分析 |
| **MySQL** | 主持久化：Job / Task / Violation / 规则分级 / Worker 注册与心跳 |
| **NFS 共享目录** | 存放源 SQL、ZIP、解压文件与分析结果 JSON；Web 与 Worker 须挂载到相同路径 |
| **Consul**（可选） | 服务注册与发现，供网关或其他服务发现本实例 |

```
客户端 / 上游服务
        │
        ▼
  FastAPI Web  ──写入 PENDING Task──►  MySQL
        │                                  │
        │                                  │ claim (SKIP LOCKED)
        ▼                                  ▼
   NFS 共享目录 ◄──读写 SQL / 结果──  DB Worker
```

### 核心工作流

1. 客户端调用 `POST /api/v1/jobs`（或 `/jobs/upload`、`/jobs/create-from-extracted`）创建核验工作。
2. Web 在 MySQL 写入 `linting_jobs`，并为每个 SQL 文件写入 `PENDING` 状态的 `linting_tasks`；源文件落在 NFS。
3. Worker 按优先级领取任务，执行 SQLFluff，将结果 JSON 写回 NFS，更新 Task 状态与违规明细。
4. 客户端轮询 Job / Task 接口获取进度，或导出 CSV / HTML 报告。

同步场景可直接调用 `POST /api/v1/sql/check`，无需创建 Job。

## 技术栈

- Python 3.11+、FastAPI、Uvicorn / Gunicorn
- SQLAlchemy 2、Alembic、PyMySQL
- SQLFluff（本地 wheel，含 Hive 自定义规则）
- Jinja2（HTML 报告）、python-consul

## 目录结构

```
sqlfluff-service/
├── app/
│   ├── api/routes/          # HTTP 路由 (jobs / tasks / sql / health)
│   ├── config/              # 配置
│   ├── core/                # 数据库、日志、Consul、异常等
│   ├── models/              # SQLAlchemy 模型
│   ├── schemas/             # Pydantic 请求/响应模型
│   ├── services/            # 业务逻辑、SQLFluff、报告
│   ├── worker/              # DB-as-Queue Worker
│   ├── web_main.py          # Web 入口
│   └── worker_main.py       # 兼容入口（优先使用 app.worker.run_worker）
├── alembic/                 # 数据库迁移
├── scripts/                 # 启停、部署、运维脚本
├── deploy/                  # 打包与发布准备
├── docs/                    # 补充文档
├── tests/                   # 测试
├── env.example
├── requirements.txt
└── DEPLOYMENT_README.md     # 堡垒机部署速览
```

## 快速开始

### 1. 环境准备

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

> `requirements.txt` 依赖 `./local_wheels/` 下的 SQLFluff 相关 wheel，请确保该目录存在。

### 2. 配置

复制并编辑环境变量：

```bash
cp env.example .env
```

**必需配置：**

| 变量 | 说明 |
| --- | --- |
| `DATABASE_URL` 或 `MYSQL_DATABASE_*` | MySQL 连接（二选一） |
| `NFS_SHARE_ROOT_PATH` | 共享存储根路径（开发可用本地目录） |

**常用可选配置：**

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `WEB_HOST` / `WEB_PORT` | `0.0.0.0` / `8000` | Web 监听地址 |
| `WORKER_CONCURRENCY` | `4` | Worker 并发线程数 |
| `WORKER_POLL_INTERVAL` | `2.0` | 无任务时轮询间隔（秒） |
| `WORKER_HEARTBEAT_INTERVAL` | `30` | Worker 心跳间隔（秒） |
| `WORKER_ZOMBIE_TIMEOUT` | `600` | 心跳超时，超时任务可被回收 |
| `WORKER_TASK_TIMEOUT` | `1800` | 单任务超时（秒） |
| `WORKER_MAX_RETRIES` | `3` | 任务最大重试次数 |
| `CONSUL_HOST` / `CONSUL_PORT` | `127.0.0.1` / `8500` | Consul 服务发现 |
| `CONSUL_SERVICE_IP` | — | 注册到 Consul 的服务 IP |
| `HIVE_RULES` / `GBASE8A_RULES` | — | 实时检查接口按方言使用的规则列表 |
| `REALTIME_SQL_MAX_CONCURRENCY` | `2` | 单个 Web 进程的实时 SQL 最大并发分析数 |
| `REALTIME_SQL_QUEUE_TIMEOUT` | `5` | 实时检查等待并发槽位的超时（秒） |
| `REALTIME_SQL_SOFT_TIMEOUT` / `REALTIME_SQL_HARD_TIMEOUT` | `30` / `35` | 实时检查子进程软/硬超时（秒） |

更完整的说明见 [docs/environment_variables.md](docs/environment_variables.md)（其中部分 Redis/Celery 条目为历史遗留，当前运行时不再需要）。

### 3. 初始化数据库

```bash
alembic upgrade head
```

### 4. 启动服务

**Web：**

```bash
# 开发
python -m app.web_main
# 或
uvicorn app.web_main:app --host 0.0.0.0 --port 8000 --reload

# 生产
gunicorn app.web_main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

**Worker（至少一个实例）：**

```bash
python -m app.worker.run_worker
```

部署环境可使用：

```bash
bash scripts/start_web_new.sh
bash scripts/start_worker_new.sh
bash scripts/status.sh
```

### 5. 验证

- API 文档：`http://localhost:8000/docs`
- 健康检查：`GET /api/v1/health`
- 就绪 / 存活：`GET /api/v1/health/ready`、`GET /api/v1/health/live`

## API 概览

所有业务接口前缀为 `/api/v1`。完整契约以 OpenAPI（`/docs`）为准。

### Jobs

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/jobs` | 创建 Job（`sql_content` 或已上传的 `zip_file_path`） |
| `POST` | `/jobs/upload` | 创建 Job（表单上传 ZIP 或提交 SQL） |
| `POST` | `/jobs/create-from-extracted` | 从已解压目录创建 Job |
| `GET` | `/jobs` | 按 `job_id` 查询详情 |
| `GET` | `/jobs/list`、`/jobs/search` | 列表 / 搜索 |
| `GET` | `/jobs/statistics` | Job 统计 |
| `GET` | `/jobs/tasks` | 某 Job 下的 Task ID 列表 |
| `GET` | `/jobs/{job_id}/violations` | 违规明细 |
| `GET` | `/jobs/{job_id}/statistics` | 严重级别等统计 |
| `GET` | `/jobs/{job_id}/export/csv` | 导出 CSV |
| `GET` | `/jobs/{job_id}/export/html` | 导出 HTML 片段 |
| `GET` | `/jobs/{job_id}/export/html/standalone` | 导出独立 HTML |

创建 Job 示例：

```json
POST /api/v1/jobs
{
  "sql_content": "SELECT * FROM my_table;",
  "user_id": "u001",
  "product_name": "demo",
  "dialect": "hive",
  "rules": ["RF02", "L032"]
}
```

```json
{
  "job_id": "job-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
}
```

响应状态码：`202 Accepted`。

### Tasks

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/tasks` | 任务详情 |
| `GET` | `/tasks/result` | 分析结果 JSON |
| `GET` | `/tasks/result/lint` | Lint 结果视图 |
| `GET` | `/tasks/result/download` | 下载结果文件 |
| `GET` | `/tasks/list` | 任务列表 |
| `POST` | `/tasks/retry` | 重试失败任务 |
| `GET` | `/tasks/severity-statistics` 等 | 按严重级别统计 / 筛选 |

### SQL 实时检查

```http
POST /api/v1/sql/check
```

同步返回违规列表，适用于编辑器侧即时反馈；Hive / GBase8a 规则可由环境变量配置。请求中的 SQL 最长为 1 MiB 字符；分析在隔离子进程中执行，达到并发或超时限制时分别返回 `503` 或 `504`。

### Health

| 路径 | 说明 |
| --- | --- |
| `/health` | 完整检查（数据库、Worker、NFS、磁盘等） |
| `/health/quick`、`/health/simple` | 轻量检查（Consul / 探活） |
| `/health/metrics` | Prometheus 指标 |

## 数据模型（摘要）

### `linting_jobs`

核验工作主表。关键字段：`job_id`、`status`（`ACCEPTED` / `PROCESSING` / `COMPLETED` / `PARTIALLY_COMPLETED` / `FAILED`）、`submission_type`（`SINGLE_FILE` / `ZIP_ARCHIVE`）、`source_path`、`dialect`、`user_id`、`product_name`、`boc_batch_number`、`boc_task_number`、`rules`。

### `linting_tasks`

文件级任务。关键字段：`task_id`、`job_id`、`status`（`PENDING` / `IN_PROGRESS` / `SUCCESS` / `FAILURE`）、源/结果路径、违规计数与严重级别统计；以及队列字段 `priority`、`claim_id`、`claimed_at`、`retry_count`。

### `linting_violations`

违规明细，关联 `task_id` / `job_id`，支持报告与按规则统计。

### `rule_definitions`

规则元数据与严重级别（`INFO` / `MINOR` / `MAJOR` / `BLOCKER` / `CRITICAL`）。

### `worker_registry`

Worker 心跳与状态，供健康检查与僵尸任务回收。

## Worker 行为

每个 Worker 进程包含：

- **N 个工作线程**：领取并执行最高优先级的 `PENDING` 任务
- **心跳线程**：向 `worker_registry` 写入心跳
- **僵尸扫描线程**：回收心跳超时或任务超时的 `IN_PROGRESS` 任务，并按 `retry_count` 决定重试或失败

多实例可水平扩展；任务领取依赖 InnoDB 行锁与 `SKIP LOCKED`，无需额外消息中间件。

Worker 使用**任务级租约**（`lease_token` / `lease_expires_at`）：领取时签发租约，执行中续租，结果写入带 fencing 校验；过期租约由扫描线程回收并按指数退避重试。

## 测试

```bash
# 单元 / SQLite 测试
export NFS_SHARE_ROOT_PATH=/tmp/sqlfluff_nfs_test
export DATABASE_URL=sqlite:///./test.db
export ENVIRONMENT=test
pytest tests/worker tests/services tests/config tests/api/test_health.py -q

# MySQL 8 并发领取 / SKIP LOCKED / fencing（T00、T18）
# 需先准备一个可访问的 MySQL 8 测试库，并设置 MYSQL_TEST_DATABASE_URL
./scripts/run_mysql_integration_tests.sh
```

SQLite 测试可保留，但不作为队列并发正确性的依据。

## 生产部署

堡垒机场景的打包、上传、启停与回滚见：

- [DEPLOYMENT_README.md](DEPLOYMENT_README.md)（一页纸速览）
- [docs/deployment_guide.md](docs/deployment_guide.md)（完整部署手册）

要点：

1. 所有 Web / Worker 节点挂载同一 NFS 路径，且与 `NFS_SHARE_ROOT_PATH` 一致
2. 运行用户对该目录具备读写权限
3. 至少启动一个 DB Worker；无 Worker 时 Job 会一直停留在 `PENDING`
4. 使用 Alembic 管理 schema：`alembic upgrade head`

## 相关文档

| 文档 | 内容 |
| --- | --- |
| [docs/deployment_guide.md](docs/deployment_guide.md) | 部署手册 |
| [docs/dialect_configuration.md](docs/dialect_configuration.md) | SQL 方言配置 |
| [docs/internal_network_ip_configuration.md](docs/internal_network_ip_configuration.md) | 内网 IP / Consul 注册 |
| [scripts/README_CSV_REPORT.md](scripts/README_CSV_REPORT.md) | CSV 报告脚本 |

## 许可证

内部项目，按组织规范使用与分发。
