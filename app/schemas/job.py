"""
Job相关API数据模型

定义与核验工作(Job)相关的Pydantic数据模型。
包括创建请求、查询响应等模型定义。
"""

from pydantic import BaseModel, Field, validator, model_validator
from typing import Optional, List
from datetime import datetime

from app.schemas.common import (
    JobStatusEnum, 
    SubmissionTypeEnum, 
    PaginationResponse,
    BaseQueryParams,
    DateRangeParams
)


class JobCreateRequest(BaseModel):
    """创建核验工作请求模型"""
    sql_content: Optional[str] = Field(
        default=None,
        description="单段SQL内容（与zip_file_path二选一）"
    )
    zip_file_path: Optional[str] = Field(
        default=None,
        description="ZIP包在NFS中的相对路径（与sql_content二选一）"
    )
    dialect: Optional[str] = Field(
        default="ansi",
        description="SQLFluff方言，如mysql、postgres、bigquery等"
    )
    
    @model_validator(mode='after')
    def validate_request(self):
        """验证请求参数"""
        sql_content = self.sql_content
        zip_file_path = self.zip_file_path
        
        # 必须提供其中一个
        if not sql_content and not zip_file_path:
            raise ValueError("必须提供 sql_content 或 zip_file_path 其中之一")
        
        # 不能同时提供两个
        if sql_content and zip_file_path:
            raise ValueError("sql_content 和 zip_file_path 不能同时提供")
        
        return self
    
    @validator('sql_content')
    def validate_sql_content(cls, v):
        """验证SQL内容"""
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("SQL内容不能为空")
            if len(v) > 1024 * 1024:  # 1MB限制
                raise ValueError("SQL内容不能超过1MB")
        return v
    
    @validator('zip_file_path')
    def validate_zip_file_path(cls, v):
        """验证ZIP文件路径"""
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("ZIP文件路径不能为空")
            if not v.endswith('.zip'):
                raise ValueError("文件必须是ZIP格式")
            if len(v) > 1024:
                raise ValueError("文件路径不能超过1024字符")
        return v
    
    @validator('dialect')
    def validate_dialect(cls, v):
        """验证SQLFluff方言"""
        if v is not None:
            v = v.strip().lower()
            if not v:
                raise ValueError("方言不能为空")
            # 常见的SQLFluff支持的方言
            supported_dialects = {
                'ansi', 'mysql', 'postgres', 'postgresql', 'sqlite', 'bigquery', 
                'snowflake', 'redshift', 'oracle', 'tsql', 'hive', 'spark',
                'teradata', 'exasol', 'db2', 'duckdb'
            }
            if v not in supported_dialects:
                raise ValueError(f"不支持的方言: {v}，支持的方言包括: {', '.join(sorted(supported_dialects))}")
        return v


class JobCreateResponse(BaseModel):
    """创建核验工作响应模型"""
    job_id: str = Field(description="工作ID")
    
    class Config:
        schema_extra = {
            "example": {
                "job_id": "job-d8b8a7e0-4f7f-4f7b-8f1e-8e6a1e8e6a1e"
            }
        }


class JobSummary(BaseModel):
    """工作摘要信息"""
    job_id: str = Field(description="工作ID")
    status: JobStatusEnum = Field(description="工作状态")
    submission_type: SubmissionTypeEnum = Field(description="提交类型")
    source_path: str = Field(description="源文件路径")
    dialect: str = Field(description="SQLFluff方言")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="最后更新时间")
    task_count: int = Field(description="任务总数")
    successful_tasks: int = Field(description="成功任务数")
    failed_tasks: int = Field(description="失败任务数")
    error_message: Optional[str] = Field(default=None, description="错误消息")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
        schema_extra = {
            "example": {
                "job_id": "job-d8b8a7e0-4f7f-4f7b-8f1e-8e6a1e8e6a1e",
                "status": "PROCESSING",
                "submission_type": "ZIP_ARCHIVE",
                "source_path": "archives/your-uploaded-file-uuid.zip",
                "dialect": "mysql",
                "created_at": "2025-06-27T09:30:00.123456",
                "updated_at": "2025-06-27T09:30:05.654321",
                "task_count": 50,
                "successful_tasks": 30,
                "failed_tasks": 5
            }
        }


class TaskSummary(BaseModel):
    """任务摘要信息（用于Job详情中的子任务列表）"""
    task_id: str = Field(description="任务ID")
    file_name: str = Field(description="文件名")
    status: str = Field(description="任务状态")
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


