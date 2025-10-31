"""
Job相关API路由

实现核验工作(Job)相关的HTTP接口，包括创建、查询、状态管理等功能。
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import Optional, List

from app.api.deps import (
    get_job_service, validate_job_id, get_pagination_params,
    get_search_params, handle_service_exception
)
from app.services.job_service import JobService
from app.schemas.job import (
    JobCreateRequest, JobCreateWithUploadRequest, JobCreateFromExtractedRequest, JobCreateResponse, JobDetailResponse,
    JobListResponse, JobSummary, JobStatistics, JobTaskIdsResponse
)
from app.schemas.violation import JobViolationsResponse, JobStatisticsResponse
from app.schemas.common import JobStatusEnum, SubmissionTypeEnum
from app.core.logging import api_logger
from app.core.database import get_db

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


@router.post("/jobs/upload", response_model=JobCreateResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_job_with_upload(
    user_id: str = Form(..., description="创建工作的用户ID"),
    product_name: str = Form(..., description="产品名称"),
    dialect: str = Form("ansi", description="SQLFluff方言"),
    boc_batch_number: str = Form(None, description="BOC批次号"),
    boc_task_number: str = Form(None, description="BOC任务号"),
    sql_content: str = Form(None, description="单段SQL内容（与zip_file二选一）"),
    zip_file: UploadFile = File(None, description="ZIP文件（与sql_content二选一）"),
    rules: Optional[str] = Form(None, description="SQLFluff规则列表，逗号分隔，如RF02,L032"),
    job_service: JobService = Depends(get_job_service)
):
    """
    创建新的核验工作（带文件上传）
    
    支持两种提交模式：
    1. 单SQL文件：直接提交SQL内容
    2. ZIP包：上传ZIP文件，系统会自动保存到NFS
    
    创建成功后会自动派发Celery任务进行处理。
    """
    try:
        # 验证参数
        if not sql_content and not zip_file:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="必须提供 sql_content 或 zip_file 其中之一"
            )
        
        if sql_content and zip_file:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="sql_content 和 zip_file 不能同时提供"
            )
        
        # 处理文件上传
        zip_file_path = None
        if zip_file:
            # 验证文件类型
            if not zip_file.filename.endswith('.zip'):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="文件必须是ZIP格式"
                )
            
            # 验证文件大小（例如限制50MB）
            file_content = await zip_file.read()
            if len(file_content) > 50 * 1024 * 1024:  # 50MB
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="文件大小不能超过50MB"
                )
            
            # 保存文件到NFS
            try:
                import uuid
                import os
                from app.config.settings import get_settings
                
                settings = get_settings()
                nfs_root = settings.NFS_SHARE_ROOT_PATH
                
                # 生成唯一文件名
                file_uuid = str(uuid.uuid4())
                file_extension = os.path.splitext(zip_file.filename)[1]
                unique_filename = f"{file_uuid}{file_extension}"
                
                # 创建上传目录
                upload_dir = os.path.join(nfs_root, "uploads")
                os.makedirs(upload_dir, exist_ok=True)
                
                # 完整文件路径
                file_path = os.path.join(upload_dir, unique_filename)
                
                # 写入文件
                with open(file_path, "wb") as f:
                    f.write(file_content)
                
                # 设置相对路径
                zip_file_path = f"uploads/{unique_filename}"
                
                api_logger.info(f"文件上传成功: {zip_file_path}")
                
            except Exception as e:
                api_logger.error(f"文件上传失败: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"文件上传失败: {str(e)}"
                )
        
        # 处理rules参数
        rules_list: Optional[List[str]] = None
        if rules:
            rules_list = [r.strip().upper() for r in rules.split(',') if r.strip()]
            if not rules_list:
                rules_list = None
        # 创建请求对象
        request = JobCreateRequest(
            sql_content=sql_content,
            zip_file_path=zip_file_path,
            dialect=dialect,
            user_id=user_id,
            product_name=product_name,
            boc_batch_number=boc_batch_number,
            boc_task_number=boc_task_number,
            rules=rules_list
        )
        
        api_logger.info(f"创建Job请求（带上传）: {request.dict()}")
        
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
        
        api_logger.info(f"Job创建成功（带上传）: {response.job_id}")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"创建Job失败（带上传）: {e}")
        raise handle_service_exception(e, "创建核验工作")


@router.post("/jobs/create-from-extracted", response_model=JobCreateResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_job_from_extracted_folder(
    request: JobCreateFromExtractedRequest,
    job_service: JobService = Depends(get_job_service)
):
    """
    从解压后的文件夹创建新的核验工作（异步优化版本）
    
    接收已解压的ZIP文件夹路径，立即返回job_id，后台异步处理文件扫描、
    Task创建和Celery任务派发。
    
    适用于已经预处理过的ZIP文件场景，特别是大文件夹场景。
    
    优化特性：
    - 立即返回响应，避免Feign调用超时
    - 异步处理文件扫描和验证
    - 自动派发Celery任务处理
    """
    try:
        api_logger.info(f"从解压文件夹创建Job请求: {request.dict()}")
        
        # 调用业务服务创建Job（立即返回）
        response = await job_service.create_job_from_extracted_folder(request)
        
        # 不再在这里派发Celery任务，已移到JobService的异步处理中
        # 文件扫描、Task创建、Celery派发都在后台异步进行
        
        api_logger.info(f"Job创建成功（异步模式）: {response.job_id}")
        return response
        
    except Exception as e:
        api_logger.error(f"创建Job失败（从解压文件夹）: {e}")
        raise handle_service_exception(e, "创建核验工作")


@router.get("/jobs", response_model=JobDetailResponse)
async def get_job(
    job_id: str = Query(..., description="核验工作ID"),
    pagination: tuple[int, int] = Depends(get_pagination_params),
    job_service: JobService = Depends(get_job_service)
):
    """
    查询核验工作状态与详情
    
    返回Job的基本信息和关联的Task列表（分页）。
    可以通过分页参数控制Task列表的返回数量。
    """
    try:
        # 验证job_id格式
        job_id = validate_job_id(job_id)
        
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


@router.get("/jobs/list", response_model=JobListResponse)
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


@router.get("/jobs/search", response_model=JobListResponse)
async def search_jobs(
    # 搜索参数
    user_id: Optional[str] = Query(None, description="用户ID（支持模糊搜索）"),
    product_name: Optional[str] = Query(None, description="产品名称（支持模糊搜索）"),
    boc_batch_number: Optional[str] = Query(None, description="BOC批次号（支持模糊搜索）"),
    boc_task_number: Optional[str] = Query(None, description="BOC任务号（支持模糊搜索）"),
    status: Optional[JobStatusEnum] = Query(None, description="状态过滤"),
    submission_type: Optional[SubmissionTypeEnum] = Query(None, description="提交类型过滤"),
    dialect: Optional[str] = Query(None, description="SQLFluff方言"),
    # 分页和排序参数
    search_params: dict = Depends(get_search_params),
    job_service: JobService = Depends(get_job_service)
):
    """
    高级搜索核验工作列表
    
    支持多种搜索条件：
    - 模糊搜索：user_id、product_name、boc_batch_number、boc_task_number
    - 精确匹配：status、submission_type、dialect
    - 日期范围：created_at
    - 分页和排序
    
    所有搜索条件都是可选的，可以组合使用。
    """
    try:
        # 提取搜索参数
        page = search_params["page"]
        size = search_params["size"]
        sort_by = search_params["sort_by"]
        sort_order = search_params["sort_order"]
        start_date = search_params["start_date"]
        end_date = search_params["end_date"]
        
        api_logger.info(
            f"搜索Job: 页码={page}, 大小={size}, 用户ID={user_id}, "
            f"产品={product_name}, BOC批次={boc_batch_number}, BOC任务={boc_task_number}, "
            f"状态={status}, 类型={submission_type}, 方言={dialect}, "
            f"排序={sort_by}:{sort_order}, 日期范围={start_date}~{end_date}"
        )
        
        # 调用业务服务搜索Job列表
        job_list = await job_service.search_jobs(
            page=page,
            size=size,
            user_id=user_id,
            product_name=product_name,
            boc_batch_number=boc_batch_number,
            boc_task_number=boc_task_number,
            status=status,
            submission_type=submission_type,
            dialect=dialect,
            start_date=start_date,
            end_date=end_date,
            sort_by=sort_by,
            sort_order=sort_order
        )
        
        response = JobListResponse(jobs=job_list)
        api_logger.debug(f"Job搜索成功: 总数={job_list.total}")
        return response
        
    except Exception as e:
        api_logger.error(f"搜索Job列表失败: {e}")
        raise handle_service_exception(e, "搜索核验工作列表")


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


@router.get("/jobs/tasks", response_model=JobTaskIdsResponse)
async def get_job_task_ids(
    job_id: str = Query(..., description="核验工作ID"),
    job_service: JobService = Depends(get_job_service)
):
    """
    获取核验工作下的所有任务ID列表
    
    返回指定Job下的所有Task ID，用于批量操作或快速查看任务列表。
    """
    try:
        # 验证job_id格式
        job_id = validate_job_id(job_id)
        
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


# ============= Violations 相关接口 =============

@router.get("/jobs/{job_id}/violations", response_model=JobViolationsResponse)
async def get_job_violations(
    job_id: str,
    db: Session = Depends(get_db)
):
    """
    获取Job下所有违规项（用于CSV生成和详细查询）
    
    返回Job下所有Task及其violations明细，按文件路径和行号排序。
    适用于生成详细报告和数据分析。
    """
    try:
        from app.models.database import LintingJob, LintingTask, LintingViolation
        from app.schemas.violation import TaskWithViolations, ViolationSimple
        import os
        
        # 验证job_id格式
        job_id = validate_job_id(job_id)
        api_logger.info(f"查询Job violations: {job_id}")
        
        # 验证Job是否存在
        job = db.query(LintingJob).filter(LintingJob.job_id == job_id).first()
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"核验工作不存在: {job_id}"
            )
        
        # 查询Job下的所有Task和Violations（一次JOIN查询）
        query = db.query(
            LintingTask,
            LintingViolation
        ).outerjoin(
            LintingViolation,
            LintingTask.task_id == LintingViolation.task_id
        ).filter(
            LintingTask.job_id == job_id
        ).order_by(
            LintingTask.source_file_path,
            LintingViolation.line_no
        )
        
        results = query.all()
        
        # 按Task分组处理数据
        tasks_dict = {}
        total_violations_count = 0
        
        for task, violation in results:
            if task.task_id not in tasks_dict:
                tasks_dict[task.task_id] = {
                    'task_id': task.task_id,
                    'source_file_path': task.source_file_path,
                    'file_name': os.path.basename(task.source_file_path) if task.source_file_path else '',
                    'sql_lines': task.sql_lines,
                    'total_violations': task.total_violations or 0,
                    'violations': []
                }
            
            # 添加violation（如果存在）
            if violation:
                tasks_dict[task.task_id]['violations'].append(
                    ViolationSimple(
                        rule_code=violation.rule_code,
                        rule_name=violation.rule_name,
                        severity_level=violation.severity_level,
                        line_no=violation.line_no,
                        line_pos=violation.line_pos,
                        description=violation.description,
                        sql_line=violation.sql_line,
                        fixable=violation.fixable or False
                    )
                )
                total_violations_count += 1
        
        # 转换为列表
        tasks_list = [TaskWithViolations(**task_data) for task_data in tasks_dict.values()]
        
        response = JobViolationsResponse(
            job_id=job_id,
            total_tasks=len(tasks_list),
            total_violations=total_violations_count,
            tasks=tasks_list
        )
        
        api_logger.info(f"Job violations查询成功: {job_id}, tasks: {len(tasks_list)}, violations: {total_violations_count}")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"查询Job violations失败: {job_id}, 错误: {e}")
        raise handle_service_exception(e, "查询违规项")


@router.get("/jobs/{job_id}/statistics", response_model=JobStatisticsResponse)
async def get_job_statistics(
    job_id: str,
    db: Session = Depends(get_db)
):
    """
    获取Job的统计信息（规则热度、严重级别分布）
    
    返回Job下的聚合统计数据，包括：
    - 严重级别分布
    - 规则触发次数 TOP 20
    """
    try:
        from app.models.database import LintingJob, LintingTask, LintingViolation
        from app.schemas.violation import RuleStatistics, SeverityStatistics
        from sqlalchemy import func, distinct
        
        # 验证job_id格式
        job_id = validate_job_id(job_id)
        api_logger.info(f"查询Job statistics: {job_id}")
        
        # 验证Job是否存在
        job = db.query(LintingJob).filter(LintingJob.job_id == job_id).first()
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"核验工作不存在: {job_id}"
            )
        
        # 统计总文件数和有违规项的文件数
        total_files = db.query(func.count(LintingTask.task_id)).filter(
            LintingTask.job_id == job_id
        ).scalar()
        
        files_with_violations = db.query(func.count(distinct(LintingViolation.task_id))).filter(
            LintingViolation.job_id == job_id
        ).scalar()
        
        # 统计总违规项数
        total_violations = db.query(func.count(LintingViolation.id)).filter(
            LintingViolation.job_id == job_id
        ).scalar()
        
        # 统计严重级别分布
        severity_query = db.query(
            LintingViolation.severity_level,
            func.count(LintingViolation.id).label('count')
        ).filter(
            LintingViolation.job_id == job_id
        ).group_by(
            LintingViolation.severity_level
        ).all()
        
        severity_distribution = []
        for sev_level, count in severity_query:
            percentage = (count / total_violations * 100) if total_violations > 0 else 0
            severity_distribution.append(
                SeverityStatistics(
                    severity_level=sev_level or 'UNKNOWN',
                    count=count,
                    percentage=round(percentage, 2)
                )
            )
        
        # 统计规则热度 TOP 20
        rule_query = db.query(
            LintingViolation.rule_code,
            LintingViolation.rule_name,
            LintingViolation.severity_level,
            func.count(LintingViolation.id).label('count'),
            func.count(distinct(LintingViolation.task_id)).label('affected_files')
        ).filter(
            LintingViolation.job_id == job_id
        ).group_by(
            LintingViolation.rule_code,
            LintingViolation.rule_name,
            LintingViolation.severity_level
        ).order_by(
            func.count(LintingViolation.id).desc()
        ).limit(20).all()
        
        top_rules = []
        for rule_code, rule_name, severity_level, count, affected_files in rule_query:
            top_rules.append(
                RuleStatistics(
                    rule_code=rule_code,
                    rule_name=rule_name,
                    severity_level=severity_level,
                    count=count,
                    affected_files=affected_files
                )
            )
        
        response = JobStatisticsResponse(
            job_id=job_id,
            total_violations=total_violations or 0,
            total_files=total_files or 0,
            files_with_violations=files_with_violations or 0,
            severity_distribution=severity_distribution,
            top_rules=top_rules
        )
        
        api_logger.info(f"Job statistics查询成功: {job_id}")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"查询Job statistics失败: {job_id}, 错误: {e}")
        raise handle_service_exception(e, "查询统计信息")


@router.get("/jobs/{job_id}/export/csv")
async def export_job_csv(
    job_id: str,
    db: Session = Depends(get_db)
):
    """
    导出Job的CSV报告

    直接返回CSV文件供下载，包含所有Task的violations明细。
    """
    try:
        from fastapi.responses import StreamingResponse
        from app.models.database import LintingJob, LintingTask, LintingViolation
        import io
        import csv
        import os

        # 验证job_id格式
        job_id = validate_job_id(job_id)
        api_logger.info(f"导出Job CSV: {job_id}")

        # 验证Job是否存在
        job = db.query(LintingJob).filter(LintingJob.job_id == job_id).first()
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"核验工作不存在: {job_id}"
            )

        # 查询Job下的所有Task和Violations
        query = db.query(
            LintingTask,
            LintingViolation
        ).outerjoin(
            LintingViolation,
            LintingTask.task_id == LintingViolation.task_id
        ).filter(
            LintingTask.job_id == job_id
        ).order_by(
            LintingTask.source_file_path,
            LintingViolation.line_no
        )

        results = query.all()

        # 创建CSV内容
        output = io.StringIO()
        writer = csv.writer(output)

        # 写入CSV表头
        writer.writerow([
            '文件路径',
            '文件名',
            '代码行数',
            '行号',
            '列号',
            '规则编号',
            '规则名称',
            '严重级别',
            '问题描述',
            '是否可修复',
            'SQL代码行'
        ])

        # 写入数据行
        for task, violation in results:
            if violation:
                # 有violation的行
                writer.writerow([
                    task.source_file_path or '',
                    os.path.basename(task.source_file_path) if task.source_file_path else '',
                    task.sql_lines or '',
                    violation.line_no or '',
                    violation.line_pos or '',
                    violation.rule_code or '',
                    violation.rule_name or '',
                    violation.severity_level or '',
                    violation.description or '',
                    '是' if violation.fixable else '否',
                    violation.sql_line or ''
                ])
            else:
                # 没有violation的Task（仍然显示文件信息）
                writer.writerow([
                    task.source_file_path or '',
                    os.path.basename(task.source_file_path) if task.source_file_path else '',
                    task.sql_lines or '',
                    '', '', '', '', '', '无违规项', '', ''
                ])

        # 重置流位置
        output.seek(0)

        # 返回CSV文件
        api_logger.info(f"CSV导出成功: {job_id}")
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=job_{job_id}_report.csv"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"导出CSV失败: {job_id}, 错误: {e}")
        raise handle_service_exception(e, "导出CSV报告")


@router.get("/jobs/{job_id}/export/html")
async def export_job_html(
    job_id: str,
    db: Session = Depends(get_db)
):
    """
    导出Job的HTML报告（Fragment版本）

    返回HTML片段用于Vue3前端集成。
    如果文件数量超过限制，返回JSON错误响应。
    """
    try:
        from fastapi.responses import HTMLResponse, JSONResponse
        from app.services.html_report_service import html_report_service

        # 验证job_id格式
        job_id = validate_job_id(job_id)
        api_logger.info(f"导出Job HTML报告: {job_id}")

        # 生成HTML报告
        html_content, error = await html_report_service.generate_html_report(
            job_id=job_id,
            db=db,
            standalone=False
        )

        # 如果有错误，返回JSON错误响应
        if error:
            api_logger.warning(f"HTML报告生成失败: {job_id}, {error}")
            return JSONResponse(
                content=eval(error),  # error is a JSON string
                status_code=status.HTTP_200_OK
            )

        # 返回HTML内容
        api_logger.info(f"HTML报告导出成功: {job_id}")
        return HTMLResponse(content=html_content)

    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"导出HTML失败: {job_id}, 错误: {e}")
        raise handle_service_exception(e, "导出HTML报告")


@router.get("/jobs/{job_id}/export/html/standalone")
async def export_job_html_standalone(
    job_id: str,
    db: Session = Depends(get_db)
):
    """
    导出Job的HTML报告（Standalone版本）

    返回完整的HTML文档，可在浏览器中直接打开。
    用于开发调试和独立查看。
    """
    try:
        from fastapi.responses import HTMLResponse, JSONResponse
        from app.services.html_report_service import html_report_service

        # 验证job_id格式
        job_id = validate_job_id(job_id)
        api_logger.info(f"导出Job HTML报告（Standalone）: {job_id}")

        # 生成HTML报告
        html_content, error = await html_report_service.generate_html_report(
            job_id=job_id,
            db=db,
            standalone=True
        )

        # 如果有错误，返回JSON错误响应
        if error:
            api_logger.warning(f"HTML报告生成失败（Standalone）: {job_id}, {error}")
            return JSONResponse(
                content=eval(error),  # error is a JSON string
                status_code=status.HTTP_200_OK
            )

        # 返回HTML内容
        api_logger.info(f"HTML报告导出成功（Standalone）: {job_id}")
        return HTMLResponse(content=html_content)

    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"导出HTML失败（Standalone）: {job_id}, 错误: {e}")
        raise handle_service_exception(e, "导出HTML报告")


# ============= 内部管理接口（可选实现） =============

@router.put("/jobs/status", include_in_schema=False)
async def update_job_status(
    job_id: str = Query(..., description="核验工作ID"),
    status_update: dict = None,  # 简化的状态更新，实际应该用专门的schema
    job_service: JobService = Depends(get_job_service)
):
    """
    更新Job状态（内部接口）
    
    此接口主要用于Celery Worker更新Job状态，不对外公开。
    """
    try:
        # 验证job_id格式
        job_id = validate_job_id(job_id)
        
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