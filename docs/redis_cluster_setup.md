# Redis集群配置指南

本文档介绍如何配置 SQL 核验服务以支持 Redis 集群，解决 `cluster cross-slot` 问题。

## 问题背景

在 Redis 集群环境中，Celery 可能会遇到 `ClusterCrossSlotError` 错误，这是因为 Celery 的某些操作需要在不同的键之间进行原子操作，而这些键可能分布在不同的槽位（slot）上。

## 解决方案

我们使用 `celery-redis-cluster` 依赖包，它提供了 `RedisClusterBackend` 类来支持 Redis 集群。当使用 `redis+cluster://` URL 格式时，Celery 会自动使用集群后端。

## 安装依赖

已经在 `requirements.txt` 中添加了必要的依赖：

```txt
celery-redis-cluster
```

安装依赖：

```bash
pip install -r requirements.txt
```

## 配置步骤

### 1. 环境变量配置

在你的 `.env` 文件中添加以下配置：

```bash
# 启用Redis集群模式
REDIS_CLUSTER_ENABLED=true

# Redis集群节点列表（替换为你的实际节点地址）
REDIS_CLUSTER_NODES=redis-node1:6379,redis-node2:6379,redis-node3:6379

# 键前缀（重要：不要修改此值）
REDIS_CLUSTER_KEY_PREFIX={celery}:

# 其他Redis配置（如果集群需要认证）
REDIS_PASSWORD=your_cluster_password
REDIS_DB_BROKER=0
REDIS_DB_RESULT=1
```

### 2. 单节点到集群的迁移

如果你当前使用单节点 Redis，迁移到集群模式：

**原配置（单节点）：**
```bash
REDIS_CLUSTER_ENABLED=false
REDIS_HOST=your-redis-host
REDIS_PORT=6379
REDIS_PASSWORD=your_password
```

**新配置（集群）：**
```bash
REDIS_CLUSTER_ENABLED=true
REDIS_CLUSTER_NODES=node1:6379,node2:6379,node3:6379
REDIS_PASSWORD=your_cluster_password
```

## 配置验证

### 1. 检查配置加载

启动服务时，你应该看到类似的日志输出：

```
[Celery] 启用Redis集群模式，节点数: 3, 键前缀: {celery}:
```

如果看到以下输出，说明配置有问题：
```
[Celery] 警告: 启用了集群模式但未找到有效节点，将使用单节点模式
```

### 2. 测试配置

启动 Celery Worker 时，你应该看到类似的日志输出：

**集群模式启用时：**
```
[Celery] Redis集群后端可用
[Celery] 启用Redis集群模式
[Celery] Broker: redis+cluster://:password@your-host:6379/0
[Celery] Backend: redis+cluster://:password@your-host:6379/1
```

**单节点模式时：**
```
[Celery] 使用Redis单节点模式
[Celery] Broker: redis://:password@your-host:6379/0
[Celery] Backend: redis://:password@your-host:6379/1
```

### 3. 启动测试

```bash
# 启动 Celery Worker
python -m app.worker_main
```

如果配置正确，Worker 应该能够成功启动而不出现 `ClusterCrossSlotError`。

## 关键配置说明

### 1. URL 格式的重要性

`redis+cluster://` URL 格式是解决集群问题的关键：

- **Broker 和 Backend** 都使用 `redis+cluster://` 前缀
- Celery 会自动识别这个格式并使用 `RedisClusterBackend`
- 集群后端会正确处理跨槽位的操作

### 2. 集群节点配置

- 至少配置 3 个节点以确保高可用性
- 节点格式：`host:port`，多个节点用逗号分隔
- 服务会自动发现集群中的其他节点

### 3. 向下兼容

- 当 `REDIS_CLUSTER_ENABLED=false` 时，服务会使用传统的单节点模式
- 现有的单节点配置无需修改

## 常见问题

### Q1: 启动时报错 "No module named 'rediscluster'"

**解决方案：** 确保已安装 `celery-redis-cluster`：
```bash
pip install celery-redis-cluster
```

### Q2: 仍然出现 ClusterCrossSlotError

**可能原因：**
1. 键前缀配置错误，检查 `REDIS_CLUSTER_KEY_PREFIX={celery}:`
2. 某些第三方库直接使用 Redis 而不是通过 Celery

**解决方案：** 确保所有 Redis 操作都通过 Celery 或使用相同的键前缀。

### Q3: 集群节点连接失败

**检查项：**
1. 网络连通性：`telnet node1 6379`
2. Redis 集群状态：`redis-cli -c -h node1 -p 6379 cluster info`
3. 认证信息是否正确

## 性能优化建议

1. **连接池大小**：根据并发需求调整 `REDIS_MAX_CONNECTIONS`
2. **节点选择**：将服务部署在靠近 Redis 集群的网络位置
3. **监控**：使用 Redis 集群监控工具观察性能指标

## 总结

通过以上配置，你的 Celery 应用将能够：

- ✅ 支持 Redis 集群模式
- ✅ 解决 cluster cross-slot 问题
- ✅ 保持向下兼容性
- ✅ 提供高可用性

如有问题，请检查日志输出并参考本文档的故障排除部分。
