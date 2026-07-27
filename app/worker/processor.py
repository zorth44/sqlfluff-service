"""
任务处理器

将原 Celery tasks.py 中 240 行的 process_sql_file 拆分为多个职责单一的函数。
每个函数 20-40 行，易于测试和维护。

处理流程:
    1. load    - 从 DB 加载 task 和关联 job
    2. validate - 验证文件存在且为有效 SQL
    3. analyze  - 运行 SQLFluff 分析
    4. map      - 应用规则分级 (RuleSeverityMapper)
    5. save     - 结果写入 JSON 文件 + violations 批量写入 DB
    6. update   - 更新 task 和 job 状态
"""

import os
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.db_session import managed_db_session
from app.models.database import LintingTask, LintingJob, LintingViolation
from app.services.sqlfluff_service import SQLFluffService
from app.services.rule_severity_mapper import RuleSeverityMapper
from app.utils.file_utils import FileManager
from app.utils.encoding_utils import count_file_lines, build_line_map
from app.utils.severity_utils import calculate_severity_statistics_from_result
from app.schemas.common import TaskStatusEnum, JobStatusEnum
from app.core.exceptions import TaskException, JobException, FileException, ErrorCode

logger = logging.getLogger(__name__)


# ───────────────────── Entry Point ─────────────────────

def process_task_safe(task_id: str, worker_id: str) -> Dict[str, Any]:
    """
    任务处理入口（异常安全包装）

    捕获所有异常，确保任务状态正确更新。

    Args:
        task_id: 任务 ID
        worker_id: 处理该任务的 Worker 标识

    Returns:
        dict: 处理结果摘要
    """
    try:
        return process_sql_file(task_id, worker_id)
    except Exception as e:
        logger.error(f"Failed to process task {task_id}: {e}", exc_info=True)
        _mark_task_failed(task_id, str(e))
        return {
            "status": "failed",
            "task_id": task_id,
            "error": str(e)
        }


# ───────────────────── Orchestrator ─────────────────────

def process_sql_file(task_id: str, worker_id: str) -> Dict[str, Any]:
    """
    处理单个 SQL 文件（编排函数）

    依次调用子函数完成:
    load → validate → analyze → map severity → save results → update status

    Args:
        task_id: 任务 ID
        worker_id: Worker 标识

    Returns:
        dict: 处理结果摘要
    """
    logger.info(f"Starting processing for task: {task_id} by worker: {worker_id}")

    # 1. 从 DB 加载 task 和关联 job
    with managed_db_session() as db:
        task, job = _load_task_and_job(db, task_id)

        # 领取时已设为 IN_PROGRESS；此处仅确保状态一致
        if task.status != TaskStatusEnum.IN_PROGRESS:
            task.status = TaskStatusEnum.IN_PROGRESS
            db.commit()

    # 2. 验证文件
    file_manager = FileManager()
    error_msg = _validate_sql_file(file_manager, task)
    if error_msg:
        _mark_task_failed(task_id, error_msg)
        return {"status": "skipped", "task_id": task_id, "message": error_msg}

    # 3. 计算文件行数
    sql_file_path = file_manager.get_absolute_path(task.source_file_path)
    line_count = count_file_lines(str(sql_file_path))

    # 4. 运行 SQLFluff 分析
    sqlfluff_service = SQLFluffService()
    logger.info(
        f"Analyzing SQL file: {task.source_file_path}, "
        f"dialect: {job.dialect}, rules: {job.rules}"
    )
    analysis_result = sqlfluff_service.analyze_sql_file(
        task.source_file_path, job.dialect, job.rules
    )

    # 5. 应用规则分级映射
    with managed_db_session() as db:
        _apply_severity_mapping(db, analysis_result, job.dialect)

    # 6. 保存结果文件到 NFS
    result_path = _save_result_file(file_manager, task, analysis_result)

    # 7. 批量写入 violations 到 DB
    with managed_db_session() as db:
        _batch_insert_violations(db, task, job, analysis_result, str(sql_file_path))

    # 8. 更新 task 状态和统计
    with managed_db_session() as db:
        _update_task_success(db, task_id, analysis_result, result_path, line_count)

    # 9. 更新 job 状态
    with managed_db_session() as db:
        _update_job_status(db, task.job_id)

    total_violations = analysis_result.get("summary", {}).get("total_violations", 0)
    logger.info(
        f"Successfully processed task {task_id}, violations: {total_violations}"
    )

    return {
        "status": "success",
        "task_id": task_id,
        "job_id": task.job_id,
        "result_file_path": result_path,
        "violations_count": total_violations
    }


