"""
自定义异常处理模块

定义业务异常类层次结构、标准错误码和错误消息。
提供异常转HTTP响应的工具函数。
"""

from typing import Any, Dict, Optional, Union
from enum import Enum
import traceback


class ErrorCode(Enum):
    """错误码枚举"""
    
    # ============= 通用错误 (1000-1999) =============
    INTERNAL_SERVER_ERROR = (1000, "内部服务器错误")
    INVALID_REQUEST = (1001, "无效请求")
    VALIDATION_ERROR = (1002, "参数验证失败")
    AUTHENTICATION_ERROR = (1003, "认证失败")
    AUTHORIZATION_ERROR = (1004, "权限不足")
    RESOURCE_NOT_FOUND = (1005, "资源不存在")
    RESOURCE_ALREADY_EXISTS = (1006, "资源已存在")
    OPERATION_TIMEOUT = (1007, "操作超时")
    RATE_LIMIT_EXCEEDED = (1008, "请求频率超限")
    
    # ============= 配置错误 (2000-2099) =============
    CONFIG_ERROR = (2000, "配置错误")
    DATABASE_CONFIG_ERROR = (2001, "数据库配置错误")
    REDIS_CONFIG_ERROR = (2002, "Redis配置错误")
    NFS_CONFIG_ERROR = (2003, "NFS配置错误")
    CONSUL_CONFIG_ERROR = (2004, "Consul配置错误")
    
    # ============= 数据库错误 (2100-2199) =============
    DATABASE_CONNECTION_ERROR = (2100, "数据库连接失败")
    DATABASE_TRANSACTION_ERROR = (2101, "数据库事务失败")
    DATABASE_QUERY_ERROR = (2102, "数据库查询失败")
    DATABASE_CONSTRAINT_ERROR = (2103, "数据库约束冲突")
    DATABASE_TIMEOUT_ERROR = (2104, "数据库操作超时")
    
    # ============= 任务队列错误 (2200-2299) =============
    CELERY_CONNECTION_ERROR = (2200, "Celery连接失败")
    TASK_DISPATCH_ERROR = (2201, "任务派发失败")
    TASK_EXECUTION_ERROR = (2202, "任务执行失败")
    TASK_TIMEOUT_ERROR = (2203, "任务执行超时")
    TASK_RETRY_EXCEEDED = (2204, "任务重试次数超限")
    
    # ============= 文件处理错误 (3000-3099) =============
    FILE_NOT_FOUND = (3000, "文件不存在")
    FILE_ACCESS_ERROR = (3001, "文件访问失败")
    FILE_SIZE_EXCEEDED = (3002, "文件大小超限")
    FILE_FORMAT_ERROR = (3003, "文件格式错误")
    FILE_PERMISSION_ERROR = (3004, "文件权限不足")
    NFS_MOUNT_ERROR = (3005, "NFS挂载失败")
    
    # ============= ZIP处理错误 (3100-3199) =============
    ZIP_EXTRACT_ERROR = (3100, "ZIP解压失败")
    ZIP_FILE_COUNT_EXCEEDED = (3101, "ZIP文件数量超限")
    ZIP_CORRUPT_ERROR = (3102, "ZIP文件损坏")
    ZIP_PASSWORD_ERROR = (3103, "ZIP文件密码错误")
    
    # ============= Job相关错误 (4000-4099) =============
    JOB_NOT_FOUND = (4000, "核验工作不存在")
    JOB_INVALID_STATUS = (4001, "核验工作状态无效")
    JOB_ALREADY_PROCESSING = (4002, "核验工作正在处理中")
    JOB_CREATION_FAILED = (4003, "核验工作创建失败")
    JOB_UPDATE_FAILED = (4004, "核验工作更新失败")
    
    # ============= Task相关错误 (4100-4199) =============
    TASK_NOT_FOUND = (4100, "任务不存在")
    TASK_INVALID_STATUS = (4101, "任务状态无效")
    TASK_RESULT_NOT_READY = (4102, "任务结果未准备就绪")
    TASK_CREATION_FAILED = (4103, "任务创建失败")
    TASK_UPDATE_FAILED = (4104, "任务更新失败")
    
    # ============= SQLFluff错误 (5000-5099) =============
    SQLFLUFF_EXECUTION_ERROR = (5000, "SQLFluff执行失败")
    SQLFLUFF_CONFIG_ERROR = (5001, "SQLFluff配置错误")
    SQLFLUFF_PARSE_ERROR = (5002, "SQL解析失败")
    SQLFLUFF_LINT_ERROR = (5003, "SQL检查失败")
    
    # ============= 服务发现错误 (6000-6099) =============
    SERVICE_REGISTER_ERROR = (6000, "服务注册失败")
    SERVICE_DISCOVERY_ERROR = (6001, "服务发现失败")
    HEALTH_CHECK_FAILED = (6002, "健康检查失败")
    
    @property
    def code(self) -> int:
        """获取错误码"""
        return self.value[0]
    
    @property
    def message(self) -> str:
        """获取错误消息"""
        return self.value[1]


