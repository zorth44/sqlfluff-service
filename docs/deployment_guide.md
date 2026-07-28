# SQL 核验服务部署手册

当前版本采用 **DB-as-Queue** 架构：Web（FastAPI）写入 MySQL `PENDING` 任务，DB Worker 通过 `FOR UPDATE SKIP LOCKED` 领取并执行。运行时 **不依赖 Redis / Celery**。

相关速览：[DEPLOYMENT_README.md](../DEPLOYMENT_README.md)（堡垒机一页纸）、[env.example](../env.example)、[environment_variables.md](environment_variables.md)。

## 1. 架构与组件

| 组件 | 作用 |
| --- | --- |
| FastAPI Web | HTTP API；创建 Job / Task，查询结果，导出报告；可选注册 Consul |
| DB Worker | 后台消费 `PENDING` 任务，跑 SQLFluff，写回结果 |
| MySQL 8+ | Job / Task / Violation / Worker 注册与心跳 |
| NFS 共享目录 | SQL / ZIP / 解压文件 / 结果 JSON；Web 与 Worker 须同路径 |
| Consul（可选） | 服务发现 |

至少启动 **1 个 Worker**；否则 Job 会一直停在 `PENDING`。

## 2. 环境要求

### 软件

- Python 3.11+
- MySQL 8.0+
- NFS（或本地目录模拟，开发可用）
- Consul 1.15+（可选）
- `gunicorn` + `uvicorn`（生产 Web）
- `local_wheels/` 下 SQLFluff 相关 wheel（与 `requirements.txt` 配套）

### 硬件参考

| 角色 | CPU | 内存 | 磁盘 |
| --- | --- | --- | --- |
| Web | 2 核+ | 4GB+ | 20GB+ |
| Worker | 4 核+ | 8GB+ | 50GB+（另挂 NFS） |
| MySQL | 2 核+ | 4GB+ | 按数据量 |

## 3. 配置

应用从环境变量 / `.env` 加载配置（见 `app/config/settings.py`）。

```bash
cp env.example .env
# 或生产：写到 ~/.bashrc（init_server.sh 会追加模板）
```

### 必需

| 变量 | 说明 |
| --- | --- |
| `DATABASE_URL` **或** 全套 `MYSQL_DATABASE_*` | MySQL 连接 |
| `NFS_SHARE_ROOT_PATH` | 共享存储根路径，Web/Worker 一致 |

### 生产常用

| 变量 | 建议 | 说明 |
| --- | --- | --- |
| `ENVIRONMENT` | `prod` | 仅允许 `dev` / `test` / `prod` |
| `PORT` / `GUNICORN_WORKERS` | `8000` / `4` | 部署脚本启 Web 用 |
| `WORKER_CONCURRENCY` 等 | 见 `env.example` | DB Worker 并发与超时 |
| `CONSUL_HOST` / `CONSUL_PORT` | 内网 Consul | 可选 |
| `CONSUL_SERVICE_IP` | 本机内网 IP | 注册到 Consul 时必填，见 [internal_network_ip_configuration.md](internal_network_ip_configuration.md) |
| `LOG_FORMAT` | `json` | 仅控制标准输出；`web.log` / `worker.log` 固定为可读文本 |
| `LOG_FILE_PATH` / `LOG_FILE_BACKUP_COUNT` | 由启动脚本设置 | 进程内按日轮转并 gzip |

完整字段以 [env.example](../env.example) 为准。

检查：

```bash
bash scripts/check_env.sh
# 或服务器:
~/sqlfluff-service/scripts/check_env.sh
```

## 4. 本地 / 开发启动

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp env.example .env
# 编辑 .env：MySQL + NFS 路径（可用本地目录）

alembic upgrade head

# 终端 1
python -m app.web_main
# 终端 2
python -m app.worker.run_worker
```

验证：

- `http://localhost:8000/docs`
- `GET /api/v1/health`、`/api/v1/health/ready`、`/api/v1/health/live`

## 5. 生产部署（堡垒机打包上传）

典型目录：

