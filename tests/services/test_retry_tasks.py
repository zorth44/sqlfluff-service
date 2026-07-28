import asyncio
import uuid
from datetime import datetime

from app.models.database import LintingJob, LintingTask
from app.schemas.common import JobStatusEnum, SubmissionTypeEnum, TaskStatusEnum
from app.services.task_service import TaskService


def _create_task(
    db_session,
    *,
    status=TaskStatusEnum.FAILURE,
    job_status=JobStatusEnum.FAILED,
):
    from app.models.database import LintingViolation

    job_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())

    job = LintingJob(
        job_id=job_id,
        status=job_status,
        submission_type=SubmissionTypeEnum.SINGLE_FILE,
        source_path="jobs/test/query.sql",
        dialect="ansi",
        user_id="test-user",
        product_name="test-product",
    )
    task = LintingTask(
        task_id=task_id,
        job_id=job_id,
        status=status,
        source_file_path="jobs/test/query.sql",
        error_message="lint failed",
        result_file_path="results/test.json",
        claim_id="worker-1:abc123",
        claimed_at=datetime.utcnow(),
        retry_count=2,
        finished_at=datetime.utcnow(),
        total_violations=3,
        critical_violations=1,
        severity_info=1,
        severity_major=2,
    )
    db_session.add(job)
    db_session.add(task)
    db_session.add(
        LintingViolation(
            id=1,
            task_id=task_id,
            job_id=job_id,
            rule_code="L001",
            description="old violation",
        )
    )
    db_session.commit()
    return job_id, task_id


def test_retry_failed_tasks_success(db_session):
    from app.models.database import LintingViolation

    job_id, task_id = _create_task(db_session)
    service = TaskService(db_session)

    submitted, failed = asyncio.run(service.retry_failed_tasks([task_id]))

    assert submitted == [task_id]
    assert failed == []

    task = db_session.query(LintingTask).filter(LintingTask.task_id == task_id).one()
    assert task.status == TaskStatusEnum.PENDING
    assert task.claim_id is None
    assert task.claimed_at is None
    assert task.error_message is None
    assert task.result_file_path is None
    assert task.retry_count == 0
    assert task.finished_at is None
    assert task.total_violations is None
    assert task.critical_violations is None
    assert task.severity_info is None
    assert (
        db_session.query(LintingViolation)
        .filter(LintingViolation.task_id == task_id)
        .count()
        == 0
    )

    job = db_session.query(LintingJob).filter(LintingJob.job_id == job_id).one()
    assert job.status == JobStatusEnum.PROCESSING


def test_retry_non_failure_task_fails_with_clear_error(db_session):
    _, task_id = _create_task(db_session, status=TaskStatusEnum.SUCCESS)
    service = TaskService(db_session)

    submitted, failed = asyncio.run(service.retry_failed_tasks([task_id]))

    assert submitted == []
    assert failed == [{
        "task_id": task_id,
        "error": "任务状态不允许重试: SUCCESS",
    }]


def test_retry_task_not_found(db_session):
    service = TaskService(db_session)
    missing_id = "missing-task-id"

    submitted, failed = asyncio.run(service.retry_failed_tasks([missing_id]))

    assert submitted == []
    assert failed == [{
        "task_id": missing_id,
        "error": "任务不存在",
    }]
