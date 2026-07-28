"""
Job 处理器

负责 Worker 侧 Job 展开：ZIP 解压、文件夹遍历、创建 PENDING Tasks。
展开过程带租约，崩溃后可由 sweeper 回收回 ACCEPTED。
"""

import os
import time
import uuid
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.database import LintingJob, LintingTask
from app.utils.file_utils import FileManager
from app.utils.uuid_utils import generate_task_id
from app.schemas.common import JobStatusEnum, TaskStatusEnum, SubmissionTypeEnum
from app.worker.config import WorkerConfig

logger = logging.getLogger(__name__)


class JobExpansionError(Exception):
    """Job 展开失败基类"""

    def __init__(self, message: str, *, permanent: bool = True):
        super().__init__(message)
        self.permanent = permanent


class JobExpansionLeaseLostError(Exception):
    """Raised when this worker no longer owns the Job expansion lease."""


def _clear_expansion_lease(job: LintingJob) -> None:
    job.expansion_lease_token = None
    job.expansion_lease_expires_at = None
    job.expansion_started_at = None


# ───────────────────── Claim ─────────────────────

def claim_job_for_expansion(
    db: Session,
    lease_seconds: Optional[int] = None,
) -> Optional[LintingJob]:
    """
    原子领取一个 ACCEPTED Job 用于展开（ACCEPTED → EXPANDING）。

    使用 FOR UPDATE SKIP LOCKED，仅一个 Worker 能成功领取，并签发展开租约。
    """
    if lease_seconds is None:
        lease_seconds = WorkerConfig().job_expansion_lease_seconds

    try:
        now = db.execute(select(func.now())).scalar() or datetime.utcnow()
    except Exception:
        now = datetime.utcnow()

    job = (
        db.query(LintingJob)
        .filter(LintingJob.status == JobStatusEnum.ACCEPTED)
        .order_by(LintingJob.created_at.asc(), LintingJob.id.asc())
        .with_for_update(skip_locked=True)
        .first()
    )
    if not job:
        return None

    job.status = JobStatusEnum.EXPANDING
    job.expansion_lease_token = uuid.uuid4().hex
    job.expansion_lease_expires_at = now + timedelta(seconds=lease_seconds)
    job.expansion_started_at = now
    job.error_message = None
    db.flush()
    logger.info("Claimed job %s for expansion", job.job_id)
    return job


def reclaim_expired_job_expansions(
    db: Session,
    config: Optional[WorkerConfig] = None,
) -> int:
    """
    回收过期的 EXPANDING Job，重置为 ACCEPTED 以便重新展开。

    若已有部分 Task，保留 Task；下次展开会幂等跳过已存在路径。
    """
    if config is None:
        config = WorkerConfig()

    candidates = (
        db.query(LintingJob)
        .filter(
            LintingJob.status == JobStatusEnum.EXPANDING,
            LintingJob.expansion_lease_expires_at.isnot(None),
            LintingJob.expansion_lease_expires_at < func.now(),
        )
        .with_for_update(skip_locked=True)
        .all()
    )

    reclaimed = 0
    for job in candidates:
        reason = (
            f"展开租约过期（expansion_lease_expires_at="
            f"{job.expansion_lease_expires_at}）"
        )
        job.status = JobStatusEnum.ACCEPTED
        job.error_message = reason
        _clear_expansion_lease(job)
        reclaimed += 1
        logger.warning("Reclaimed stuck EXPANDING job %s: %s", job.job_id, reason)

    if reclaimed:
        logger.info("Job expansion sweep: %d jobs reset to ACCEPTED", reclaimed)
    return reclaimed


# ───────────────────── Entry Point ─────────────────────

