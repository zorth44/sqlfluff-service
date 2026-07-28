import pytest
from unittest.mock import patch, MagicMock
from pydantic import ValidationError
from app.services.job_service import JobService
from app.schemas.job import JobCreateRequest
from app.schemas.common import JobStatusEnum, SubmissionTypeEnum


def _job_request(**overrides):
    data = {
        "sql_content": "SELECT * FROM users;",
        "user_id": "test-user",
        "product_name": "test-product",
    }
    data.update(overrides)
    return JobCreateRequest(**data)


class TestJobService:
    @pytest.mark.asyncio
    async def test_create_single_sql_job(self, db_session):
        """测试创建单SQL工作"""
        job_service = JobService(db_session)
        request = _job_request()

        response = await job_service.create_job(request)

        assert response.job_id is not None
        job = await job_service.get_job_by_id(response.job_id)
        assert job.submission_type == SubmissionTypeEnum.SINGLE_FILE
        assert job.status == JobStatusEnum.ACCEPTED

    @pytest.mark.asyncio
    async def test_create_zip_job(self, db_session):
        """测试创建ZIP工作"""
        job_service = JobService(db_session)
        request = _job_request(
            sql_content=None,
            zip_file_path="archives/test.zip",
        )

        with patch.object(job_service.file_manager, 'file_exists', return_value=True):
            response = await job_service.create_job(request)

        job = await job_service.get_job_by_id(response.job_id)
        assert job.submission_type == SubmissionTypeEnum.ZIP_ARCHIVE
        assert job.status == JobStatusEnum.ACCEPTED

    @pytest.mark.asyncio
    async def test_get_job_by_id_success(self, db_session):
        """测试根据ID获取Job成功"""
        job_service = JobService(db_session)
        response = await job_service.create_job(_job_request())

        job = await job_service.get_job_by_id(response.job_id)
        assert job is not None
        assert job.job_id == response.job_id

    @pytest.mark.asyncio
    async def test_get_job_by_id_not_found(self, db_session):
        """测试根据ID获取Job失败"""
        job_service = JobService(db_session)

        job = await job_service.get_job_by_id("non-existent-id")
        assert job is None

    @pytest.mark.asyncio
    async def test_update_job_status(self, db_session):
        """测试更新Job状态"""
        job_service = JobService(db_session)
        response = await job_service.create_job(_job_request())

        await job_service.update_job_status(response.job_id, JobStatusEnum.PROCESSING)

        job = await job_service.get_job_by_id(response.job_id)
        assert job.status == JobStatusEnum.PROCESSING

    @pytest.mark.asyncio
    async def test_calculate_job_status_completed(self, db_session):
        """测试计算Job状态为完成"""
        job_service = JobService(db_session)
        response = await job_service.create_job(_job_request())

        with patch(
            'app.services.job_status.compute_aggregate_job_status',
            return_value=JobStatusEnum.COMPLETED,
        ):
            status = await job_service.calculate_job_status(response.job_id)
            assert status == JobStatusEnum.COMPLETED

    @pytest.mark.asyncio
    async def test_calculate_job_status_partially_completed(self, db_session):
        """测试计算Job状态为部分完成"""
        job_service = JobService(db_session)
        response = await job_service.create_job(_job_request())

        with patch(
            'app.services.job_status.compute_aggregate_job_status',
            return_value=JobStatusEnum.PARTIALLY_COMPLETED,
        ):
            status = await job_service.calculate_job_status(response.job_id)
            assert status == JobStatusEnum.PARTIALLY_COMPLETED

    @pytest.mark.asyncio
    async def test_get_job_statistics(self, db_session):
        """SQLite 不支持 MySQL 的 TIMESTAMPDIFF，统计接口需集成测覆盖。"""
        pytest.skip("get_job_statistics 依赖 MySQL TIMESTAMPDIFF，SQLite 单测跳过")

    def test_invalid_job_request(self, db_session):
        """测试无效的Job请求"""
        with pytest.raises(ValidationError):
            JobCreateRequest(user_id="u", product_name="p")
