"""
Prometheus监控指标
提供系统性能监控和业务指标收集
"""

from prometheus_client import Counter, Histogram, Gauge, start_http_server, generate_latest
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from functools import wraps

from sqlalchemy.orm import Session

# 定义监控指标
# 请求相关指标
request_counter = Counter(
    'sql_linting_requests_total',
    'Total number of requests',
    ['method', 'endpoint', 'status']
)

request_duration = Histogram(
    'sql_linting_request_duration_seconds',
    'Request duration in seconds',
    ['method', 'endpoint']
)

# 业务相关指标
job_counter = Counter(
    'sql_linting_jobs_total',
    'Total number of jobs',
    ['status', 'submission_type']
)

task_counter = Counter(
    'sql_linting_tasks_total',
    'Total number of tasks (legacy, includes job_id label)',
    ['status', 'job_id']
)

task_status_counter = Counter(
    'sql_linting_task_events_total',
    'Task lifecycle events without high-cardinality labels',
    ['status']
)

# 系统状态指标
active_jobs = Gauge(
    'sql_linting_active_jobs',
    'Number of active jobs'
)

active_tasks = Gauge(
    'sql_linting_active_tasks',
    'Number of active tasks'
)

# DB Queue gauges (low cardinality)
pending_task_count = Gauge(
    'sql_linting_pending_task_count',
    'Number of PENDING tasks ready to claim',
)
in_progress_task_count = Gauge(
    'sql_linting_in_progress_task_count',
    'Number of IN_PROGRESS tasks',
)
oldest_pending_age_seconds = Gauge(
    'sql_linting_oldest_pending_age_seconds',
    'Age in seconds of the oldest claimable PENDING task',
)
active_worker_count = Gauge(
    'sql_linting_active_worker_count',
    'Number of RUNNING workers with fresh heartbeat',
)

# DB Queue counters
expired_lease_count = Counter(
    'sql_linting_expired_lease_count_total',
    'Expired task leases reclaimed',
)
retry_task_count = Counter(
    'sql_linting_retry_task_count_total',
    'Tasks reset to PENDING for retry',
)
permanent_failure_count = Counter(
    'sql_linting_permanent_failure_count_total',
    'Tasks marked permanent FAILURE',
)
lease_lost_count = Counter(
    'sql_linting_lease_lost_count_total',
    'Tasks abandoned after lease loss during processing',
)

# DB Queue histograms
task_duration_seconds = Histogram(
    'sql_linting_task_duration_seconds',
    'Task processing duration in seconds',
    buckets=(1, 5, 15, 30, 60, 120, 300, 600, 900, 1800),
)
claim_duration_seconds = Histogram(
    'sql_linting_claim_duration_seconds',
    'Task claim DB operation duration in seconds',
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)
job_expansion_duration_seconds = Histogram(
    'sql_linting_job_expansion_duration_seconds',
    'Job ZIP/folder expansion duration in seconds',
    buckets=(0.5, 1, 2, 5, 10, 30, 60, 120, 300),
)

# 性能指标
sql_analysis_duration = Histogram(
    'sql_linting_analysis_duration_seconds',
    'SQL analysis duration in seconds',
    ['file_size', 'dialect']
)

zip_processing_duration = Histogram(
    'sql_linting_zip_processing_duration_seconds',
    'ZIP processing duration in seconds',
    ['file_count']
)

# 错误指标
error_counter = Counter(
    'sql_linting_errors_total',
    'Total number of errors',
    ['error_type', 'component']
)

# 资源使用指标
memory_usage = Gauge(
    'sql_linting_memory_usage_bytes',
    'Memory usage in bytes'
)

disk_usage = Gauge(
    'sql_linting_disk_usage_bytes',
    'Disk usage in bytes'
)


