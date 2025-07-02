"""
Celery应用配置（已废弃）

此文件现在仅保留兼容性，实际Worker已迁移到事件驱动架构。
新的事件处理请参考：
- app/event_handlers/
- app/worker_main.py
"""

from app.config.settings import get_settings
from app.core.logging import setup_logging, service_logger

settings = get_settings()

# 保留兼容性的空对象
class DeprecatedCeleryApp:
    def __init__(self):
        service_logger.warning("Celery app is deprecated. Use event-driven architecture instead.")
    
    def __getattr__(self, name):
        service_logger.warning(f"Celery method '{name}' is no longer available. Use event handlers instead.")
        return None

celery_app = DeprecatedCeleryApp()

# 以下代码已移除：Celery配置、任务发现、定期任务等
# 新的架构使用Redis pub/sub进行事件驱动通信

if __name__ == '__main__':
    service_logger.error("celery_main.py is deprecated. Use 'python -m app.worker_main' instead.") 