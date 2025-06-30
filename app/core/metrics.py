"""
Prometheus监控指标
提供系统性能监控和业务指标收集
"""

from prometheus_client import Counter, Histogram, Gauge, start_http_server, generate_latest
import time
from typing import Dict, Any
from functools import wraps

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
    'Total number of tasks', 
    ['status', 'job_id']
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

class MetricsMiddleware:
    """FastAPI中间件，用于收集请求指标"""
    
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        start_time = time.time()
        
        # 获取请求信息
        method = scope.get("method", "UNKNOWN")
        path = scope.get("path", "/")
        
        # 执行请求
        try:
            await self.app(scope, receive, send)
            
            # 记录成功请求
            request_counter.labels(
                method=method,
                endpoint=path,
                status="200"
            ).inc()
            
        except Exception as e:
            # 记录错误请求
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
            # 记录请求时间
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

def record_task_created(status: str, job_id: str):
    """记录Task创建"""
    task_counter.labels(
        status=status,
        job_id=job_id
    ).inc()

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

# 预定义的监控装饰器
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