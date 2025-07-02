"""
事件驱动 + Celery混合架构入口

架构设计：
- Redis事件系统负责解耦和通信
- Celery任务队列负责可靠执行和企业级特性
- 结合两者优势：解耦 + 可靠性 + 扩展性
"""

import json
import redis
from typing import Dict, Any, Callable
from app.config.settings import get_settings
from app.core.logging import service_logger

settings = get_settings()


class EventDrivenCeleryListener:
    """
    事件驱动的Celery触发器
    
    工作流程：
    1. 监听Redis事件
    2. 解析事件数据
    3. 触发对应的Celery任务
    4. 利用Celery的重试、监控、并发等特性
    """
    
    def __init__(self):
        self.redis_client = redis.Redis.from_url(settings.get_celery_broker_url())
        self.logger = service_logger
        self.task_handlers = {}
        self._setup_handlers()
        
    def _setup_handlers(self):
        """设置事件到Celery任务的映射"""
        # 延迟导入避免循环依赖
        from app.celery_app.tasks import process_sql_check_event
        
        self.task_handlers = {
            'SqlCheckRequested': process_sql_check_event
        }
        
    def listen_events(self):
        """监听Redis事件并触发Celery任务"""
        try:
            pubsub = self.redis_client.pubsub()
            pubsub.subscribe('sql_check_requests')
            
            self.logger.info("🚀 Event-Driven Celery Listener started")
            self.logger.info("📡 Listening for SQL check requests...")
            self.logger.info("⚙️  Architecture: Redis Events → Celery Tasks")
            
            for message in pubsub.listen():
                if message['type'] == 'message':
                    try:
                        event_data = json.loads(message['data'])
                        event_type = event_data.get('event_type')
                        
                        if event_type in self.task_handlers:
                            job_id = event_data.get('payload', {}).get('job_id', 'unknown')
                            self.logger.info(f"📨 Received event: {event_type} (job: {job_id})")
                            
                            # 🔥 触发Celery任务 (异步执行，具备企业级特性)
                            celery_task = self.task_handlers[event_type]
                            result = celery_task.delay(event_data)  # Celery异步任务
                            
                            self.logger.info(f"🎯 Celery task dispatched: {result.id} (job: {job_id})")
                            
                        else:
                            self.logger.warning(f"❓ Unknown event type: {event_type}")
                            
                    except json.JSONDecodeError as e:
                        self.logger.error(f"❌ JSON decode error: {e}")
                    except Exception as e:
                        self.logger.error(f"❌ Error processing event: {e}")
                        
        except KeyboardInterrupt:
            self.logger.info("🛑 Event listener interrupted by user")
            raise
        except Exception as e:
            self.logger.error(f"💥 Critical error in event subscription: {e}")
            raise
            
    def add_task_handler(self, event_type: str, celery_task):
        """添加事件类型到Celery任务的映射"""
        self.task_handlers[event_type] = celery_task
        self.logger.info(f"✅ Added Celery task handler for event: {event_type}")

    def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """获取Celery任务状态"""
        try:
            # 延迟导入避免循环依赖
            from app.celery_app.tasks import get_task_status
            result = get_task_status.delay(task_id)
            return result.get(timeout=5)  # 5秒超时
        except Exception as e:
            self.logger.error(f"Error getting task status: {e}")
            return {'error': str(e)}


# 全局事件监听器实例
event_listener = EventDrivenCeleryListener()


def create_celery_app():
    """
    创建Celery应用实例
    
    Returns:
        Celery: 配置好的Celery应用实例
    """
    from app.celery_app.celery_main import celery_app
    return celery_app


# 导出接口
__all__ = ['event_listener', 'create_celery_app', 'EventDrivenCeleryListener']
