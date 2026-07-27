"""
DB-as-Queue Worker 核心逻辑测试
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
    claim_task,
    reset_task_after_failure,
    reclaim_zombie_tasks,
)


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
        task = SimpleNamespace(
            retry_count=0,
            claim_id="worker:abc",
            claimed_at=datetime.utcnow(),
            status=TaskStatusEnum.IN_PROGRESS,
            error_message="old",
        )
        result = reset_task_after_failure(task, max_retries=3, reason="timeout")
        assert result == "PENDING"
        assert task.status == TaskStatusEnum.PENDING
        assert task.retry_count == 1
        assert task.claim_id is None
        assert task.claimed_at is None
        assert task.error_message is None

    def test_marks_failure_when_exceeding_max_retries(self):
        task = SimpleNamespace(
            retry_count=3,
            claim_id="worker:abc",
            claimed_at=datetime.utcnow(),
            status=TaskStatusEnum.IN_PROGRESS,
            error_message=None,
        )
        result = reset_task_after_failure(task, max_retries=3, reason="dead worker")
        assert result == "FAILURE"
        assert task.status == TaskStatusEnum.FAILURE
        assert task.retry_count == 4
        assert "超过最大重试次数" in task.error_message


class TestClaimTask:
    def test_claims_pending_and_sets_in_progress(self, db_session):
        _create_job(db_session, "job-1", JobStatusEnum.ACCEPTED)
        _create_task(db_session, "task-1", "job-1", TaskStatusEnum.PENDING, priority=10)
        _create_task(db_session, "task-2", "job-1", TaskStatusEnum.PENDING, priority=1)

        claimed = claim_task(db_session, "host_123")

        assert claimed is not None
        assert claimed.task_id == "task-1"  # 高优先级优先
        assert claimed.status == TaskStatusEnum.IN_PROGRESS
        assert claimed.claim_id.startswith("host_123:")
        assert claimed.claimed_at is not None

        job = db_session.query(LintingJob).filter_by(job_id="job-1").first()
        assert job.status == JobStatusEnum.PROCESSING

    def test_returns_none_when_queue_empty(self, db_session):
        assert claim_task(db_session, "host_123") is None


class TestReclaimZombieTasks:
    def test_reclaims_stopped_worker_tasks(self, db_session):
        _create_job(db_session)
        _create_task(
            db_session,
            status=TaskStatusEnum.IN_PROGRESS,
            claim_id="dead-host_1:abcd",
            claimed_at=datetime.utcnow(),
            retry_count=0,
        )
        db_session.add(WorkerRegistry(
            worker_id="dead-host_1",
            hostname="dead-host",
            pid=1,
            status="STOPPED",
            heartbeat_at=datetime.utcnow(),
            started_at=datetime.utcnow(),
        ))
        db_session.commit()

        config = WorkerConfig(
            zombie_timeout=600,
            task_timeout=1800,
            max_retries=3,
        )
        count = reclaim_zombie_tasks(db_session, config)
        db_session.commit()

        assert count == 1
        task = db_session.query(LintingTask).filter_by(task_id="task-1").first()
        assert task.status == TaskStatusEnum.PENDING
        assert task.retry_count == 1
        assert task.claim_id is None

    def test_reclaims_timed_out_tasks_even_if_worker_running(self, db_session):
        _create_job(db_session)
        old_time = datetime.utcnow() - timedelta(seconds=2000)
        _create_task(
            db_session,
            status=TaskStatusEnum.IN_PROGRESS,
            claim_id="alive-host_1:abcd",
            claimed_at=old_time,
            retry_count=0,
        )
        db_session.add(WorkerRegistry(
            worker_id="alive-host_1",
            hostname="alive-host",
            pid=2,
            status="RUNNING",
            heartbeat_at=datetime.utcnow(),
            started_at=datetime.utcnow(),
        ))
        db_session.commit()

        config = WorkerConfig(
            zombie_timeout=600,
            task_timeout=1800,
            max_retries=3,
        )
        count = reclaim_zombie_tasks(db_session, config)
        db_session.commit()

        assert count == 1
        task = db_session.query(LintingTask).filter_by(task_id="task-1").first()
        assert task.status == TaskStatusEnum.PENDING
        assert task.retry_count == 1

    def test_does_not_reclaim_fresh_running_worker_tasks(self, db_session):
        _create_job(db_session)
        _create_task(
            db_session,
            status=TaskStatusEnum.IN_PROGRESS,
            claim_id="alive-host_1:abcd",
            claimed_at=datetime.utcnow(),
            retry_count=0,
        )
        db_session.add(WorkerRegistry(
            worker_id="alive-host_1",
            hostname="alive-host",
            pid=2,
            status="RUNNING",
            heartbeat_at=datetime.utcnow(),
            started_at=datetime.utcnow(),
        ))
        db_session.commit()

        config = WorkerConfig(
            zombie_timeout=600,
            task_timeout=1800,
            max_retries=3,
        )
        count = reclaim_zombie_tasks(db_session, config)
        assert count == 0

        task = db_session.query(LintingTask).filter_by(task_id="task-1").first()
        assert task.status == TaskStatusEnum.IN_PROGRESS

    def test_marks_dead_on_stale_heartbeat_and_reclaims(self, db_session):
        _create_job(db_session)
        _create_task(
            db_session,
            status=TaskStatusEnum.IN_PROGRESS,
            claim_id="stale-host_1:abcd",
            claimed_at=datetime.utcnow(),
            retry_count=0,
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

        config = WorkerConfig(
            zombie_timeout=600,
            task_timeout=1800,
            max_retries=3,
        )
        count = reclaim_zombie_tasks(db_session, config)
        db_session.commit()

        assert count == 1
        worker = db_session.query(WorkerRegistry).filter_by(
            worker_id="stale-host_1"
        ).first()
        assert worker.status == "DEAD"

        task = db_session.query(LintingTask).filter_by(task_id="task-1").first()
        assert task.status == TaskStatusEnum.PENDING