def process_job_expansion(db: Session, job: LintingJob) -> Dict[str, Any]:
    """
    展开 Job（调用方已通过 claim 将状态置为 EXPANDING）。

    幂等：若已有 Task 且 Job 已在 PROCESSING，跳过；
    若 EXPANDING 且已有 Task，补全后转 PROCESSING。
    """
    start = time.monotonic()
    job_id = job.job_id
    lease_token = job.expansion_lease_token

    try:
        try:
            from app.core.metrics import record_job_expansion_duration
        except ImportError:
            record_job_expansion_duration = None

        # 先确认租约仍归当前 Worker 所有。失败时必须回滚并停止展开，
        # 否则外层 managed_db_session 会提交失去所有权后创建的 Task。
        if not lease_token or not _renew_expansion_lease(
            db, job_id, lease_token
        ):
            raise JobExpansionLeaseLostError(
                f"Expansion lease lost for job {job_id} before processing"
            )

        existing_count = (
            db.query(LintingTask)
            .filter(LintingTask.job_id == job_id)
            .count()
        )

        if job.status == JobStatusEnum.PROCESSING and existing_count > 0:
            logger.info("Job %s already processing with tasks, skipping", job_id)
            return {
                "status": "skipped",
                "job_id": job_id,
                "reason": "Already processing",
            }

        if existing_count > 0:
            job = _finish_expansion(db, job_id, lease_token, JobStatusEnum.PROCESSING)
            if not job:
                raise JobExpansionLeaseLostError(
                    f"Expansion lease lost for job {job_id} before finish"
                )
            logger.info(
                "Job %s has %d existing tasks, marked PROCESSING",
                job_id,
                existing_count,
            )
            return {
                "status": "skipped",
                "job_id": job_id,
                "reason": "Tasks already exist",
                "total_tasks": existing_count,
            }

        if job.submission_type == SubmissionTypeEnum.SINGLE_FILE:
            task_ids = _handle_single_file_job(db, job)
        else:
            task_ids = _handle_archive_job(db, job)

        job = _finish_expansion(db, job_id, lease_token, JobStatusEnum.PROCESSING)
        if not job:
            raise JobExpansionLeaseLostError(
                f"Expansion lease lost for job {job_id} before finish"
            )

        duration = time.monotonic() - start
        if record_job_expansion_duration:
            record_job_expansion_duration(duration)

        logger.info(
            "Job expansion complete: %s, created %d PENDING tasks",
            job_id,
            len(task_ids),
        )
        return {
            "status": "success",
            "job_id": job_id,
            "total_tasks": len(task_ids),
            "task_ids": task_ids,
        }

    except JobExpansionLeaseLostError as e:
        # 这是 fencing 失败而不是业务失败。必须回滚本次展开创建的 Task，
        # 且不能修改已由其他 Worker 持有的 Job。
        db.rollback()
        logger.warning("Abandoned job expansion for %s: %s", job_id, e)
        return {
            "status": "abandoned",
            "job_id": job_id,
            "reason": "expansion lease lost",
        }

    except JobExpansionError as e:
        db.rollback()
        _fail_or_retry_expansion(db, job_id, lease_token, e, permanent=e.permanent)
        logger.error("Job expansion failed for %s: %s", job_id, e)
        return {"status": "failed", "job_id": job_id, "error": str(e)}

    except Exception as e:
        db.rollback()
        _fail_or_retry_expansion(db, job_id, lease_token, e, permanent=True)
        logger.exception("Unexpected job expansion error for %s", job_id)
        return {"status": "failed", "job_id": job_id, "error": str(e)}


def _renew_expansion_lease(
    db: Session,
    job_id: str,
    lease_token: str,
    lease_seconds: Optional[int] = None,
) -> bool:
    if lease_seconds is None:
        lease_seconds = WorkerConfig().job_expansion_lease_seconds
    try:
        now = db.execute(select(func.now())).scalar() or datetime.utcnow()
    except Exception:
        now = datetime.utcnow()

    updated = (
        db.query(LintingJob)
        .filter(
            LintingJob.job_id == job_id,
            LintingJob.status == JobStatusEnum.EXPANDING,
            LintingJob.expansion_lease_token == lease_token,
        )
        .update(
            {
                LintingJob.expansion_lease_expires_at: now + timedelta(
                    seconds=lease_seconds
                ),
            },
            synchronize_session=False,
        )
    )
    return updated == 1


def _finish_expansion(
    db: Session,
    job_id: str,
    lease_token: Optional[str],
    new_status: JobStatusEnum,
) -> Optional[LintingJob]:
    """带 fencing 的展开完成更新。"""
    filters = [
        LintingJob.job_id == job_id,
        LintingJob.status == JobStatusEnum.EXPANDING,
    ]
    if lease_token:
        filters.append(LintingJob.expansion_lease_token == lease_token)

    job = db.query(LintingJob).filter(*filters).with_for_update().first()
    if not job:
        logger.warning("Job %s expansion lease lost before finish", job_id)
        return None

    job.status = new_status
    _clear_expansion_lease(job)
    db.commit()
    return job


def _fail_or_retry_expansion(
    db: Session,
    job_id: str,
    lease_token: Optional[str],
    error: Exception,
    *,
    permanent: bool,
) -> None:
    filters = [LintingJob.job_id == job_id]
    if lease_token:
        filters.extend([
            LintingJob.status == JobStatusEnum.EXPANDING,
            LintingJob.expansion_lease_token == lease_token,
        ])

    job = (
        db.query(LintingJob)
        .filter(*filters)
        .with_for_update()
        .first()
    )
    if not job:
        logger.warning(
            "Job %s expansion lease lost before failure update", job_id
        )
        return

    if permanent:
        job.status = JobStatusEnum.FAILED
    else:
        job.status = JobStatusEnum.ACCEPTED
    job.error_message = str(error)
    _clear_expansion_lease(job)
    db.commit()


