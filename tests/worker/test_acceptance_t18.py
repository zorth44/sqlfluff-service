"""
T18 故障与并发验收测试（可在 SQLite 上跑的子集 + MySQL 场景索引）。

完整 MySQL 并发/SKIP LOCKED 场景见:
  tests/worker/test_mysql_claim_concurrency.py
  scripts/run_mysql_integration_tests.sh
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.database import LintingJob, LintingTask
from app.schemas.common import JobStatusEnum, SubmissionTypeEnum, TaskStatusEnum
from app.services.job_status import compute_aggregate_job_status, update_job_status_from_tasks
from app.worker.config import WorkerConfig
from app.worker.loop import claim_task, reclaim_expired_leases, renew_lease
from app.worker.retry import classify_task_failure


@pytest.fixture
def db_session():
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


def _job(db, job_id="job-1", status=JobStatusEnum.PROCESSING):
    job = LintingJob(
        job_id=job_id,
        status=status,
        submission_type=SubmissionTypeEnum.SINGLE_FILE,
        source_path="a.sql",
        dialect="ansi",
        user_id="u1",
        product_name="p1",
    )
    db.add(job)
    db.commit()
    return job


def _task(db, **kwargs):
    defaults = dict(
        task_id="task-1",
        job_id="job-1",
        status=TaskStatusEnum.PENDING,
        source_file_path="a.sql",
        priority=0,
        attempt_count=0,
        next_attempt_at=None,
    )
    defaults.update(kwargs)
    task = LintingTask(**defaults)
    db.add(task)
    db.commit()
    return task


class TestAcceptanceScenarios:
    def test_two_claimers_one_task_only_one_wins(self, db_session):
        _job(db_session)
        _task(db_session)
        c1 = claim_task(db_session, "w1", 60)
        db_session.commit()
        c2 = claim_task(db_session, "w2", 60)
        db_session.commit()
        assert c1 is not None
        assert c2 is None

    def test_crash_after_claim_reclaims_when_lease_expires(self, db_session):
        _job(db_session)
        _task(
            db_session,
            status=TaskStatusEnum.IN_PROGRESS,
            lease_token="tok",
            lease_expires_at=datetime.utcnow() - timedelta(seconds=1),
            attempt_count=1,
        )
        n = reclaim_expired_leases(db_session, WorkerConfig(max_retries=3))
        db_session.commit()
        assert n == 1
        task = db_session.query(LintingTask).one()
        assert task.status == TaskStatusEnum.PENDING
        assert task.lease_token is None

    def test_renew_prevents_reclaim(self, db_session):
        _job(db_session)
        token = "alive"
        _task(
            db_session,
            status=TaskStatusEnum.IN_PROGRESS,
            lease_token=token,
            lease_expires_at=datetime.utcnow() + timedelta(seconds=5),
            attempt_count=1,
        )
        assert renew_lease(db_session, "task-1", token, 120) is True
        db_session.commit()
        n = reclaim_expired_leases(db_session, WorkerConfig(max_retries=3))
        assert n == 0

    def test_stale_worker_cannot_complete(self, db_session):
        _job(db_session)
        _task(
            db_session,
            status=TaskStatusEnum.IN_PROGRESS,
            lease_token="current",
            lease_expires_at=datetime.utcnow() + timedelta(seconds=60),
            attempt_count=1,
        )
        updated = (
            db_session.query(LintingTask)
            .filter(
                LintingTask.task_id == "task-1",
                LintingTask.lease_token == "stale",
                LintingTask.status == TaskStatusEnum.IN_PROGRESS,
            )
            .update({LintingTask.status: TaskStatusEnum.SUCCESS})
        )
        assert updated == 0

    def test_permanent_vs_retryable_classification(self):
        assert classify_task_failure("SQL file not found: x") == "permanent"
        assert classify_task_failure("connection reset by peer") == "retryable"

    def test_job_status_converges_on_all_success(self, db_session):
        _job(db_session)
        _task(db_session, task_id="t1", status=TaskStatusEnum.SUCCESS)
        _task(db_session, task_id="t2", status=TaskStatusEnum.SUCCESS)
        update_job_status_from_tasks(db_session, "job-1", lock=True)
        db_session.commit()
        assert db_session.query(LintingJob).one().status == JobStatusEnum.COMPLETED

    def test_partial_completion_only_when_all_terminal(self, db_session):
        _job(db_session)
        _task(db_session, task_id="t1", status=TaskStatusEnum.SUCCESS)
        _task(db_session, task_id="t2", status=TaskStatusEnum.PENDING)
        assert compute_aggregate_job_status(
            db_session.query(LintingTask).filter_by(job_id="job-1").all()
        ) == JobStatusEnum.PROCESSING

        t2 = db_session.query(LintingTask).filter_by(task_id="t2").one()
        t2.status = TaskStatusEnum.FAILURE
        db_session.commit()
        assert compute_aggregate_job_status(
            db_session.query(LintingTask).filter_by(job_id="job-1").all()
        ) == JobStatusEnum.PARTIALLY_COMPLETED

    def test_max_attempts_marks_failure_and_job(self, db_session):
        _job(db_session)
        _task(
            db_session,
            status=TaskStatusEnum.IN_PROGRESS,
            lease_token="tok",
            lease_expires_at=datetime.utcnow() - timedelta(seconds=1),
            attempt_count=4,
        )
        reclaim_expired_leases(db_session, WorkerConfig(max_retries=3))
        db_session.commit()
        task = db_session.query(LintingTask).one()
        assert task.status == TaskStatusEnum.FAILURE
        job = db_session.query(LintingJob).one()
        assert job.status == JobStatusEnum.FAILED
