"""
Worker 配置

定义 DB-as-Queue Worker 的所有可配置参数。
所有参数都可以通过环境变量覆盖。
"""

import os
from dataclasses import dataclass, field


@dataclass
class WorkerConfig:
    """Worker 配置类"""

    # 并发线程数（每个 Worker 进程同时处理的任务数）
    concurrency: int = field(
        default_factory=lambda: int(os.getenv('WORKER_CONCURRENCY', '4'))
    )

    # 无任务时的轮询间隔（秒）
    poll_interval: float = field(
        default_factory=lambda: float(os.getenv('WORKER_POLL_INTERVAL', '2.0'))
    )

    # Worker 心跳间隔（秒）
    heartbeat_interval: int = field(
        default_factory=lambda: int(os.getenv('WORKER_HEARTBEAT_INTERVAL', '30'))
    )

    # 僵尸任务超时（秒）- 超过此时间无心跳的 PROCESSING 任务将被回收
    zombie_timeout: int = field(
        default_factory=lambda: int(os.getenv('WORKER_ZOMBIE_TIMEOUT', '600'))
    )

    # 僵尸扫描间隔（秒）
    zombie_sweep_interval: int = field(
        default_factory=lambda: int(os.getenv('WORKER_ZOMBIE_SWEEP_INTERVAL', '120'))
    )

    # 最大重试次数
    max_retries: int = field(
        default_factory=lambda: int(os.getenv('WORKER_MAX_RETRIES', '3'))
    )
