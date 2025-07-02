"""
Task业务服务

实现单个文件处理任务(Task)的业务逻辑，包括创建、状态更新、批量操作等功能。
为FastAPI Web服务和Celery Worker提供统一的Task业务接口。
"""

from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta
import os

from app.models.database import LintingJob, LintingTask
from app.schemas.task import (
    TaskResponse, TaskDetailResponse, TaskResultContent,
    TaskStatusUpdateRequest, TaskStatistics, TaskFileInfo
)
from app.schemas.common import PaginationResponse, TaskStatusEnum
from app.core.exceptions import TaskException, JobException, FileException, ErrorCode, DatabaseException
from app.core.logging import service_logger
from app.utils.uuid_utils import generate_task_id
from app.utils.file_utils import FileManager
from app.config.settings import get_settings

settings = get_settings()


class TaskService:
    """Task业务服务类"""
    
    def __init__(self, db: Session):
        self.db = db
        self.file_manager = FileManager()
        self.logger = service_logger
    
    async def create_task(self, job_id: str, source_file_path: str) -> str:
        """
        创建新的文件处理任务
        
        Args:
            job_id: 关联的Job ID
            source_file_path: 源文件路径
            
        Returns:
            str: 生成的Task ID
        """
        try:
            # 验证Job存在
            job = self.db.query(LintingJob).filter(LintingJob.job_id == job_id).first()
            if not job:
                raise JobException(ErrorCode.JOB_NOT_FOUND, job_id, f"关联的Job不存在: {job_id}")
            
            # 验证源文件存在
            if not self.file_manager.file_exists(source_file_path):
                raise FileException("验证源文件", source_file_path, "源文件不存在")
            
            # 生成task_id
            task_id = generate_task_id()
            
            # 创建数据库记录
            task = LintingTask(
                task_id=task_id,
                job_id=job_id,
                status=TaskStatusEnum.PENDING,
                source_file_path=source_file_path
            )
            
            self.db.add(task)
            self.db.commit()
            
            self.logger.info(f"Task创建成功: {task_id}, Job: {job_id}")
            return task_id
            
        except Exception as e:
            self.db.rollback()
            self.logger.error(f"创建Task失败: {e}")
            if isinstance(e, TaskException):
                raise
            raise TaskException(ErrorCode.TASK_CREATION_FAILED, task_id if 'task_id' in locals() else "unknown", str(e))
    
    async def get_task_by_id(self, task_id: str) -> Optional[LintingTask]:
        """
        根据ID获取Task
        
        Args:
            task_id: Task ID
            
        Returns:
            Optional[LintingTask]: Task对象
        """
        try:
            task = self.db.query(LintingTask).filter(LintingTask.task_id == task_id).first()
            if task:
                self.logger.debug(f"获取Task: {task_id}")
            return task
        except Exception as e:
            self.logger.error(f"获取Task失败: {task_id}, 错误: {e}")
            raise TaskException(ErrorCode.TASK_NOT_FOUND, task_id, str(e))
    
    async def get_task_detail(self, task_id: str) -> Optional[TaskDetailResponse]:
        """
        获取Task详细信息
        
        Args:
            task_id: Task ID
            
        Returns:
            Optional[TaskDetailResponse]: Task详细响应
        """
        try:
            task = await self.get_task_by_id(task_id)
            if not task:
                return None
            
            # 获取文件信息
            file_size = None
            processing_duration = None
            
            try:
                if self.file_manager.file_exists(task.source_file_path):
                    file_size = self.file_manager.get_file_size(task.source_file_path)
                
                # 计算处理时长
                if task.status in [TaskStatusEnum.SUCCESS, TaskStatusEnum.FAILURE]:
                    if task.created_at and task.updated_at:
                        duration = task.updated_at - task.created_at
                        processing_duration = duration.total_seconds()
                        
            except Exception as e:
                self.logger.warning(f"获取Task文件信息失败: {task_id}, {e}")
            
            return TaskDetailResponse(
                task_id=task.task_id,
                job_id=task.job_id,
                status=task.status,
                source_file_path=task.source_file_path,
                result_file_path=task.result_file_path,
                error_message=task.error_message,
                created_at=task.created_at,
                updated_at=task.updated_at,
                file_size=file_size,
                processing_duration=processing_duration
            )
            
        except Exception as e:
            self.logger.error(f"获取Task详情失败: {task_id}, 错误: {e}")
            if isinstance(e, TaskException):
                raise
            raise TaskException(ErrorCode.TASK_NOT_FOUND, task_id, str(e))
    
    async def update_task_status(self, task_id: str, status: TaskStatusEnum,
                               result_file_path: Optional[str] = None,
                               error_message: Optional[str] = None) -> None:
        """
        更新Task状态和结果
        
        Args:
            task_id: Task ID
            status: 新状态
            result_file_path: 结果文件路径
            error_message: 错误消息
        """
        try:
            task = await self.get_task_by_id(task_id)
            if not task:
                raise TaskException(ErrorCode.TASK_NOT_FOUND, task_id, "Task不存在")
            
            # 验证状态转换
            if not self._is_valid_status_transition(task.status, status):
                raise TaskException(ErrorCode.TASK_INVALID_STATUS, task_id, f"无效的状态转换: {task.status} -> {status}")
            
            # 更新状态
            task.status = status
            if result_file_path:
                task.result_file_path = result_file_path
            if error_message:
                task.error_message = error_message
            
            self.db.commit()
            
            # 更新关联Job的状态
            await self._update_job_status_by_task_change(task.job_id)
            
            self.logger.info(f"Task状态更新: {task_id}, {status}")
            
        except Exception as e:
            self.db.rollback()
            self.logger.error(f"更新Task状态失败: {task_id}, 错误: {e}")
            if isinstance(e, TaskException):
                raise
            raise TaskException(ErrorCode.TASK_UPDATE_FAILED, task_id, str(e))
    
    async def get_tasks_by_job_id(self, job_id: str, page: int = 1, size: int = 10,
                                status: Optional[TaskStatusEnum] = None) -> PaginationResponse[TaskResponse]:
        """
        获取Job下的Tasks分页列表
        
        Args:
            job_id: Job ID
            page: 页码
            size: 每页大小
            status: 状态过滤
            
        Returns:
            PaginationResponse[TaskResponse]: 分页的Task列表
        """
        try:
            query = self.db.query(LintingTask).filter(LintingTask.job_id == job_id)
            
            # 状态过滤
            if status:
                query = query.filter(LintingTask.status == status)
            
            # 排序
            query = query.order_by(LintingTask.created_at.desc())
            
            # 分页
            total = query.count()
            tasks = query.offset((page - 1) * size).limit(size).all()
            
            # 构造响应列表
            task_responses = []
            for task in tasks:
                task_responses.append(TaskResponse(
                    task_id=task.task_id,
                    file_name=task.file_name,
                    status=task.status,
                    result_file_path=task.result_file_path,
                    error_message=task.error_message,
                    created_at=task.created_at,
                    updated_at=task.updated_at
                ))
            
            # 构造分页响应
            pages = (total + size - 1) // size
            return PaginationResponse[TaskResponse](
                items=task_responses,
                total=total,
                page=page,
                size=size,
                pages=pages,
                has_next=page < pages,
                has_prev=page > 1
            )
            
        except Exception as e:
            self.logger.error(f"获取Job Tasks失败: {job_id}, 错误: {e}")
            raise JobException(ErrorCode.DATABASE_QUERY_ERROR, job_id, str(e))
    
    async def batch_create_tasks(self, job_id: str, file_paths: List[str]) -> List[str]:
        """
        批量创建Tasks
        
        Args:
            job_id: Job ID
            file_paths: 文件路径列表
            
        Returns:
            List[str]: 创建的Task ID列表
        """
        try:
            # 验证Job存在
            job = self.db.query(LintingJob).filter(LintingJob.job_id == job_id).first()
            if not job:
                raise JobException(ErrorCode.JOB_NOT_FOUND, job_id, f"关联的Job不存在: {job_id}")
            
            task_ids = []
            tasks_to_add = []
            
            for file_path in file_paths:
                # 验证文件存在
                if not self.file_manager.file_exists(file_path):
                    self.logger.warning(f"跳过不存在的文件: {file_path}")
                    continue
                
                # 生成task_id
                task_id = generate_task_id()
                task_ids.append(task_id)
                
                # 创建Task对象
                task = LintingTask(
                    task_id=task_id,
                    job_id=job_id,
                    status=TaskStatusEnum.PENDING,
                    source_file_path=file_path
                )
                tasks_to_add.append(task)
            
            # 批量插入
            if tasks_to_add:
                self.db.add_all(tasks_to_add)
                self.db.commit()
                
                self.logger.info(f"批量创建Task成功: Job {job_id}, 数量: {len(tasks_to_add)}")
            
            return task_ids
            
        except Exception as e:
            self.db.rollback()
            self.logger.error(f"批量创建Task失败: {job_id}, 错误: {e}")
            if isinstance(e, TaskException):
                raise
            raise JobException(ErrorCode.JOB_CREATION_FAILED, job_id, str(e))
    
    async def get_task_result(self, task_id: str) -> Optional[TaskResultContent]:
        """
        获取Task分析结果
        
        Args:
            task_id: Task ID
            
        Returns:
            Optional[TaskResultContent]: 分析结果内容
        """
        try:
            task = await self.get_task_by_id(task_id)
            if not task or not task.result_file_path:
                return None
            
            # 读取结果文件
            if not self.file_manager.file_exists(task.result_file_path):
                self.logger.warning(f"结果文件不存在: {task.result_file_path}")
                return None
            
            result_data = self.file_manager.read_json_file(task.result_file_path)
            
            # 获取 file_info 并添加 file_path 属性
            file_info = result_data.get('file_info', {})
            file_info['file_path'] = task.source_file_path
            
            return TaskResultContent(
                violations=result_data.get('violations', []),
                summary=result_data.get('summary', {}),
                file_info=file_info,
                analysis_metadata=result_data.get('analysis_metadata', {})
            )
            
        except Exception as e:
            self.logger.error(f"获取Task结果失败: {task_id}, 错误: {e}")
            raise TaskException(ErrorCode.TASK_RESULT_NOT_READY, task_id, str(e))
    
    async def get_task_statistics(self, job_id: Optional[str] = None,
                                start_date: Optional[datetime] = None,
                                end_date: Optional[datetime] = None) -> TaskStatistics:
        """
        获取Task统计信息
        
        Args:
            job_id: Job ID过滤
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            TaskStatistics: 统计信息
        """
        try:
            query = self.db.query(LintingTask)
            
            # 过滤条件
            if job_id:
                query = query.filter(LintingTask.job_id == job_id)
            if start_date:
                query = query.filter(LintingTask.created_at >= start_date)
            if end_date:
                query = query.filter(LintingTask.created_at <= end_date)
            
            # 统计各状态的Task数量
            total_tasks = query.count()
            pending_tasks = query.filter(LintingTask.status == TaskStatusEnum.PENDING).count()
            in_progress_tasks = query.filter(LintingTask.status == TaskStatusEnum.IN_PROGRESS).count()
            successful_tasks = query.filter(LintingTask.status == TaskStatusEnum.SUCCESS).count()
            failed_tasks = query.filter(LintingTask.status == TaskStatusEnum.FAILURE).count()
            
            # 计算成功率
            success_rate = (successful_tasks / total_tasks * 100) if total_tasks > 0 else 0
            
            # 计算平均处理时间
            avg_processing_time = None
            if successful_tasks > 0:
                from sqlalchemy import text
                avg_time_result = self.db.query(
                    func.avg(
                        text("TIMESTAMPDIFF(SECOND, created_at, updated_at)")
                    )
                ).filter(LintingTask.status == TaskStatusEnum.SUCCESS).scalar()
                
                if avg_time_result:
                    avg_processing_time = float(avg_time_result)
            
            return TaskStatistics(
                total_tasks=total_tasks,
                pending_tasks=pending_tasks,
                in_progress_tasks=in_progress_tasks,
                successful_tasks=successful_tasks,
                failed_tasks=failed_tasks,
                avg_processing_time=avg_processing_time,
                success_rate=success_rate
            )
            
        except Exception as e:
            self.logger.error(f"获取Task统计失败: {e}")
            raise DatabaseException("查询Task统计", str(e))
    
    async def get_pending_tasks(self, limit: int = 100) -> List[LintingTask]:
        """
        获取待处理的Task列表（供Celery Worker使用）
        
        Args:
            limit: 返回数量限制
            
        Returns:
            List[LintingTask]: 待处理的Task列表
        """
        try:
            tasks = self.db.query(LintingTask)\
                .filter(LintingTask.status == TaskStatusEnum.PENDING)\
                .order_by(LintingTask.created_at)\
                .limit(limit)\
                .all()
            
            self.logger.debug(f"获取待处理Task: {len(tasks)}个")
            return tasks
            
        except Exception as e:
            self.logger.error(f"获取待处理Task失败: {e}")
            raise DatabaseException("查询待处理Task", str(e))
    
    async def retry_failed_tasks(self, task_ids: List[str]) -> Tuple[List[str], List[str]]:
        """
        重试失败的Task
        
        Args:
            task_ids: 要重试的Task ID列表
            
        Returns:
            Tuple[List[str], List[str]]: (成功重试的Task ID列表, 失败的Task ID列表)
        """
        try:
            successful_retries = []
            failed_retries = []
            
            for task_id in task_ids:
                try:
                    task = await self.get_task_by_id(task_id)
                    if not task:
                        failed_retries.append(task_id)
                        continue
                    
                    # 只能重试失败的Task
                    if task.status != TaskStatusEnum.FAILURE:
                        failed_retries.append(task_id)
                        continue
                    
                    # 重置状态
                    task.status = TaskStatusEnum.PENDING
                    task.error_message = None
                    task.result_file_path = None
                    
                    successful_retries.append(task_id)
                    
                except Exception as e:
                    self.logger.error(f"重试Task失败: {task_id}, {e}")
                    failed_retries.append(task_id)
            
            if successful_retries:
                self.db.commit()
                self.logger.info(f"重试Task成功: {len(successful_retries)}个")
            
            return successful_retries, failed_retries
            
        except Exception as e:
            self.db.rollback()
            self.logger.error(f"批量重试Task失败: {e}")
            raise DatabaseException("批量重试Task", str(e))
    
    # 私有方法
    
    def _is_valid_status_transition(self, current_status: TaskStatusEnum, new_status: TaskStatusEnum) -> bool:
        """验证状态转换是否有效"""
        valid_transitions = {
            TaskStatusEnum.PENDING: [TaskStatusEnum.IN_PROGRESS, TaskStatusEnum.FAILURE],
            TaskStatusEnum.IN_PROGRESS: [TaskStatusEnum.SUCCESS, TaskStatusEnum.FAILURE],
            TaskStatusEnum.SUCCESS: [],  # 成功状态不能转换
            TaskStatusEnum.FAILURE: [TaskStatusEnum.PENDING, TaskStatusEnum.IN_PROGRESS]  # 失败状态可以重试
        }
        
        return new_status in valid_transitions.get(current_status, [])
    
    async def _update_job_status_by_task_change(self, job_id: str):
        """根据Task变化更新Job状态"""
        try:
            from app.services.job_service import JobService
            
            job_service = JobService(self.db)
            await job_service.calculate_job_status(job_id)
            
        except Exception as e:
            self.logger.error(f"更新Job状态失败: {job_id}, {e}")
            # 不抛出异常，避免影响Task状态更新 