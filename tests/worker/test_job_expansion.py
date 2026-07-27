"""
Job 展开幂等与原子领取测试
"""

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.database import LintingJob, LintingTask
from app.schemas.common import JobStatusEnum, SubmissionTypeEnum, TaskStatusEnum
from app.worker.job_processor import (
    claim_job_for_expansion,
    process_job_expansion,
    try_expand_one_job,
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


def _create_accepted_zip_job(db, job_id="job-zip-1", source_path="jobs/job-zip-1/archive.zip"):
    job = LintingJob(
        job_id=job_id,
        status=JobStatusEnum.ACCEPTED,
        submission_type=SubmissionTypeEnum.ZIP_ARCHIVE,
        source_path=source_path,
        dialect="ansi",
        user_id="u1",
        product_name="p1",
    )
    db.add(job)
    db.commit()
    return job


class TestClaimJobForExpansion:
    def test_only_one_worker_wins_accepted_to_expanding(self, db_session):
        _create_accepted_zip_job(db_session)

        Session = sessionmaker(bind=db_session.get_bind())
        session_a = Session()
        session_b = Session()
        try:
            job_a = claim_job_for_expansion(session_a)
            session_a.commit()
            job_b = claim_job_for_expansion(session_b)

            assert job_a is not None
            assert job_b is None
            assert job_a.status == JobStatusEnum.EXPANDING
        finally:
            session_a.close()
            session_b.close()

    def test_double_expansion_does_not_double_create_tasks(self, db_session, tmp_path, monkeypatch):
        monkeypatch.setenv("NFS_SHARE_ROOT_PATH", str(tmp_path))

        extract_dir = tmp_path / "jobs" / "job-zip-1" / "extracted"
        extract_dir.mkdir(parents=True)
        (extract_dir / "a.sql").write_text("SELECT 1;")
        (extract_dir / "b.sql").write_text("SELECT 2;")

        job = LintingJob(
            job_id="job-zip-1",
            status=JobStatusEnum.ACCEPTED,
            submission_type=SubmissionTypeEnum.ZIP_ARCHIVE,
            source_path=str(extract_dir.relative_to(tmp_path)).replace("\\", "/"),
            dialect="ansi",
            user_id="u1",
            product_name="p1",
        )
        db_session.add(job)
        db_session.commit()

        claimed = claim_job_for_expansion(db_session)
        db_session.commit()
        assert claimed is not None

        with patch(
            "app.worker.job_processor._handle_archive_job",
            return_value=["task-1", "task-2"],
        ) as mock_expand:
            result1 = process_job_expansion(db_session, claimed)
            assert result1["status"] == "success"
            assert mock_expand.call_count == 1

            for tid in ("task-1", "task-2"):
                db_session.add(
                    LintingTask(
                        task_id=tid,
                        job_id="job-zip-1",
                        status=TaskStatusEnum.PENDING,
                        source_file_path=f"jobs/job-zip-1/{tid}.sql",
                    )
                )
            db_session.commit()

            job_row = db_session.query(LintingJob).filter_by(job_id="job-zip-1").one()
            job_row.status = JobStatusEnum.EXPANDING
            db_session.commit()

            result2 = process_job_expansion(db_session, job_row)
            assert result2["status"] == "skipped"
            assert mock_expand.call_count == 1

        task_count = (
            db_session.query(LintingTask)
            .filter(LintingTask.job_id == "job-zip-1")
            .count()
        )
        assert task_count == 2

    def test_try_expand_one_job_returns_none_when_queue_empty(self, db_session):
        assert try_expand_one_job(db_session) is None
