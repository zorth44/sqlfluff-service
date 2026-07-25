"""
Job 处理器

将原 expand_zip_and_dispatch_tasks 拆分为多个独立函数。
负责处理 Job 级别的操作：ZIP 解压、文件夹遍历、创建 PENDING Tasks。

Worker 不需要显式 "派发" 子任务 — Task 创建后 status=PENDING，
其他 Worker 线程会通过 claim_task() 自动领取处理。
"""

import os
import tempfile
import logging
from typing import Dict, Any, Optional, List

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.db_session import managed_db_session
from app.models.database import LintingJob, LintingTask
from app.services.sqlfluff_service import SQLFluffService
from app.utils.file_utils import FileManager
from app.utils.uuid_utils import generate_task_id
from app.schemas.common import JobStatusEnum, TaskStatusEnum, SubmissionTypeEnum
from app.core.exceptions import JobException, ErrorCode

logger = logging.getLogger(__name__)


# ───────────────────── Entry Point ─────────────────────

def process_job_expansion(job_id: str) -> Dict[str, Any]:
    """
    处理 Job 展开（ZIP 解压 + 创建 PENDING Tasks）

    由 API 层在创建 Job 后异步调用，或由 Worker 直接调用。
    对于单文件 Job：确保存在一个 PENDING Task
    对于 ZIP Job：解压并为每个 SQL 文件创建 PENDING Task
    对于已解压文件夹：遍历并为每个 SQL 文件创建 PENDING Task

    Args:
        job_id: Job ID

    Returns:
        dict: 处理结果摘要
    """
    logger.info(f"Starting job expansion for: {job_id}")

    with managed_db_session() as db:
        job = db.query(LintingJob).filter(
            LintingJob.job_id == job_id
        ).first()

        if not job:
            raise JobException(ErrorCode.JOB_NOT_FOUND, job_id,
                              f"Job not found: {job_id}")

        # 防止重复展开
        if job.status == JobStatusEnum.PROCESSING:
            logger.info(f"Job {job_id} already processing, skipping")
            return {"status": "skipped", "job_id": job_id,
                    "reason": "Already processing"}

        # 更新状态
        job.status = JobStatusEnum.PROCESSING
        db.commit()

        # 根据类型处理
        if job.submission_type == SubmissionTypeEnum.SINGLE_FILE:
            task_ids = _handle_single_file_job(db, job)
        else:
            task_ids = _handle_archive_job(db, job)

    logger.info(
        f"Job expansion complete: {job_id}, "
        f"created {len(task_ids)} PENDING tasks"
    )

    return {
        "status": "success",
        "job_id": job_id,
        "total_tasks": len(task_ids),
        "task_ids": task_ids
    }


# ───────────────────── Step Functions ─────────────────────

def _handle_single_file_job(db: Session, job: LintingJob) -> List[str]:
    """
    处理单文件 Job

    验证文件存在，确保对应的 PENDING Task 存在。
    """
    file_manager = FileManager()

    # 检查是否已有 Task
    existing = db.query(LintingTask).filter(
        LintingTask.job_id == job.job_id
    ).first()

    if existing:
        logger.info(f"Task already exists for job {job.job_id}: {existing.task_id}")
        return [existing.task_id]

    # 验证文件
    if not file_manager.file_exists(job.source_path):
        error_msg = f"SQL file not found: {job.source_path}"
        job.status = JobStatusEnum.FAILED
        job.error_message = error_msg
        db.commit()
        return []

    # 创建 PENDING Task（Worker 会自动领取）
    task_id = generate_task_id()
    task = LintingTask(
        task_id=task_id,
        job_id=job.job_id,
        status=TaskStatusEnum.PENDING,
        source_file_path=job.source_path
    )
    db.add(task)
    db.commit()

    logger.info(f"Created PENDING task {task_id} for single-file job {job.job_id}")
    return [task_id]


def _handle_archive_job(db: Session, job: LintingJob) -> List[str]:
    """
    处理 ZIP/文件夹 Job

    判断 source_path 是文件还是目录，分别处理。
    """
    file_manager = FileManager()
    source_full = file_manager.get_absolute_path(job.source_path)

    if source_full.is_dir():
        return _handle_extracted_folder_job(db, job, file_manager)
    else:
        return _handle_zip_file_job(db, job, file_manager)


def _handle_extracted_folder_job(
    db: Session, job: LintingJob, file_manager: FileManager
) -> List[str]:
    """
    处理已解压文件夹：遍历 SQL 文件，创建 PENDING Tasks
    """
    try:
        sql_files = file_manager.list_sql_files(job.source_path)
        logger.info(
            f"Found {len(sql_files)} SQL files in folder for job {job.job_id}"
        )
    except Exception as e:
        error_msg = f"Failed to list SQL files: {e}"
        job.status = JobStatusEnum.FAILED
        job.error_message = error_msg
        db.commit()
        return []

    if not sql_files:
        job.status = JobStatusEnum.FAILED
        job.error_message = "No SQL files found in folder"
        db.commit()
        return []

    return _create_task_records(db, job, sql_files, job.source_path)


def _handle_zip_file_job(
    db: Session, job: LintingJob, file_manager: FileManager
) -> List[str]:
    """
    处理 ZIP 文件：解压 + 创建 PENDING Tasks
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            extract_dir, sql_files = file_manager.extract_zip_file(
                job.source_path, temp_dir
            )
            logger.info(
                f"Extracted {len(sql_files)} SQL files from ZIP for job {job.job_id}"
            )
        except Exception as e:
            error_msg = f"ZIP extraction failed: {e}"
            job.status = JobStatusEnum.FAILED
            job.error_message = error_msg
            db.commit()
            return []

        if not sql_files:
            job.status = JobStatusEnum.FAILED
            job.error_message = "No SQL files found in ZIP"
            db.commit()
            return []

        # 复制文件到标准位置
        task_files = []
        for sql_file in sql_files:
            file_name = os.path.basename(sql_file)
            target_path = f"jobs/{job.job_id}/{file_name}"
            file_manager.copy_file(sql_file, target_path)
            task_files.append(target_path)

        return _create_task_records(db, job, task_files, None)


def _create_task_records(
    db: Session,
    job: LintingJob,
    file_paths: List[str],
    root_path: Optional[str] = None
) -> List[str]:
    """
    批量创建 PENDING Task 记录

    Args:
        db: 数据库会话
        job: 父 Job
        file_paths: 文件路径列表
        root_path: 根路径（文件夹模式时需要拼接）

    Returns:
        List[str]: 创建的 task_id 列表
    """
    task_ids = []

    for file_path in file_paths:
        # 拼接完整路径
        if root_path:
            full_path = os.path.join(root_path, file_path).replace('\\', '/')
        else:
            full_path = file_path

        task_id = generate_task_id()
        task = LintingTask(
            task_id=task_id,
            job_id=job.job_id,
            status=TaskStatusEnum.PENDING,
            source_file_path=full_path
        )
        db.add(task)
        task_ids.append(task_id)

    db.commit()
    logger.info(
        f"Created {len(task_ids)} PENDING tasks for job {job.job_id}"
    )
    return task_ids
