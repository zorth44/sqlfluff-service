"""
Redis工具类

提供Redis连接和基本操作功能，用于事件驱动架构。
"""

import redis
from typing import Optional
from app.config.settings import get_settings
from app.core.logging import service_logger

settings = get_settings()

class RedisClient:
    """Redis客户端封装类"""
    
    def __init__(self):
        self.client: Optional[redis.Redis] = None
        self.logger = service_logger
        
    def get_client(self) -> redis.Redis:
        """获取Redis客户端实例"""
        if self.client is None:
            try:
                self.client = redis.Redis.from_url(
                    settings.get_celery_broker_url(),
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    retry_on_timeout=True
                )
                # 测试连接
                self.client.ping()
                self.logger.info("Redis connection established")
            except Exception as e:
                self.logger.error(f"Failed to connect to Redis: {e}")
                raise
        
        return self.client
    
    def publish(self, channel: str, message: str) -> int:
        """发布消息到指定频道"""
        try:
            client = self.get_client()
            return client.publish(channel, message)
        except Exception as e:
            self.logger.error(f"Failed to publish message to {channel}: {e}")
            raise
    
    def subscribe(self, channels: list):
        """订阅指定频道"""
        try:
            client = self.get_client()
            pubsub = client.pubsub()
            for channel in channels:
                pubsub.subscribe(channel)
            return pubsub
        except Exception as e:
            self.logger.error(f"Failed to subscribe to channels {channels}: {e}")
            raise
    
    def close(self):
        """关闭Redis连接"""
        if self.client:
            try:
                self.client.close()
                self.logger.info("Redis connection closed")
            except Exception as e:
                self.logger.error(f"Error closing Redis connection: {e}")
            finally:
                self.client = None

# 全局Redis客户端实例
redis_client = RedisClient() 