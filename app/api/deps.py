"""
API依赖注入模块

定义FastAPI的依赖注入函数，包括数据库会话、业务服务实例、参数验证等。
为API路由提供统一的依赖管理。
"""

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional
import uuid

from app.core.database import get_db
from app.services.job_service import JobService
from app.services.task_service import TaskService
from app.core.exceptions import ErrorCode, get_http_status_code
from app.core.logging import api_logger


# ============= 数据库会话依赖 =============

def get_database_session() -> Session:
    """获取数据库会话（别名，便于测试时替换）"""
    return Depends(get_db)


# ============= 业务服务依赖 =============

def get_job_service(db: Session = Depends(get_db)) -> JobService:
    """获取Job服务实例"""
    return JobService(db)


def get_task_service(db: Session = Depends(get_db)) -> TaskService:
    """获取Task服务实例"""
    return TaskService(db)


# ============= 参数验证依赖 =============

def validate_job_id(job_id: str) -> str:
    """
    验证job_id格式
    
    Args:
        job_id: Job ID字符串
        
    Returns:
        str: 验证后的job_id
        
    Raises:
        HTTPException: 格式无效时抛出400错误
    """
    try:
        # 验证UUID格式
        if not job_id.startswith('job-'):
            raise ValueError("Job ID必须以'job-'开头")
        
        # 提取UUID部分并验证
        uuid_part = job_id[4:]  # 去掉'job-'前缀
        uuid.UUID(uuid_part)
        
        api_logger.debug(f"Job ID验证通过: {job_id}")
        return job_id
        
    except ValueError as e:
        api_logger.warning(f"无效的Job ID: {job_id}, 错误: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无效的Job ID格式: {job_id}"
        )


def validate_task_id(task_id: str) -> str:
    """
    验证task_id格式
    
    Args:
        task_id: Task ID字符串
        
    Returns:
        str: 验证后的task_id
        
    Raises:
        HTTPException: 格式无效时抛出400错误
    """
    try:
        # 验证UUID格式
        if not task_id.startswith('task-'):
            raise ValueError("Task ID必须以'task-'开头")
        
        # 提取UUID部分并验证
        uuid_part = task_id[5:]  # 去掉'task-'前缀
        uuid.UUID(uuid_part)
        
        api_logger.debug(f"Task ID验证通过: {task_id}")
        return task_id
        
    except ValueError as e:
        api_logger.warning(f"无效的Task ID: {task_id}, 错误: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无效的Task ID格式: {task_id}"
        )


# ============= 分页参数依赖 =============

def get_pagination_params(
    page: int = 1,
    size: int = 10
) -> tuple[int, int]:
    """
    获取分页参数
    
    Args:
        page: 页码（默认1）
        size: 每页大小（默认10）
        
    Returns:
        tuple[int, int]: 验证后的页码和每页大小
        
    Raises:
        HTTPException: 参数无效时抛出400错误
    """
    if page < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="页码必须大于0"
        )
    
    if size < 1 or size > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="每页大小必须在1-100之间"
        )
    
    return page, size


# ============= 错误处理工具 =============

def handle_service_exception(e: Exception, operation: str = "操作") -> HTTPException:
    """
    处理业务服务异常，转换为HTTP异常
    
    Args:
        e: 业务异常
        operation: 操作描述
        
    Returns:
        HTTPException: HTTP异常
    """
    from app.core.exceptions import BaseException as BusinessException
    
    if isinstance(e, BusinessException):
        status_code = get_http_status_code(e.error_code)
        api_logger.warning(f"{operation}失败: {e.detail}")
        return HTTPException(
            status_code=status_code,
            detail=str(e.detail)
        )
    else:
        api_logger.error(f"{operation}发生未知错误: {e}")
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{operation}失败，请稍后重试"
        )


# ============= 公共响应处理 =============

def create_success_response(data: any = None, message: str = "操作成功"):
    """
    创建成功响应
    
    Args:
        data: 响应数据
        message: 响应消息
        
    Returns:
        dict: 标准化响应格式
    """
    response = {
        "success": True,
        "message": message
    }
    
    if data is not None:
        response["data"] = data
    
    return response


def create_error_response(message: str, error_code: Optional[str] = None):
    """
    创建错误响应
    
    Args:
        message: 错误消息
        error_code: 错误码
        
    Returns:
        dict: 标准化错误响应格式
    """
    response = {
        "success": False,
        "message": message
    }
    
    if error_code:
        response["error_code"] = error_code
    
    return response 