"""
Celery应用配置

配置Celery消息队列，定义任务队列和基本设置。
为FastAPI提供异步任务派发功能。
"""

from celery import Celery
from app.config.settings import get_settings
from app.core.logging import setup_logging

settings = get_settings()

# 创建Celery应用实例
celery_app = Celery(
    "sql_linting_worker",
    broker=settings.get_celery_broker_url(),
    backend=settings.get_celery_result_backend_url(),
    include=['app.celery_app.tasks']
)

# 配置Celery
celery_app.conf.update(
    # 任务序列化
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='Asia/Shanghai',
    enable_utc=True,
    
    # 任务确认和重试
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_max_retries=3,
    task_default_retry_delay=60,
    
    # 任务路由
    task_routes={
        'app.celery_app.tasks.expand_zip_and_dispatch_tasks': {'queue': 'zip_processing'},
        'app.celery_app.tasks.process_sql_file': {'queue': 'sql_analysis'},
    },
    
    # Worker配置
    worker_max_tasks_per_child=1000,
    worker_disable_rate_limits=False,
    
    # 结果存储
    result_expires=3600,
    
    # 任务超时配置
    task_soft_time_limit=1800,  # 30分钟软超时
    task_time_limit=2100,       # 35分钟硬超时
    
    # 任务重试配置
    task_retry_jitter=True,
    task_retry_backoff=True,
    task_retry_backoff_max=700,
    
    # 连接池配置
    broker_pool_limit=10,
    broker_connection_retry_on_startup=True,
    
    # 监控配置
    worker_send_task_events=True,
    task_send_sent_event=True,
)

# 任务自动发现
celery_app.autodiscover_tasks(['app.celery_app'])

@celery_app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    """配置定期任务（如果需要）"""
    # 可以在这里添加定期任务，如清理临时文件等
    pass

# 启动时初始化
@celery_app.on_after_configure.connect
def setup_celery_logging(sender, **kwargs):
    """设置Celery日志"""
    setup_logging()

if __name__ == '__main__':
    celery_app.start() 