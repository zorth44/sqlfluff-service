"""
事件驱动 + Celery混合架构配置

架构特点：
- 通过Redis事件触发Celery任务，实现解耦
- 保留Celery的企业级特性：可靠性、并发、监控、重试
- 支持水平扩展和负载均衡
"""

from celery import Celery
from app.config.settings import get_settings
from app.core.logging import setup_logging, service_logger

settings = get_settings()

def create_celery_app() -> Celery:
    """创建并配置Celery应用实例"""
    
    celery_app = Celery(
        "sqlfluff_worker",
        broker=settings.get_celery_broker_url(),
        backend=settings.get_celery_result_backend_url(),
        include=['app.celery_app.tasks']
    )
    
    # Celery配置
    celery_app.conf.update(
        # 任务执行配置
        task_serializer='json',
        accept_content=['json'],
        result_serializer='json',
        timezone='UTC',
        enable_utc=True,
        
        # 任务路由和队列
        task_default_queue='sql_check_queue',
        task_routes={
            'app.celery_app.tasks.process_sql_check_event': {'queue': 'sql_check_queue'},
        },
        
        # 并发和性能
        worker_concurrency=4,  # 并发进程数
        worker_prefetch_multiplier=1,  # 预取任务数
        worker_max_tasks_per_child=1000,  # 每个子进程最大任务数
        
        # 可靠性配置
        task_acks_late=True,  # 任务完成后才确认
        worker_disable_rate_limits=False,
        task_reject_on_worker_lost=True,
        
        # 重试配置
        task_default_retry_delay=60,  # 默认重试延迟60秒
        task_max_retries=3,  # 最大重试次数
        
        # 结果存储配置
        result_expires=3600,  # 结果保留1小时
        result_cache_max=10000,
        
        # 监控配置
        worker_send_task_events=True,
        task_send_sent_event=True,
        
        # 安全配置
        worker_hijack_root_logger=False,
        worker_log_format='[%(asctime)s: %(levelname)s/%(processName)s] %(message)s',
        worker_task_log_format='[%(asctime)s: %(levelname)s/%(processName)s][%(task_name)s(%(task_id)s)] %(message)s',
        
        # 其他配置
        beat_schedule={},  # 不使用定时任务
        broker_connection_retry_on_startup=True,
    )
    
    # 设置日志
    setup_logging()
    
    return celery_app


# 创建全局Celery应用实例
celery_app = create_celery_app()

# 自动发现任务
celery_app.autodiscover_tasks(['app.celery_app'])

service_logger.info("Celery app configured for event-driven architecture")

if __name__ == '__main__':
    service_logger.error("celery_main.py is deprecated. Use 'python -m app.worker_main' instead.") 