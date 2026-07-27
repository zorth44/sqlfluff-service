"""
Job 状态聚合

根据子 Task 状态计算 Job 总体状态，供 Worker processor 与 JobService 共用。
"""

import logging
from typing import Iterable, List, Optional, Union

from sqlalchemy.orm import Session

from app.models.database import LintingJob, LintingTask
from app.schemas.common import JobStatusEnum, TaskStatusEnum

logger = logging.getLogger(__name__)

TERMINAL_TASK_STATUSES = frozenset(
    {TaskStatusEnum.SUCCESS, TaskStatusEnum.FAILURE}
)
ACTIVE_TASK_STATUSES = frozenset(
    {TaskStatusEnum.PENDING, TaskStatusEnum.IN_PROGRESS}
)


def is_skipped_invalid_sql_task(task: LintingTask) -> bool:
    """是否为「跳过无效 SQL 文件」的 FAILURE Task（不计入 Job 聚合）。"""
    return (
        task.status == TaskStatusEnum.FAILURE
        and bool(task.error_message)
        and "跳过无效的SQL文件" in task.error_message
    )


def filter_valid_tasks(tasks: Iterable[LintingTask]) -> List[LintingTask]:
    return [t for t in tasks if not is_skipped_invalid_sql_task(t)]


def compute_aggregate_job_status(
    tasks: Iterable[LintingTask],
) -> Optional[JobStatusEnum]:
    """
    根据 Task 列表计算 Job 聚合状态。

    规则:
    - 任一 PENDING / IN_PROGRESS → PROCESSING
    - 全部 SUCCESS → COMPLETED
    - 全部终态且 SUCCESS/FAILURE 混合 → PARTIALLY_COMPLETED
    - 全部 FAILURE → FAILED
    """
    valid = filter_valid_tasks(tasks)
    if not valid:
        return JobStatusEnum.FAILED

    statuses = [t.status for t in valid]

    if any(s in ACTIVE_TASK_STATUSES for s in statuses):
        return JobStatusEnum.PROCESSING
    if all(s == TaskStatusEnum.SUCCESS for s in statuses):
        return JobStatusEnum.COMPLETED
    if all(s in TERMINAL_TASK_STATUSES for s in statuses):
        has_success = any(s == TaskStatusEnum.SUCCESS for s in statuses)
        has_failure = any(s == TaskStatusEnum.FAILURE for s in statuses)
        if has_success and has_failure:
            return JobStatusEnum.PARTIALLY_COMPLETED
        if all(s == TaskStatusEnum.FAILURE for s in statuses):
            return JobStatusEnum.FAILED

    return JobStatusEnum.PROCESSING


def update_job_status_from_tasks(
    db: Session,
    job_id: str,
    *,
    lock: bool = True,
) -> bool:
    """
    锁定 Job 行，按 Task 聚合更新 Job 状态。

    Returns:
        True 若 Job 状态被更新；False 若无需更新或 Job 不存在。

    Raises:
        Exception: 数据库更新失败时记录日志并重新抛出。
    """
    try:
        query = db.query(LintingJob).filter(LintingJob.job_id == job_id)
        if lock:
            query = query.with_for_update()
        job = query.first()
        if not job:
            logger.warning("Job not found for status aggregation: %s", job_id)
            return False

        if job.status in (JobStatusEnum.ACCEPTED, JobStatusEnum.EXPANDING):
            # 展开阶段尚未产生 Task，或 Task 尚未开始执行，不覆盖 Job 状态
            task_count = (
                db.query(LintingTask)
                .filter(LintingTask.job_id == job_id)
                .count()
            )
            if task_count == 0:
                return False

        tasks = (
            db.query(LintingTask)
            .filter(LintingTask.job_id == job_id)
            .all()
        )
        if not tasks:
            return False

        new_status = compute_aggregate_job_status(tasks)
        if new_status is None or job.status == new_status:
            return False

        job.status = new_status
        db.commit()
        logger.info("Updated job %s status to %s", job_id, new_status)
        return True

    except Exception:
        db.rollback()
        logger.exception("Failed to update job status for %s", job_id)
        raise