class BaseException(Exception):
    """基础异常类"""
    
    def __init__(
        self,
        error_code: ErrorCode,
        detail: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        self.error_code = error_code
        self.detail = detail or error_code.message
        self.context = context or {}
        
        super().__init__(self.detail)
    
    @property
    def code(self) -> int:
        """获取错误码"""
        return self.error_code.code
    
    @property
    def message(self) -> str:
        """获取错误消息"""
        return self.error_code.message
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'error_code': self.code,
            'error_message': self.message,
            'detail': self.detail,
            'context': self.context
        }
    
    def __str__(self) -> str:
        return f"[{self.code}] {self.detail}"


class ValidationException(BaseException):
    """参数验证异常"""
    
    def __init__(self, detail: str, field: Optional[str] = None, value: Any = None):
        context = {}
        if field:
            context['field'] = field
        if value is not None:
            context['value'] = str(value)
        
        super().__init__(ErrorCode.VALIDATION_ERROR, detail, context)


class ResourceNotFoundException(BaseException):
    """资源不存在异常"""
    
    def __init__(self, resource_type: str, resource_id: str):
        detail = f"{resource_type}不存在: {resource_id}"
        context = {
            'resource_type': resource_type,
            'resource_id': resource_id
        }
        super().__init__(ErrorCode.RESOURCE_NOT_FOUND, detail, context)


class DatabaseException(BaseException):
    """数据库异常"""
    
    def __init__(self, operation: str, detail: Optional[str] = None, original_error: Optional[Exception] = None):
        context = {
            'operation': operation
        }
        if original_error:
            context['original_error'] = str(original_error)
            context['original_error_type'] = type(original_error).__name__
        
        error_detail = detail or f"数据库{operation}操作失败"
        super().__init__(ErrorCode.DATABASE_QUERY_ERROR, error_detail, context)


class CeleryException(BaseException):
    """Celery任务异常"""
    
    def __init__(self, task_name: str, detail: Optional[str] = None, task_id: Optional[str] = None):
        context = {
            'task_name': task_name
        }
        if task_id:
            context['task_id'] = task_id
        
        error_detail = detail or f"任务{task_name}执行失败"
        super().__init__(ErrorCode.TASK_EXECUTION_ERROR, error_detail, context)


class FileException(BaseException):
    """文件处理异常"""
    
    def __init__(self, operation: str, file_path: str, detail: Optional[str] = None):
        context = {
            'operation': operation,
            'file_path': file_path
        }
        
        error_detail = detail or f"文件{operation}操作失败: {file_path}"
        super().__init__(ErrorCode.FILE_ACCESS_ERROR, error_detail, context)


class ZipException(BaseException):
    """ZIP处理异常"""
    
    def __init__(self, operation: str, zip_path: str, detail: Optional[str] = None):
        context = {
            'operation': operation,
            'zip_path': zip_path
        }
        
        error_detail = detail or f"ZIP{operation}操作失败: {zip_path}"
        super().__init__(ErrorCode.ZIP_EXTRACT_ERROR, error_detail, context)


class JobException(BaseException):
    """Job相关异常"""
    
    def __init__(self, error_code: ErrorCode, job_id: str, detail: Optional[str] = None):
        context = {
            'job_id': job_id
        }
        
        error_detail = detail or error_code.message
        super().__init__(error_code, error_detail, context)


class TaskException(BaseException):
    """Task相关异常"""
    
    def __init__(self, error_code: ErrorCode, task_id: str, detail: Optional[str] = None):
        context = {
            'task_id': task_id
        }
        
        error_detail = detail or error_code.message
        super().__init__(error_code, error_detail, context)