def try_expand_one_job(db: Session) -> Optional[Dict[str, Any]]:
    """领取并展开一个 ACCEPTED Job；无 Job 时返回 None。"""
    job = claim_job_for_expansion(db)
    if not job:
        return None
    db.commit()
    return process_job_expansion(db, job)


# ───────────────────── Step Functions ─────────────────────

def _handle_single_file_job(db: Session, job: LintingJob) -> List[str]:
    """单文件 Job：验证文件并创建 PENDING Task。"""
    file_manager = FileManager()

    existing = (
        db.query(LintingTask)
        .filter(LintingTask.job_id == job.job_id)
        .first()
    )
    if existing:
        return [existing.task_id]

    if not file_manager.file_exists(job.source_path):
        raise JobExpansionError(
            f"SQL file not found: {job.source_path}",
            permanent=True,
        )

    task_id = generate_task_id()
    task = LintingTask(
        task_id=task_id,
        job_id=job.job_id,
        status=TaskStatusEnum.PENDING,
        source_file_path=job.source_path,
    )
    db.add(task)
    db.flush()
    return [task_id]


def _handle_archive_job(db: Session, job: LintingJob) -> List[str]:
    """ZIP 或已解压文件夹 Job。"""
    file_manager = FileManager()
    source_full = file_manager.get_absolute_path(job.source_path)

    if source_full.is_dir():
        return _handle_extracted_folder_job(db, job, file_manager)
    return _handle_zip_file_job(db, job, file_manager)


def _handle_extracted_folder_job(
    db: Session, job: LintingJob, file_manager: FileManager
) -> List[str]:
    try:
        sql_files = file_manager.list_sql_files(job.source_path)
        logger.info(
            "Found %d SQL files in folder for job %s",
            len(sql_files),
            job.job_id,
        )
    except OSError as e:
        raise JobExpansionError(
            f"Failed to list SQL files (transient): {e}",
            permanent=False,
        ) from e
    except Exception as e:
        raise JobExpansionError(
            f"Failed to list SQL files: {e}",
            permanent=True,
        ) from e

    if not sql_files:
        raise JobExpansionError(
            "No SQL files found in folder",
            permanent=True,
        )

    return _create_task_records(db, job, sql_files, job.source_path)


def _handle_zip_file_job(
    db: Session, job: LintingJob, file_manager: FileManager
) -> List[str]:
    if not file_manager.file_exists(job.source_path):
        raise JobExpansionError(
            f"ZIP file not found: {job.source_path}",
            permanent=True,
        )

    extract_to = f"jobs/{job.job_id}/extracted"
    try:
        _, sql_files = file_manager.extract_zip_file(
            job.source_path, extract_to
        )
        logger.info(
            "Extracted %d SQL files from ZIP for job %s",
            len(sql_files),
            job.job_id,
        )
    except OSError as e:
        raise JobExpansionError(
            f"ZIP extraction failed (transient): {e}",
            permanent=False,
        ) from e
    except Exception as e:
        raise JobExpansionError(
            f"ZIP extraction failed: {e}",
            permanent=True,
        ) from e

    if not sql_files:
        raise JobExpansionError(
            "No SQL files found in ZIP",
            permanent=True,
        )

    # extract_zip_file() 返回的 sql_files 已是相对于 NFS 根目录的完整路径
    return _create_task_records(db, job, sql_files, None)


def _create_task_records(
    db: Session,
    job: LintingJob,
    file_paths: List[str],
    root_path: Optional[str] = None,
) -> List[str]:
    """批量创建 PENDING Task（按 source_file_path 去重，支持部分展开续跑）。"""
    existing_paths = {
        t.source_file_path
        for t in db.query(LintingTask)
        .filter(LintingTask.job_id == job.job_id)
        .all()
    }

    task_ids: List[str] = []
    for file_path in file_paths:
        if root_path:
            full_path = os.path.join(root_path, file_path).replace("\\", "/")
        else:
            full_path = file_path

        if full_path in existing_paths:
            continue

        task_id = generate_task_id()
        task = LintingTask(
            task_id=task_id,
            job_id=job.job_id,
            status=TaskStatusEnum.PENDING,
            source_file_path=full_path,
        )
        db.add(task)
        task_ids.append(task_id)
        existing_paths.add(full_path)

    db.flush()
    logger.info("Created %d PENDING tasks for job %s", len(task_ids), job.job_id)
    return task_ids
