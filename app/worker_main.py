"""
DB-as-Queue Worker 启动入口

启动基于数据库任务队列的 Worker 进程。
Worker 通过 SELECT ... FOR UPDATE SKIP LOCKED 原子领取任务，
不再依赖 Celery 或 Redis。
"""

import os
import sys
from app.config.settings import get_settings
from app.core.logging import setup_logging
from app.worker.config import WorkerConfig
from app.worker.loop import start_worker


def main():
    """Worker主启动函数"""
    # 设置日志
    setup_logging()

    # 加载配置
    settings = get_settings()
    config = WorkerConfig()

    print(f"Starting DB-as-Queue Worker...")
    print(f"  Worker Concurrency: {config.concurrency}")
    print(f"  Poll Interval: {config.poll_interval}s")
    print(f"  Heartbeat Interval: {config.heartbeat_interval}s")
    print(f"  Zombie Timeout: {config.zombie_timeout}s")
    print(f"  Max Retries: {config.max_retries}")

    # 启动 DB Worker
    start_worker(config)


if __name__ == "__main__":
    main() 