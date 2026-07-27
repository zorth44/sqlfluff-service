"""
Retryable vs permanent failure classification tests.
"""

import uuid
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.core.exceptions import FileException, SQLFluffException
from app.models.database import LintingJob, LintingTask
from app.schemas.common import JobStatusEnum, SubmissionTypeEnum, TaskStatusEnum
from app.worker.processor import _mark_task_failed
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


@pytest.fixture
def mock_managed_db(db_session):
    @contextmanager
    def _managed():
        try:
            yield db_session
            db_session.commit()
        except Exception:
            db_session.rollback()
            raise

    with patch("app.worker.processor.managed_db_session", _managed):
        yield _managed


def _create_in_progress_task(db, lease_token="tok-1", attempt_count=1):
    job_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    job = LintingJob(
        job_id=job_id,
        status=JobStatusEnum.PROCESSING,
        submission_type=SubmissionTypeEnum.SINGLE_FILE,
        source_path="jobs/test/a.sql",
        dialect="ansi",
        user_id="u1",
        product_name="p1",
    )
    task = LintingTask(
        task_id=task_id,
        job_id=job_id,
        status=TaskStatusEnum.IN_PROGRESS,
        source_file_path="jobs/test/a.sql",
        lease_token=lease_token,
        lease_expires_at=datetime.utcnow(),
        attempt_count=attempt_count,
    )
    db.add(job)
    db.add(task)
    db.commit()
    return task_id, lease_token


class TestClassifyTaskFailure:
    def test_file_not_found_is_permanent(self):
        assert classify_task_failure("SQL file not found: x.sql") == "permanent"

    def test_invalid_sql_skip_is_permanent(self):
        msg = "跳过无效的SQL文件: jobs/x.sql"
        assert classify_task_failure(msg) == "permanent"

    def test_illegal_dialect_is_permanent(self):
        exc = SQLFluffException("创建Linter", "x.sql", "unsupported dialect foo")
        assert classify_task_failure(str(exc), exc) == "permanent"

    def test_os_error_is_retryable(self):
        assert classify_task_failure("NFS read failed", OSError("nfs timeout")) == "retryable"

    def test_connection_error_is_retryable(self):
        assert classify_task_failure(
            "database connection reset",
            ConnectionError("reset"),
        ) == "retryable"

    def test_file_exception_is_retryable(self):
        exc = FileException("写入", "/nfs/x", "I/O error")
        assert classify_task_failure(str(exc), exc) == "retryable"


class TestMarkTaskFailed:
    def test_permanent_failure_marks_failure_immediately(
        self, db_session, mock_managed_db
    ):
        task_id, lease_token = _create_in_progress_task(db_session)

        _mark_task_failed(
            task_id,
            "SQL file not found: missing.sql",
            lease_token,
        )

        task = db_session.query(LintingTask).filter_by(task_id=task_id).one()
        assert task.status == TaskStatusEnum.FAILURE
        assert task.finished_at is not None
        assert task.next_attempt_at is None
        assert task.lease_token is None

    def test_retryable_failure_resets_to_pending_with_backoff(
        self, db_session, mock_managed_db
    ):
        task_id, lease_token = _create_in_progress_task(
            db_session, attempt_count=1
        )

        _mark_task_failed(
            task_id,
            "NFS timeout while reading file",
            lease_token,
            exc=OSError("timeout"),
        )

        task = db_session.query(LintingTask).filter_by(task_id=task_id).one()
        assert task.status == TaskStatusEnum.PENDING
        assert task.finished_at is None
        assert task.next_attempt_at is not None
        assert task.next_attempt_at > datetime.utcnow()
        assert task.attempt_count == 1

    def test_retryable_exhausted_becomes_failure(
        self, db_session, mock_managed_db
    ):
        task_id, lease_token = _create_in_progress_task(
            db_session, attempt_count=4
        )

        _mark_task_failed(
            task_id,
            "connection reset",
            lease_token,
            exc=ConnectionError("reset"),
        )

        task = db_session.query(LintingTask).filter_by(task_id=task_id).one()
        assert task.status == TaskStatusEnum.FAILURE
        assert "超过最大重试次数" in task.error_message
