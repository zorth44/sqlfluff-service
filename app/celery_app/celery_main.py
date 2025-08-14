"""
Celery应用配置

配置Celery消息队列，定义任务队列和基本设置。
为FastAPI提供异步任务派发功能。
支持Redis集群模式，解决cross-slot问题。
"""

from celery import Celery
from app.config.settings import get_settings
from app.core.logging import setup_logging

settings = get_settings()

# 如果启用了集群模式，确保集群后端可用
if settings.REDIS_CLUSTER_ENABLED:
    try:
        from app.third_party.celery_redis_cluster_backend import RedisClusterBackend
        print("[Celery] Redis集群后端可用")
    except ImportError as e:
        print(f"[Celery] 警告: 无法导入集群后端: {e}")
        print("[Celery] redis-py 5.0.1 原生支持集群，无需额外依赖")

# 创建Celery应用实例
# 根据集群配置自动选择正确的URL格式
if settings.REDIS_CLUSTER_ENABLED:
    # 集群模式：broker使用标准redis连接，backend使用自定义集群backend
    broker_url = settings.get_celery_broker_url()  # broker使用标准连接
    backend_url = settings.get_celery_result_backend_url()  # 占位URL，实际由自定义backend处理
else:
    # 单节点模式：使用标准URL
    broker_url = settings.get_celery_broker_url()
    backend_url = settings.get_celery_result_backend_url()

celery_app = Celery(
    "sql_linting_worker",
    broker=broker_url,
    backend=backend_url,
    include=['app.celery_app.tasks']
)

# 基础配置
base_config = {
    # 任务序列化
    'task_serializer': 'json',
    'accept_content': ['json'],
    'result_serializer': 'json',
    'timezone': 'Asia/Shanghai',
    'enable_utc': True,
    
    # 任务确认和重试
    'task_acks_late': True,
    'worker_prefetch_multiplier': 1,
    'task_max_retries': 3,
    'task_default_retry_delay': 60,
    
    # 任务路由
    'task_routes': {
        'app.celery_app.tasks.expand_zip_and_dispatch_tasks': {'queue': 'zip_processing'},
        'app.celery_app.tasks.process_sql_file': {'queue': 'sql_analysis'},
    },
    
    # Worker配置
    'worker_max_tasks_per_child': 1000,
    'worker_disable_rate_limits': False,
    
    # 结果存储
    'result_expires': 3600,
    
    # 任务超时配置
    'task_soft_time_limit': 1800,  # 30分钟软超时
    'task_time_limit': 2100,       # 35分钟硬超时
    
    # 任务重试配置
    'task_retry_jitter': True,
    'task_retry_backoff': True,
    'task_retry_backoff_max': 700,
    
    # 连接池配置
    'broker_pool_limit': 10,
    'broker_connection_retry_on_startup': True,
    
    # 监控配置（集群模式下会被覆盖）
    'worker_send_task_events': True,
    'task_send_sent_event': True,
    
    # Redis集群兼容性配置 - 禁用需要管道的功能  
    'task_always_eager': False,
}

# Redis集群特殊配置
if settings.REDIS_CLUSTER_ENABLED:
    # 添加集群模式下的特殊配置
    cluster_config = {
        # 使用自定义的Redis集群结果后端
        'result_backend': 'app.third_party.celery_redis_cluster_backend.redis_cluster.RedisClusterBackend',
        
        # Redis集群配置
        'redis_cluster_settings': settings.get_celery_redis_cluster_settings(),
        
        # 关键：完全禁用 worker 远程控制以避免 pidbox 跨槽操作
        'worker_enable_remote_control': False,
        'worker_send_task_events': False,
        'task_send_sent_event': False,
        
        # 禁用 mingle 和其他导致跨槽的功能  
        'worker_direct': True,
        'worker_disable_rate_limits': True,
        
        # 禁用管道操作，避免集群中的MovedError
        'broker_transport_options': {
            # 关键：强制禁用所有管道操作
            'master_name': None,
            'db': settings.REDIS_DB_BROKER,
            # 使用集群键前缀确保所有键在同一个哈希槽
            'global_keyprefix': settings.REDIS_CLUSTER_KEY_PREFIX,
            'keyprefix_queue': settings.REDIS_CLUSTER_KEY_PREFIX + 'queue:',
            'keyprefix_routing': settings.REDIS_CLUSTER_KEY_PREFIX + 'routing:',
            'unacked_key': settings.REDIS_CLUSTER_KEY_PREFIX + 'unacked',
            'unacked_index_key': settings.REDIS_CLUSTER_KEY_PREFIX + 'unacked_index',
            'unacked_mutex_key': settings.REDIS_CLUSTER_KEY_PREFIX + 'unacked_mutex',
            'unacked_mutex_expire': 300,
            'visibility_timeout': 3600,
            # 完全禁用管道相关功能
            'fanout_prefix': False,  # 禁用 fanout
            'fanout_patterns': False,  # 禁用 fanout 模式
            # 集群相关配置
            'retry_on_timeout': True,
            'socket_keepalive': True,
            'socket_keepalive_options': {},
            'health_check_interval': 30,
            # 连接池配置 - 限制连接数避免管道
            'connection_pool_kwargs': {
                'retry_on_timeout': True,
                'health_check_interval': 30,
                'socket_connect_timeout': 5,
                'socket_timeout': 5,
            },
            # 强制单连接模式，避免管道
            'max_connections': 1,
        },
        # Result Backend配置 - 也需要禁用管道
        'result_backend_transport_options': {
            'retry_on_timeout': True,
            'health_check_interval': 30,
            'socket_connect_timeout': 5,
            'socket_timeout': 5,
        }
    }
    base_config.update(cluster_config)
    print("[Celery] 已配置Redis集群优化选项（禁用管道操作，使用自定义集群后端）")

# 配置Celery
celery_app.conf.update(**base_config)


# 打印当前配置信息
if settings.REDIS_CLUSTER_ENABLED:
    print(f"[Celery] 启用Redis集群模式")
    print(f"[Celery] Broker: {broker_url}")
    print(f"[Celery] Backend: {backend_url}")
else:
    print("[Celery] 使用Redis单节点模式")
    print(f"[Celery] Broker: {broker_url}")
    print(f"[Celery] Backend: {backend_url}")

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