class JobDetailResponse(BaseModel):
    """工作详情响应模型"""
    job_id: str = Field(description="工作ID")
    job_status: JobStatusEnum = Field(description="工作状态")
    submission_type: SubmissionTypeEnum = Field(description="提交类型")
    source_path: str = Field(description="源文件路径")
    dialect: str = Field(description="SQLFluff方言")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="最后更新时间")
    error_message: Optional[str] = Field(default=None, description="错误消息")
    sub_tasks: Optional[PaginationResponse[TaskSummary]] = Field(
        default=None, 
        description="子任务列表（分页）"
    )
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
        schema_extra = {
            "example": {
                "job_id": "job-d8b8a7e0-4f7f-4f7b-8f1e-8e6a1e8e6a1e",
                "job_status": "PROCESSING",
                "submission_type": "ZIP_ARCHIVE",
                "source_path": "archives/your-uploaded-file-uuid.zip",
                "dialect": "mysql",
                "created_at": "2025-06-27T09:30:00.123456",
                "updated_at": "2025-06-27T09:30:05.654321",
                "sub_tasks": {
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
                            "result_file_path": "jobs/job-d8b8.../results/task-e0e1....json"
                        }
                    ]
                }
            }
        }


class JobQueryParams(BaseQueryParams, DateRangeParams):
    """工作查询参数"""
    status: Optional[JobStatusEnum] = Field(default=None, description="状态过滤")
    submission_type: Optional[SubmissionTypeEnum] = Field(default=None, description="提交类型过滤")
    
    @validator('sort_by')
    def validate_job_sort_by(cls, v):
        """验证Job排序字段"""
        allowed_fields = ['created_at', 'updated_at', 'status', 'submission_type']
        if v and v not in allowed_fields:
            raise ValueError(f'排序字段必须是以下之一: {", ".join(allowed_fields)}')
        return v


class JobListResponse(BaseModel):
    """工作列表响应模型"""
    jobs: PaginationResponse[JobSummary] = Field(description="工作列表（分页）")
    
    class Config:
        schema_extra = {
            "example": {
                "jobs": {
                    "total": 100,
                    "page": 1,
                    "size": 10,
                    "pages": 10,
                    "has_next": True,
                    "has_prev": False,
                    "items": [
                        {
                            "job_id": "job-d8b8a7e0-4f7f-4f7b-8f1e-8e6a1e8e6a1e",
                            "status": "COMPLETED",
                            "submission_type": "ZIP_ARCHIVE",
                            "source_path": "archives/example.zip",
                            "dialect": "postgres",
                            "created_at": "2025-06-27T09:30:00.123456",
                            "updated_at": "2025-06-27T09:35:00.123456",
                            "task_count": 50,
                            "successful_tasks": 45,
                            "failed_tasks": 5
                        }
                    ]
                }
            }
        }


class JobStatusUpdateRequest(BaseModel):
    """工作状态更新请求模型（内部使用）"""
    status: JobStatusEnum = Field(description="新状态")
    error_message: Optional[str] = Field(default=None, description="错误消息")
    
    @validator('error_message')
    def validate_error_message(cls, v, values):
        """验证错误消息"""
        status = values.get('status')
        if status == JobStatusEnum.FAILED and not v:
            raise ValueError("状态为FAILED时必须提供错误消息")
        return v


class JobStatistics(BaseModel):
    """工作统计信息"""
    total_jobs: int = Field(description="总工作数")
    accepted_jobs: int = Field(description="已接受工作数")
    processing_jobs: int = Field(description="处理中工作数")
    completed_jobs: int = Field(description="已完成工作数")
    partially_completed_jobs: int = Field(description="部分完成工作数")
    failed_jobs: int = Field(description="失败工作数")
    avg_processing_time: Optional[float] = Field(default=None, description="平均处理时间（分钟）")
    
    class Config:
        schema_extra = {
            "example": {
                "total_jobs": 1000,
                "accepted_jobs": 10,
                "processing_jobs": 5,
                "completed_jobs": 800,
                "partially_completed_jobs": 150,
                "failed_jobs": 35,
                "avg_processing_time": 12.5
            }
        }


class JobTaskIdsResponse(BaseModel):
    """工作任务ID列表响应模型"""
    job_id: str = Field(description="工作ID")
    task_ids: List[str] = Field(description="任务ID列表")
    total_count: int = Field(description="任务总数")
    
    class Config:
        schema_extra = {
            "example": {
                "job_id": "job-d8b8a7e0-4f7f-4f7b-8f1e-8e6a1e8e6a1e",
                "task_ids": [
                    "task-e0e1f2e3-4f5f-6a6b-7c7d-8e8f9a9b0c0d",
                    "task-f1f2e3e4-5f6f-7a7b-8c8d-9e9f0a0b1c1d",
                    "task-g2g3f4f5-6f7f-8a8b-9c9d-0e0f1a1b2c2d"
                ],
                "total_count": 3
            }
        } 