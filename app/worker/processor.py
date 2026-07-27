"""
任务处理器

将原 Celery tasks.py 中 240 行的 process_sql_file 拆分为多个职责单一的函数。
每个函数 20-40 行，易于测试和维护。

处理流程:
    1. load    - 从 DB 加载 task 和关联 job
    2. validate - 验证文件存在且为有效 SQL
    3. analyze  - 运行 SQLFluff 分析（子进程隔离）
    4. map      - 应用规则分级 (RuleSeverityMapper)
    5. save     - 结果写入 JSON 文件 + violations 与 SUCCESS 同事务提交
    6. update   - 更新 job 状态
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.db_session import managed_db_session
from app.models.database import LintingTask, LintingJob, LintingViolation
from app.services.rule_severity_mapper import RuleSeverityMapper
from app.utils.file_utils import FileManager
from app.utils.encoding_utils import count_file_lines, build_line_map
from app.utils.severity_utils import calculate_severity_statistics_from_result
from app.schemas.common import TaskStatusEnum, JobStatusEnum
from app.core.exceptions import TaskException, JobException, ErrorCode
from app.worker.config import WorkerConfig
from app.worker.analyze_process import run_analyze_in_process
from app.worker.retry import classify_task_failure, compute_next_attempt_at

logger = logging.getLogger(__name__)


class LeaseLostError(Exception):
    """Raised when a task lease is no longer held by this worker."""


# ───────────────────── Entry Point ─────────────────────

def process_task_safe(
    task_id: str,
    worker_id: str,
    lease_token: Optional[str] = None,
) -> Dict[str, Any]:
    """
    任务处理入口（异常安全包装）

    捕获所有异常，确保任务状态正确更新。
    """
    try:
        return process_sql_file(task_id, worker_id, lease_token)
    except Exception as e:
        logger.error(f"Failed to process task {task_id}: {e}", exc_info=True)
        _mark_task_failed(task_id, str(e), lease_token, exc=e)
        return {
            "status": "failed",
            "task_id": task_id,
            "error": str(e),
        }


# ───────────────────── Orchestrator ─────────────────────

def process_sql_file(
    task_id: str,
    worker_id: str,
    lease_token: Optional[str] = None,
) -> Dict[str, Any]:
    """
    处理单个 SQL 文件（编排函数）

    依次调用子函数完成:
    load → validate → analyze → map severity → save results → update status
    """
    config = WorkerConfig()
    logger.info(f"Starting processing for task: {task_id} by worker: {worker_id}")

    with managed_db_session() as db:
        task, job = _load_task_and_job(db, task_id)

    file_manager = FileManager()
    error_msg = _validate_sql_file(file_manager, task)
    if error_msg:
        _mark_task_failed(task_id, error_msg, lease_token)
        return {"status": "skipped", "task_id": task_id, "message": error_msg}

    sql_file_path = file_manager.get_absolute_path(task.source_file_path)
    line_count = count_file_lines(str(sql_file_path))

    logger.debug(
        f"Analyzing SQL file: {task.source_file_path}, "
        f"dialect: {job.dialect}, rules: {job.rules}"
    )
    analysis_result = run_analyze_in_process(
        task.source_file_path,
        job.dialect,
        job.rules,
        soft_timeout=config.analyze_soft_timeout,
        hard_timeout=config.analyze_hard_timeout,
        concurrency=config.concurrency,
    )

    with managed_db_session() as db:
        _apply_severity_mapping(db, analysis_result, job.dialect)

    result_path = _build_result_path(task.job_id, task.task_id, lease_token)
    file_manager.write_json_file_atomic(result_path, analysis_result)

    # 仅在 fencing 提交成功后才能清理旧结果文件，避免旧 Worker 删掉新结果
    try:
        _commit_success_with_violations(
            task_id=task_id,
            job=job,
            lease_token=lease_token,
            analysis_result=analysis_result,
            result_path=result_path,
            line_count=line_count,
            sql_file_abs_path=str(sql_file_path),
        )
    except LeaseLostError:
        logger.warning(
            f"Task {task_id} lease lost before success commit, abandoning"
        )
        return {
            "status": "abandoned",
            "task_id": task_id,
            "message": "lease lost",
        }

    try:
        file_manager.cleanup_stale_result_files(
            task.job_id, task.task_id, result_path
        )
    except Exception as e:
        logger.warning(
            f"Stale result cleanup failed for task {task_id}: {e}"
        )

    try:
        with managed_db_session() as db:
            update_job_status_after_task(db, task.job_id)
    except Exception as e:
        logger.error(
            f"Failed to update job status for {task.job_id} after task "
            f"{task_id} success: {e}",
            exc_info=True,
        )
        raise

    total_violations = analysis_result.get("summary", {}).get(
        "total_violations", 0
    )
    logger.info(
        f"Successfully processed task {task_id}, violations: {total_violations}"
    )

    return {
        "status": "success",
        "task_id": task_id,
        "job_id": task.job_id,
        "result_file_path": result_path,
        "violations_count": total_violations,
    }


# ───────────────────── Step Functions ─────────────────────

def _load_task_and_job(db: Session, task_id: str) -> Tuple[LintingTask, LintingJob]:
    """从 DB 加载 task 和关联的 job"""
    task = db.query(LintingTask).filter(
        LintingTask.task_id == task_id
    ).first()
    if not task:
        raise TaskException(
            ErrorCode.TASK_NOT_FOUND, task_id, f"Task not found: {task_id}"
        )

    job = db.query(LintingJob).filter(
        LintingJob.job_id == task.job_id
    ).first()
    if not job:
        raise JobException(
            ErrorCode.JOB_NOT_FOUND, task.job_id, f"Job not found: {task.job_id}"
        )

    return task, job


def _validate_sql_file(file_manager: FileManager, task: LintingTask) -> Optional[str]:
    """验证 SQL 文件存在且有效"""
    sql_file_path = file_manager.get_absolute_path(task.source_file_path)

    if not sql_file_path.exists():
        return f"SQL file not found: {task.source_file_path}"

    if not file_manager._is_valid_sql_file(sql_file_path):
        return f"跳过无效的SQL文件: {task.source_file_path}"

    return None


def _build_result_path(
    job_id: str,
    task_id: str,
    lease_token: Optional[str],
) -> str:
    token = lease_token or "no-lease"
    return f"results/{job_id}/{task_id}/{token}.json"


def _apply_severity_mapping(
    db: Session,
    analysis_result: Dict[str, Any],
    dialect: Optional[str] = None,
) -> None:
    """用 RuleSeverityMapper 给 violations 打 severity_level"""
    try:
        severity_map = RuleSeverityMapper.get_mapping_for_dialect(
            db, dialect or "ansi"
        )
        violations = analysis_result.get("violations", [])
        if violations and severity_map:
            for v in violations:
                code = v.get("code")
                if code in severity_map:
                    v["severity_level"] = severity_map[code]
    except Exception as e:
        logger.warning(f"Failed to apply severity mapping: {e}")


def _commit_success_with_violations(
    task_id: str,
    job: LintingJob,
    lease_token: Optional[str],
    analysis_result: Dict[str, Any],
    result_path: str,
    line_count: Optional[int],
    sql_file_abs_path: str,
) -> None:
    """
    Single transaction: verify lease, replace violations, mark SUCCESS.

    Raises:
        LeaseLostError: 租约已丢失，事务回滚，调用方不得清理结果文件
    """
    with managed_db_session() as db:
        if lease_token:
            held = db.query(LintingTask.task_id).filter(
                LintingTask.task_id == task_id,
                LintingTask.status == TaskStatusEnum.IN_PROGRESS,
                LintingTask.lease_token == lease_token,
            ).first()
            if not held:
                raise LeaseLostError(
                    f"Lease lost for task {task_id} before success commit"
                )

        db.query(LintingViolation).filter(
            LintingViolation.task_id == task_id
        ).delete(synchronize_session=False)

        violations = analysis_result.get("violations", [])
        if violations:
            line_map = build_line_map(sql_file_abs_path)
            violation_records = []
            for v in violations:
                line_no = v.get("line_no")
                sql_line = line_map.get(line_no, "") if line_no else ""
                violation_records.append({
                    "task_id": task_id,
                    "job_id": job.job_id,
                    "rule_code": v.get("code", ""),
                    "rule_name": v.get("rule"),
                    "severity": v.get("severity"),
                    "severity_level": v.get("severity_level"),
                    "line_no": line_no,
                    "line_pos": v.get("line_pos"),
                    "description": v.get("description"),
                    "sql_line": sql_line,
                    "fixable": v.get("fixable", False),
                    "support": v.get("support", ""),
                })
            db.add_all([
                LintingViolation(**record) for record in violation_records
            ])

        summary = analysis_result.get("summary", {})
        total_violations = summary.get("total_violations", 0)
        critical_violations_count = summary.get("critical_violations_count", 0)

        try:
            severity_statistics = calculate_severity_statistics_from_result(
                analysis_result
            )
        except Exception as e:
            logger.warning(f"Failed to calculate severity statistics: {e}")
            severity_statistics = {
                "INFO": 0,
                "MINOR": 0,
                "MAJOR": 0,
                "BLOCKER": 0,
                "CRITICAL": 0,
                "UNKNOWN": total_violations,
            }

        now = datetime.utcnow()
        update_values = {
            LintingTask.status: TaskStatusEnum.SUCCESS,
            LintingTask.result_file_path: result_path,
            LintingTask.sql_lines: line_count,
            LintingTask.total_violations: total_violations,
            LintingTask.critical_violations: critical_violations_count,
            LintingTask.severity_info: severity_statistics["INFO"],
            LintingTask.severity_minor: severity_statistics["MINOR"],
            LintingTask.severity_major: severity_statistics["MAJOR"],
            LintingTask.severity_blocker: severity_statistics["BLOCKER"],
            LintingTask.severity_critical: severity_statistics["CRITICAL"],
            LintingTask.severity_unknown: severity_statistics["UNKNOWN"],
            LintingTask.claim_id: None,
            LintingTask.claimed_at: None,
            LintingTask.lease_token: None,
            LintingTask.lease_expires_at: None,
            LintingTask.finished_at: now,
            LintingTask.error_message: None,
            LintingTask.last_error: None,
        }

        filters = [
            LintingTask.task_id == task_id,
            LintingTask.status == TaskStatusEnum.IN_PROGRESS,
        ]
        if lease_token:
            filters.append(LintingTask.lease_token == lease_token)

        updated = db.query(LintingTask).filter(*filters).update(
            update_values,
            synchronize_session=False,
        )
        if updated != 1:
            raise LeaseLostError(
                f"Lease lost for task {task_id} during success commit"
            )

        logger.debug(
            f"Task {task_id} committed SUCCESS with "
            f"{len(violations)} violations"
        )


def update_job_status_after_task(db: Session, job_id: str) -> bool:
    """根据子任务状态更新父 Job 状态（可被 loop 回收逻辑复用）"""
    from app.services.job_status import update_job_status_from_tasks

    return update_job_status_from_tasks(db, job_id, lock=True)


def _mark_task_failed(
    task_id: str,
    error_message: str,
    lease_token: Optional[str] = None,
    exc: Optional[BaseException] = None,
) -> None:
    """Mark task failed (permanent) or pending for retry (retryable)."""
    config = WorkerConfig()
    failure_kind = classify_task_failure(error_message, exc)

    with managed_db_session() as db:
        filters = [LintingTask.task_id == task_id]
        if lease_token:
            filters.extend([
                LintingTask.status == TaskStatusEnum.IN_PROGRESS,
                LintingTask.lease_token == lease_token,
            ])

        task = db.query(LintingTask).filter(*filters).first()
        if not task:
            if lease_token:
                logger.warning(
                    f"Task {task_id} lease lost before failure update, abandoning"
                )
            return

        now = datetime.utcnow()
        task.last_error = error_message
        task.claim_id = None
        task.claimed_at = None
        task.lease_token = None
        task.lease_expires_at = None

        if failure_kind == "permanent":
            task.status = TaskStatusEnum.FAILURE
            task.error_message = error_message
            task.finished_at = now
            task.next_attempt_at = None
            try:
                from app.core.metrics import record_permanent_failure
                record_permanent_failure()
            except ImportError:
                pass
            logger.error(
                f"Task {task_id} marked permanent FAILURE: {error_message}"
            )
        else:
            attempt_count = task.attempt_count or 0
            if attempt_count > config.max_retries:
                task.status = TaskStatusEnum.FAILURE
                task.error_message = (
                    f"超过最大重试次数（{config.max_retries}次），{error_message}"
                )
                task.finished_at = now
                task.next_attempt_at = None
                try:
                    from app.core.metrics import record_permanent_failure
                    record_permanent_failure()
                except ImportError:
                    pass
                logger.error(
                    f"Task {task_id} retryable failure exhausted retries: "
                    f"{error_message}"
                )
            else:
                task.status = TaskStatusEnum.PENDING
                task.error_message = None
                task.finished_at = None
                task.next_attempt_at = compute_next_attempt_at(
                    attempt_count, config
                )
                logger.warning(
                    f"Task {task_id} scheduled for retry at "
                    f"{task.next_attempt_at}: {error_message}"
                )

        update_job_status_after_task(db, task.job_id)
