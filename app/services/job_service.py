"""
Job业务服务

实现核验工作(Job)的完整业务逻辑，包括创建、查询、状态管理等功能。
为FastAPI Web服务和Celery Worker提供统一的Job业务接口。
"""

from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta
import os

from app.models.database import LintingJob, LintingTask
from app.schemas.job import (
    JobCreateRequest, JobCreateResponse, JobDetailResponse, 
    JobSummary, JobStatistics, TaskSummary
)
from app.schemas.common import PaginationResponse, JobStatusEnum, SubmissionTypeEnum
from app.core.exceptions import JobException, FileException, ErrorCode
from app.core.logging import service_logger
from app.utils.uuid_utils import generate_job_id, generate_task_id
from app.utils.file_utils import FileManager
from app.config.settings import get_settings

settings = get_settings()


class JobService:
    """Job业务服务类"""
    
    def __init__(self, db: Session):
        self.db = db
        self.file_manager = FileManager()
        self.logger = service_logger
    
    async def create_job(self, request: JobCreateRequest) -> JobCreateResponse:
        """
        创建新的核验工作
        
        Args:
            request: 创建请求
            
        Returns:
            JobCreateResponse: 创建响应，包含job_id
        """
        try:
            # 生成job_id
            job_id = generate_job_id()
            
            # 确定submission_type和处理文件
            if request.sql_content:
                submission_type = SubmissionTypeEnum.SINGLE_FILE
                source_path = await self._save_single_sql_content(job_id, request.sql_content)
            else:
                submission_type = SubmissionTypeEnum.ZIP_ARCHIVE
                source_path = request.zip_file_path
                # 验证ZIP文件存在
                if not self.file_manager.file_exists(source_path):
                    raise JobException(ErrorCode.FILE_NOT_FOUND, job_id, "ZIP文件不存在")
            
            # 创建数据库记录
            job = LintingJob(
                job_id=job_id,
                status=JobStatusEnum.ACCEPTED,
                submission_type=submission_type,
                source_path=source_path,
                dialect=request.dialect or "ansi",
                user_id=request.user_id,
                product_name=request.product_name
            )
            
            self.db.add(job)
            self.db.flush()  # 获取数据库生成的id，但不提交事务
            
            # 根据类型创建子任务
            if submission_type == SubmissionTypeEnum.SINGLE_FILE:
                await self._create_single_file_task(job_id, source_path)
            else:
                await self._create_zip_archive_tasks(job_id, source_path)
            
            self.db.commit()
            
            self.logger.info(f"Job创建成功: {job_id}, 类型: {submission_type}")
            return JobCreateResponse(job_id=job_id)
            
        except Exception as e:
            self.db.rollback()
            self.logger.error(f"创建Job失败: {e}")
            if isinstance(e, (JobException, FileException)):
                raise
            raise JobException(ErrorCode.JOB_CREATION_FAILED, job_id, str(e))
    
    async def get_job_by_id(self, job_id: str) -> Optional[LintingJob]:
        """
        根据ID获取Job
        
        Args:
            job_id: Job ID
            
        Returns:
            Optional[LintingJob]: Job对象
        """
        try:
            job = self.db.query(LintingJob).filter(LintingJob.job_id == job_id).first()
            if job:
                self.logger.debug(f"获取Job: {job_id}")
            return job
        except Exception as e:
            self.logger.error(f"获取Job失败: {job_id}, 错误: {e}")
            raise JobException(ErrorCode.JOB_NOT_FOUND, job_id, str(e))
    
    async def get_job_with_tasks(self, job_id: str, page: int = 1, size: int = 10) -> Optional[JobDetailResponse]:
        """
        获取Job及其关联的Tasks分页列表
        
        Args:
            job_id: Job ID
            page: 页码
            size: 每页大小
            
        Returns:
            Optional[JobDetailResponse]: Job详情响应
        """
        try:
            # 获取Job
            job = await self.get_job_by_id(job_id)
            if not job:
                return None
            
            # 获取Task分页数据
            total_tasks = job.tasks.count()
            tasks = job.tasks.offset((page - 1) * size).limit(size).all()
            
            # 构造Task摘要列表
            task_summaries = []
            for task in tasks:
                task_summaries.append(TaskSummary(
                    task_id=task.task_id,
                    file_name=task.file_name,
                    status=task.status,
                    result_file_path=task.result_file_path,
                    error_message=task.error_message,
                    created_at=task.created_at,
                    updated_at=task.updated_at
                ))
            
            # 构造分页响应
            pages = (total_tasks + size - 1) // size
            pagination_response = PaginationResponse[TaskSummary](
                items=task_summaries,
                total=total_tasks,
                page=page,
                size=size,
                pages=pages,
                has_next=page < pages,
                has_prev=page > 1
            )
            
            # 构造完整响应
            response = JobDetailResponse(
                job_id=job.job_id,
                job_status=job.status,
                submission_type=job.submission_type,
                source_path=job.source_path,
                dialect=job.dialect,
                user_id=job.user_id,
                product_name=job.product_name,
                created_at=job.created_at,
                updated_at=job.updated_at,
                error_message=job.error_message,
                sub_tasks=pagination_response
            )
            
            self.logger.debug(f"获取Job详情: {job_id}, 任务数: {total_tasks}")
            return response
            
        except Exception as e:
            self.logger.error(f"获取Job详情失败: {job_id}, 错误: {e}")
            raise JobException(ErrorCode.JOB_NOT_FOUND, job_id, str(e))
    
    async def get_job_task_ids(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        获取Job下的所有任务ID列表
        
        Args:
            job_id: Job ID
            
        Returns:
            Optional[Dict[str, Any]]: 包含task_ids列表和总数的字典
        """
        try:
            # 获取Job
            job = await self.get_job_by_id(job_id)
            if not job:
                return None
            
            # 获取所有任务的ID
            task_ids = [task.task_id for task in job.tasks.all()]
            
            result = {
                "job_id": job_id,
                "task_ids": task_ids,
                "total_count": len(task_ids)
            }
            
            self.logger.debug(f"获取Job任务ID列表: {job_id}, 任务数: {len(task_ids)}")
            return result
            
        except Exception as e:
            self.logger.error(f"获取Job任务ID列表失败: {job_id}, 错误: {e}")
            raise JobException(ErrorCode.JOB_NOT_FOUND, job_id, str(e))
    
    async def update_job_status(self, job_id: str, status: JobStatusEnum, error_message: Optional[str] = None):
        """
        更新Job状态
        
        Args:
            job_id: Job ID
            status: 新状态
            error_message: 错误消息
        """
        try:
            job = await self.get_job_by_id(job_id)
            if not job:
                raise JobException(ErrorCode.JOB_NOT_FOUND, job_id, "Job不存在")
            
            # 验证状态转换
            if not self._is_valid_status_transition(job.status, status):
                raise JobException(ErrorCode.JOB_INVALID_STATUS, job_id, f"无效的状态转换: {job.status} -> {status}")
            
            job.status = status
            if error_message:
                job.error_message = error_message
            
            self.db.commit()
            self.logger.info(f"Job状态更新: {job_id}, {status}")
            
        except Exception as e:
            self.db.rollback()
            self.logger.error(f"更新Job状态失败: {job_id}, 错误: {e}")
            if isinstance(e, JobException):
                raise
            raise JobException(ErrorCode.JOB_UPDATE_FAILED, job_id, str(e))
    
    async def calculate_job_status(self, job_id: str) -> JobStatusEnum:
        """
        根据子任务状态计算Job总体状态
        
        Args:
            job_id: Job ID
            
        Returns:
            JobStatusEnum: 计算后的状态
        """
        try:
            job = await self.get_job_by_id(job_id)
            if not job:
                raise JobException(ErrorCode.JOB_NOT_FOUND, job_id, "Job不存在")
            
            # 获取任务统计
            total_tasks = job.get_task_count()
            successful_tasks = job.get_successful_task_count()
            failed_tasks = job.get_failed_task_count()
            pending_tasks = job.tasks.filter(LintingTask.status == 'PENDING').count()
            in_progress_tasks = job.tasks.filter(LintingTask.status == 'IN_PROGRESS').count()
            
            # 计算状态
            if total_tasks == 0:
                new_status = JobStatusEnum.ACCEPTED
            elif pending_tasks > 0 or in_progress_tasks > 0:
                new_status = JobStatusEnum.PROCESSING
            elif successful_tasks == total_tasks:
                new_status = JobStatusEnum.COMPLETED
            elif successful_tasks > 0:
                new_status = JobStatusEnum.PARTIALLY_COMPLETED
            else:
                new_status = JobStatusEnum.FAILED
            
            # 如果状态发生变化，更新数据库
            if job.status != new_status:
                await self.update_job_status(job_id, new_status)
            
            self.logger.debug(f"Job状态计算: {job_id}, {new_status}")
            return new_status
            
        except Exception as e:
            self.logger.error(f"计算Job状态失败: {job_id}, 错误: {e}")
            if isinstance(e, JobException):
                raise
            raise JobException(ErrorCode.JOB_UPDATE_FAILED, job_id, str(e))
    
    async def get_job_statistics(self, start_date: Optional[datetime] = None, 
                               end_date: Optional[datetime] = None) -> JobStatistics:
        """
        获取Job统计信息
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            JobStatistics: 统计信息
        """
        try:
            query = self.db.query(LintingJob)
            
            # 日期范围过滤
            if start_date:
                query = query.filter(LintingJob.created_at >= start_date)
            if end_date:
                query = query.filter(LintingJob.created_at <= end_date)
            
            # 统计各状态的Job数量
            total_jobs = query.count()
            accepted_jobs = query.filter(LintingJob.status == JobStatusEnum.ACCEPTED).count()
            processing_jobs = query.filter(LintingJob.status == JobStatusEnum.PROCESSING).count()
            completed_jobs = query.filter(LintingJob.status == JobStatusEnum.COMPLETED).count()
            partially_completed_jobs = query.filter(LintingJob.status == JobStatusEnum.PARTIALLY_COMPLETED).count()
            failed_jobs = query.filter(LintingJob.status == JobStatusEnum.FAILED).count()
            
            # 计算平均处理时间
            avg_processing_time = None
            if completed_jobs > 0:
                completed_query = query.filter(LintingJob.status == JobStatusEnum.COMPLETED)
                avg_time_result = self.db.query(
                    func.avg(
                        func.timestampdiff(
                            "SECOND", 
                            LintingJob.created_at, 
                            LintingJob.updated_at
                        )
                    )
                ).filter(LintingJob.status == JobStatusEnum.COMPLETED).scalar()
                
                if avg_time_result:
                    avg_processing_time = float(avg_time_result) / 60  # 转换为分钟
            
            return JobStatistics(
                total_jobs=total_jobs,
                accepted_jobs=accepted_jobs,
                processing_jobs=processing_jobs,
                completed_jobs=completed_jobs,
                partially_completed_jobs=partially_completed_jobs,
                failed_jobs=failed_jobs,
                avg_processing_time=avg_processing_time
            )
            
        except Exception as e:
            self.logger.error(f"获取Job统计失败: {e}")
            raise JobException(ErrorCode.DATABASE_QUERY_ERROR, "all", str(e))
    
    async def list_jobs(self, page: int = 1, size: int = 10,
                       status: Optional[JobStatusEnum] = None,
                       submission_type: Optional[SubmissionTypeEnum] = None,
                       start_date: Optional[datetime] = None,
                       end_date: Optional[datetime] = None) -> PaginationResponse[JobSummary]:
        """
        获取Job列表（分页）
        
        Args:
            page: 页码
            size: 每页大小
            status: 状态过滤
            submission_type: 提交类型过滤
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            PaginationResponse[JobSummary]: 分页的Job摘要列表
        """
        try:
            query = self.db.query(LintingJob)
            
            # 应用过滤条件
            if status:
                query = query.filter(LintingJob.status == status)
            if submission_type:
                query = query.filter(LintingJob.submission_type == submission_type)
            if start_date:
                query = query.filter(LintingJob.created_at >= start_date)
            if end_date:
                query = query.filter(LintingJob.created_at <= end_date)
            
            # 排序
            query = query.order_by(LintingJob.created_at.desc())
            
            # 分页
            total = query.count()
            jobs = query.offset((page - 1) * size).limit(size).all()
            
            # 构造摘要列表
            job_summaries = []
            for job in jobs:
                job_summaries.append(JobSummary(
                    job_id=job.job_id,
                    status=job.status,
                    submission_type=job.submission_type,
                    source_path=job.source_path,
                    dialect=job.dialect,
                    user_id=job.user_id,
                    product_name=job.product_name,
                    created_at=job.created_at,
                    updated_at=job.updated_at,
                    task_count=job.get_task_count(),
                    successful_tasks=job.get_successful_task_count(),
                    failed_tasks=job.get_failed_task_count(),
                    error_message=job.error_message
                ))
            
            # 构造分页响应
            pages = (total + size - 1) // size
            return PaginationResponse[JobSummary](
                items=job_summaries,
                total=total,
                page=page,
                size=size,
                pages=pages,
                has_next=page < pages,
                has_prev=page > 1
            )
            
        except Exception as e:
            self.logger.error(f"获取Job列表失败: {e}")
            raise JobException(ErrorCode.DATABASE_QUERY_ERROR, "all", str(e))
    
    # 私有方法
    
    async def _save_single_sql_content(self, job_id: str, sql_content: str) -> str:
        """保存单个SQL内容到文件"""
        try:
            # 生成文件路径
            file_name = f"single_sql_{job_id}.sql"
            relative_path = f"jobs/{job_id}/sources/{file_name}"
            
            # 保存文件
            self.file_manager.write_text_file(relative_path, sql_content)
            
            self.logger.debug(f"保存单SQL文件: {relative_path}")
            return relative_path
            
        except Exception as e:
            raise FileException("保存SQL文件", relative_path if 'relative_path' in locals() else "unknown", str(e))
    
    async def _create_single_file_task(self, job_id: str, source_path: str):
        """为单个SQL文件创建Task"""
        from app.services.task_service import TaskService
        
        task_service = TaskService(self.db)
        await task_service.create_task(job_id, source_path)
    
    async def _create_zip_archive_tasks(self, job_id: str, zip_path: str):
        """为ZIP文件创建多个Task"""
        try:
            # 解压ZIP文件
            extract_to = f"jobs/{job_id}/extracted"
            extracted_dir, sql_files = self.file_manager.extract_zip_file(zip_path, extract_to)
            
            if not sql_files:
                raise JobException(ErrorCode.FILE_NOT_FOUND, job_id, "ZIP文件中没有找到SQL文件")
            
            # 批量创建Task
            from app.services.task_service import TaskService
            task_service = TaskService(self.db)
            
            # 生成源文件路径列表
            source_paths = []
            for sql_file in sql_files:
                # 相对于NFS根目录的路径
                relative_path = os.path.join(extracted_dir, sql_file).replace('\\', '/')
                source_paths.append(relative_path)
            
            await task_service.batch_create_tasks(job_id, source_paths)
            
            self.logger.info(f"为ZIP文件创建任务: {job_id}, 文件数: {len(sql_files)}")
            
        except Exception as e:
            if isinstance(e, (JobException, FileException)):
                raise
            raise JobException("创建ZIP任务", job_id, str(e))
    
    def _is_valid_status_transition(self, current_status: JobStatusEnum, new_status: JobStatusEnum) -> bool:
        """验证状态转换是否有效"""
        valid_transitions = {
            JobStatusEnum.ACCEPTED: [JobStatusEnum.PROCESSING, JobStatusEnum.FAILED],
            JobStatusEnum.PROCESSING: [JobStatusEnum.COMPLETED, JobStatusEnum.PARTIALLY_COMPLETED, JobStatusEnum.FAILED],
            JobStatusEnum.COMPLETED: [],  # 完成状态不能转换
            JobStatusEnum.PARTIALLY_COMPLETED: [],  # 部分完成状态不能转换
            JobStatusEnum.FAILED: [JobStatusEnum.PROCESSING]  # 失败状态可以重新处理
        }
        
        return new_status in valid_transitions.get(current_status, []) 