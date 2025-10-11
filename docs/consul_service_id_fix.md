# Consul 服务实例ID修复说明

## 问题描述

### 现象
重启服务后，Consul 服务监控界面中会不断新增带有不同 ID 的 `sql-linting-service` 实例，即使 IP 和端口不变。每个实例表现为"所有服务检查失败"，同时老的与新的实例都会保留在列表中。

### 原因分析

**核心问题**：服务实例ID生成方式不当

原代码使用 `uuid.uuid4()` 生成随机ID：
```python
# 旧代码
instance_uuid = str(uuid.uuid4())[:8]
self.service_id = f"{self.service_name}-{hostname}-{instance_uuid}"
```

这导致：
1. **每次重启生成不同ID**：即使在同一台机器上，重启后ID都会变化
   - 第一次：`sql-linting-service-server1-a1b2c3d4`
   - 第二次：`sql-linting-service-server1-e5f6g7h8`
   
2. **旧实例无法被覆盖**：Consul 认为是不同的服务实例，新实例无法覆盖旧实例

3. **注销逻辑失效**：
   - 进程被强制终止（kill -9、断电等）时，shutdown hook 不会执行
   - 即使执行注销，也只能注销当前ID，无法清理历史遗留实例

4. **健康检查全部失败**：旧实例服务已停止，TTL 健康检查超时，显示为失败状态

## 解决方案

### 1. 修改服务实例ID生成策略

**新策略**：使用 `服务名-主机名-端口号` 的固定格式

```python
# 新代码
hostname = socket.gethostname()
port = settings.CONSUL_SERVICE_PORT
self.service_id = f"{self.service_name}-{hostname}-{port}"
```

**优点**：
- ✅ 重启后ID保持不变，新实例会自动覆盖旧实例
- ✅ 支持多机部署（不同主机名）
- ✅ 支持同机多实例（不同端口）
- ✅ 清晰明了，便于运维识别

**示例**：
- 服务器A：`sql-linting-service-server-a-8000`
- 服务器B：`sql-linting-service-server-b-8000`
- 服务器A（第二个实例）：`sql-linting-service-server-a-8001`

### 2. 添加自动注销机制

在健康检查配置中添加 `deregister_critical_service_after` 参数：

```python
health_check = consul.Check.ttl(
    ttl="30s",
    deregister_critical_service_after="5m"  # 健康检查持续失败5分钟后自动注销
)
```

**作用**：
- 如果服务意外终止（未正常注销），健康检查会持续失败
- 5分钟后，Consul 会自动注销该服务实例
- 避免僵尸实例长期保留

### 3. 支持手动指定服务ID（可选）

添加环境变量 `CONSUL_SERVICE_ID` 支持手动指定：

```bash
# 在 .env 文件中
CONSUL_SERVICE_ID=sql-linting-service-custom-id
```

**适用场景**：
- 容器化部署，主机名可能变化
- 特殊的命名需求
- 测试和调试

## 升级步骤

### 步骤1：清理现有的垃圾实例

**方法一：通过 Consul UI**
1. 访问 Consul UI：`http://consul-server:8500/ui`
2. 进入 Services → sql-linting-service
3. 手动注销所有失败的旧实例

**方法二：通过 API**
```bash
# 1. 查看所有实例
curl http://consul-server:8500/v1/agent/services | jq

# 2. 注销指定实例（替换 service-id）
curl -X PUT http://consul-server:8500/v1/agent/service/deregister/sql-linting-service-xxxx-yyyy
```

**方法三：使用脚本批量清理**
```bash
#!/bin/bash
# cleanup_consul_instances.sh

CONSUL_HOST="your-consul-host"
CONSUL_PORT=8500
SERVICE_NAME="sql-linting-service"

# 获取所有服务实例
instances=$(curl -s "http://${CONSUL_HOST}:${CONSUL_PORT}/v1/agent/services" | jq -r "to_entries[] | select(.value.Service == \"${SERVICE_NAME}\") | .key")

echo "找到以下实例："
echo "$instances"
echo ""
echo "是否全部注销？(y/n)"
read confirm

if [ "$confirm" = "y" ]; then
    for instance in $instances; do
        echo "注销实例: $instance"
        curl -X PUT "http://${CONSUL_HOST}:${CONSUL_PORT}/v1/agent/service/deregister/${instance}"
    done
    echo "清理完成"
else
    echo "已取消"
fi
```

