# 内网环境IP配置指南

## 概述

在内网环境中部署服务时，需要通过环境变量 `CONSUL_SERVICE_IP` 明确指定服务注册的IP地址。

## 配置方法

### 环境变量配置

**必须设置环境变量 `CONSUL_SERVICE_IP` 来指定服务注册使用的IP地址：**

```bash
# 设置环境变量
export CONSUL_SERVICE_IP=192.168.1.100

# 或在.env文件中配置
CONSUL_SERVICE_IP=192.168.1.100
```

### 获取服务器IP地址

在服务器上运行以下命令查看IP地址：

```bash
# 查看所有网络接口
ip addr show

# 或使用传统命令
ifconfig

# 查看路由表确定主要网络接口
ip route show default
```

## 部署示例

### 直接运行

```bash
# 1. 确定服务器IP地址
ip addr show

# 2. 设置环境变量
export CONSUL_SERVICE_IP=192.168.1.100

# 3. 启动服务
python -m app.web_main
```

### 容器化部署

**Docker示例：**

```bash
# 运行时指定
docker run -e CONSUL_SERVICE_IP=192.168.1.100 your-image

# 或在Dockerfile中设置
ENV CONSUL_SERVICE_IP=192.168.1.100
```

**Kubernetes示例：**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: sqlfluff-service
spec:
  template:
    spec:
      containers:
      - name: sqlfluff-service
        env:
        - name: CONSUL_SERVICE_IP
          value: "192.168.1.100"
```

### 系统服务

在systemd服务文件中设置：

```ini
[Unit]
Description=SQLFluff Service
After=network.target

[Service]
Environment=CONSUL_SERVICE_IP=192.168.1.100
ExecStart=/path/to/python -m app.web_main
Restart=always

[Install]
WantedBy=multi-user.target
```

## 验证配置

启动服务后查看日志，确认IP设置正确：

```
INFO - 使用环境变量指定的服务IP: 192.168.1.100
INFO - 服务注册成功: sql-linting-service-hostname-12345678 @ 192.168.1.100:8000
```

如果未设置环境变量，会看到错误提示：

```
ERROR - 未设置 CONSUL_SERVICE_IP 环境变量，使用默认回环地址
ERROR - 请设置环境变量: export CONSUL_SERVICE_IP=your_server_ip
```
