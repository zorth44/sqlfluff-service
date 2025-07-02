"""
事件驱动架构入口

替代传统Celery架构，通过Redis事件监听器触发任务处理。
"""

import json
import redis
from typing import Dict, Any, Callable
from app.config.settings import get_settings
from app.celery_app.tasks import process_sql_check_event
from app.core.logging import service_logger

settings = get_settings()


class CeleryEventListener:
    """Redis事件监听器，触发事件驱动任务处理"""
    
    def __init__(self):
        self.redis_client = redis.Redis.from_url(settings.get_celery_broker_url())
        self.logger = service_logger
        self.handlers = {
            'SqlCheckRequested': process_sql_check_event
        }
        
    def listen_events(self):
        """监听Redis事件并触发任务处理"""
        try:
            pubsub = self.redis_client.pubsub()
            pubsub.subscribe('sql_check_requests')
            
            self.logger.info("Event listener started, waiting for SQL check requests...")
            
            for message in pubsub.listen():
                if message['type'] == 'message':
                    try:
                        event_data = json.loads(message['data'])
                        event_type = event_data.get('event_type')
                        
                        if event_type in self.handlers:
                            self.logger.debug(f"Processing event: {event_type}")
                            # 直接调用事件处理函数（替代Celery的delay调用）
                            self.handlers[event_type](event_data)
                        else:
                            self.logger.warning(f"Unknown event type: {event_type}")
                            
                    except Exception as e:
                        self.logger.error(f"Error processing event: {e}")
                        
        except Exception as e:
            self.logger.error(f"Error in event subscription: {e}")
            raise
            
    def add_handler(self, event_type: str, handler: Callable[[Dict[str, Any]], None]):
        """添加事件处理器"""
        self.handlers[event_type] = handler
        self.logger.info(f"Added handler for event type: {event_type}")


# 全局事件监听器实例
event_listener = CeleryEventListener()

# 保持向后兼容的接口
def create_celery_app():
    """创建Celery应用实例（已废弃，返回事件监听器）"""
    service_logger.warning("create_celery_app() is deprecated - returning event listener instead")
    return event_listener