# ───────────────────── Step Functions ─────────────────────

def _load_task_and_job(db: Session, task_id: str) -> Tuple[LintingTask, LintingJob]:
    """
    从 DB 加载 task 和关联的 job

    Raises:
        TaskException: task 不存在
        JobException: job 不存在
    """
    task = db.query(LintingTask).filter(
        LintingTask.task_id == task_id
    ).first()
    if not task:
        raise TaskException(ErrorCode.TASK_NOT_FOUND, task_id,
                           f"Task not found: {task_id}")

    job = db.query(LintingJob).filter(
        LintingJob.job_id == task.job_id
    ).first()
    if not job:
        raise JobException(ErrorCode.JOB_NOT_FOUND, task.job_id,
                          f"Job not found: {task.job_id}")

    return task, job


def _validate_sql_file(file_manager: FileManager, task: LintingTask) -> Optional[str]:
    """
    验证 SQL 文件存在且有效

    Returns:
        Optional[str]: 错误消息（None 表示验证通过）
    """
    sql_file_path = file_manager.get_absolute_path(task.source_file_path)

    if not sql_file_path.exists():
        return f"SQL file not found: {task.source_file_path}"

    if not file_manager._is_valid_sql_file(sql_file_path):
        return f"跳过无效的SQL文件: {task.source_file_path}"

    return None


def _apply_severity_mapping(
    db: Session,
    analysis_result: Dict[str, Any],
    dialect: Optional[str] = None
) -> None:
    """
    用 RuleSeverityMapper 给 violations 打 severity_level

    修改 analysis_result['violations'] 中的每个违规项，新增 severity_level 字段。
    """
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


def _save_result_file(
    file_manager: FileManager,
    task: LintingTask,
    analysis_result: Dict[str, Any]
) -> str:
    """保存分析结果 JSON 到 NFS"""
    result_path = f"results/{task.job_id}/{task.task_id}_result.json"
    file_manager.write_json_file(result_path, analysis_result)
    logger.info(f"Analysis result saved to: {result_path}")
    return result_path


def _batch_insert_violations(
    db: Session,
    task: LintingTask,
    job: LintingJob,
    analysis_result: Dict[str, Any],
    sql_file_abs_path: str
) -> None:
    """
    批量写入 violations 到 linting_violations 表

    从源文件中读取对应行的 SQL 代码填充 sql_line 字段。
    """
    violations = analysis_result.get("violations", [])

    # 重试/回收后重跑时先清理旧 violations，避免重复插入
    try:
        deleted = db.query(LintingViolation).filter(
            LintingViolation.task_id == task.task_id
        ).delete(synchronize_session=False)
        if deleted:
            logger.info(
                f"Cleared {deleted} existing violations for task {task.task_id}"
            )
    except Exception as e:
        logger.error(
            f"Failed to clear old violations for task {task.task_id}: {e}"
        )
        db.rollback()
        return

    if not violations:
        logger.info(f"Task {task.task_id} has no violations, skipping insert")
        return

    # 构建行号到内容的映射
    line_map = build_line_map(sql_file_abs_path)

    violation_records = []
    for v in violations:
        line_no = v.get('line_no')
        sql_line = line_map.get(line_no, '') if line_no else ''

        violation_records.append({
            'task_id': task.task_id,
            'job_id': job.job_id,
            'rule_code': v.get('code', ''),
            'rule_name': v.get('rule'),
            'severity': v.get('severity'),
            'severity_level': v.get('severity_level'),
            'line_no': line_no,
            'line_pos': v.get('line_pos'),
            'description': v.get('description'),
            'sql_line': sql_line,
            'fixable': v.get('fixable', False),
            'support': v.get('support', ''),
        })

    try:
        db.bulk_insert_mappings(LintingViolation, violation_records)
        logger.info(
            f"Successfully inserted {len(violation_records)} violations "
            f"for task {task.task_id}"
        )
    except Exception as e:
        logger.error(
            f"Failed to insert violations for task {task.task_id}: {e}"
        )
        # violations 写入失败不影响任务状态


