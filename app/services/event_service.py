"""
事件服务

提供Redis事件发布和订阅功能，是Worker与外部系统通信的核心接口。
"""

import json
import redis
from typing import Dict, Any
from app.models.events import BaseEvent
from app.config.settings import get_settings
from app.core.logging import service_logger

settings = get_settings()

class EventService:
    def __init__(self):
        self.redis_client = redis.Redis.from_url(settings.get_celery_broker_url())
        self.logger = service_logger
    
    def publish_event(self, topic: str, event: BaseEvent):
        """发布事件到Redis"""
        try:
            event_data = {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "timestamp": event.timestamp,
                "correlation_id": event.correlation_id,
                "payload": event.payload
            }
            
            self.redis_client.publish(topic, json.dumps(event_data))
            self.logger.info(f"Published event {event.event_type} to {topic}")
            
        except Exception as e:
            self.logger.error(f"Failed to publish event: {e}")
            raise
    
    def subscribe_events(self, topics: list, callback):
        """订阅事件"""
        try:
            pubsub = self.redis_client.pubsub()
            for topic in topics:
                pubsub.subscribe(topic)
            
            for message in pubsub.listen():
                if message['type'] == 'message':
                    try:
                        event_data = json.loads(message['data'])
                        callback(message['channel'].decode(), event_data)
                    except Exception as e:
                        self.logger.error(f"Error processing event: {e}")
                        
        except Exception as e:
            self.logger.error(f"Error in event subscription: {e}")
            raise