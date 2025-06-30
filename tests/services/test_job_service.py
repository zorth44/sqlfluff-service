import pytest
from unittest.mock import patch, MagicMock
from app.services.job_service import JobService
from app.schemas.job import JobCreateRequest
from app.models.database import LintingJob, JobStatusEnum, SubmissionTypeEnum
from app.core.exceptions import JobException

class TestJobService:
    def test_create_single_sql_job(self, db_session):
        """测试创建单SQL工作"""
        job_service = JobService(db_session)
        request = JobCreateRequest(sql_content="SELECT * FROM users;")
        
        job_id = job_service.create_job(request)
        
        assert job_id is not None
        job = job_service.get_job_by_id(job_id)
        assert job.submission_type == SubmissionTypeEnum.SINGLE_FILE
        assert job.status == JobStatusEnum.ACCEPTED
    
    def test_create_zip_job(self, db_session):
        """测试创建ZIP工作"""
        job_service = JobService(db_session)
        request = JobCreateRequest(zip_file_path="/tmp/test.zip")
        
        job_id = job_service.create_job(request)
        
        job = job_service.get_job_by_id(job_id)
        assert job.submission_type == SubmissionTypeEnum.ZIP_ARCHIVE
        assert job.status == JobStatusEnum.ACCEPTED
    
    def test_get_job_by_id_success(self, db_session):
        """测试根据ID获取Job成功"""
        job_service = JobService(db_session)
        request = JobCreateRequest(sql_content="SELECT * FROM users;")
        job_id = job_service.create_job(request)
        
        job = job_service.get_job_by_id(job_id)
        assert job is not None
        assert job.job_id == job_id
    
    def test_get_job_by_id_not_found(self, db_session):
        """测试根据ID获取Job失败"""
        job_service = JobService(db_session)
        
        job = job_service.get_job_by_id("non-existent-id")
        assert job is None
    
    def test_update_job_status(self, db_session):
        """测试更新Job状态"""
        job_service = JobService(db_session)
        request = JobCreateRequest(sql_content="SELECT * FROM users;")
        job_id = job_service.create_job(request)
        
        job_service.update_job_status(job_id, JobStatusEnum.PROCESSING)
        
        job = job_service.get_job_by_id(job_id)
        assert job.status == JobStatusEnum.PROCESSING
    
    def test_calculate_job_status_completed(self, db_session):
        """测试计算Job状态为完成"""
        job_service = JobService(db_session)
        request = JobCreateRequest(sql_content="SELECT * FROM users;")
        job_id = job_service.create_job(request)
        
        # 模拟所有任务完成
        with patch.object(job_service.task_service, 'get_tasks_by_job_id') as mock_get_tasks:
            mock_get_tasks.return_value = [
                MagicMock(status='SUCCESS'),
                MagicMock(status='SUCCESS')
            ]
            
            status = job_service.calculate_job_status(job_id)
            assert status == JobStatusEnum.COMPLETED
    
    def test_calculate_job_status_partially_completed(self, db_session):
        """测试计算Job状态为部分完成"""
        job_service = JobService(db_session)
        request = JobCreateRequest(sql_content="SELECT * FROM users;")
        job_id = job_service.create_job(request)
        
        # 模拟部分任务完成
        with patch.object(job_service.task_service, 'get_tasks_by_job_id') as mock_get_tasks:
            mock_get_tasks.return_value = [
                MagicMock(status='SUCCESS'),
                MagicMock(status='FAILURE')
            ]
            
            status = job_service.calculate_job_status(job_id)
            assert status == JobStatusEnum.PARTIALLY_COMPLETED
    
    def test_get_job_statistics(self, db_session):
        """测试获取Job统计信息"""
        job_service = JobService(db_session)
        
        # 创建多个Job
        for i in range(3):
            request = JobCreateRequest(sql_content=f"SELECT * FROM table{i};")
            job_service.create_job(request)
        
        stats = job_service.get_job_statistics()
        assert stats.total_jobs >= 3
        assert stats.completed_jobs >= 0
        assert stats.failed_jobs >= 0
    
    def test_invalid_job_request(self, db_session):
        """测试无效的Job请求"""
        job_service = JobService(db_session)
        request = JobCreateRequest()  # 没有sql_content也没有zip_file_path
        
        with pytest.raises(JobException):
            job_service.create_job(request) 