### 步骤2：更新代码

代码已经更新，包括：
- `app/core/consul.py`：修改 `_generate_service_id` 方法
- `app/config/settings.py`：添加 `CONSUL_SERVICE_ID` 配置项
- `env.example`：添加配置说明

### 步骤3：重新部署服务

```bash
# 1. 拉取最新代码
git pull origin <branch-name>

# 2. 重启 Web 服务
./scripts/stop_web.sh
./scripts/start_web.sh

# 或使用 systemd
systemctl restart sqlfluff-web
```

### 步骤4：验证部署

```bash
# 1. 检查服务日志，确认生成的服务ID
tail -f /var/log/sqlfluff-service.log | grep "生成服务实例ID"

# 预期输出：
# 生成服务实例ID: sql-linting-service-your-hostname-8000

# 2. 检查 Consul 注册状态
curl http://consul-server:8500/v1/agent/services | jq '.["sql-linting-service-your-hostname-8000"]'

# 3. 重启服务，验证ID不变
./scripts/stop_web.sh
./scripts/start_web.sh
tail -f /var/log/sqlfluff-service.log | grep "生成服务实例ID"

# 应该看到相同的服务ID
```

### 步骤5：验证自动注销功能（可选）

```bash
# 1. 启动服务
./scripts/start_web.sh

# 2. 强制终止服务（模拟异常退出）
kill -9 $(pgrep -f "app.web_main")

# 3. 等待5分钟，检查 Consul
# 服务应该会自动从 Consul 注销
```

## 注意事项

### 1. 多机部署
确保每台服务器的主机名不同：
```bash
# 检查主机名
hostname

# 如果需要修改
hostnamectl set-hostname server-a
```

### 2. 同机多实例
如果在同一台机器上运行多个实例，必须使用不同的端口：
```bash
# 实例1
export CONSUL_SERVICE_PORT=8000
./scripts/start_web.sh

# 实例2  
export CONSUL_SERVICE_PORT=8001
./scripts/start_web.sh
```

### 3. 容器化部署
如果使用 Docker/Kubernetes，主机名可能是随机的，建议手动指定服务ID：
```yaml
# docker-compose.yml
environment:
  - CONSUL_SERVICE_ID=sql-linting-service-container-1
```

### 4. 健康检查时间
- TTL：30秒（服务每20秒报告一次心跳）
- 自动注销时间：5分钟（可根据需要调整）

如需调整，修改 `app/core/consul.py` 中的配置：
```python
health_check = consul.Check.ttl(
    ttl="30s",
    deregister_critical_service_after="5m"  # 可调整为 "10m"、"1h" 等
)
```

## 技术对比

### Spring Cloud vs 当前实现

| 特性 | Spring Cloud (Eureka) | 当前实现 (Consul) |
|------|----------------------|------------------|
| 实例ID格式 | `service:port` | `service-hostname-port` |
| 实例区分 | 通过 IP + Port | 通过 instance_id |
| ID唯一性 | 可重复（通过IP区分） | 必须全局唯一 |
| 多机部署 | ✅ 支持 | ✅ 支持 |
| 自动注销 | ✅ 支持 | ✅ 支持 |

**选择原因**：
- Consul 要求 `service_id` 全局唯一，后注册的会覆盖先注册的
- 添加主机名确保多机部署时ID不冲突
- 去除随机UUID确保重启后ID稳定

## 监控与排查

### 查看当前注册的服务
```bash
curl http://consul-server:8500/v1/catalog/service/sql-linting-service | jq
```

### 查看服务健康状态
```bash
curl http://consul-server:8500/v1/health/service/sql-linting-service | jq
```

### 查看特定实例
```bash
curl http://consul-server:8500/v1/agent/service/sql-linting-service-hostname-8000 | jq
```

## 参考资料

- [Consul Service Registration](https://developer.hashicorp.com/consul/docs/services/usage/register-services-checks)
- [Consul Health Checks](https://developer.hashicorp.com/consul/docs/services/usage/checks)
- [Consul TTL Checks](https://developer.hashicorp.com/consul/docs/services/usage/checks#ttl)

---

**更新时间**：2025-10-11  
**版本**：1.0.0  
**作者**：系统架构团队