def collect_queue_gauges(db: Session, *, worker_heartbeat_seconds: int = 90) -> None:
    """Query queue counts and active workers; set Prometheus gauges."""
    from app.models.database import LintingTask, WorkerRegistry
    from app.schemas.common import TaskStatusEnum

    now = datetime.utcnow()
    pending = db.query(LintingTask).filter(
        LintingTask.status == TaskStatusEnum.PENDING
    ).count()
    in_progress = db.query(LintingTask).filter(
        LintingTask.status == TaskStatusEnum.IN_PROGRESS
    ).count()
    pending_task_count.set(pending)
    in_progress_task_count.set(in_progress)

    oldest = (
        db.query(LintingTask.created_at)
        .filter(LintingTask.status == TaskStatusEnum.PENDING)
        .order_by(LintingTask.created_at.asc())
        .limit(1)
        .scalar()
    )
    if oldest:
        oldest_pending_age_seconds.set(max(0.0, (now - oldest).total_seconds()))
    else:
        oldest_pending_age_seconds.set(0)

    cutoff = now - timedelta(seconds=worker_heartbeat_seconds)
    workers = db.query(WorkerRegistry).filter(
        WorkerRegistry.status == 'RUNNING',
        WorkerRegistry.heartbeat_at >= cutoff,
    ).count()
    active_worker_count.set(workers)


def record_claim_duration(seconds: float) -> None:
    claim_duration_seconds.observe(seconds)


def record_task_duration(seconds: float) -> None:
    task_duration_seconds.observe(seconds)


def record_job_expansion_duration(seconds: float) -> None:
    job_expansion_duration_seconds.observe(seconds)


def record_expired_lease() -> None:
    expired_lease_count.inc()


def record_retry_task() -> None:
    retry_task_count.inc()


def record_permanent_failure() -> None:
    permanent_failure_count.inc()


def record_lease_lost() -> None:
    lease_lost_count.inc()


class MetricsMiddleware:
    """FastAPI中间件，用于收集请求指标"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start_time = time.time()

        method = scope.get("method", "UNKNOWN")
        path = scope.get("path", "/")

        try:
            await self.app(scope, receive, send)

            request_counter.labels(
                method=method,
                endpoint=path,
                status="200"
            ).inc()

        except Exception as e:
            request_counter.labels(
                method=method,
                endpoint=path,
                status="500"
            ).inc()

            error_counter.labels(
                error_type=type(e).__name__,
                component="web"
            ).inc()

            raise
        finally:
            duration = time.time() - start_time
            request_duration.labels(
                method=method,
                endpoint=path
            ).observe(duration)


def start_metrics_server(port: int = 8001):
    """启动监控指标服务器"""
    start_http_server(port)
    print(f"Metrics server started on port {port}")


def get_metrics():
    """获取所有监控指标"""
    return generate_latest()


def record_job_created(status: str, submission_type: str):
    """记录Job创建"""
    job_counter.labels(
        status=status,
        submission_type=submission_type
    ).inc()


def record_task_created(status: str, job_id: Optional[str] = None):
    """记录Task创建（优先使用低基数 counter）"""
    task_status_counter.labels(status=status).inc()
    if job_id:
        task_counter.labels(status=status, job_id=job_id).inc()


def record_sql_analysis(duration: float, file_size: int, dialect: str):
    """记录SQL分析性能"""
    sql_analysis_duration.labels(
        file_size=str(file_size),
        dialect=dialect
    ).observe(duration)


def record_zip_processing(duration: float, file_count: int):
    """记录ZIP处理性能"""
    zip_processing_duration.labels(
        file_count=str(file_count)
    ).observe(duration)


def record_error(error_type: str, component: str):
    """记录错误"""
    error_counter.labels(
        error_type=error_type,
        component=component
    ).inc()


def update_active_jobs(count: int):
    """更新活跃Job数量"""
    active_jobs.set(count)


def update_active_tasks(count: int):
    """更新活跃Task数量"""
    active_tasks.set(count)


def update_memory_usage(bytes_used: int):
    """更新内存使用量"""
    memory_usage.set(bytes_used)


def update_disk_usage(bytes_used: int):
    """更新磁盘使用量"""
    disk_usage.set(bytes_used)


def metrics_decorator(metric_func):
    """监控装饰器，用于包装函数并记录性能指标"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                metric_func(duration)
                return result
            except Exception as e:
                record_error(type(e).__name__, func.__module__)
                raise
        return wrapper
    return decorator


sql_analysis_metrics = metrics_decorator(
    lambda duration: sql_analysis_duration.labels(
        file_size="unknown",
        dialect="unknown"
    ).observe(duration)
)

zip_processing_metrics = metrics_decorator(
    lambda duration: zip_processing_duration.labels(
        file_count="unknown"
    ).observe(duration)
)
