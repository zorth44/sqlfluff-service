"""
Worker 进程入口

用法:
    python -m app.worker.run_worker

环境变量:
    WORKER_CONCURRENCY      并发线程数（默认 4）
    WORKER_POLL_INTERVAL    轮询间隔秒数（默认 2.0）
    WORKER_HEARTBEAT_INTERVAL 心跳间隔秒数（默认 30）
    WORKER_ZOMBIE_TIMEOUT   Worker 心跳超时秒数（默认 600）
    WORKER_TASK_TIMEOUT     单任务超时秒数（默认 1800）
    WORKER_ZOMBIE_SWEEP_INTERVAL 僵尸扫描间隔秒数（默认 120）
    WORKER_MAX_RETRIES      最大重试次数（默认 3）
"""

import sys
import os
import logging

# 确保项目根目录在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)
))))

from app.core.logging import setup_logging
from app.worker.config import WorkerConfig
from app.worker.loop import start_worker


def main():
    """Worker 主入口"""
    # 初始化日志
    setup_logging()
    logger = logging.getLogger(__name__)

    # 加载配置
    config = WorkerConfig()

    logger.info("=" * 60)
    logger.info("SQLFluff DB Worker Starting")
    logger.info(f"  Concurrency: {config.concurrency}")
    logger.info(f"  Poll Interval: {config.poll_interval}s")
    logger.info(f"  Heartbeat Interval: {config.heartbeat_interval}s")
    logger.info(f"  Zombie Timeout: {config.zombie_timeout}s")
    logger.info(f"  Task Timeout: {config.task_timeout}s")
    logger.info(f"  Max Retries: {config.max_retries}")
    logger.info("=" * 60)

    # 启动 Worker
    start_worker(config)


if __name__ == "__main__":
    main()