```
开发机:  sqlfluff-service/releases/release_<version>.tar.gz
服务器:  ~/sqlfluff-service/
         ├── current/     # 当前运行版本
         ├── backups/     # 历史备份（deploy 自动保留最近 5 份）
         ├── releases/    # 上传的包
         ├── logs/        # web.log / worker.log
         ├── scripts/     # 启停与部署脚本
         ├── web.pid
         └── worker.pid
```

### 5.1 开发机：打包

```bash
cd /path/to/sqlfluff-service
./deploy/quick_prepare.sh
# 或指定版本:
./deploy/package.sh 20250727_160000
```

产物：`releases/release_<version>.tar.gz`（含 `app/`、`scripts/`、`alembic/`、`local_wheels/`、`requirements.txt` 等）。

经堡垒机 / FTP 上传到服务器：`~/sqlfluff-service/releases/`。

### 5.2 服务器：首次初始化

```bash
bash init_server.sh

vim ~/.bashrc    # 改成真实 MySQL / NFS / CONSUL_SERVICE_IP 等
source ~/.bashrc
~/sqlfluff-service/scripts/check_env.sh
```

依赖安装（按环境选择其一）：

```bash
# 系统 Python（当前堡垒机流程默认假设）
pip install -r ~/sqlfluff-service/current/requirements.txt
# 首次尚无 current 时，可对解压临时目录或上传后的包内 requirements 安装
```

数据库迁移（在可连库、且已有代码目录的节点上执行）：

```bash
cd ~/sqlfluff-service/current   # 或首次解压后的目录
alembic upgrade head
```

### 5.3 服务器：发布 / 升级

```bash
cd ~/sqlfluff-service
bash scripts/deploy.sh <version>
# 例: bash scripts/deploy.sh 20250727_160000
```

`deploy.sh` 会：停 Web/Worker → 备份 `current` → 解压新包 → `check_env` → 启动 Web + Worker。

### 5.4 日常运维

```bash
bash ~/sqlfluff-service/scripts/status.sh

bash ~/sqlfluff-service/scripts/start_web_new.sh
bash ~/sqlfluff-service/scripts/start_worker_new.sh
bash ~/sqlfluff-service/scripts/stop_web.sh
bash ~/sqlfluff-service/scripts/stop_worker.sh

bash ~/sqlfluff-service/scripts/rollback.sh
```

日志（进程内按日轮转，历史为 `*.YYYY-MM-DD.gz`）：

```bash
tail -f ~/sqlfluff-service/logs/web.log
tail -f ~/sqlfluff-service/logs/worker.log
```

`ENVIRONMENT=prod` 时 Web 使用 Gunicorn；`dev`/`test` 使用 Uvicorn。

## 6. 部署检查清单

- [ ] MySQL 可达，`alembic upgrade head` 已执行
- [ ] `NFS_SHARE_ROOT_PATH` 在所有 Web/Worker 节点一致且可读写
- [ ] `ENVIRONMENT=prod`（勿写 `production`，settings 不认）
- [ ] 至少 1 个 Worker 进程在跑（`status.sh`）
- [ ] 健康检查通过；需要服务发现时 `CONSUL_SERVICE_IP` 已设为内网 IP
- [ ] 创建测试 Job 后 Task 能从 `PENDING` → `IN_PROGRESS` → 完成

## 7. 故障排查

| 现象 | 排查 |
| --- | --- |
| `check_env` 失败 | `source ~/.bashrc`，核对 `MYSQL_*`、`NFS_SHARE_ROOT_PATH` |
| Job 一直 PENDING | Worker 是否启动；DB 连接；`worker.log` |
| NFS / 权限错误 | 挂载、路径、运行用户写权限 |
| Consul 注册异常 | `CONSUL_SERVICE_IP`、Agent 地址，见内网 IP 文档 |
| Web 起不来 | `web.log`、端口占用、Gunicorn/依赖是否安装 |
| 配置校验报错 | 生产下勿 `DEBUG=true`；`ENVIRONMENT` 必须为 `prod` |

不再需要检查 Redis / Celery；若旧文档或旧 `.bashrc` 仍有相关变量，可删除，不影响当前运行时。
