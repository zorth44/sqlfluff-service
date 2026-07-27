# SQLFluff 服务部署速览

堡垒机环境下的快速部署说明。完整手册见 [docs/deployment_guide.md](docs/deployment_guide.md)。

当前架构为 **DB-as-Queue**，不依赖 Redis / Celery。

## 快速开始

### 开发机

```bash
cd /path/to/sqlfluff-service
./deploy/quick_prepare.sh
```

将 `releases/release_<version>.tar.gz` 上传到服务器 `~/sqlfluff-service/releases/`。

### 服务器

**首次：**

```bash
bash init_server.sh
vim ~/.bashrc          # 修改 MySQL / NFS / CONSUL_SERVICE_IP 等
source ~/.bashrc
~/sqlfluff-service/scripts/check_env.sh
```

安装依赖并执行迁移后：

```bash
cd ~/sqlfluff-service
bash scripts/deploy.sh <version>
bash scripts/status.sh
```

## 目录结构

```
开发机:
sqlfluff-service/
├── deploy/                # package / prepare / quick_prepare
├── releases/
└── init_server.sh

服务器:
~/sqlfluff-service/
├── current/
├── backups/
├── releases/
├── logs/                  # web.log / worker.log
├── scripts/
│   ├── deploy.sh
│   ├── start_web_new.sh / start_worker_new.sh
│   ├── stop_web.sh / stop_worker.sh
│   ├── status.sh / rollback.sh / check_env.sh
├── web.pid
└── worker.pid
```

## 常用命令

```bash
# 部署
cd ~/sqlfluff-service && bash scripts/deploy.sh <version>

# 状态 / 启停
bash ~/sqlfluff-service/scripts/status.sh
bash ~/sqlfluff-service/scripts/start_web_new.sh
bash ~/sqlfluff-service/scripts/start_worker_new.sh
bash ~/sqlfluff-service/scripts/stop_web.sh
bash ~/sqlfluff-service/scripts/stop_worker.sh
bash ~/sqlfluff-service/scripts/rollback.sh

# 日志
tail -f ~/sqlfluff-service/logs/web.log
tail -f ~/sqlfluff-service/logs/worker.log

# 环境
source ~/.bashrc
~/sqlfluff-service/scripts/check_env.sh
```

## 注意事项

1. 配置在 `~/.bashrc`，修改后需 `source ~/.bashrc`
2. `ENVIRONMENT` 只能是 `dev` / `test` / `prod`（生产用 `prod`）
3. Web 与 Worker 必须挂载同一 `NFS_SHARE_ROOT_PATH`
4. 至少启动一个 DB Worker，否则 Job 会一直 `PENDING`
5. Schema 变更用 Alembic：`alembic upgrade head`
6. 无需 Redis / Celery

## 故障排除

1. `check_env.sh` 是否通过
2. `status.sh` 与 `logs/*.log`
3. MySQL、NFS 连通与权限
4. 需要 Consul 时检查 `CONSUL_SERVICE_IP`

详见 [docs/deployment_guide.md](docs/deployment_guide.md)。
