"""
Worker retry helpers — backoff and failure classification.

Shared by loop (lease reclaim) and processor (in-flight failures).
"""

import random
from datetime import datetime, timedelta
from typing import Optional

from app.worker.config import WorkerConfig

BACKOFF_BASE_SECONDS = 5


def compute_backoff_seconds(attempt_count: int, config: WorkerConfig) -> float:
    """指数退避 + 随机抖动，base=5s"""
    raw = min(
        config.max_backoff_seconds,
        (2 ** max(attempt_count, 1)) * BACKOFF_BASE_SECONDS,
    )
    jitter = random.uniform(0, min(5.0, raw * 0.1))
    return raw + jitter


def classify_task_failure(
    error_message: str,
    exc: Optional[BaseException] = None,
) -> str:
    """
    Classify a task failure as permanent or retryable.

    Returns:
        'permanent' | 'retryable'
    """
    msg = error_message or ""

    permanent_markers = (
        "SQL file not found",
        "跳过无效的SQL文件",
        "illegal dialect",
        "无效方言",
        "unsupported dialect",
        "不支持的方言",
    )
    lower_msg = msg.lower()
    for marker in permanent_markers:
        if marker.lower() in lower_msg or marker in msg:
            return "permanent"

    if exc is not None:
        if isinstance(exc, FileNotFoundError):
            return "permanent"

        from app.core.exceptions import SQLFluffException

        if isinstance(exc, SQLFluffException):
            detail = str(exc).lower()
            if "dialect" in detail or "方言" in detail:
                return "permanent"

        retryable_types = (ConnectionError, TimeoutError, OSError, IOError)
        if isinstance(exc, retryable_types):
            return "retryable"

        try:
            from sqlalchemy.exc import OperationalError, DBAPIError

            if isinstance(exc, (OperationalError, DBAPIError)):
                return "retryable"
        except ImportError:
            pass

        from app.core.exceptions import FileException

        if isinstance(exc, FileException):
            return "retryable"

    transient_markers = (
        "timeout",
        "timed out",
        "connection",
        "nfs",
        "database",
        "operationalerror",
        "oserror",
        "i/o",
    )
    for marker in transient_markers:
        if marker in lower_msg:
            return "retryable"

    return "retryable"


def compute_next_attempt_at(
    attempt_count: int,
    config: WorkerConfig,
) -> datetime:
    """Return UTC timestamp for the next retry attempt."""
    delay = compute_backoff_seconds(attempt_count, config)
    return datetime.utcnow() + timedelta(seconds=delay)