class SQLFluffException(BaseException):
    """SQLFluff处理异常"""
    
    def __init__(self, operation: str, sql_file: str, detail: Optional[str] = None):
        context = {
            'operation': operation,
            'sql_file': sql_file
        }
        
        error_detail = detail or f"SQLFluff{operation}失败: {sql_file}"
        super().__init__(ErrorCode.SQLFLUFF_EXECUTION_ERROR, error_detail, context)
    
    def __reduce__(self):
        """支持Celery序列化"""
        return (SQLFluffException, (self.context.get('operation', ''), self.context.get('sql_file', ''), self.detail))


# ============= HTTP状态码映射 =============

HTTP_STATUS_CODE_MAP = {
    # 通用错误
    ErrorCode.INTERNAL_SERVER_ERROR: 500,
    ErrorCode.INVALID_REQUEST: 400,
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.AUTHENTICATION_ERROR: 401,
    ErrorCode.AUTHORIZATION_ERROR: 403,
    ErrorCode.RESOURCE_NOT_FOUND: 404,
    ErrorCode.RESOURCE_ALREADY_EXISTS: 409,
    ErrorCode.OPERATION_TIMEOUT: 408,
    ErrorCode.RATE_LIMIT_EXCEEDED: 429,
    
    # 配置和数据库错误
    ErrorCode.CONFIG_ERROR: 500,
    ErrorCode.DATABASE_CONNECTION_ERROR: 503,
    ErrorCode.DATABASE_QUERY_ERROR: 500,
    ErrorCode.DATABASE_CONSTRAINT_ERROR: 409,
    ErrorCode.DATABASE_TIMEOUT_ERROR: 408,
    
    # 任务队列错误
    ErrorCode.CELERY_CONNECTION_ERROR: 503,
    ErrorCode.TASK_DISPATCH_ERROR: 500,
    ErrorCode.TASK_EXECUTION_ERROR: 500,
    ErrorCode.TASK_TIMEOUT_ERROR: 408,
    ErrorCode.TASK_RETRY_EXCEEDED: 500,
    
    # 文件处理错误
    ErrorCode.FILE_NOT_FOUND: 404,
    ErrorCode.FILE_ACCESS_ERROR: 500,
    ErrorCode.FILE_SIZE_EXCEEDED: 413,
    ErrorCode.FILE_FORMAT_ERROR: 400,
    ErrorCode.FILE_PERMISSION_ERROR: 403,
    
    # ZIP处理错误
    ErrorCode.ZIP_EXTRACT_ERROR: 500,
    ErrorCode.ZIP_FILE_COUNT_EXCEEDED: 413,
    ErrorCode.ZIP_CORRUPT_ERROR: 400,
    
    # 业务逻辑错误
    ErrorCode.JOB_NOT_FOUND: 404,
    ErrorCode.JOB_INVALID_STATUS: 409,
    ErrorCode.JOB_ALREADY_PROCESSING: 409,
    ErrorCode.TASK_NOT_FOUND: 404,
    ErrorCode.TASK_INVALID_STATUS: 409,
    ErrorCode.TASK_RESULT_NOT_READY: 409,
    
    # SQLFluff错误
    ErrorCode.SQLFLUFF_EXECUTION_ERROR: 500,
    ErrorCode.SQLFLUFF_PARSE_ERROR: 400,
    
    # 服务发现错误
    ErrorCode.SERVICE_REGISTER_ERROR: 503,
    ErrorCode.SERVICE_DISCOVERY_ERROR: 503,
    ErrorCode.HEALTH_CHECK_FAILED: 503,
}


def get_http_status_code(error_code: ErrorCode) -> int:
    """获取错误码对应的HTTP状态码"""
    return HTTP_STATUS_CODE_MAP.get(error_code, 500)


def create_error_response(
    exception: BaseException,
    include_traceback: bool = False
) -> Dict[str, Any]:
    """创建错误响应"""
    
    response = {
        'error': True,
        'error_code': exception.code,
        'error_message': exception.message,
        'detail': exception.detail,
        'context': exception.context
    }
    
    if include_traceback:
        response['traceback'] = traceback.format_exc()
    
    return response


def handle_unexpected_error(error: Exception) -> Dict[str, Any]:
    """处理未预期的错误"""
    
    # 记录详细的错误信息
    from app.core.logging import app_logger, log_error_with_context
    
    log_error_with_context(
        app_logger,
        error,
        "未处理的异常",
        error_type=type(error).__name__,
        traceback=traceback.format_exc()
    )
    
    # 返回通用错误响应
    return create_error_response(
        BaseException(
            ErrorCode.INTERNAL_SERVER_ERROR,
            "系统发生未知错误，请联系管理员"
        )
    ) 