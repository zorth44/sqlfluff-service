"""
Celery任务定义

实现SQL文件处理和ZIP解压的异步任务，包括：
- expand_zip_and_dispatch_tasks: ZIP文件解压和任务派发
- process_sql_file: SQL文件分析任务
- 分布式锁防止任务重复执行
- 完善的错误处理和重试机制
"""

import os
import tempfile
import redis
from contextlib import contextmanager
from celery import current_task
from sqlalchemy.orm import Session
from typing import List, Dict, Any

from app.celery_app.celery_main import celery_app
from app.core.database import SessionLocal
from app.models.database import LintingJob, LintingTask
from app.services.sqlfluff_service import SQLFluffService
from app.utils.file_utils import FileManager
from app.core.logging import service_logger
from app.core.exceptions import JobException, TaskException, FileException, SQLFluffException, ErrorCode
from app.config.settings import get_settings
from app.schemas.common import JobStatusEnum, TaskStatusEnum, SubmissionTypeEnum
from app.utils.uuid_utils import generate_task_id

settings = get_settings()

# Redis客户端用于分布式锁
redis_client = redis.Redis.from_url(settings.get_celery_broker_url())


@contextmanager
def task_lock(task_id: str, timeout: int = 300):
    """
    任务执行锁，防止任务重复执行
    
    Args:
        task_id: 任务ID
        timeout: 锁超时时间（秒）
    """
    lock_key = f"task_lock:{task_id}"
    lock = redis_client.lock(lock_key, timeout=timeout)
    
    try:
        if lock.acquire(blocking=False):
            yield
        else:
            raise Exception(f"Task {task_id} is already being processed")
    finally:
        try:
            lock.release()
        except:
            pass


