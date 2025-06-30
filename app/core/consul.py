"""
Consul服务注册和发现

实现与Consul服务发现系统的集成，包括服务注册、注销、健康检查等功能。
支持多实例部署和负载均衡。
"""

import consul
import asyncio
import socket
from typing import Optional, Dict, Any
from datetime import datetime
import uuid

from app.core.logging import service_logger
from app.config.settings import get_settings

settings = get_settings()


class ConsulClient:
    """Consul客户端类"""
    
    def __init__(self):
        self.consul = None
        self.service_id = None
        self.service_name = "sql-linting-service"
        self.logger = service_logger
        self._init_consul_client()
        self._generate_service_id()
    
    def _init_consul_client(self):
        """初始化Consul客户端"""
        try:
            self.consul = consul.Consul(
                host=settings.CONSUL_HOST,
                port=settings.CONSUL_PORT
            )
            self.logger.info(f"Consul客户端初始化成功: {settings.CONSUL_HOST}:{settings.CONSUL_PORT}")
        except Exception as e:
            self.logger.error(f"Consul客户端初始化失败: {e}")
            raise
    
    def _generate_service_id(self):
        """生成唯一的服务实例ID"""
        hostname = socket.gethostname()
        instance_uuid = str(uuid.uuid4())[:8]
        self.service_id = f"{self.service_name}-{hostname}-{instance_uuid}"
        self.logger.info(f"生成服务实例ID: {self.service_id}")
    
    async def register_service(self) -> bool:
        """
        注册服务到Consul
        
        Returns:
            bool: 注册是否成功
        """
        try:
            if not self.consul:
                self.logger.error("Consul客户端未初始化")
                return False
            
            # 获取本机IP地址
            service_address = self._get_local_ip()
            service_port = settings.CONSUL_SERVICE_PORT
            
            # 使用TTL健康检查，服务主动报告健康状态
            # 这样就不需要远程Consul访问本地服务了
            health_check = consul.Check.ttl(
                ttl="30s"  # TTL时间，服务需要在30秒内报告一次健康状态
            )
            
            # 服务元数据
            tags = [
                "sql-linting",
                "fastapi",
                "api",
                f"version-1.0.0",
                f"environment-{settings.ENVIRONMENT}"
            ]
            
            # 注册服务
            self.consul.agent.service.register(
                name=self.service_name,
                service_id=self.service_id,
                address=service_address,
                port=service_port,
                tags=tags,
                check=health_check,
                enable_tag_override=True
            )
            
            self.logger.info(f"服务注册成功: {self.service_id} @ {service_address}:{service_port}")
            
            # 立即报告健康状态
            await self._report_health_status()
            
            return True
            
        except Exception as e:
            self.logger.error(f"服务注册失败: {e}")
            return False
    
    async def deregister_service(self) -> bool:
        """
        从Consul注销服务
        
        Returns:
            bool: 注销是否成功
        """
        try:
            if not self.consul or not self.service_id:
                self.logger.warning("Consul客户端或服务ID未设置")
                return False
            
            self.consul.agent.service.deregister(self.service_id)
            self.logger.info(f"服务注销成功: {self.service_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"服务注销失败: {e}")
            return False
    
    async def update_service_health(self, check_id: str, status: str, output: str = "") -> bool:
        """
        更新服务健康状态
        
        Args:
            check_id: 健康检查ID
            status: 状态 (passing, warning, critical)
            output: 输出信息
            
        Returns:
            bool: 更新是否成功
        """
        try:
            if not self.consul:
                return False
            
            # 使用TTL方式更新健康状态
            if status == "passing":
                self.consul.agent.check.ttl_pass(check_id, output)
            elif status == "warning":
                self.consul.agent.check.ttl_warn(check_id, output)
            else:  # critical
                self.consul.agent.check.ttl_fail(check_id, output)
                
            self.logger.debug(f"健康状态更新成功: {check_id}, 状态: {status}")
            return True
            
        except Exception as e:
            self.logger.error(f"健康状态更新失败: {e}")
            return False
    
    async def _report_health_status(self) -> bool:
        """
        报告服务健康状态到Consul
        
        Returns:
            bool: 报告是否成功
        """
        try:
            if not self.consul or not self.service_id:
                return False
            
            # 构造健康检查ID
            check_id = f"service:{self.service_id}"
            
            # 执行简单的健康检查
            is_healthy = await self._check_service_health()
            
            if is_healthy:
                self.consul.agent.check.ttl_pass(
                    check_id, 
                    f"Service {self.service_id} is healthy at {datetime.utcnow().isoformat()}"
                )
                self.logger.debug(f"健康状态报告成功: {self.service_id}")
            else:
                self.consul.agent.check.ttl_fail(
                    check_id,
                    f"Service {self.service_id} health check failed at {datetime.utcnow().isoformat()}"
                )
                self.logger.warning(f"健康状态报告失败: {self.service_id}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"健康状态报告异常: {e}")
            return False
    
    async def _check_service_health(self) -> bool:
        """
        检查服务健康状态
        
        Returns:
            bool: 服务是否健康
        """
        try:
            # 检查数据库连接
            from app.core.database import engine
            from sqlalchemy import text
            
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            
            self.logger.debug("服务健康检查通过")
            return True
        except Exception as e:
            self.logger.error(f"服务健康检查失败: {e}")
            return False
    
    async def start_health_reporting(self) -> None:
        """
        启动定期健康状态报告
        """
        if not self.service_id:
            self.logger.error("服务ID未设置，无法启动健康状态报告")
            return
        
        # 创建后台任务定期报告健康状态
        async def health_reporter():
            while True:
                try:
                    await self._report_health_status()
                    # 每20秒报告一次（TTL是30秒，留10秒缓冲时间）
                    await asyncio.sleep(20)
                except Exception as e:
                    self.logger.error(f"健康状态报告任务异常: {e}")
                    await asyncio.sleep(20)
        
        # 启动后台任务
        asyncio.create_task(health_reporter())
        self.logger.info("健康状态报告任务已启动")
    
    async def discover_services(self, service_name: str) -> list:
        """
        发现指定服务的实例
        
        Args:
            service_name: 服务名称
            
        Returns:
            list: 服务实例列表
        """
        try:
            if not self.consul:
                return []
            
            # 获取健康的服务实例
            _, services = self.consul.health.service(service_name, passing=True)
            
            instances = []
            for service in services:
                service_info = service['Service']
                instance = {
                    "id": service_info['ID'],
                    "address": service_info['Address'],
                    "port": service_info['Port'],
                    "tags": service_info['Tags'],
                    "meta": service_info.get('Meta', {})
                }
                instances.append(instance)
            
            self.logger.debug(f"发现服务实例: {service_name}, 数量: {len(instances)}")
            return instances
            
        except Exception as e:
            self.logger.error(f"服务发现失败: {e}")
            return []
    
    async def get_service_config(self, key: str) -> Optional[str]:
        """
        从Consul KV存储获取配置
        
        Args:
            key: 配置键
            
        Returns:
            Optional[str]: 配置值
        """
        try:
            if not self.consul:
                return None
            
            _, data = self.consul.kv.get(key)
            if data:
                return data['Value'].decode('utf-8')
            return None
            
        except Exception as e:
            self.logger.error(f"获取配置失败: {key}, 错误: {e}")
            return None
    
    async def set_service_config(self, key: str, value: str) -> bool:
        """
        设置Consul KV存储配置
        
        Args:
            key: 配置键
            value: 配置值
            
        Returns:
            bool: 设置是否成功
        """
        try:
            if not self.consul:
                return False
            
            success = self.consul.kv.put(key, value)
            if success:
                self.logger.info(f"配置设置成功: {key}")
            return success
            
        except Exception as e:
            self.logger.error(f"配置设置失败: {key}, 错误: {e}")
            return False
    
    def _get_local_ip(self) -> str:
        """
        获取本机IP地址
        
        Returns:
            str: IP地址
        """
        try:
            # 创建一个UDP socket连接到外部地址（不会实际发送数据）
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
            
            self.logger.debug(f"获取本机IP: {local_ip}")
            return local_ip
            
        except Exception as e:
            self.logger.warning(f"获取本机IP失败，使用默认值: {e}")
            return "127.0.0.1"
    
    async def check_consul_health(self) -> Dict[str, Any]:
        """
        检查Consul集群健康状态
        
        Returns:
            Dict[str, Any]: 健康状态信息
        """
        try:
            if not self.consul:
                return {"status": "unhealthy", "message": "Consul客户端未初始化"}
            
            # 检查Consul agent状态
            self.consul.agent.self()
            
            # 检查集群leader
            leader = self.consul.status.leader()
            
            # 检查集群成员
            members = self.consul.agent.members()
            
            health_info = {
                "status": "healthy",
                "leader": leader,
                "member_count": len(members),
                "checked_at": datetime.utcnow().isoformat()
            }
            
            self.logger.debug("Consul健康检查通过")
            return health_info
            
        except Exception as e:
            self.logger.error(f"Consul健康检查失败: {e}")
            return {
                "status": "unhealthy",
                "message": str(e),
                "checked_at": datetime.utcnow().isoformat()
            }


# 全局Consul客户端实例
consul_client = ConsulClient()


# ============= 便捷函数 =============

async def register_to_consul() -> bool:
    """注册服务到Consul"""
    return await consul_client.register_service()


async def deregister_from_consul() -> bool:
    """从Consul注销服务"""
    return await consul_client.deregister_service()


async def start_consul_health_reporting() -> None:
    """启动Consul健康状态报告"""
    await consul_client.start_health_reporting()


async def discover_service_instances(service_name: str) -> list:
    """发现服务实例"""
    return await consul_client.discover_services(service_name)


async def get_config_from_consul(key: str) -> Optional[str]:
    """从Consul获取配置"""
    return await consul_client.get_service_config(key)


async def set_config_to_consul(key: str, value: str) -> bool:
    """设置配置到Consul"""
    return await consul_client.set_service_config(key, value)


async def check_consul_status() -> Dict[str, Any]:
    """检查Consul状态"""
    return await consul_client.check_consul_health() 