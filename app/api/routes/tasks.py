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
    TaskStatistics, TaskRetryRequest, TaskRetryResponse,
    TaskLintResultResponse, SeverityLevelStatistics, TaskSeverityCalculateResponse,
    TaskWithViolationsListResponse
)
from app.schemas.common import TaskStatusEnum
from app.core.logging import api_logger
from app.utils.file_utils import FileManager

router = APIRouter()


@router.get("/tasks", response_model=TaskDetailResponse)
async def get_task(
    task_id: str = Query(..., description="任务ID"),
    task_service: TaskService = Depends(get_task_service)
):
    """
    获取单个任务的详细信息
    
    返回任务的完整信息，包括状态、文件路径、处理时长等。
    """
    try:
        # 验证task_id格式
        task_id = validate_task_id(task_id)
        
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


@router.get("/tasks/result", response_model=TaskResultContent)
async def get_task_result(
    task_id: str = Query(..., description="任务ID"),
    task_service: TaskService = Depends(get_task_service)
):
    """
    获取单个文件任务的详细结果
    
    返回SQLFluff分析的完整结果，包括违规项、摘要信息等。
    只有状态为SUCCESS的任务才能获取结果。
    """
    try:
        # 验证task_id格式
        task_id = validate_task_id(task_id)
        
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


@router.get("/tasks/result/lint", response_model=TaskLintResultResponse)
async def get_task_lint_result(
    task_id: str = Query(..., description="任务ID"),
    task_service: TaskService = Depends(get_task_service)
):
    """
    获取单个文件任务的Lint结果（只包含violations和SQL行内容）
    
    返回SQLFluff分析的违规项列表，每个违规项都包含对应的SQL行内容。
    只有状态为SUCCESS的任务才能获取结果。
    """
    try:
        # 验证task_id格式
        task_id = validate_task_id(task_id)
        
        api_logger.info(f"获取Task Lint结果: {task_id}")
        
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
        
        # 获取Lint结果
        result = await task_service.get_task_lint_result(task_id)
        if result is None:
            api_logger.error(f"Task Lint结果文件不存在: {task_id}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="结果文件不存在或读取失败"
            )
        
        api_logger.debug(f"Task Lint结果获取成功: {task_id}, 违规项数量: {len(result.violations)}")
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"获取Task Lint结果失败: {task_id}, 错误: {e}")
        raise handle_service_exception(e, "获取任务Lint结果")


@router.get("/tasks/result/download")
async def download_task_result(
    task_id: str = Query(..., description="任务ID"),
    task_service: TaskService = Depends(get_task_service)
):
    """
    下载任务结果文件
    
    直接返回JSON文件供下载。
    """
    try:
        # 验证task_id格式
        task_id = validate_task_id(task_id)
        
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


