"""
Task相关API数据模型

定义与处理任务(Task)相关的Pydantic数据模型。
包括任务详情、结果响应等模型定义。
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime

from app.schemas.common import (
    TaskStatusEnum,
    BaseQueryParams,
    DateRangeParams,
    PaginationResponse
)


class TaskResponse(BaseModel):
    """任务基础响应模型"""
    task_id: str = Field(description="任务ID")
    file_name: str = Field(description="文件名")
    status: TaskStatusEnum = Field(description="任务状态")
    result_file_path: Optional[str] = Field(default=None, description="结果文件路径")
    error_message: Optional[str] = Field(default=None, description="错误消息")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="最后更新时间")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
        schema_extra = {
            "example": {
                "task_id": "task-e0e1f2e3-4f5f-6a6b-7c7d-8e8f9a9b0c0d",
                "file_name": "query_users.sql",
                "status": "SUCCESS",
                "result_file_path": "jobs/job-d8b8.../results/task-e0e1....json",
                "created_at": "2025-06-27T09:30:01.123456",
                "updated_at": "2025-06-27T09:30:15.654321"
            }
        }


class TaskDetailResponse(BaseModel):
    """任务详细响应模型"""
    task_id: str = Field(description="任务ID")
    job_id: str = Field(description="关联的工作ID")
    status: TaskStatusEnum = Field(description="任务状态")
    source_file_path: str = Field(description="源文件路径")
    result_file_path: Optional[str] = Field(default=None, description="结果文件路径")
    error_message: Optional[str] = Field(default=None, description="错误消息")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="最后更新时间")
    file_size: Optional[int] = Field(default=None, description="文件大小（字节）")
    processing_duration: Optional[float] = Field(default=None, description="处理时长（秒）")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
        schema_extra = {
            "example": {
                "task_id": "task-e0e1f2e3-4f5f-6a6b-7c7d-8e8f9a9b0c0d",
                "job_id": "job-d8b8a7e0-4f7f-4f7b-8f1e-8e6a1e8e6a1e",
                "status": "SUCCESS",
                "source_file_path": "jobs/job-d8b8.../sources/query_users.sql",
                "result_file_path": "jobs/job-d8b8.../results/task-e0e1....json",
                "created_at": "2025-06-27T09:30:01.123456",
                "updated_at": "2025-06-27T09:30:15.654321",
                "file_size": 2048,
                "processing_duration": 12.5
            }
        }


class TaskResultContent(BaseModel):
    """任务结果内容模型（SQLFluff分析结果）"""
    violations: List[Dict[str, Any]] = Field(description="SQLFluff违规项列表")
    summary: Dict[str, Any] = Field(description="分析摘要")
    file_info: Dict[str, Any] = Field(description="文件信息")
    analysis_metadata: Dict[str, Any] = Field(description="分析元数据")
    
    class Config:
        schema_extra = {
            "example": {
                "violations": [
                    {
                        "line_no": 5,
                        "line_pos": 10,
                        "code": "L010",
                        "description": "Keywords must be consistently upper case.",
                        "rule": "capitalisation.keywords"
                    }
                ],
                "summary": {
                    "total_violations": 3,
                    "critical_violations": 0,
                    "warning_violations": 3,
                    "file_passed": False
                },
                "file_info": {
                    "file_name": "query_users.sql",
                    "file_size": 2048,
                    "line_count": 25
                },
                "analysis_metadata": {
                    "sqlfluff_version": "2.3.5",
                    "dialect": "mysql",
                    "analysis_time": "2025-06-27T09:30:15.654321"
                }
            }
        }


class TaskStatusUpdateRequest(BaseModel):
    """任务状态更新请求模型（内部使用）"""
    status: TaskStatusEnum = Field(description="新状态")
    result_file_path: Optional[str] = Field(default=None, description="结果文件路径")
    error_message: Optional[str] = Field(default=None, description="错误消息")
    processing_duration: Optional[float] = Field(default=None, description="处理时长（秒）")
    
    @validator('result_file_path')
    def validate_result_file_path(cls, v, values):
        """验证结果文件路径"""
        status = values.get('status')
        if status == TaskStatusEnum.SUCCESS and not v:
            raise ValueError("状态为SUCCESS时必须提供结果文件路径")
        return v
    
    @validator('error_message')
    def validate_error_message(cls, v, values):
        """验证错误消息"""
        status = values.get('status')
        if status == TaskStatusEnum.FAILURE and not v:
            raise ValueError("状态为FAILURE时必须提供错误消息")
        return v


class TaskQueryParams(BaseQueryParams, DateRangeParams):
    """任务查询参数"""
    status: Optional[TaskStatusEnum] = Field(default=None, description="状态过滤")
    job_id: Optional[str] = Field(default=None, description="工作ID过滤")
    
    @validator('sort_by')
    def validate_task_sort_by(cls, v):
        """验证Task排序字段"""
        allowed_fields = ['created_at', 'updated_at', 'status', 'source_file_path']
        if v and v not in allowed_fields:
            raise ValueError(f'排序字段必须是以下之一: {", ".join(allowed_fields)}')
        return v


class TaskListResponse(BaseModel):
    """任务列表响应模型"""
    tasks: PaginationResponse[TaskResponse] = Field(description="任务列表（分页）")
    
    class Config:
        schema_extra = {
            "example": {
                "tasks": {
                    "total": 50,
                    "page": 1,
                    "size": 10,
                    "pages": 5,
                    "has_next": True,
                    "has_prev": False,
                    "items": [
                        {
                            "task_id": "task-e0e1f2e3-4f5f-6a6b-7c7d-8e8f9a9b0c0d",
                            "file_name": "query_users.sql",
                            "status": "SUCCESS",
                            "result_file_path": "jobs/job-d8b8.../results/task-e0e1....json",
                            "created_at": "2025-06-27T09:30:01.123456",
                            "updated_at": "2025-06-27T09:30:15.654321"
                        }
                    ]
                }
            }
        }


class TaskStatistics(BaseModel):
    """任务统计信息"""
    total_tasks: int = Field(description="总任务数")
    pending_tasks: int = Field(description="待处理任务数")
    in_progress_tasks: int = Field(description="处理中任务数")
    successful_tasks: int = Field(description="成功任务数")
    failed_tasks: int = Field(description="失败任务数")
    avg_processing_time: Optional[float] = Field(default=None, description="平均处理时间（秒）")
    success_rate: float = Field(description="成功率（百分比）")
    
    class Config:
        schema_extra = {
            "example": {
                "total_tasks": 5000,
                "pending_tasks": 50,
                "in_progress_tasks": 20,
                "successful_tasks": 4500,
                "failed_tasks": 430,
                "avg_processing_time": 12.5,
                "success_rate": 91.3
            }
        }


class TaskRetryRequest(BaseModel):
    """任务重试请求模型"""
    task_ids: List[str] = Field(description="要重试的任务ID列表")
    
    @validator('task_ids')
    def validate_task_ids(cls, v):
        """验证任务ID列表"""
        if not v:
            raise ValueError("任务ID列表不能为空")
        if len(v) > 100:
            raise ValueError("一次最多重试100个任务")
        return v


class TaskRetryResponse(BaseModel):
    """任务重试响应模型"""
    submitted_tasks: List[str] = Field(description="已提交重试的任务ID列表")
    failed_submissions: List[Dict[str, str]] = Field(description="提交失败的任务信息")
    
    class Config:
        schema_extra = {
            "example": {
                "submitted_tasks": [
                    "task-e0e1f2e3-4f5f-6a6b-7c7d-8e8f9a9b0c0d",
                    "task-f1f2f3f4-5f6f-7a7b-8c8d-9e9f0a0b1c1d"
                ],
                "failed_submissions": [
                    {
                        "task_id": "task-invalid-id",
                        "reason": "任务不存在或状态不允许重试"
                    }
                ]
            }
        }


class TaskFileInfo(BaseModel):
    """任务文件信息模型"""
    file_name: str = Field(description="文件名")
    file_size: int = Field(description="文件大小（字节）")
    line_count: Optional[int] = Field(default=None, description="行数")
    encoding: Optional[str] = Field(default=None, description="文件编码")
    last_modified: Optional[datetime] = Field(default=None, description="最后修改时间")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
        schema_extra = {
            "example": {
                "file_name": "query_users.sql",
                "file_size": 2048,
                "line_count": 25,
                "encoding": "utf-8",
                "last_modified": "2025-06-27T09:25:00.123456"
            }
        }


class TaskProgressResponse(BaseModel):
    """任务进度响应模型（用于实时监控）"""
    task_id: str = Field(description="任务ID")
    status: TaskStatusEnum = Field(description="当前状态")
    progress_percentage: float = Field(description="进度百分比（0-100）")
    current_step: str = Field(description="当前处理步骤")
    estimated_completion: Optional[datetime] = Field(default=None, description="预计完成时间")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
        schema_extra = {
            "example": {
                "task_id": "task-e0e1f2e3-4f5f-6a6b-7c7d-8e8f9a9b0c0d",
                "status": "IN_PROGRESS",
                "progress_percentage": 65.0,
                "current_step": "执行SQLFluff分析",
                "estimated_completion": "2025-06-27T09:32:00.123456"
            }
        } 