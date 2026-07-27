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

    # Worker 心跳超时（秒）- 超过此时间无心跳的 RUNNING Worker 标记为 DEAD
    zombie_timeout: int = field(
        default_factory=lambda: int(os.getenv('WORKER_ZOMBIE_TIMEOUT', '600'))
    )

    # 单任务超时（秒）- 保留兼容，租约回收以 lease_expires_at 为准
    task_timeout: int = field(
        default_factory=lambda: int(os.getenv('WORKER_TASK_TIMEOUT', '1800'))
    )

    # 过期租约扫描间隔（秒）
    zombie_sweep_interval: int = field(
        default_factory=lambda: int(os.getenv('WORKER_ZOMBIE_SWEEP_INTERVAL', '120'))
    )

    # 最大重试次数
    max_retries: int = field(
        default_factory=lambda: int(os.getenv('WORKER_MAX_RETRIES', '3'))
    )

    # 任务租约时长（秒）
    task_lease_seconds: int = field(
        default_factory=lambda: int(os.getenv('WORKER_TASK_LEASE_SECONDS', '120'))
    )

    # 租约续期间隔（秒）
    lease_renew_interval: int = field(
        default_factory=lambda: int(os.getenv('WORKER_LEASE_RENEW_INTERVAL', '40'))
    )

    # 退避上限（秒）
    max_backoff_seconds: int = field(
        default_factory=lambda: int(os.getenv('WORKER_MAX_BACKOFF_SECONDS', '300'))
    )

    # SQLFluff 分析软超时（秒）
    analyze_soft_timeout: int = field(
        default_factory=lambda: int(os.getenv('WORKER_ANALYZE_SOFT_TIMEOUT', '600'))
    )

    # SQLFluff 分析硬超时（秒）
    analyze_hard_timeout: int = field(
        default_factory=lambda: int(os.getenv('WORKER_ANALYZE_HARD_TIMEOUT', '900'))
    )
