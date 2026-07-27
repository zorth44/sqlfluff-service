"""
Job 处理器

负责 Worker 侧 Job 展开：ZIP 解压、文件夹遍历、创建 PENDING Tasks。
Task 创建后由 claim_task() 自动领取处理。
"""

import os
import time
import tempfile
import logging
from typing import Dict, Any, Optional, List

from sqlalchemy.orm import Session

from app.models.database import LintingJob, LintingTask
from app.utils.file_utils import FileManager
from app.utils.uuid_utils import generate_task_id
from app.schemas.common import JobStatusEnum, TaskStatusEnum, SubmissionTypeEnum

logger = logging.getLogger(__name__)


class JobExpansionError(Exception):
    """Job 展开失败基类"""

    def __init__(self, message: str, *, permanent: bool = True):
        super().__init__(message)
        self.permanent = permanent


# ───────────────────── Claim ─────────────────────

def claim_job_for_expansion(db: Session) -> Optional[LintingJob]:
    """
    原子领取一个 ACCEPTED Job 用于展开（ACCEPTED → EXPANDING）。

    使用 FOR UPDATE SKIP LOCKED，仅一个 Worker 能成功领取。
    """
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
    db.flush()
    logger.info("Claimed job %s for expansion", job.job_id)
    return job


# ───────────────────── Entry Point ─────────────────────

def process_job_expansion(db: Session, job: LintingJob) -> Dict[str, Any]:
    """
    展开 Job（调用方已通过 claim 将状态置为 EXPANDING）。

    幂等：若已有 Task 且 Job 已在 PROCESSING，跳过；若 EXPANDING 且已有 Task，补全后转 PROCESSING。
    """
    start = time.monotonic()
    job_id = job.job_id

    try:
        try:
            from app.core.metrics import record_job_expansion_duration
        except ImportError:
            record_job_expansion_duration = None

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
            job.status = JobStatusEnum.PROCESSING
            db.commit()
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

        job = db.query(LintingJob).filter(LintingJob.job_id == job_id).first()
        if job and job.status != JobStatusEnum.FAILED:
            job.status = JobStatusEnum.PROCESSING
            db.commit()

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

    except JobExpansionError as e:
        db.rollback()
        job = (
            db.query(LintingJob)
            .filter(LintingJob.job_id == job_id)
            .with_for_update()
            .first()
        )
        if job:
            if e.permanent:
                job.status = JobStatusEnum.FAILED
                job.error_message = str(e)
            else:
                job.status = JobStatusEnum.ACCEPTED
                job.error_message = str(e)
            db.commit()
        logger.error("Job expansion failed for %s: %s", job_id, e)
        return {"status": "failed", "job_id": job_id, "error": str(e)}

    except Exception as e:
        db.rollback()
        job = (
            db.query(LintingJob)
            .filter(LintingJob.job_id == job_id)
            .with_for_update()
            .first()
        )
        if job:
            job.status = JobStatusEnum.FAILED
            job.error_message = str(e)
            db.commit()
        logger.exception("Unexpected job expansion error for %s", job_id)
        return {"status": "failed", "job_id": job_id, "error": str(e)}


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
        extract_dir, sql_files = file_manager.extract_zip_file(
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

    source_paths = []
    for sql_file in sql_files:
        relative_path = os.path.join(extract_dir, sql_file).replace("\\", "/")
        source_paths.append(relative_path)

    return _create_task_records(db, job, source_paths, None)


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
