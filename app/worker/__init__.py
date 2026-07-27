"""Worker 包 - DB-as-Queue 任务处理引擎"""

from app.worker.config import WorkerConfig
from app.worker.loop import start_worker

__all__ = [
    'WorkerConfig',
    'start_worker',
    'process_task_safe',
    'process_job_expansion',
]


def __getattr__(name):
    if name == 'process_task_safe':
        from app.worker.processor import process_task_safe
        return process_task_safe
    if name == 'process_job_expansion':
        from app.worker.job_processor import process_job_expansion
        return process_job_expansion
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
