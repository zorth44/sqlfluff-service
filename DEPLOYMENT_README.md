# SQLFluff服务部署指南

本文档提供SQLFluff服务在堡垒机环境下的快速部署指南。

## 快速开始

### 开发机操作

1. **一键准备部署包**
```bash
cd /path/to/sqlfluff-service
./deploy/quick_prepare.sh
```

2. **手动上传文件**
- 使用堡垒机或FTP工具上传 `releases/release_<version>.tar.gz` 到服务器
- 目标路径: `~/sqlfluff-service/releases/`

### 服务器操作

1. **首次部署 - 初始化环境**
```bash
# 上传并运行初始化脚本
bash init_server.sh

# 编辑环境变量
vim ~/.bashrc
# 修改SQLFluff相关的export配置

# 重新加载配置
source ~/.bashrc

# 检查配置
~/sqlfluff-service/scripts/check_env.sh
```

2. **执行部署**
```bash
cd ~/sqlfluff-service
bash scripts/deploy.sh <version>
```

3. **检查服务状态**
```bash
bash ~/sqlfluff-service/scripts/status.sh
```

## 目录结构

```
开发机:
sqlfluff-service/
├── deploy/                # 部署脚本
│   ├── package.sh         # 打包脚本
│   ├── prepare_deploy.sh  # 准备部署说明
│   └── quick_prepare.sh   # 一键准备
├── releases/              # 发布包目录
└── init_server.sh         # 服务器初始化脚本

服务器:
~/sqlfluff-service/
├── current/               # 当前运行版本
├── backups/               # 版本备份
├── releases/              # 上传的发布包
├── logs/                  # 服务日志
├── scripts/               # 管理脚本
│   ├── deploy.sh          # 部署脚本
│   ├── start_web_new.sh   # Web服务启动
│   ├── start_worker_new.sh # Worker服务启动
│   ├── stop_web.sh        # Web服务停止
│   ├── stop_worker.sh     # Worker服务停止
│   ├── status.sh          # 状态检查
│   ├── rollback.sh        # 版本回滚
│   └── check_env.sh       # 环境检查
├── web.pid                # Web服务PID
└── worker.pid             # Worker服务PID
```

## 常用命令

### 日常部署
```bash
# 开发机: 一键准备
./deploy/quick_prepare.sh

# 手动上传文件到服务器

# 服务器: 执行部署
cd ~/sqlfluff-service && bash scripts/deploy.sh <version>
```

### 服务管理
```bash
# 查看状态
bash ~/sqlfluff-service/scripts/status.sh

# 手动启动/停止服务
bash ~/sqlfluff-service/scripts/start_web_new.sh
bash ~/sqlfluff-service/scripts/start_worker_new.sh
bash ~/sqlfluff-service/scripts/stop_web.sh
bash ~/sqlfluff-service/scripts/stop_worker.sh

# 回滚到上一版本
bash ~/sqlfluff-service/scripts/rollback.sh
```

### 日志查看
```bash
# 查看实时日志
tail -f ~/sqlfluff-service/logs/web_$(date +%Y%m%d).log
tail -f ~/sqlfluff-service/logs/worker_$(date +%Y%m%d).log

# 搜索错误
grep -i error ~/sqlfluff-service/logs/*.log
```

### 环境检查
```bash
# 检查环境变量配置
~/sqlfluff-service/scripts/check_env.sh

# 重新加载环境变量
source ~/.bashrc

# 检查Python环境
which python
which gunicorn
which celery
```

## 注意事项

1. **环境变量**: 所有配置都在 `~/.bashrc` 中，修改后需要 `source ~/.bashrc`
2. **无venv**: 直接使用系统Python环境，确保已安装所需依赖
3. **无数据库迁移**: 数据库变更需要手动执行
4. **堡垒机**: 使用手动文件上传，不依赖SSH/SCP
5. **日志**: 所有服务日志都在 `~/sqlfluff-service/logs/` 目录

## 故障排除

如遇问题，请检查：
1. 环境变量是否正确配置 (`check_env.sh`)
2. 服务日志是否有错误信息
3. 进程是否正常运行 (`status.sh`)
4. 网络连接是否正常（数据库、Redis、NFS）

详细部署指南请参考 `python-deploy-guide.md`。