def update_job_status_based_on_tasks(job_id: str, db: Session):
    """根据子任务状态更新Job状态"""
    try:
        # 获取Job下所有Task的状态
        tasks = db.query(LintingTask).filter(LintingTask.job_id == job_id).all()
        
        if not tasks:
            return
        
        # 过滤掉被跳过的无效文件Task（错误消息包含"跳过无效的SQL文件"）
        valid_tasks = []
        skipped_count = 0
        
        for task in tasks:
            if (task.status == TaskStatusEnum.FAILURE and 
                task.error_message and "跳过无效的SQL文件" in task.error_message):
                skipped_count += 1
                service_logger.debug(f"忽略被跳过的Task: {task.task_id}")
            else:
                valid_tasks.append(task)
        
        service_logger.info(f"Job {job_id}: 总Task数={len(tasks)}, 有效Task数={len(valid_tasks)}, 跳过的无效文件={skipped_count}")
        
        if not valid_tasks:
            # 如果没有有效的Task，说明所有文件都是无效的
            new_status = JobStatusEnum.FAILED
            service_logger.warning(f"Job {job_id} 中没有有效的SQL文件")
        else:
            # 只基于有效Task计算状态
            valid_task_statuses = [task.status for task in valid_tasks]
            
            if all(status == TaskStatusEnum.SUCCESS for status in valid_task_statuses):
                new_status = JobStatusEnum.COMPLETED
            elif any(status == TaskStatusEnum.SUCCESS for status in valid_task_statuses):
                new_status = JobStatusEnum.PARTIALLY_COMPLETED
            elif all(status == TaskStatusEnum.FAILURE for status in valid_task_statuses):
                new_status = JobStatusEnum.FAILED
            else:
                new_status = JobStatusEnum.PROCESSING
        
        # 更新Job状态
        job = db.query(LintingJob).filter(LintingJob.job_id == job_id).first()
        if job:
            job.status = new_status
            db.commit()
            service_logger.info(f"Updated job status: {job_id} -> {new_status} (基于 {len(valid_tasks)} 个有效Task)")
    except Exception as e:
        db.rollback()
        service_logger.error(f"Failed to update job status for {job_id}: {e}")


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def expand_zip_and_dispatch_tasks(self, job_id: str):
    """
    处理Job并派发相应的任务
    
    根据Job的提交类型：
    - 单SQL文件：直接创建Task并派发process_sql_file任务
    - ZIP包：解压ZIP文件并为每个SQL文件创建Task
    
    Args:
        job_id: 核验工作ID
    """
    db = SessionLocal()
    try:
        with task_lock(f"expand_zip_{job_id}"):
            service_logger.info(f"Starting job processing for job: {job_id}")
            
            # 获取Job信息
            job = db.query(LintingJob).filter(LintingJob.job_id == job_id).first()
            if not job:
                raise JobException(ErrorCode.JOB_NOT_FOUND, job_id, f"Job not found: {job_id}")
            
            # 更新Job状态为PROCESSING
            job.status = JobStatusEnum.PROCESSING
            db.commit()
            
            # 初始化文件管理器
            file_manager = FileManager()
            
            # 根据提交类型处理
            if job.submission_type == SubmissionTypeEnum.SINGLE_FILE:
                # 单SQL文件处理
                service_logger.info(f"Processing single SQL file for job: {job_id}")
                
                # 检查是否已经存在Task记录
                existing_task = db.query(LintingTask).filter(LintingTask.job_id == job_id).first()
                if existing_task:
                    service_logger.info(f"Task already exists for job {job_id}: {existing_task.task_id}")
                    # 如果Task已经存在，直接派发处理任务
                    process_sql_file.delay(existing_task.task_id)
                    return {
                        "status": "success",
                        "job_id": job_id,
                        "total_tasks": 1,
                        "task_ids": [existing_task.task_id]
                    }
                
                # 验证SQL文件存在
                if not file_manager.file_exists(job.source_path):
                    error_msg = f"SQL file not found: {job.source_path}"
                    service_logger.error(error_msg)
                    job.status = JobStatusEnum.FAILED
                    job.error_message = error_msg
                    db.commit()
                    return {"status": "failed", "message": error_msg}
                
                # 创建Task记录
                task_id = generate_task_id()
                task = LintingTask(
                    task_id=task_id,
                    job_id=job_id,
                    status=TaskStatusEnum.PENDING,
                    source_file_path=job.source_path
                )
                db.add(task)
                db.commit()
                
                # 派发SQL文件处理任务
                process_sql_file.delay(task_id)
                service_logger.info(f"Dispatched SQL processing task: {task_id} for single file")
                
                return {
                    "status": "success",
                    "job_id": job_id,
                    "total_tasks": 1,
                    "task_ids": [task_id]
                }
                
            else:
                # ZIP包处理
                service_logger.info(f"Processing ZIP file for job: {job_id}")
                
                # 构建ZIP文件完整路径
                zip_full_path = file_manager.get_absolute_path(job.source_path)
                service_logger.info(f"Processing ZIP file: {zip_full_path}")
                
                # 创建临时解压目录
                with tempfile.TemporaryDirectory() as temp_dir:
                    service_logger.info(f"Extracting ZIP file to: {temp_dir}")
                    
                    # 解压ZIP文件并获取SQL文件列表
                    try:
                        extract_dir, sql_files = file_manager.extract_zip_file(job.source_path, temp_dir)
                        service_logger.info(f"Found {len(sql_files)} SQL files in ZIP")
                    except Exception as e:
                        error_msg = f"ZIP extraction failed: {e}"
                        service_logger.error(error_msg)
                        job.status = JobStatusEnum.FAILED
                        job.error_message = error_msg
                        db.commit()
                        raise
                    
                    if not sql_files:
                        error_msg = "No SQL files found in ZIP archive"
                        service_logger.warning(error_msg)
                        job.status = JobStatusEnum.FAILED
                        job.error_message = error_msg
                        db.commit()
                        return {"status": "failed", "message": error_msg}
                    
                    # 为每个SQL文件创建Task记录和处理任务
                    task_ids = []
                    
                    for sql_file_path in sql_files:
                        # sql_files现在是字符串列表，每个元素是相对路径
                        file_name = os.path.basename(sql_file_path)
                        
                        # 生成目标文件路径
                        job_dir = f"jobs/{job_id}"
                        file_manager.create_directory(job_dir)
                        target_relative_path = f"{job_dir}/{file_name}"
                        
                        # 复制文件到标准位置
                        file_manager.copy_file(
                            sql_file_path,
                            target_relative_path
                        )
                        
                        # 创建Task记录
                        task_id = generate_task_id()
                        task = LintingTask(
                            task_id=task_id,
                            job_id=job_id,
                            status=TaskStatusEnum.PENDING,
                            source_file_path=target_relative_path
                        )
                        db.add(task)
                        task_ids.append(task_id)
                        
                        # 派发SQL文件处理任务
                        process_sql_file.delay(task_id)
                        service_logger.info(f"Dispatched SQL processing task: {task_id} for file: {file_name}")
                    
                    db.commit()
                    service_logger.info(f"Successfully dispatched {len(task_ids)} SQL processing tasks for job {job_id}")
                    
                    return {
                        "status": "success",
                        "job_id": job_id,
                        "total_tasks": len(task_ids),
                        "task_ids": task_ids
                    }
                
    except Exception as e:
        service_logger.error(f"Failed to process job {job_id}: {e}")
        db.rollback()
        
        try:
            job = db.query(LintingJob).filter(LintingJob.job_id == job_id).first()
            if job:
                job.status = JobStatusEnum.FAILED
                job.error_message = str(e)
                db.commit()
        except Exception as update_error:
            service_logger.error(f"Failed to update job status after error: {update_error}")
        
        # 重试机制
        if self.request.retries < self.max_retries:
            service_logger.info(f"Retrying expand_zip_and_dispatch_tasks for job {job_id} (attempt {self.request.retries + 1})")
            raise self.retry(countdown=60 * (2 ** self.request.retries))
        
        raise
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_sql_file(self, task_id: str):
    """
    处理单个SQL文件
    
    Args:
        task_id: 任务ID
    """
    db = SessionLocal()
    try:
        with task_lock(f"process_sql_{task_id}"):
            service_logger.info(f"Starting SQL file processing for task: {task_id}")
            
            # 获取任务信息
            task = db.query(LintingTask).filter(LintingTask.task_id == task_id).first()
            if not task:
                raise TaskException(ErrorCode.TASK_NOT_FOUND, task_id, f"Task not found: {task_id}")
            
            # 获取关联的Job信息，获取方言设置
            job = db.query(LintingJob).filter(LintingJob.job_id == task.job_id).first()
            if not job:
                raise JobException(ErrorCode.JOB_NOT_FOUND, task.job_id, f"Job not found: {task.job_id}")
            
            # 更新任务状态为IN_PROGRESS
            task.status = TaskStatusEnum.IN_PROGRESS
            db.commit()
            
            service_logger.info(f"Processing SQL file for task {task_id}: {task.source_file_path}")
            
            # 初始化文件管理器
            file_manager = FileManager()
            
            # 获取SQL文件完整路径
            sql_file_path = file_manager.get_absolute_path(task.source_file_path)
            
            if not sql_file_path.exists():
                raise FileException("process_sql_file", str(sql_file_path), "SQL file not found")
            
            # 检查是否为有效的SQL文件（防止处理系统隐藏文件）
            if not file_manager._is_valid_sql_file(sql_file_path):
                error_msg = f"跳过无效的SQL文件: {task.source_file_path}"
                service_logger.warning(error_msg)
                # 将Task标记为失败，但不影响Job状态
                task.status = TaskStatusEnum.FAILURE
                task.error_message = error_msg
                db.commit()
                return {
                    "status": "skipped",
                    "task_id": task_id,
                    "job_id": task.job_id,
                    "message": error_msg
                }
            
            # 使用SQLFluff分析SQL文件
            sqlfluff_service = SQLFluffService()
            service_logger.info(f"Analyzing SQL file with SQLFluff: {sql_file_path}, dialect: {job.dialect}")
            
            # 传递相对路径和方言给SQLFluffService
            analysis_result = sqlfluff_service.analyze_sql_file(task.source_file_path, job.dialect)
            
            # 生成结果文件路径
            result_relative_path = f"results/{task.job_id}/{task_id}_result.json"
            
            # 保存分析结果
            result_file_path = file_manager.write_json_file(result_relative_path, analysis_result)
            service_logger.info(f"Analysis result saved to: {result_file_path}")
            
            # 更新任务状态为SUCCESS
            task.status = TaskStatusEnum.SUCCESS
            task.result_file_path = result_relative_path
            db.commit()
            
            service_logger.info(f"Successfully processed SQL file for task {task_id}")
            
            # 检查并更新父Job状态
            update_job_status_based_on_tasks(task.job_id, db)
            
            return {
                "status": "success",
                "task_id": task_id,
                "job_id": task.job_id,
                "result_file_path": result_relative_path,
                "violations_count": analysis_result.get("summary", {}).get("total_violations", 0)
            }
            
    except Exception as e:
        service_logger.error(f"Failed to process SQL file for task {task_id}: {e}")
        db.rollback()
        
        try:
            task = db.query(LintingTask).filter(LintingTask.task_id == task_id).first()
            if task:
                # 更新任务状态为FAILURE
                task.status = TaskStatusEnum.FAILURE
                task.error_message = str(e)
                db.commit()
                
                # 检查并更新父Job状态
                update_job_status_based_on_tasks(task.job_id, db)
                
        except Exception as update_error:
            service_logger.error(f"Failed to update task status after error: {update_error}")
        
        # 重试机制
        if self.request.retries < self.max_retries:
            service_logger.info(f"Retrying process_sql_file for task {task_id} (attempt {self.request.retries + 1})")
            raise self.retry(countdown=60 * (2 ** self.request.retries))
        
        raise
    finally:
        db.close()


# 任务状态查询辅助函数（用于FastAPI）
def get_task_status(task_id: str) -> Dict[str, Any]:
    """
    获取任务状态
    
    Args:
        task_id: Celery任务ID
        
    Returns:
        dict: 任务状态信息
    """
    result = celery_app.AsyncResult(task_id)
    return {
        "task_id": task_id,
        "status": result.status,
        "result": result.result,
        "traceback": result.traceback
    }


def revoke_task(task_id: str, terminate: bool = False):
    """
    撤销任务
    
    Args:
        task_id: Celery任务ID
        terminate: 是否强制终止正在运行的任务
    """
    celery_app.control.revoke(task_id, terminate=terminate) 