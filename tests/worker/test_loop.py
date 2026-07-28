"""
DB-as-Queue Worker 核心逻辑测试（租约语义）
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.database import LintingJob, LintingTask, WorkerRegistry
from app.schemas.common import TaskStatusEnum, JobStatusEnum, SubmissionTypeEnum
from app.worker.config import WorkerConfig
from app.worker.loop import (
    ClaimedTask,
    claim_task,
    renew_lease,
    reset_task_after_failure,
    reclaim_expired_leases,
    mark_stale_workers_dead,
)
from app.services.job_status import reconcile_terminal_processing_jobs


@pytest.fixture
def db_session():
    """每个测试使用独立的内存 SQLite 库"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _create_job(db, job_id="job-1", status=JobStatusEnum.ACCEPTED):
    job = LintingJob(
        job_id=job_id,
        status=status,
        submission_type=SubmissionTypeEnum.SINGLE_FILE,
        source_path="jobs/job-1/a.sql",
        dialect="ansi",
        user_id="u1",
        product_name="p1",
    )
    db.add(job)
    db.commit()
    return job


def _create_task(
    db,
    task_id="task-1",
    job_id="job-1",
    status=TaskStatusEnum.PENDING,
    claim_id=None,
    claimed_at=None,
    retry_count=0,
    priority=0,
    lease_token=None,
    lease_expires_at=None,
    next_attempt_at=None,
    attempt_count=0,
):
    task = LintingTask(
        task_id=task_id,
        job_id=job_id,
        status=status,
        source_file_path="jobs/job-1/a.sql",
        claim_id=claim_id,
        claimed_at=claimed_at,
        retry_count=retry_count,
        priority=priority,
        lease_token=lease_token,
        lease_expires_at=lease_expires_at,
        next_attempt_at=next_attempt_at,  # None = 立即可领（避免 utcnow 秒级截断导致不可领）
        attempt_count=attempt_count,
    )
    db.add(task)
    db.commit()
    return task


class TestTaskStatusEnum:
    def test_has_in_progress_not_processing(self):
        assert hasattr(TaskStatusEnum, "IN_PROGRESS")
        assert not hasattr(TaskStatusEnum, "PROCESSING")
        assert TaskStatusEnum.IN_PROGRESS.value == "IN_PROGRESS"


class TestResetTaskAfterFailure:
    def test_resets_to_pending_under_max_retries(self):
        config = WorkerConfig(max_backoff_seconds=300)
        task = SimpleNamespace(
            attempt_count=1,
            lease_token="tok",
            lease_expires_at=datetime.utcnow(),
            claim_id="worker:abc",
            claimed_at=datetime.utcnow(),
            status=TaskStatusEnum.IN_PROGRESS,
            error_message="old",
            last_error=None,
            next_attempt_at=None,
            finished_at=None,
        )
        result = reset_task_after_failure(
            task, max_retries=3, reason="lease expired", config=config
        )
        assert result == "PENDING"
        assert task.status == TaskStatusEnum.PENDING
        assert task.lease_token is None
        assert task.lease_expires_at is None
        assert task.claim_id is None
        assert task.claimed_at is None
        assert task.last_error == "lease expired"
        assert task.next_attempt_at is not None

    def test_marks_failure_when_exceeding_max_retries(self):
        config = WorkerConfig(max_backoff_seconds=300)
        task = SimpleNamespace(
            attempt_count=4,
            lease_token="tok",
            lease_expires_at=datetime.utcnow(),
            claim_id="worker:abc",
            claimed_at=datetime.utcnow(),
            status=TaskStatusEnum.IN_PROGRESS,
            error_message=None,
            last_error=None,
            next_attempt_at=None,
            finished_at=None,
        )
        result = reset_task_after_failure(
            task, max_retries=3, reason="lease expired", config=config
        )
        assert result == "FAILURE"
        assert task.status == TaskStatusEnum.FAILURE
        assert "超过最大重试次数" in task.error_message
        assert task.finished_at is not None


