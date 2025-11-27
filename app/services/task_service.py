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
import json

from app.models.database import LintingJob, LintingTask, LintingViolation
from app.schemas.task import (
    TaskResponse, TaskDetailResponse, TaskResultContent,
    TaskStatusUpdateRequest, TaskStatistics, TaskFileInfo,
    TaskLintResultResponse, TaskViolationWithSQL, SeverityLevelStatistics,
    TaskSeverityCalculateResponse, TaskWithViolationsResponse,
    TaskWithViolationsListResponse
)
from app.schemas.common import PaginationResponse, TaskStatusEnum
from app.core.exceptions import TaskException, JobException, FileException, ErrorCode, DatabaseException
from app.core.logging import service_logger
from app.utils.uuid_utils import generate_task_id
from app.utils.file_utils import FileManager
from app.utils.severity_utils import calculate_severity_statistics
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
            
            # 验证文件是否为SQL文件
            if not self.file_manager.is_sql_file(source_file_path):
                raise FileException("验证源文件", source_file_path, "文件不是SQL文件")
            
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
                processing_duration=processing_duration,
                sql_lines=task.sql_lines,
                total_violations=task.total_violations,
                critical_violations=task.critical_violations,
                severity_info=task.severity_info,
                severity_minor=task.severity_minor,
                severity_major=task.severity_major,
                severity_blocker=task.severity_blocker,
                severity_critical=task.severity_critical,
                severity_unknown=task.severity_unknown
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
    
    async def get_tasks_by_job_id(self, job_id: Optional[str], page: int = 1, size: int = 10,
                                status: Optional[TaskStatusEnum] = None,
                                violation_exists: Optional[bool] = None) -> PaginationResponse[TaskResponse]:
        """
        获取Job下的Tasks分页列表
        
        Args:
            job_id: Job ID，如果为None则查询所有任务
            page: 页码
            size: 每页大小  
            status: 状态过滤
            violation_exists: 违规项过滤，True表示只返回有违规的任务，False表示只返回无违规的任务，None表示不过滤
            
        Returns:
            PaginationResponse[TaskResponse]: 分页的Task列表
        """
        try:
            # 构造基础查询
            if job_id:
                query = self.db.query(LintingTask).filter(LintingTask.job_id == job_id)
            else:
                query = self.db.query(LintingTask)
            
            # 状态过滤
            if status:
                query = query.filter(LintingTask.status == status)
            
            # 违规项过滤
            if violation_exists is not None:
                if violation_exists:
                    # 只显示有违规的任务（total_violations > 0）
                    query = query.filter(and_(LintingTask.total_violations.isnot(None), LintingTask.total_violations > 0))
                else:
                    # 只显示无违规的任务（total_violations = 0 或 NULL）
                    query = query.filter(or_(LintingTask.total_violations.is_(None), LintingTask.total_violations == 0))
            
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
                    updated_at=task.updated_at,
                    sql_lines=task.sql_lines,
                    total_violations=task.total_violations,
                    critical_violations=task.critical_violations,
                    severity_info=task.severity_info,
                    severity_minor=task.severity_minor,
                    severity_major=task.severity_major,
                    severity_blocker=task.severity_blocker,
                    severity_critical=task.severity_critical,
                    severity_unknown=task.severity_unknown
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
                
                # 验证文件是否为SQL文件
                if not self.file_manager.is_sql_file(file_path):
                    self.logger.warning(f"跳过非SQL文件: {file_path}")
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
    
    async def get_task_lint_result(self, task_id: str) -> Optional[TaskLintResultResponse]:
        """
        获取Task的Lint结果，包含SQL行内容（从数据库读取）
        
        Args:
            task_id: Task ID
            
        Returns:
            Optional[TaskLintResultResponse]: 带SQL行内容的违规项列表
        """
        try:
            # 验证任务是否存在
            task = await self.get_task_by_id(task_id)
            if not task:
                return None
            
            # 从数据库中查询violations
            from app.models.database import LintingViolation
            violations_records = self.db.query(LintingViolation).filter(
                LintingViolation.task_id == task_id
            ).order_by(LintingViolation.line_no, LintingViolation.line_pos).all()
            
            # 如果没有违规项，直接返回空列表
            if not violations_records:
                self.logger.debug(f"Task {task_id} 没有violations")
                return TaskLintResultResponse(violations=[])
            
            # 将数据库记录转换为响应模型
            violations_with_sql = []
            for violation_record in violations_records:
                violation_with_sql = TaskViolationWithSQL(
                    violation_id=violation_record.id,  # 新增
                    is_appealed=violation_record.is_appealed,  # 新增
                    line_no=violation_record.line_no or 0,
                    line_pos=violation_record.line_pos or 0,
                    code=violation_record.rule_code or '',
                    description=violation_record.description or '',
                    rule=violation_record.rule_name or '',
                    severity=violation_record.severity or '',
                    severity_level=violation_record.severity_level,
                    fixable=violation_record.fixable or False,
                    sql_line=violation_record.sql_line or '',  # 直接从数据库读取
                    support=violation_record.support or ''  # 从数据库读取support字段
                )
                violations_with_sql.append(violation_with_sql)
            
            self.logger.debug(f"获取Task Lint结果成功: {task_id}, 违规项数量: {len(violations_with_sql)}")
            return TaskLintResultResponse(violations=violations_with_sql)
            
        except Exception as e:
            self.logger.error(f"获取Task Lint结果失败: {task_id}, 错误: {e}")
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
    
    async def get_severity_level_statistics(self, job_id: str) -> SeverityLevelStatistics:
        """
        获取指定Job下所有任务的Severity Level统计信息
        
        Args:
            job_id: Job ID
            
        Returns:
            SeverityLevelStatistics: severity level统计信息
        """
        try:
            self.logger.info(f"获取Job的Severity Level统计: {job_id}")
            
            # 验证Job是否存在
            job = self.db.query(LintingJob).filter(LintingJob.job_id == job_id).first()
            if not job:
                raise JobException(ErrorCode.JOB_NOT_FOUND, job_id, f"Job不存在: {job_id}")
            
            # 获取该Job下所有成功的任务
            tasks = self.db.query(LintingTask).filter(
                LintingTask.job_id == job_id,
                LintingTask.status == TaskStatusEnum.SUCCESS,
                LintingTask.result_file_path.isnot(None)
            ).all()
            
            # 初始化统计计数器
            statistics = {
                "INFO": 0,
                "MINOR": 0,
                "MAJOR": 0,
                "BLOCKER": 0,
                "CRITICAL": 0,
                "UNKNOWN": 0
            }
            
            # 遍历所有任务的结果文件
            for task in tasks:
                try:
                    # 读取结果文件
                    result_content = self.file_manager.read_json_file(task.result_file_path)
                    if not result_content:
                        continue
                    
                    violations = result_content.get('violations', [])
                    
                    # 统计每个violation的severity_level
                    for violation in violations:
                        severity_level = violation.get('severity_level')
                        
                        # 处理不同的severity_level值
                        if severity_level is None or severity_level == "null":
                            statistics["UNKNOWN"] += 1
                        elif severity_level in statistics:
                            statistics[severity_level] += 1
                        else:
                            # 对于未知的severity_level值，归类为UNKNOWN
                            statistics["UNKNOWN"] += 1
                            
                except Exception as e:
                    self.logger.warning(f"读取任务结果文件失败: {task.task_id}, {e}")
                    continue
            
            result = SeverityLevelStatistics(**statistics)
            
            total_violations = sum(statistics.values())
            self.logger.info(f"Severity Level统计完成: {job_id}, 总违规项数: {total_violations}")
            
            return result
            
        except JobException:
            raise
        except Exception as e:
            self.logger.error(f"获取Severity Level统计失败: {job_id}, {e}")
            raise TaskException(ErrorCode.TASK_QUERY_FAILED, "severity_statistics", str(e))
    
    async def get_severity_level_statistics_v2(self, job_id: str) -> SeverityLevelStatistics:
        """
        获取指定Job下所有任务的Severity Level统计信息（V2版本 - 基于数据库查询）
        
        与V1版本的区别：
        1. 直接查询linting_violations表，不读取JSON文件，性能更优
        2. 统计时剔除is_appealed=1的violations（已申诉的违规项）
        3. 新增appealed字段，统计所有已申诉的违规项数量
        
        Args:
            job_id: Job ID
            
        Returns:
            SeverityLevelStatistics: severity level统计信息，包含appealed字段
        """
        try:
            self.logger.info(f"获取Job的Severity Level统计(V2): {job_id}")
            
            # 验证Job是否存在
            job = self.db.query(LintingJob).filter(LintingJob.job_id == job_id).first()
            if not job:
                raise JobException(ErrorCode.JOB_NOT_FOUND, job_id, f"Job不存在: {job_id}")
            
            # 初始化统计计数器
            statistics = {
                "INFO": 0,
                "MINOR": 0,
                "MAJOR": 0,
                "BLOCKER": 0,
                "CRITICAL": 0,
                "UNKNOWN": 0,
                "appealed": 0
            }
            
            # 统计未申诉的violations（按severity_level分组）
            # 使用case处理NULL值，将NULL视为UNKNOWN
            unappealed_stats = self.db.query(
                func.coalesce(LintingViolation.severity_level, 'UNKNOWN').label('level'),
                func.count(LintingViolation.id).label('count')
            ).filter(
                LintingViolation.job_id == job_id,
                LintingViolation.is_appealed == False  # 剔除已申诉的
            ).group_by(
                func.coalesce(LintingViolation.severity_level, 'UNKNOWN')
            ).all()
            
            # 填充未申诉的统计数据
            for level, count in unappealed_stats:
                if level in statistics:
                    statistics[level] = count
                else:
                    # 对于未知的severity_level值，归类为UNKNOWN
                    statistics["UNKNOWN"] += count
            
            # 统计已申诉的violations总数（所有级别）
            appealed_count = self.db.query(
                func.count(LintingViolation.id)
            ).filter(
                LintingViolation.job_id == job_id,
                LintingViolation.is_appealed == True
            ).scalar()
            
            statistics["appealed"] = appealed_count or 0
            
            result = SeverityLevelStatistics(**statistics)
            
            total_unappealed = sum([v for k, v in statistics.items() if k != "appealed"])
            self.logger.info(
                f"Severity Level统计完成(V2): {job_id}, "
                f"未申诉违规项: {total_unappealed}, 已申诉违规项: {statistics['appealed']}"
            )
            
            return result
            
        except JobException:
            raise
        except Exception as e:
            self.logger.error(f"获取Severity Level统计失败(V2): {job_id}, {e}")
            raise TaskException(ErrorCode.TASK_QUERY_FAILED, "severity_statistics_v2", str(e))
    
    async def get_tasks_by_severity_level(
        self,
        job_id: str,
        severity_level: str,
        page: int = 1,
        size: int = 10,
        status: Optional[TaskStatusEnum] = None,
        violation_exists: Optional[bool] = None
    ) -> PaginationResponse[TaskResponse]:
        """
        获取指定Job和Severity Level的任务列表（支持分页）
        
        Args:
            job_id: Job ID
            severity_level: 要过滤的severity level (INFO/MINOR/MAJOR/BLOCKER/CRITICAL)
            page: 页码
            size: 每页大小
            status: 任务状态过滤
            violation_exists: 是否有违规项过滤
            
        Returns:
            PaginationResponse[TaskResponse]: 分页的任务列表
        """
        try:
            self.logger.info(f"按Severity Level查询任务列表: {job_id}, level={severity_level}, 页码={page}, 大小={size}")
            
            # 验证Job是否存在
            job = self.db.query(LintingJob).filter(LintingJob.job_id == job_id).first()
            if not job:
                raise JobException(ErrorCode.JOB_NOT_FOUND, job_id, f"Job不存在: {job_id}")
            
            # 验证severity_level参数
            valid_levels = {"INFO", "MINOR", "MAJOR", "BLOCKER", "CRITICAL", "UNKNOWN"}
            if severity_level not in valid_levels:
                raise TaskException(
                    ErrorCode.TASK_QUERY_FAILED, 
                    "severity_level_filter", 
                    f"无效的severity_level: {severity_level}, 必须是: {', '.join(valid_levels)}"
                )
            
            # 构建查询条件
            query = self.db.query(LintingTask).filter(LintingTask.job_id == job_id)
            
            # 添加状态过滤
            if status:
                query = query.filter(LintingTask.status == status)
            
            # 获取所有任务
            all_tasks = query.all()
            
            # 过滤出包含指定severity_level的任务
            matching_tasks = []
            
            for task in all_tasks:
                # 跳过没有结果文件的任务
                if not task.result_file_path or task.status != TaskStatusEnum.SUCCESS:
                    continue
                
                try:
                    # 读取结果文件
                    result_content = self.file_manager.read_json_file(task.result_file_path)
                    if not result_content:
                        continue
                    
                    violations = result_content.get('violations', [])
                    
                    # 检查是否有匹配的severity_level
                    has_matching_level = False
                    
                    for violation in violations:
                        violation_level = violation.get('severity_level')
                        
                        # 处理UNKNOWN级别的匹配
                        if severity_level == "UNKNOWN" and (violation_level is None or violation_level == "null"):
                            has_matching_level = True
                            break
                        elif violation_level == severity_level:
                            has_matching_level = True
                            break
                    
                    if has_matching_level:
                        matching_tasks.append(task)
                        
                except Exception as e:
                    self.logger.warning(f"读取任务结果文件失败: {task.task_id}, {e}")
                    continue
            
            # 应用violation_exists过滤（如果有）
            if violation_exists is not None:
                if violation_exists:
                    # 只保留有违规的任务
                    matching_tasks = [t for t in matching_tasks if t.total_violations and t.total_violations > 0]
                else:
                    # 只保留无违规的任务
                    matching_tasks = [t for t in matching_tasks if not t.total_violations or t.total_violations == 0]
            
            # 计算分页信息
            total = len(matching_tasks)
            total_pages = (total + size - 1) // size if total > 0 else 1
            
            # 分页切片
            start_idx = (page - 1) * size
            end_idx = start_idx + size
            page_tasks = matching_tasks[start_idx:end_idx]
            
            # 转换为响应格式
            task_responses = []
            for task in page_tasks:
                task_response = TaskResponse(
                    task_id=task.task_id,
                    file_name=task.file_name,
                    status=task.status,
                    result_file_path=task.result_file_path,
                    error_message=task.error_message,
                    created_at=task.created_at,
                    updated_at=task.updated_at,
                    sql_lines=task.sql_lines,
                    total_violations=task.total_violations,
                    critical_violations=task.critical_violations,
                    severity_info=task.severity_info,
                    severity_minor=task.severity_minor,
                    severity_major=task.severity_major,
                    severity_blocker=task.severity_blocker,
                    severity_critical=task.severity_critical,
                    severity_unknown=task.severity_unknown
                )
                task_responses.append(task_response)
            
            # 构造分页响应
            pagination_response = PaginationResponse(
                total=total,
                page=page,
                size=size,
                pages=total_pages,
                has_next=page < total_pages,
                has_prev=page > 1,
                items=task_responses
            )
            
            self.logger.info(f"按Severity Level查询任务完成: {job_id}, 匹配任务数: {total}")
            
            return pagination_response
            
        except (JobException, TaskException):
            raise
        except Exception as e:
            self.logger.error(f"按Severity Level查询任务失败: {job_id}, {e}")
            raise TaskException(ErrorCode.TASK_QUERY_FAILED, "severity_level_filter", str(e))
    
    async def get_tasks_by_severity_level_v2(
        self,
        job_id: str,
        severity_level: Optional[str] = None,
        include_appealed: bool = False,
        page: int = 1,
        size: int = 10,
        status: Optional[TaskStatusEnum] = None
    ) -> TaskWithViolationsListResponse:
        """
        获取指定Job的任务列表及其violations（V2版本 - 基于数据库查询）
        
        与V1版本的区别：
        1. 直接查询linting_violations表，不读取JSON文件
        2. 支持severity_level为可选参数，不传则返回所有级别
        3. 支持severity_level="is_appealed"，查询已申诉的violations
        4. 支持include_appealed参数，控制是否包含已申诉的violations
        5. 返回每个task的matched_violations详细信息，包含violation_id和is_appealed
        
        Args:
            job_id: Job ID
            severity_level: Severity Level过滤（可选）：
                          - INFO/MINOR/MAJOR/BLOCKER/CRITICAL/UNKNOWN：查询指定级别的violations
                          - "is_appealed"：查询已申诉的violations（忽略include_appealed参数）
                          - None：查询所有级别的violations
            include_appealed: 是否包含已申诉的violations（仅当severity_level不为"is_appealed"时有效）
            page: 页码
            size: 每页数量
            status: 任务状态过滤（可选）
            
        Returns:
            TaskWithViolationsListResponse: 任务列表及其violations
        """
        try:
            self.logger.info(
                f"获取任务列表(V2): job_id={job_id}, severity_level={severity_level}, "
                f"include_appealed={include_appealed}, page={page}, size={size}"
            )
            
            # 验证Job是否存在
            job = self.db.query(LintingJob).filter(LintingJob.job_id == job_id).first()
            if not job:
                raise JobException(ErrorCode.JOB_NOT_FOUND, job_id, f"Job不存在: {job_id}")
            
            # 验证severity_level参数（如果提供）
            if severity_level is not None:
                valid_levels = {"INFO", "MINOR", "MAJOR", "BLOCKER", "CRITICAL", "UNKNOWN", "is_appealed"}
                if severity_level not in valid_levels:
                    raise TaskException(
                        ErrorCode.TASK_QUERY_FAILED,
                        "severity_level_filter",
                        f"无效的severity_level: {severity_level}, 必须是: {', '.join(valid_levels)}"
                    )
            
            # 构建基础任务查询
            task_query = self.db.query(LintingTask).filter(
                LintingTask.job_id == job_id
            )
            
            # 添加状态过滤
            if status:
                task_query = task_query.filter(LintingTask.status == status)
            
            # 构建violation查询条件
            violation_filters = [LintingViolation.job_id == job_id]
            
            # 根据severity_level参数构建过滤条件
            if severity_level == "is_appealed":
                # 查询已申诉的violations（不限级别）
                violation_filters.append(LintingViolation.is_appealed == True)
            elif severity_level is not None:
                # 查询指定级别的violations
                # 处理UNKNOWN级别（NULL值）
                if severity_level == "UNKNOWN":
                    violation_filters.append(
                        or_(
                            LintingViolation.severity_level.is_(None),
                            LintingViolation.severity_level == "UNKNOWN"
                        )
                    )
                else:
                    violation_filters.append(LintingViolation.severity_level == severity_level)
                
                # 根据include_appealed参数决定是否过滤已申诉项
                if not include_appealed:
                    violation_filters.append(LintingViolation.is_appealed == False)
            else:
                # severity_level为None，查询所有级别
                # 根据include_appealed参数决定是否过滤已申诉项
                if not include_appealed:
                    violation_filters.append(LintingViolation.is_appealed == False)
            
            # 查询符合条件的task_id列表（去重）
            matching_task_ids = self.db.query(LintingViolation.task_id).filter(
                and_(*violation_filters)
            ).distinct().subquery()
            
            # 获取匹配的任务
            matching_tasks_query = task_query.filter(
                LintingTask.task_id.in_(matching_task_ids)
            ).order_by(LintingTask.created_at.desc())
            
            # 计算总数
            total = matching_tasks_query.count()
            total_pages = (total + size - 1) // size if total > 0 else 1
            
            # 分页查询
            tasks = matching_tasks_query.offset((page - 1) * size).limit(size).all()
            
            # 为每个任务获取匹配的violations
            task_responses = []
            for task in tasks:
                # 查询该任务下符合条件的violations
                violations_query = self.db.query(LintingViolation).filter(
                    LintingViolation.task_id == task.task_id,
                    *violation_filters
                )
                violations = violations_query.all()
                
                # 转换violations为TaskViolationWithSQL
                # 注意字段映射：rule_code → code, rule_name → rule
                violation_details = []
                for violation in violations:
                    violation_detail = TaskViolationWithSQL(
                        violation_id=violation.id,
                        is_appealed=violation.is_appealed,
                        line_no=violation.line_no or 0,
                        line_pos=violation.line_pos or 0,
                        code=violation.rule_code or '',  # rule_code → code
                        description=violation.description or '',
                        rule=violation.rule_name or '',  # rule_name → rule
                        severity=violation.severity or '',
                        severity_level=violation.severity_level,
                        fixable=violation.fixable or False,
                        sql_line=violation.sql_line or '',
                        support=violation.support or ''  # 从数据库读取support字段
                    )
                    violation_details.append(violation_detail)
                
                # 构建任务响应
                task_response = TaskWithViolationsResponse(
                    task_id=task.task_id,
                    file_name=task.file_name,
                    status=task.status,
                    result_file_path=task.result_file_path,
                    error_message=task.error_message,
                    created_at=task.created_at,
                    updated_at=task.updated_at,
                    sql_lines=task.sql_lines,
                    total_violations=task.total_violations,
                    critical_violations=task.critical_violations,
                    matched_violations=violation_details,
                    matched_count=len(violation_details)
                )
                task_responses.append(task_response)
            
            # 构造分页响应
            pagination_response = PaginationResponse(
                total=total,
                page=page,
                size=size,
                pages=total_pages,
                has_next=page < total_pages,
                has_prev=page > 1,
                items=task_responses
            )
            
            result = TaskWithViolationsListResponse(tasks=pagination_response)
            
            self.logger.info(
                f"任务列表查询完成(V2): {job_id}, 总任务数: {total}, "
                f"当前页任务数: {len(task_responses)}"
            )
            
            return result
            
        except (JobException, TaskException):
            raise
        except Exception as e:
            self.logger.error(f"查询任务列表失败(V2): {job_id}, {e}")
            raise TaskException(ErrorCode.TASK_QUERY_FAILED, "tasks_by_severity_v2", str(e))
    
    async def batch_calculate_all_severity_statistics(self) -> TaskSeverityCalculateResponse:
        """
        批量计算所有任务的Severity Level统计信息并更新到数据库（历史数据修复接口）
        
        此接口用于修复历史数据中缺失的severity_level统计字段。
        对于新创建的任务，severity_level统计会在任务处理时自动计算，无需调用此接口。
        
        遍历数据库中的所有任务，读取每个任务的结果JSON文件，
        统计不同severity_level的违规项数量，并更新到数据库字段。
        
        Returns:
            TaskSeverityCalculateResponse: 处理结果统计
        """
        try:
            self.logger.info("开始批量计算所有任务的Severity Level统计")
            
            # 查询所有任务
            all_tasks = self.db.query(LintingTask).all()
            
            total_processed = len(all_tasks)
            success_count = 0
            failed_count = 0
            skipped_count = 0
            failed_tasks = []
            
            for task in all_tasks:
                try:
                    # 检查任务状态
                    if task.status != TaskStatusEnum.SUCCESS:
                        skipped_count += 1
                        self.logger.debug(f"跳过非SUCCESS状态的任务: {task.task_id}, 状态: {task.status}")
                        continue
                    
                    # 检查是否有结果文件路径
                    if not task.result_file_path:
                        skipped_count += 1
                        self.logger.debug(f"跳过没有结果文件的任务: {task.task_id}")
                        continue
                    
                    # 检查结果文件是否存在
                    if not self.file_manager.file_exists(task.result_file_path):
                        failed_count += 1
                        failed_tasks.append({
                            "task_id": task.task_id,
                            "reason": "结果文件不存在"
                        })
                        self.logger.warning(f"任务结果文件不存在: {task.task_id}, 路径: {task.result_file_path}")
                        continue
                    
                    # 读取结果文件
                    try:
                        result_content = self.file_manager.read_json_file(task.result_file_path)
                    except Exception as e:
                        failed_count += 1
                        failed_tasks.append({
                            "task_id": task.task_id,
                            "reason": f"读取JSON文件失败: {str(e)}"
                        })
                        self.logger.warning(f"读取结果文件失败: {task.task_id}, 错误: {e}")
                        continue
                    
                    # 使用工具函数统计severity_level
                    violations = result_content.get('violations', [])
                    statistics = calculate_severity_statistics(violations)
                    
                    # 更新数据库字段
                    task.severity_info = statistics["INFO"]
                    task.severity_minor = statistics["MINOR"]
                    task.severity_major = statistics["MAJOR"]
                    task.severity_blocker = statistics["BLOCKER"]
                    task.severity_critical = statistics["CRITICAL"]
                    task.severity_unknown = statistics["UNKNOWN"]
                    
                    success_count += 1
                    self.logger.debug(f"任务统计计算成功: {task.task_id}, 统计: {statistics}")
                    
                except Exception as e:
                    # 单个任务的异常不应该中断整个批量操作
                    failed_count += 1
                    failed_tasks.append({
                        "task_id": task.task_id,
                        "reason": f"处理异常: {str(e)}"
                    })
                    self.logger.error(f"计算任务Severity统计失败: {task.task_id}, 错误: {e}")
                    continue
            
            # 提交所有更新
            try:
                self.db.commit()
                self.logger.info(f"批量计算完成，总计: {total_processed}, 成功: {success_count}, 失败: {failed_count}, 跳过: {skipped_count}")
            except Exception as e:
                self.db.rollback()
                self.logger.error(f"提交数据库更新失败: {e}")
                raise DatabaseException("批量更新Severity统计", str(e))
            
            return TaskSeverityCalculateResponse(
                total_processed=total_processed,
                success_count=success_count,
                failed_count=failed_count,
                skipped_count=skipped_count,
                failed_tasks=failed_tasks
            )
            
        except DatabaseException:
            raise
        except Exception as e:
            self.logger.error(f"批量计算Severity Level统计失败: {e}")
            raise TaskException(ErrorCode.TASK_QUERY_FAILED, "batch_calculate_severity", str(e)) 