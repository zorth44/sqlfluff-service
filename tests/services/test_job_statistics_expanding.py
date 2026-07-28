"""Job statistics coverage for the EXPANDING state."""

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.database import LintingJob
from app.schemas.common import JobStatusEnum, SubmissionTypeEnum
from app.services.job_service import JobService


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


def test_job_statistics_counts_expanding_jobs(db_session):
    db_session.add(
        LintingJob(
            job_id="expanding-job",
            status=JobStatusEnum.EXPANDING,
            submission_type=SubmissionTypeEnum.ZIP_ARCHIVE,
            source_path="jobs/expanding-job/archive.zip",
            dialect="ansi",
            user_id="u1",
            product_name="p1",
        )
    )
    db_session.commit()

    stats = asyncio.run(JobService(db_session).get_job_statistics())

    assert stats.total_jobs == 1
    assert stats.expanding_jobs == 1
    assert (
        stats.accepted_jobs
        + stats.expanding_jobs
        + stats.processing_jobs
        + stats.completed_jobs
        + stats.partially_completed_jobs
        + stats.failed_jobs
        == stats.total_jobs
    )
