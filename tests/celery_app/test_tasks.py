import pytest
from unittest.mock import patch, MagicMock
from app.celery_app.tasks import process_sql_file, expand_zip_and_dispatch_tasks
from app.models.database import TaskStatusEnum, JobStatusEnum

class TestCeleryTasks:
    @patch('app.celery_app.tasks.SQLFluffService')
    @patch('app.celery_app.tasks.FileUtils')
    def test_process_sql_file_success(self, mock_file_utils, mock_sqlfluff):
        """测试SQL文件处理任务成功"""
        # 设置mock
        mock_sqlfluff.return_value.analyze_sql_file.return_value = {
            "violations": [],
            "summary": {"error_count": 0}
        }
        
        # 模拟数据库会话
        mock_db = MagicMock()
        mock_task = MagicMock()
        mock_task.task_id = "test-task-id"
        mock_task.status = TaskStatusEnum.PENDING
        
        with patch('app.celery_app.tasks.get_db') as mock_get_db:
            mock_get_db.return_value = mock_db
            with patch('app.celery_app.tasks.TaskService') as mock_task_service:
                mock_task_service.return_value.get_task_by_id.return_value = mock_task
                
                # 执行任务
                result = process_sql_file("test-task-id")
                
                # 验证结果
                assert result is not None
                mock_sqlfluff.return_value.analyze_sql_file.assert_called_once()
                mock_task_service.return_value.update_task_status.assert_called()
    
    @patch('app.celery_app.tasks.SQLFluffService')
    def test_process_sql_file_failure(self, mock_sqlfluff):
        """测试SQL文件处理任务失败"""
        # 设置mock抛出异常
        mock_sqlfluff.return_value.analyze_sql_file.side_effect = Exception("Analysis failed")
        
        # 模拟数据库会话
        mock_db = MagicMock()
        mock_task = MagicMock()
        mock_task.task_id = "test-task-id"
        mock_task.status = TaskStatusEnum.PENDING
        
        with patch('app.celery_app.tasks.get_db') as mock_get_db:
            mock_get_db.return_value = mock_db
            with patch('app.celery_app.tasks.TaskService') as mock_task_service:
                mock_task_service.return_value.get_task_by_id.return_value = mock_task
                
                # 执行任务
                result = process_sql_file("test-task-id")
                
                # 验证任务被标记为失败
                mock_task_service.return_value.update_task_status.assert_called_with(
                    "test-task-id", 
                    TaskStatusEnum.FAILURE,
                    error_message="Analysis failed"
                )
    
    @patch('app.celery_app.tasks.zipfile')
    @patch('app.celery_app.tasks.os')
    def test_expand_zip_and_dispatch_tasks_success(self, mock_os, mock_zipfile):
        """测试ZIP解压和任务派发成功"""
        # 设置mock
        mock_os.path.exists.return_value = True
        mock_os.path.join.return_value = "/tmp/test"
        mock_os.makedirs.return_value = None
        
        # 模拟ZIP文件内容
        mock_zipfile.ZipFile.return_value.__enter__.return_value.namelist.return_value = [
            "query1.sql",
            "query2.sql"
        ]
        
        # 模拟数据库会话
        mock_db = MagicMock()
        mock_job = MagicMock()
        mock_job.job_id = "test-job-id"
        mock_job.status = JobStatusEnum.ACCEPTED
        
        with patch('app.celery_app.tasks.get_db') as mock_get_db:
            mock_get_db.return_value = mock_db
            with patch('app.celery_app.tasks.JobService') as mock_job_service:
                mock_job_service.return_value.get_job_by_id.return_value = mock_job
                with patch('app.celery_app.tasks.TaskService') as mock_task_service:
                    mock_task_service.return_value.batch_create_tasks.return_value = [
                        "task1", "task2"
                    ]
                    with patch('app.celery_app.tasks.process_sql_file') as mock_process_task:
                        
                        # 执行任务
                        result = expand_zip_and_dispatch_tasks("test-job-id")
                        
                        # 验证结果
                        assert result is not None
                        mock_job_service.return_value.update_job_status.assert_called_with(
                            "test-job-id", 
                            JobStatusEnum.PROCESSING
                        )
                        assert mock_process_task.delay.call_count == 2
    
    def test_expand_zip_and_dispatch_tasks_job_not_found(self):
        """测试ZIP解压任务中Job不存在"""
        # 模拟数据库会话
        mock_db = MagicMock()
        
        with patch('app.celery_app.tasks.get_db') as mock_get_db:
            mock_get_db.return_value = mock_db
            with patch('app.celery_app.tasks.JobService') as mock_job_service:
                mock_job_service.return_value.get_job_by_id.return_value = None
                
                # 执行任务
                result = expand_zip_and_dispatch_tasks("non-existent-job-id")
                
                # 验证任务失败
                assert result is None
    
    @patch('app.celery_app.tasks.redis_client')
    def test_task_lock_mechanism(self, mock_redis):
        """测试任务锁机制"""
        # 设置Redis锁mock
        mock_lock = MagicMock()
        mock_lock.__enter__ = MagicMock()
        mock_lock.__exit__ = MagicMock()
        mock_redis.lock.return_value = mock_lock
        
        # 模拟数据库会话
        mock_db = MagicMock()
        
        with patch('app.celery_app.tasks.get_db') as mock_get_db:
            mock_get_db.return_value = mock_db
            with patch('app.celery_app.tasks.TaskService') as mock_task_service:
                mock_task = MagicMock()
                mock_task.task_id = "test-task-id"
                mock_task_service.return_value.get_task_by_id.return_value = mock_task
                
                # 执行任务
                result = process_sql_file("test-task-id")
                
                # 验证锁被使用
                mock_redis.lock.assert_called_with("task_lock:test-task-id", timeout=300)
                mock_lock.__enter__.assert_called_once()
                mock_lock.__exit__.assert_called_once()
    
    def test_task_retry_mechanism(self):
        """测试任务重试机制"""
        # 模拟任务重试
        with patch('app.celery_app.tasks.process_sql_file.retry') as mock_retry:
            mock_retry.side_effect = Exception("Retry triggered")
            
            # 模拟数据库会话
            mock_db = MagicMock()
            
            with patch('app.celery_app.tasks.get_db') as mock_get_db:
                mock_get_db.return_value = mock_db
                with patch('app.celery_app.tasks.TaskService') as mock_task_service:
                    mock_task = MagicMock()
                    mock_task.task_id = "test-task-id"
                    mock_task_service.return_value.get_task_by_id.return_value = mock_task
                    
                    # 执行任务并触发重试
                    with pytest.raises(Exception):
                        process_sql_file("test-task-id")
                    
                    # 验证重试被调用
                    mock_retry.assert_called_once() 