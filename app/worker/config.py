"""
Worker 配置

定义 DB-as-Queue Worker 的所有可配置参数。
所有参数都可以通过环境变量覆盖。
"""

import os
from dataclasses import dataclass, field


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


@dataclass
class WorkerConfig:
    """Worker 配置类"""

    concurrency: int = field(
        default_factory=lambda: _env_int('WORKER_CONCURRENCY', 4)
    )
    poll_interval: float = field(
        default_factory=lambda: _env_float('WORKER_POLL_INTERVAL', 2.0)
    )
    heartbeat_interval: int = field(
        default_factory=lambda: _env_int('WORKER_HEARTBEAT_INTERVAL', 30)
    )
    zombie_timeout: int = field(
        default_factory=lambda: _env_int('WORKER_ZOMBIE_TIMEOUT', 600)
    )
    task_timeout: int = field(
        default_factory=lambda: _env_int('WORKER_TASK_TIMEOUT', 1800)
    )
    zombie_sweep_interval: int = field(
        default_factory=lambda: _env_int('WORKER_ZOMBIE_SWEEP_INTERVAL', 120)
    )
    max_retries: int = field(
        default_factory=lambda: _env_int('WORKER_MAX_RETRIES', 3)
    )
    task_lease_seconds: int = field(
        default_factory=lambda: _env_int('WORKER_TASK_LEASE_SECONDS', 120)
    )
    lease_renew_interval: int = field(
        default_factory=lambda: _env_int('WORKER_LEASE_RENEW_INTERVAL', 40)
    )
    max_backoff_seconds: int = field(
        default_factory=lambda: _env_int('WORKER_MAX_BACKOFF_SECONDS', 300)
    )
    analyze_soft_timeout: int = field(
        default_factory=lambda: _env_int('WORKER_ANALYZE_SOFT_TIMEOUT', 600)
    )
    analyze_hard_timeout: int = field(
        default_factory=lambda: _env_int('WORKER_ANALYZE_HARD_TIMEOUT', 900)
    )
    # Job 展开租约时长（秒）
    job_expansion_lease_seconds: int = field(
        default_factory=lambda: _env_int('WORKER_JOB_EXPANSION_LEASE_SECONDS', 600)
    )
    # Job 展开轮询间隔（秒）
    job_expansion_poll_interval: float = field(
        default_factory=lambda: _env_float('WORKER_JOB_EXPANSION_POLL_INTERVAL', 2.0)
    )

    def __post_init__(self) -> None:
        if self.lease_renew_interval >= self.task_lease_seconds:
            raise ValueError(
                "WORKER_LEASE_RENEW_INTERVAL must be < WORKER_TASK_LEASE_SECONDS "
                f"(got renew={self.lease_renew_interval}, "
                f"lease={self.task_lease_seconds})"
            )
        if self.analyze_soft_timeout >= self.analyze_hard_timeout:
            raise ValueError(
                "WORKER_ANALYZE_SOFT_TIMEOUT must be < WORKER_ANALYZE_HARD_TIMEOUT "
                f"(got soft={self.analyze_soft_timeout}, "
                f"hard={self.analyze_hard_timeout})"
            )
        if self.task_lease_seconds <= 0:
            raise ValueError("WORKER_TASK_LEASE_SECONDS must be > 0")
        if self.job_expansion_lease_seconds <= 0:
            raise ValueError("WORKER_JOB_EXPANSION_LEASE_SECONDS must be > 0")
