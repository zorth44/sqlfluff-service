"""
Task相关API路由

实现处理任务(Task)相关的HTTP接口，包括查询任务详情、获取结果等功能。
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query, Response
from sqlalchemy.orm import Session
from typing import Optional, List
import json

from app.api.deps import (
    get_task_service, validate_task_id, get_pagination_params,
    handle_service_exception
)
from app.services.task_service import TaskService
from app.schemas.task import (
    TaskDetailResponse, TaskResultContent, TaskListResponse,
    TaskStatistics, TaskRetryRequest, TaskRetryResponse
)
from app.schemas.common import TaskStatusEnum
from app.core.logging import api_logger
from app.utils.file_utils import FileManager

router = APIRouter()


@router.get("/tasks/{task_id}", response_model=TaskDetailResponse)
async def get_task(
    task_id: str = Depends(validate_task_id),
    task_service: TaskService = Depends(get_task_service)
):
    """
    获取单个任务的详细信息
    
    返回任务的完整信息，包括状态、文件路径、处理时长等。
    """
    try:
        api_logger.info(f"查询Task详情: {task_id}")
        
        # 调用业务服务查询Task详情
        task_detail = await task_service.get_task_detail(task_id)
        
        if not task_detail:
            api_logger.warning(f"Task不存在: {task_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"任务不存在: {task_id}"
            )
        
        api_logger.debug(f"Task查询成功: {task_id}")
        return task_detail
        
    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"查询Task失败: {task_id}, 错误: {e}")
        raise handle_service_exception(e, "查询任务详情")


@router.get("/tasks/{task_id}/result", response_model=TaskResultContent)
async def get_task_result(
    task_id: str = Depends(validate_task_id),
    task_service: TaskService = Depends(get_task_service)
):
    """
    获取单个文件任务的详细结果
    
    返回SQLFluff分析的完整结果，包括违规项、摘要信息等。
    只有状态为SUCCESS的任务才能获取结果。
    """
    try:
        api_logger.info(f"获取Task结果: {task_id}")
        
        # 首先检查任务状态
        task = await task_service.get_task_by_id(task_id)
        if not task:
            api_logger.warning(f"Task不存在: {task_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"任务不存在: {task_id}"
            )
        
        # 检查任务状态
        if task.status != TaskStatusEnum.SUCCESS:
            api_logger.warning(f"Task结果未准备就绪: {task_id}, 状态: {task.status}")
            
            if task.status == TaskStatusEnum.FAILURE:
                error_msg = f"任务执行失败: {task.error_message or '未知错误'}"
            elif task.status in [TaskStatusEnum.PENDING, TaskStatusEnum.IN_PROGRESS]:
                error_msg = "任务还在处理中，请稍后再试"
            else:
                error_msg = f"任务状态异常: {task.status}"
            
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=error_msg
            )
        
        # 获取分析结果
        result = await task_service.get_task_result(task_id)
        if not result:
            api_logger.error(f"Task结果文件不存在: {task_id}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="结果文件不存在或读取失败"
            )
        
        api_logger.debug(f"Task结果获取成功: {task_id}")
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"获取Task结果失败: {task_id}, 错误: {e}")
        raise handle_service_exception(e, "获取任务结果")


@router.get("/tasks/{task_id}/result/download")
async def download_task_result(
    task_id: str = Depends(validate_task_id),
    task_service: TaskService = Depends(get_task_service)
):
    """
    下载任务结果文件
    
    直接返回JSON文件供下载。
    """
    try:
        api_logger.info(f"下载Task结果: {task_id}")
        
        # 检查任务状态
        task = await task_service.get_task_by_id(task_id)
        if not task or task.status != TaskStatusEnum.SUCCESS:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="任务不存在或结果未准备就绪"
            )
        
        # 获取结果文件内容
        result = await task_service.get_task_result(task_id)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="结果文件不存在"
            )
        
        # 生成文件名
        filename = f"task_result_{task_id}.json"
        
        # 返回文件下载响应
        return Response(
            content=json.dumps(result.dict(), ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"下载Task结果失败: {task_id}, 错误: {e}")
        raise handle_service_exception(e, "下载任务结果")


@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks(
    pagination: tuple[int, int] = Depends(get_pagination_params),
    status_filter: Optional[TaskStatusEnum] = Query(None, alias="status", description="状态过滤"),
    job_id: Optional[str] = Query(None, description="Job ID过滤"),
    task_service: TaskService = Depends(get_task_service)
):
    """
    获取任务列表
    
    支持分页查询和多维度过滤。
    """
    try:
        page, size = pagination
        api_logger.info(f"查询Task列表: 页码={page}, 大小={size}, 状态={status_filter}, Job={job_id}")
        
        # 如果指定了job_id，使用专门的方法
        if job_id:
            task_list = await task_service.get_tasks_by_job_id(
                job_id=job_id,
                page=page,
                size=size,
                status=status_filter
            )
        else:
            # 否则查询全部任务（这里需要在TaskService中实现通用的list_tasks方法）
            # 暂时使用job_id=None的方式
            task_list = await task_service.get_tasks_by_job_id(
                job_id=None,  # 查询所有任务
                page=page,
                size=size,
                status=status_filter
            )
        
        response = TaskListResponse(tasks=task_list)
        api_logger.debug(f"Task列表查询成功: 总数={task_list.total}")
        return response
        
    except Exception as e:
        api_logger.error(f"查询Task列表失败: {e}")
        raise handle_service_exception(e, "查询任务列表")


@router.get("/tasks/statistics", response_model=TaskStatistics)
async def get_task_statistics(
    job_id: Optional[str] = Query(None, description="Job ID过滤"),
    task_service: TaskService = Depends(get_task_service)
):
    """
    获取任务统计信息
    
    返回各种状态的Task数量、成功率等统计数据。
    可以按Job进行过滤统计。
    """
    try:
        api_logger.info(f"查询Task统计信息, Job ID: {job_id}")
        
        # 调用业务服务获取统计信息
        statistics = await task_service.get_task_statistics(job_id=job_id)
        
        api_logger.debug(f"Task统计查询成功: 总数={statistics.total_tasks}")
        return statistics
        
    except Exception as e:
        api_logger.error(f"查询Task统计失败: {e}")
        raise handle_service_exception(e, "查询任务统计信息")


# ============= 任务管理接口 =============

@router.post("/tasks/retry", response_model=TaskRetryResponse)
async def retry_failed_tasks(
    retry_request: TaskRetryRequest,
    task_service: TaskService = Depends(get_task_service)
):
    """
    重试失败的任务
    
    将指定的失败任务重新提交到队列进行处理。
    """
    try:
        api_logger.info(f"重试失败任务: {retry_request.task_ids}")
        
        # 调用业务服务重试任务
        submitted_tasks, failed_submissions = await task_service.retry_failed_tasks(retry_request.task_ids)
        
        # 构造响应
        failed_info = []
        for task_id, error in failed_submissions:
            failed_info.append({
                "task_id": task_id,
                "error": error
            })
        
        response = TaskRetryResponse(
            submitted_tasks=submitted_tasks,
            failed_submissions=failed_info
        )
        
        api_logger.info(f"任务重试完成: 成功={len(submitted_tasks)}, 失败={len(failed_info)}")
        return response
        
    except Exception as e:
        api_logger.error(f"重试任务失败: {e}")
        raise handle_service_exception(e, "重试失败任务")


@router.get("/tasks/pending", include_in_schema=False)
async def get_pending_tasks(
    limit: int = Query(100, description="返回数量限制"),
    task_service: TaskService = Depends(get_task_service)
):
    """
    获取待处理任务列表（内部接口）
    
    主要用于Celery Worker获取待处理的任务。
    """
    try:
        api_logger.info(f"获取待处理任务: 限制={limit}")
        
        # 调用业务服务获取待处理任务
        pending_tasks = await task_service.get_pending_tasks(limit)
        
        # 简化返回格式
        task_list = [
            {
                "task_id": task.task_id,
                "job_id": task.job_id,
                "source_file_path": task.source_file_path,
                "created_at": task.created_at.isoformat()
            }
            for task in pending_tasks
        ]
        
        api_logger.debug(f"获取待处理任务成功: 数量={len(task_list)}")
        return {"tasks": task_list}
        
    except Exception as e:
        api_logger.error(f"获取待处理任务失败: {e}")
        raise handle_service_exception(e, "获取待处理任务") 