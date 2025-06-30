"""
Job相关API路由

实现核验工作(Job)相关的HTTP接口，包括创建、查询、状态管理等功能。
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.api.deps import (
    get_job_service, validate_job_id, get_pagination_params,
    handle_service_exception
)
from app.services.job_service import JobService
from app.schemas.job import (
    JobCreateRequest, JobCreateResponse, JobDetailResponse,
    JobListResponse, JobSummary, JobStatistics, JobTaskIdsResponse
)
from app.schemas.common import JobStatusEnum, SubmissionTypeEnum
from app.core.logging import api_logger

router = APIRouter()


@router.post("/jobs", response_model=JobCreateResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_job(
    request: JobCreateRequest,
    job_service: JobService = Depends(get_job_service)
):
    """
    创建新的核验工作
    
    支持两种提交模式：
    1. 单SQL文件：直接提交SQL内容
    2. ZIP包：提交ZIP文件路径（文件需预先上传到NFS）
    
    创建成功后会自动派发Celery任务进行处理。
    """
    try:
        api_logger.info(f"创建Job请求: {request.dict()}")
        
        # 调用业务服务创建Job
        response = await job_service.create_job(request)
        
        # 派发Celery任务进行后台处理
        try:
            from app.celery_app.tasks import expand_zip_and_dispatch_tasks
            
            # 对于单SQL文件和ZIP包，都派发expand_zip_and_dispatch_tasks任务
            # 该任务会根据Job类型进行相应的处理
            task_result = expand_zip_and_dispatch_tasks.delay(response.job_id)
            api_logger.info(f"派发任务处理: {task_result.id}")
                
        except Exception as e:
            api_logger.error(f"任务派发失败: {e}")
            # 注意：即使任务派发失败，Job已经创建，所以仍然返回成功
            # 用户可以稍后重试或通过其他方式处理
        
        api_logger.info(f"Job创建成功: {response.job_id}")
        return response
        
    except Exception as e:
        api_logger.error(f"创建Job失败: {e}")
        raise handle_service_exception(e, "创建核验工作")


@router.get("/jobs/{job_id}", response_model=JobDetailResponse)
async def get_job(
    job_id: str = Depends(validate_job_id),
    pagination: tuple[int, int] = Depends(get_pagination_params),
    job_service: JobService = Depends(get_job_service)
):
    """
    查询核验工作状态与详情
    
    返回Job的基本信息和关联的Task列表（分页）。
    可以通过分页参数控制Task列表的返回数量。
    """
    try:
        page, size = pagination
        api_logger.info(f"查询Job: {job_id}, 页码: {page}, 大小: {size}")
        
        # 调用业务服务查询Job详情
        job_detail = await job_service.get_job_with_tasks(job_id, page, size)
        
        if not job_detail:
            api_logger.warning(f"Job不存在: {job_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"核验工作不存在: {job_id}"
            )
        
        api_logger.debug(f"Job查询成功: {job_id}")
        return job_detail
        
    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"查询Job失败: {job_id}, 错误: {e}")
        raise handle_service_exception(e, "查询核验工作")


@router.get("/jobs", response_model=JobListResponse)
async def list_jobs(
    pagination: tuple[int, int] = Depends(get_pagination_params),
    status_filter: Optional[JobStatusEnum] = Query(None, alias="status", description="状态过滤"),
    submission_type: Optional[SubmissionTypeEnum] = Query(None, description="提交类型过滤"),
    job_service: JobService = Depends(get_job_service)
):
    """
    获取核验工作列表
    
    支持分页查询和状态过滤。
    可以按照创建时间倒序返回Job列表。
    """
    try:
        page, size = pagination
        api_logger.info(f"查询Job列表: 页码={page}, 大小={size}, 状态={status_filter}, 类型={submission_type}")
        
        # 调用业务服务查询Job列表
        job_list = await job_service.list_jobs(
            page=page,
            size=size,
            status=status_filter,
            submission_type=submission_type
        )
        
        response = JobListResponse(jobs=job_list)
        api_logger.debug(f"Job列表查询成功: 总数={job_list.total}")
        return response
        
    except Exception as e:
        api_logger.error(f"查询Job列表失败: {e}")
        raise handle_service_exception(e, "查询核验工作列表")


@router.get("/jobs/statistics", response_model=JobStatistics)
async def get_job_statistics(
    job_service: JobService = Depends(get_job_service)
):
    """
    获取核验工作统计信息
    
    返回各种状态的Job数量、成功率等统计数据。
    """
    try:
        api_logger.info("查询Job统计信息")
        
        # 调用业务服务获取统计信息
        statistics = await job_service.get_job_statistics()
        
        api_logger.debug(f"Job统计查询成功: 总数={statistics.total_jobs}")
        return statistics
        
    except Exception as e:
        api_logger.error(f"查询Job统计失败: {e}")
        raise handle_service_exception(e, "查询统计信息")


@router.get("/jobs/{job_id}/tasks", response_model=JobTaskIdsResponse)
async def get_job_task_ids(
    job_id: str = Depends(validate_job_id),
    job_service: JobService = Depends(get_job_service)
):
    """
    获取核验工作下的所有任务ID列表
    
    返回指定Job下的所有Task ID，用于批量操作或快速查看任务列表。
    """
    try:
        api_logger.info(f"查询Job任务ID列表: {job_id}")
        
        # 调用业务服务获取任务ID列表
        task_ids_info = await job_service.get_job_task_ids(job_id)
        
        if not task_ids_info:
            api_logger.warning(f"Job不存在: {job_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"核验工作不存在: {job_id}"
            )
        
        response = JobTaskIdsResponse(
            job_id=task_ids_info["job_id"],
            task_ids=task_ids_info["task_ids"],
            total_count=task_ids_info["total_count"]
        )
        
        api_logger.debug(f"Job任务ID列表查询成功: {job_id}, 任务数: {task_ids_info['total_count']}")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"查询Job任务ID列表失败: {job_id}, 错误: {e}")
        raise handle_service_exception(e, "查询任务ID列表")


# ============= 内部管理接口（可选实现） =============

@router.put("/jobs/{job_id}/status", include_in_schema=False)
async def update_job_status(
    job_id: str = Depends(validate_job_id),
    status_update: dict = None,  # 简化的状态更新，实际应该用专门的schema
    job_service: JobService = Depends(get_job_service)
):
    """
    更新Job状态（内部接口）
    
    此接口主要用于Celery Worker更新Job状态，不对外公开。
    """
    try:
        api_logger.info(f"更新Job状态: {job_id}, {status_update}")
        
        if not status_update or 'status' not in status_update:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="缺少status字段"
            )
        
        # 调用业务服务更新状态
        await job_service.update_job_status(
            job_id=job_id,
            status=JobStatusEnum(status_update['status']),
            error_message=status_update.get('error_message')
        )
        
        api_logger.info(f"Job状态更新成功: {job_id}")
        return {"message": "状态更新成功"}
        
    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"更新Job状态失败: {job_id}, 错误: {e}")
        raise handle_service_exception(e, "更新工作状态") 