def _update_task_success(
    db: Session,
    task_id: str,
    analysis_result: Dict[str, Any],
    result_path: str,
    line_count: Optional[int]
) -> None:
    """
    更新 task 状态为 SUCCESS，并写入所有统计字段
    """
    task = db.query(LintingTask).filter(
        LintingTask.task_id == task_id
    ).first()

    if not task:
        logger.error(f"Task not found for success update: {task_id}")
        return

    summary = analysis_result.get("summary", {})
    total_violations = summary.get("total_violations", 0)
    critical_violations_count = summary.get("critical_violations_count", 0)

    # 计算 severity 各级别统计
    try:
        severity_statistics = calculate_severity_statistics_from_result(
            analysis_result
        )
    except Exception as e:
        logger.warning(f"Failed to calculate severity statistics: {e}")
        severity_statistics = {
            "INFO": 0, "MINOR": 0, "MAJOR": 0,
            "BLOCKER": 0, "CRITICAL": 0,
            "UNKNOWN": total_violations
        }

    task.status = TaskStatusEnum.SUCCESS
    task.result_file_path = result_path
    task.sql_lines = line_count
    task.total_violations = total_violations
    task.critical_violations = critical_violations_count
    task.severity_info = severity_statistics["INFO"]
    task.severity_minor = severity_statistics["MINOR"]
    task.severity_major = severity_statistics["MAJOR"]
    task.severity_blocker = severity_statistics["BLOCKER"]
    task.severity_critical = severity_statistics["CRITICAL"]
    task.severity_unknown = severity_statistics["UNKNOWN"]
    task.claim_id = None
    task.error_message = None

    db.commit()
    logger.info(f"Task {task_id} updated to SUCCESS, violations: {total_violations}")


def _update_job_status(db: Session, job_id: str) -> None:
    """
    根据子任务状态更新父 Job 状态

    逻辑与原 update_job_status_based_on_tasks 完全一致。
    """
    try:
        tasks = db.query(LintingTask).filter(
            LintingTask.job_id == job_id
        ).all()

        if not tasks:
            return

        # 过滤掉被跳过的无效文件 Task
        valid_tasks = []
        for t in tasks:
            if (t.status == TaskStatusEnum.FAILURE
                    and t.error_message
                    and "跳过无效的SQL文件" in t.error_message):
                continue
            valid_tasks.append(t)

        if not valid_tasks:
            new_status = JobStatusEnum.FAILED
        else:
            statuses = [t.status for t in valid_tasks]
            if all(s == TaskStatusEnum.SUCCESS for s in statuses):
                new_status = JobStatusEnum.COMPLETED
            elif any(s == TaskStatusEnum.SUCCESS for s in statuses):
                new_status = JobStatusEnum.PARTIALLY_COMPLETED
            elif all(s == TaskStatusEnum.FAILURE for s in statuses):
                new_status = JobStatusEnum.FAILED
            else:
                new_status = JobStatusEnum.PROCESSING

        job = db.query(LintingJob).filter(
            LintingJob.job_id == job_id
        ).first()

        if job and job.status != new_status:
            job.status = new_status
            db.commit()
            logger.info(
                f"Updated job {job_id} status to {new_status}"
            )

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update job status for {job_id}: {e}")


def _mark_task_failed(task_id: str, error_message: str) -> None:
    """
    将任务标记为 FAILURE 并更新父 Job 状态
    """
    with managed_db_session() as db:
        task = db.query(LintingTask).filter(
            LintingTask.task_id == task_id
        ).first()

        if task:
            task.status = TaskStatusEnum.FAILURE
            task.error_message = error_message
            task.claim_id = None
            db.commit()
            logger.error(f"Task {task_id} marked as FAILURE: {error_message}")
            _update_job_status(db, task.job_id)