class TestClaimTask:
    def test_claims_pending_and_returns_claimed_task(self, db_session):
        _create_job(db_session, "job-1", JobStatusEnum.ACCEPTED)
        _create_task(
            db_session, "task-1", "job-1", TaskStatusEnum.PENDING, priority=10
        )
        _create_task(
            db_session, "task-2", "job-1", TaskStatusEnum.PENDING, priority=1
        )

        claimed = claim_task(db_session, "host_123", lease_seconds=120)
        db_session.commit()

        assert claimed is not None
        assert isinstance(claimed, ClaimedTask)
        assert claimed.task_id == "task-1"
        assert claimed.job_id == "job-1"
        assert claimed.source_file_path == "jobs/job-1/a.sql"
        assert len(claimed.lease_token) == 32

        task = db_session.query(LintingTask).filter_by(task_id="task-1").first()
        assert task.status == TaskStatusEnum.IN_PROGRESS
        assert task.lease_token == claimed.lease_token
        assert task.lease_expires_at is not None
        assert task.attempt_count == 1
        assert task.claim_id.startswith("host_123:")
        assert task.started_at is not None

        job = db_session.query(LintingJob).filter_by(job_id="job-1").first()
        assert job.status == JobStatusEnum.PROCESSING

    def test_returns_none_when_queue_empty(self, db_session):
        assert claim_task(db_session, "host_123", lease_seconds=120) is None

    def test_skips_task_with_future_next_attempt_at(self, db_session):
        _create_job(db_session)
        _create_task(
            db_session,
            task_id="task-future",
            next_attempt_at=datetime.utcnow() + timedelta(minutes=10),
        )
        _create_task(
            db_session,
            task_id="task-ready",
            next_attempt_at=datetime.utcnow() - timedelta(seconds=1),
        )

        claimed = claim_task(db_session, "host_123", lease_seconds=120)
        db_session.commit()

        assert claimed is not None
        assert claimed.task_id == "task-ready"

    def test_advances_expanding_job_to_processing(self, db_session):
        _create_job(db_session, status=JobStatusEnum.EXPANDING)
        _create_task(db_session)

        claim_task(db_session, "host_123", lease_seconds=120)
        db_session.commit()

        job = db_session.query(LintingJob).filter_by(job_id="job-1").first()
        assert job.status == JobStatusEnum.PROCESSING


class TestRenewLease:
    def test_renews_matching_lease(self, db_session):
        _create_job(db_session)
        old_expiry = datetime.utcnow() - timedelta(seconds=10)
        _create_task(
            db_session,
            status=TaskStatusEnum.IN_PROGRESS,
            lease_token="abc123",
            lease_expires_at=old_expiry,
        )

        ok = renew_lease(db_session, "task-1", "abc123", lease_seconds=120)
        db_session.commit()

        assert ok is True
        task = db_session.query(LintingTask).filter_by(task_id="task-1").first()
        assert task.lease_expires_at > old_expiry

    def test_fails_on_token_mismatch(self, db_session):
        _create_job(db_session)
        _create_task(
            db_session,
            status=TaskStatusEnum.IN_PROGRESS,
            lease_token="abc123",
            lease_expires_at=datetime.utcnow() + timedelta(seconds=60),
        )

        ok = renew_lease(db_session, "task-1", "wrong-token", lease_seconds=120)
        assert ok is False


