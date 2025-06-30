"""
Celery Worker服务启动入口

这是Celery Worker服务的主要入口点，负责：
- 创建Celery应用实例
- 配置任务队列和消息代理
- 启动Worker进程
- 处理异步任务
"""

import os
import sys
from app.celery_app.celery_main import celery_app
from app.config.settings import get_settings
from app.core.logging import setup_logging

settings = get_settings()


def main():
    """Worker主启动函数"""
    # 设置日志
    setup_logging()
    
    # 设置Worker参数
    worker_args = [
        'worker',
        '--loglevel=INFO',
        f'--concurrency={settings.CELERY_WORKER_CONCURRENCY}',
        '--prefetch-multiplier=1',
        '--max-tasks-per-child=1000',
        f'--hostname=worker@{os.getenv("HOSTNAME", "localhost")}',
    ]
    
    # 如果指定了队列，则只处理特定队列
    worker_queues = os.getenv('CELERY_WORKER_QUEUES')
    if worker_queues:
        worker_args.extend(['--queues', worker_queues])
    
    # 启动Worker
    print(f"Starting Celery Worker with args: {' '.join(worker_args)}")
    celery_app.worker_main(worker_args)


def create_celery_app():
    """创建Celery应用实例"""
    return celery_app


if __name__ == "__main__":
    main() 