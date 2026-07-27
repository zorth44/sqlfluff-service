"""
Processor lease fencing tests.
"""

from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.database import LintingJob, LintingTask, LintingViolation
from app.schemas.common import JobStatusEnum, SubmissionTypeEnum, TaskStatusEnum
from app.worker.processor import (
    LeaseLostError,
    _commit_success_with_violations,
    process_sql_file,
)


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


def _create_job_task(
    db,
    *,
    task_id="task-1",
    job_id="job-1",
    lease_token="lease-abc",
    status=TaskStatusEnum.IN_PROGRESS,
):
    job = LintingJob(
        job_id=job_id,
        status=JobStatusEnum.PROCESSING,
        submission_type=SubmissionTypeEnum.SINGLE_FILE,
        source_path="jobs/job-1/a.sql",
        dialect="ansi",
        user_id="u1",
        product_name="p1",
    )
    task = LintingTask(
        task_id=task_id,
        job_id=job_id,
        status=status,
        source_file_path="jobs/job-1/a.sql",
        lease_token=lease_token,
        lease_expires_at=datetime.utcnow(),
        attempt_count=1,
    )
    db.add(job)
    db.add(task)
    db.commit()
    return job, task


ANALYSIS_RESULT = {
    "summary": {"total_violations": 1, "critical_violations_count": 0},
    "violations": [
        {
            "code": "L001",
            "line_no": 1,
            "line_pos": 1,
            "description": "test",
            "severity": "warning",
        }
    ],
}

ANALYSIS_RESULT_EMPTY = {
    "summary": {"total_violations": 0, "critical_violations_count": 0},
    "violations": [],
}


class TestCommitSuccessWithViolations:
    def test_stale_worker_cannot_update_success(self, db_session, mock_managed_db):
        job, task = _create_job_task(db_session, lease_token="current-lease")

        with pytest.raises(LeaseLostError):
            _commit_success_with_violations(
                task_id=task.task_id,
                job=job,
                lease_token="stale-lease",
                analysis_result=ANALYSIS_RESULT,
                result_path=f"results/{job.job_id}/{task.task_id}/stale-lease.json",
                line_count=10,
                sql_file_abs_path="/tmp/a.sql",
            )

        db_session.expire_all()
        refreshed = db_session.query(LintingTask).filter_by(
            task_id=task.task_id
        ).one()
        assert refreshed.status == TaskStatusEnum.IN_PROGRESS
        assert refreshed.lease_token == "current-lease"
        assert refreshed.result_file_path is None

    @patch("app.worker.processor.build_line_map", return_value={1: "SELECT 1"})
    def test_matching_lease_commits_success_and_violations(
        self, mock_line_map, db_session, mock_managed_db
    ):
        job, task = _create_job_task(db_session, lease_token="good-lease")

        _commit_success_with_violations(
            task_id=task.task_id,
            job=job,
            lease_token="good-lease",
            analysis_result=ANALYSIS_RESULT_EMPTY,
            result_path=f"results/{job.job_id}/{task.task_id}/good-lease.json",
            line_count=5,
            sql_file_abs_path="/tmp/a.sql",
        )

        db_session.expire_all()
        refreshed = db_session.query(LintingTask).filter_by(
            task_id=task.task_id
        ).one()
        assert refreshed.status == TaskStatusEnum.SUCCESS
        assert refreshed.lease_token is None
        assert refreshed.result_file_path.endswith("good-lease.json")
        assert db_session.query(LintingViolation).filter_by(
            task_id=task.task_id
        ).count() == 0

    @patch("app.worker.processor.build_line_map", return_value={1: "SELECT 1"})
    @patch("sqlalchemy.orm.session.Session.add_all")
    def test_matching_lease_schedules_violation_insert(
        self, mock_add_all, mock_line_map, db_session, mock_managed_db
    ):
        job, task = _create_job_task(db_session, lease_token="good-lease")

        _commit_success_with_violations(
            task_id=task.task_id,
            job=job,
            lease_token="good-lease",
            analysis_result=ANALYSIS_RESULT,
            result_path=f"results/{job.job_id}/{task.task_id}/good-lease.json",
            line_count=5,
            sql_file_abs_path="/tmp/a.sql",
        )

        mock_add_all.assert_called_once()
        inserted = mock_add_all.call_args[0][0]
        assert len(inserted) == 1
        assert inserted[0].rule_code == "L001"


class TestProcessSqlFileLeaseAbandon:
    @patch("app.worker.processor.update_job_status_after_task")
    @patch("app.worker.processor._commit_success_with_violations")
    @patch("app.worker.processor.run_analyze_in_process")
    @patch("app.worker.processor._validate_sql_file", return_value=None)
    @patch("app.worker.processor.FileManager")
    @patch("app.worker.processor.count_file_lines", return_value=3)
    def test_abandons_when_lease_lost_at_commit(
        self,
        mock_count,
        mock_fm_cls,
        mock_validate,
        mock_analyze,
        mock_commit,
        mock_job_update,
        db_session,
        mock_managed_db,
    ):
        job, task = _create_job_task(db_session)

        fm = MagicMock()
        path_mock = MagicMock()
        path_mock.__str__ = MagicMock(return_value="/tmp/a.sql")
        fm.get_absolute_path.return_value = path_mock
        mock_fm_cls.return_value = fm

        mock_analyze.return_value = ANALYSIS_RESULT
        mock_commit.side_effect = LeaseLostError("lease lost")

        result = process_sql_file(task.task_id, "worker-1", "wrong-token")

        assert result["status"] == "abandoned"
        mock_job_update.assert_not_called()
        fm.cleanup_stale_result_files.assert_not_called()