class TestReclaimExpiredLeases:
    def test_reclaims_expired_lease(self, db_session):
        _create_job(db_session)
        _create_task(
            db_session,
            status=TaskStatusEnum.IN_PROGRESS,
            lease_token="expired-tok",
            lease_expires_at=datetime.utcnow() - timedelta(seconds=30),
            attempt_count=1,
        )

        config = WorkerConfig(max_retries=3, max_backoff_seconds=300)
        count = reclaim_expired_leases(db_session, config)
        db_session.commit()

        assert count == 1
        task = db_session.query(LintingTask).filter_by(task_id="task-1").first()
        assert task.status == TaskStatusEnum.PENDING
        assert task.lease_token is None
        assert task.next_attempt_at is not None
        assert task.last_error is not None

    def test_does_not_reclaim_fresh_lease_even_if_worker_dead(self, db_session):
        _create_job(db_session)
        _create_task(
            db_session,
            status=TaskStatusEnum.IN_PROGRESS,
            claim_id="dead-host_1:abcd",
            lease_token="fresh-tok",
            lease_expires_at=datetime.utcnow() + timedelta(seconds=120),
            attempt_count=1,
        )
        db_session.add(WorkerRegistry(
            worker_id="dead-host_1",
            hostname="dead-host",
            pid=1,
            status="DEAD",
            heartbeat_at=datetime.utcnow() - timedelta(hours=1),
            started_at=datetime.utcnow(),
        ))
        db_session.commit()

        config = WorkerConfig(max_retries=3)
        count = reclaim_expired_leases(db_session, config)
        assert count == 0

        task = db_session.query(LintingTask).filter_by(task_id="task-1").first()
        assert task.status == TaskStatusEnum.IN_PROGRESS
        assert task.lease_token == "fresh-tok"

    def test_marks_failure_when_attempts_exhausted(self, db_session):
        _create_job(db_session)
        _create_task(
            db_session,
            status=TaskStatusEnum.IN_PROGRESS,
            lease_token="expired-tok",
            lease_expires_at=datetime.utcnow() - timedelta(seconds=30),
            attempt_count=4,
        )

        config = WorkerConfig(max_retries=3)
        count = reclaim_expired_leases(db_session, config)
        db_session.commit()

        assert count == 1
        task = db_session.query(LintingTask).filter_by(task_id="task-1").first()
        assert task.status == TaskStatusEnum.FAILURE
        assert task.finished_at is not None


class TestMarkStaleWorkersDead:
    def test_marks_dead_on_stale_heartbeat_without_reclaiming_tasks(self, db_session):
        _create_job(db_session)
        _create_task(
            db_session,
            status=TaskStatusEnum.IN_PROGRESS,
            claim_id="stale-host_1:abcd",
            lease_token="still-valid",
            lease_expires_at=datetime.utcnow() + timedelta(seconds=120),
            attempt_count=1,
        )
        db_session.add(WorkerRegistry(
            worker_id="stale-host_1",
            hostname="stale-host",
            pid=3,
            status="RUNNING",
            heartbeat_at=datetime.utcnow() - timedelta(seconds=900),
            started_at=datetime.utcnow() - timedelta(seconds=1000),
        ))
        db_session.commit()

        config = WorkerConfig(zombie_timeout=600)
        dead_count = mark_stale_workers_dead(db_session, config)
        db_session.commit()

        assert dead_count == 1
        worker = db_session.query(WorkerRegistry).filter_by(
            worker_id="stale-host_1"
        ).first()
        assert worker.status == "DEAD"

        task = db_session.query(LintingTask).filter_by(task_id="task-1").first()
        assert task.status == TaskStatusEnum.IN_PROGRESS


class TestReconcileTerminalProcessingJobs:
    def test_repairs_processing_job_after_all_tasks_succeed(self, db_session):
        _create_job(db_session, status=JobStatusEnum.PROCESSING)
        _create_task(db_session, status=TaskStatusEnum.SUCCESS)

        count = reconcile_terminal_processing_jobs(db_session)
        db_session.commit()

        assert count == 1
        job = db_session.query(LintingJob).filter_by(job_id="job-1").one()
        assert job.status == JobStatusEnum.COMPLETED

    def test_leaves_job_processing_while_active_task_exists(self, db_session):
        _create_job(db_session, status=JobStatusEnum.PROCESSING)
        _create_task(db_session, status=TaskStatusEnum.PENDING)

        count = reconcile_terminal_processing_jobs(db_session)
        db_session.commit()

        assert count == 0
        job = db_session.query(LintingJob).filter_by(job_id="job-1").one()
        assert job.status == JobStatusEnum.PROCESSING