@router.get("/tasks/list", response_model=TaskListResponse)
async def list_tasks(
    pagination: tuple[int, int] = Depends(get_pagination_params),
    status_filter: Optional[TaskStatusEnum] = Query(None, alias="status", description="状态过滤"),
    job_id: Optional[str] = Query(None, description="Job ID过滤"),
    violation_exists: Optional[bool] = Query(None, description="是否有违规项过滤，true表示只显示有违规的任务，false表示只显示无违规的任务"),
    task_service: TaskService = Depends(get_task_service)
):
    """
    获取任务列表
    
    支持分页查询和多维度过滤。
    """
    try:
        page, size = pagination
        api_logger.info(f"查询Task列表: 页码={page}, 大小={size}, 状态={status_filter}, Job={job_id}, 违规过滤={violation_exists}")
        
        # 如果指定了job_id，使用专门的方法
        if job_id:
            task_list = await task_service.get_tasks_by_job_id(
                job_id=job_id,
                page=page,
                size=size,
                status=status_filter,
                violation_exists=violation_exists
            )
        else:
            # 否则查询全部任务（这里需要在TaskService中实现通用的list_tasks方法）
            # 暂时使用job_id=None的方式
            task_list = await task_service.get_tasks_by_job_id(
                job_id=None,  # 查询所有任务
                page=page,
                size=size,
                status=status_filter,
                violation_exists=violation_exists
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


@router.get("/tasks/severity-statistics", response_model=SeverityLevelStatistics)
async def get_severity_level_statistics(
    job_id: str = Query(..., description="Job ID"),
    task_service: TaskService = Depends(get_task_service)
):
    """
    获取Severity Level统计信息（旧版本 - 基于JSON文件）
    
    统计指定Job下所有任务结果中不同severity_level的违规项数量分布。
    只统计状态为SUCCESS的任务。
    
    **注意**：此接口为旧版本，建议使用 `/tasks/severity-statistics/v2` 接口，性能更好且支持申诉过滤。
    """
    try:
        api_logger.info(f"获取Severity Level统计: {job_id}")
        
        # 调用业务服务获取统计信息
        statistics = await task_service.get_severity_level_statistics(job_id)
        
        api_logger.debug(f"Severity Level统计查询成功: {job_id}")
        return statistics
        
    except Exception as e:
        api_logger.error(f"获取Severity Level统计失败: {job_id}, 错误: {e}")
        raise handle_service_exception(e, "获取Severity Level统计")


@router.get("/tasks/severity-statistics/v2", response_model=SeverityLevelStatistics)
async def get_severity_level_statistics_v2(
    job_id: str = Query(..., description="Job ID"),
    task_service: TaskService = Depends(get_task_service)
):
    """
    获取Severity Level统计信息（V2版本 - 基于数据库查询，推荐使用）
    
    统计指定Job下所有任务结果中不同severity_level的违规项数量分布。
    
    **与旧版本的区别**：
    1. 直接查询linting_violations表，性能更优（无需读取JSON文件）
    2. 统计时自动剔除is_appealed=1的violations（已申诉的违规项）
    3. 新增appealed字段，统计所有已申诉的违规项数量
    
    **返回字段说明**：
    - INFO/MINOR/MAJOR/BLOCKER/CRITICAL/UNKNOWN: 各级别的未申诉违规项数量
    - appealed: 已申诉的违规项总数（所有级别）
    """
    try:
        api_logger.info(f"获取Severity Level统计(V2): {job_id}")
        
        # 调用业务服务获取统计信息
        statistics = await task_service.get_severity_level_statistics_v2(job_id)
        
        api_logger.debug(f"Severity Level统计查询成功(V2): {job_id}")
        return statistics
        
    except Exception as e:
        api_logger.error(f"获取Severity Level统计失败(V2): {job_id}, 错误: {e}")
        raise handle_service_exception(e, "获取Severity Level统计(V2)")


@router.get("/tasks/by-severity-level", response_model=TaskListResponse)
async def get_tasks_by_severity_level(
    job_id: str = Query(..., description="Job ID"),
    severity_level: str = Query(..., description="Severity Level (INFO/MINOR/MAJOR/BLOCKER/CRITICAL/UNKNOWN)"),
    pagination: tuple[int, int] = Depends(get_pagination_params),
    status_filter: Optional[TaskStatusEnum] = Query(None, alias="status", description="状态过滤"),
    violation_exists: Optional[bool] = Query(None, description="是否有违规项过滤，true表示只显示有违规的任务，false表示只显示无违规的任务"),
    task_service: TaskService = Depends(get_task_service)
):
    """
    按Severity Level获取任务列表（旧版本 - 基于JSON文件）
    
    返回指定Job下包含指定severity_level违规项的任务列表，支持分页和过滤。
    只查询状态为SUCCESS的任务。
    
    **注意**：此接口为旧版本，建议使用 `/tasks/by-severity-level/v2` 接口，性能更好且功能更强大。
    """
    try:
        page, size = pagination
        api_logger.info(f"按Severity Level查询任务列表: Job={job_id}, Level={severity_level}, 页码={page}, 大小={size}")
        
        # 调用业务服务查询任务列表
        task_list = await task_service.get_tasks_by_severity_level(
            job_id=job_id,
            severity_level=severity_level,
            page=page,
            size=size,
            status=status_filter,
            violation_exists=violation_exists
        )
        
        response = TaskListResponse(tasks=task_list)
        api_logger.debug(f"按Severity Level查询任务成功: {job_id}, 总数={task_list.total}")
        return response
        
    except Exception as e:
        api_logger.error(f"按Severity Level查询任务失败: {job_id}, Level={severity_level}, 错误: {e}")
        raise handle_service_exception(e, "按Severity Level查询任务列表")


@router.get("/tasks/by-severity-level/v2", response_model=TaskWithViolationsListResponse)
async def get_tasks_by_severity_level_v2(
    job_id: str = Query(..., description="Job ID（必填）"),
    severity_level: Optional[str] = Query(
        None,
        description="Severity Level过滤（可选）：INFO/MINOR/MAJOR/BLOCKER/CRITICAL/UNKNOWN/is_appealed，不传则返回所有级别"
    ),
    include_appealed: bool = Query(
        False,
        description="是否包含已申诉的violations（默认false，仅当severity_level不为is_appealed时有效）"
    ),
    pagination: tuple[int, int] = Depends(get_pagination_params),
    status_filter: Optional[TaskStatusEnum] = Query(None, alias="status", description="任务状态过滤"),
    task_service: TaskService = Depends(get_task_service)
):
    """
    按Severity Level获取任务列表及violations详情（V2版本 - 基于数据库查询，推荐使用）
    
    **与旧版本的区别**：
    1. 直接查询linting_violations表，性能更优（无需读取JSON文件）
    2. severity_level为可选参数，不传则返回所有级别的violations
    3. 支持severity_level="is_appealed"，专门查询已申诉的violations
    4. 支持include_appealed参数，控制是否包含已申诉的violations
    5. 返回每个task的matched_violations详细信息，包含violation_id和is_appealed字段
    
    **参数说明**：
    - `job_id`: Job ID（必填）
    - `severity_level`: Severity Level过滤（可选）
      - 不传：返回所有级别的violations
      - INFO/MINOR/MAJOR/BLOCKER/CRITICAL/UNKNOWN：返回指定级别的violations
      - is_appealed：返回已申诉的violations（不限级别）
    - `include_appealed`: 是否包含已申诉的violations
      - false（默认）：只返回未申诉的violations
      - true：包含已申诉的violations
      - 注意：当severity_level="is_appealed"时，此参数无效
    - `status`: 任务状态过滤（可选）
    - `page`, `size`: 分页参数
    
    **使用示例**：
    - `?job_id=xxx`: 查询所有未申诉的violations
    - `?job_id=xxx&include_appealed=true`: 查询所有violations（包括已申诉）
    - `?job_id=xxx&severity_level=MAJOR`: 查询所有未申诉的MAJOR级别violations
    - `?job_id=xxx&severity_level=MAJOR&include_appealed=true`: 查询所有MAJOR级别violations（包括已申诉）
    - `?job_id=xxx&severity_level=is_appealed`: 查询所有已申诉的violations
    
    **返回结构**：
    每个task包含matched_violations数组，包含符合条件的violations详细信息：
    - violation_id: 违规项ID（可用于申诉操作）
    - is_appealed: 是否已申诉
    - rule_code, severity_level, line_no, description等完整信息
    """
    try:
        page, size = pagination
        api_logger.info(
            f"按Severity Level查询任务列表(V2): Job={job_id}, Level={severity_level}, "
            f"include_appealed={include_appealed}, 页码={page}, 大小={size}"
        )
        
        # 调用业务服务查询任务列表
        result = await task_service.get_tasks_by_severity_level_v2(
            job_id=job_id,
            severity_level=severity_level,
            include_appealed=include_appealed,
            page=page,
            size=size,
            status=status_filter
        )
        
        api_logger.debug(f"按Severity Level查询任务成功(V2): {job_id}, 总数={result.tasks.total}")
        return result
        
    except Exception as e:
        api_logger.error(
            f"按Severity Level查询任务失败(V2): {job_id}, Level={severity_level}, 错误: {e}"
        )
        raise handle_service_exception(e, "按Severity Level查询任务列表(V2)")


@router.get("/tasks/by-severity-level/v3", response_model=TaskWithViolationsListResponse)
async def get_tasks_by_severity_level_v3(
    job_id: str = Query(..., description="Job ID（必填）"),
    severity_level: Optional[List[str]] = Query(
        None,
        description="Severity Level过滤（可选，支持多值）：INFO/MINOR/MAJOR/BLOCKER/CRITICAL/UNKNOWN/is_appealed。使用重复参数形式传多个值：?severity_level=MAJOR&severity_level=CRITICAL。不传则返回所有级别"
    ),
    include_appealed: bool = Query(
        False,
        description="是否包含已申诉的violations（默认false，仅当severity_level不包含is_appealed时有效）"
    ),
    pagination: tuple[int, int] = Depends(get_pagination_params),
    status_filter: Optional[TaskStatusEnum] = Query(None, alias="status", description="任务状态过滤"),
    task_service: TaskService = Depends(get_task_service)
):
    """
    按Severity Level获取任务列表及violations详情（V3版本 - 支持多值severity_level过滤，推荐使用）
    
    **与V2版本的区别**：
    1. 支持多个severity_level值同时过滤（使用重复参数形式）
    2. 其他功能与V2相同
    
    **参数说明**：
    - `job_id`: Job ID（必填）
    - `severity_level`: Severity Level过滤（可选，支持多值）
      - 不传：返回所有级别的violations
      - 单个值：`?severity_level=MAJOR` - 返回指定级别的violations
      - 多个值：`?severity_level=MAJOR&severity_level=CRITICAL&severity_level=BLOCKER` - 返回多个级别的violations
      - `is_appealed`：返回已申诉的violations（不能与其他级别混用）
    - `include_appealed`: 是否包含已申诉的violations
      - false（默认）：只返回未申诉的violations
      - true：包含已申诉的violations
      - 注意：当severity_level包含"is_appealed"时，此参数无效
    - `status`: 任务状态过滤（可选）
    - `page`, `size`: 分页参数
    
    **使用示例**：
    - `?job_id=xxx`: 查询所有未申诉的violations
    - `?job_id=xxx&include_appealed=true`: 查询所有violations（包括已申诉）
    - `?job_id=xxx&severity_level=MAJOR`: 查询所有未申诉的MAJOR级别violations
    - `?job_id=xxx&severity_level=MAJOR&severity_level=CRITICAL`: 查询所有未申诉的MAJOR和CRITICAL级别violations
    - `?job_id=xxx&severity_level=MAJOR&severity_level=CRITICAL&include_appealed=true`: 查询所有MAJOR和CRITICAL级别violations（包括已申诉）
    - `?job_id=xxx&severity_level=is_appealed`: 查询所有已申诉的violations
    - `?job_id=xxx&severity_level=MAJOR&severity_level=UNKNOWN`: 查询MAJOR和UNKNOWN级别violations
    
    **返回结构**：
    每个task包含matched_violations数组，包含符合条件的violations详细信息：
    - violation_id: 违规项ID（可用于申诉操作）
    - is_appealed: 是否已申诉
    - rule_code, severity_level, line_no, description等完整信息
    """
    try:
        page, size = pagination
        api_logger.info(
            f"按Severity Level查询任务列表(V3): Job={job_id}, Levels={severity_level}, "
            f"include_appealed={include_appealed}, 页码={page}, 大小={size}"
        )
        
        # 调用业务服务查询任务列表
        result = await task_service.get_tasks_by_severity_level_v3(
            job_id=job_id,
            severity_levels=severity_level,
            include_appealed=include_appealed,
            page=page,
            size=size,
            status=status_filter
        )
        
        api_logger.debug(f"按Severity Level查询任务成功(V3): {job_id}, 总数={result.tasks.total}")
        return result
        
    except Exception as e:
        api_logger.error(
            f"按Severity Level查询任务失败(V3): {job_id}, Levels={severity_level}, 错误: {e}"
        )
        raise handle_service_exception(e, "按Severity Level查询任务列表(V3)")


@router.post("/tasks/calculate-severity-statistics", response_model=TaskSeverityCalculateResponse)
async def calculate_all_severity_statistics(
    task_service: TaskService = Depends(get_task_service)
):
    """
    批量计算所有任务的Severity Level统计信息（历史数据修复接口）
    
    **用途说明**：
    - 此接口专门用于修复历史数据中缺失的severity_level统计字段
    - 对于新创建的任务，severity_level统计会在任务处理时自动计算，无需调用此接口
    - 建议仅在系统升级后用于一次性修复历史数据
    
    **处理逻辑**：
    遍历数据库中的所有任务，读取每个任务的结果JSON文件，
    统计不同severity_level的违规项数量，并更新到数据库字段。
    
    **注意事项**：
    - 只处理状态为SUCCESS且有结果文件的任务
    - 对于JSON中没有violations或severity_level字段的情况，会将所有字段设为0或归类为UNKNOWN
    - 任何单个任务的失败不会中断整个批量操作
    - 支持重新计算已有数据（会覆盖现有统计值）
    """
    try:
        api_logger.info("开始批量计算所有任务的Severity Level统计")
        
        # 调用业务服务进行批量计算
        result = await task_service.batch_calculate_all_severity_statistics()
        
        api_logger.info(f"批量计算完成: 总计={result.total_processed}, 成功={result.success_count}, 失败={result.failed_count}, 跳过={result.skipped_count}")
        return result
        
    except Exception as e:
        api_logger.error(f"批量计算Severity Level统计失败: {e}")
        raise handle_service_exception(e, "批量计算Severity Level统计") 