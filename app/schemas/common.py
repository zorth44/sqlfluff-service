"""
通用API数据模型

定义通用的Pydantic数据模型，包括分页响应、基础响应等。
用于API请求和响应的数据验证和序列化。
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, List, TypeVar, Generic, Any, Dict
from datetime import datetime
from enum import Enum

# 泛型类型定义
T = TypeVar('T')


class BaseResponse(BaseModel):
    """基础响应模型"""
    success: bool = Field(default=True, description="请求是否成功")
    message: Optional[str] = Field(default=None, description="响应消息")
    timestamp: datetime = Field(default_factory=datetime.now, description="响应时间戳")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ErrorResponse(BaseResponse):
    """错误响应模型"""
    success: bool = Field(default=False, description="请求失败")
    error_code: Optional[str] = Field(default=None, description="错误代码")
    error_details: Optional[Dict[str, Any]] = Field(default=None, description="错误详情")


class PaginationParams(BaseModel):
    """分页参数模型"""
    page: int = Field(default=1, ge=1, description="页码，从1开始")
    size: int = Field(default=10, ge=1, le=100, description="每页大小，最大100")
    
    @validator('page')
    def validate_page(cls, v):
        if v < 1:
            raise ValueError('页码必须大于0')
        return v
    
    @validator('size')
    def validate_size(cls, v):
        if v < 1 or v > 100:
            raise ValueError('每页大小必须在1-100之间')
        return v


class PaginationResponse(BaseModel, Generic[T]):
    """分页响应模型"""
    total: int = Field(description="总记录数")
    page: int = Field(description="当前页码")
    size: int = Field(description="每页大小")
    pages: int = Field(description="总页数")
    has_next: bool = Field(description="是否有下一页")
    has_prev: bool = Field(description="是否有上一页")
    items: List[T] = Field(description="当前页数据")
    
    @validator('pages', pre=True, always=True)
    def calculate_pages(cls, v, values):
        """计算总页数"""
        total = values.get('total', 0)
        size = values.get('size', 10)
        return (total + size - 1) // size if total > 0 else 0
    
    @validator('has_next', pre=True, always=True)
    def calculate_has_next(cls, v, values):
        """计算是否有下一页"""
        page = values.get('page', 1)
        pages = values.get('pages', 0)
        return page < pages
    
    @validator('has_prev', pre=True, always=True)
    def calculate_has_prev(cls, v, values):
        """计算是否有上一页"""
        page = values.get('page', 1)
        return page > 1


class StatusEnum(str, Enum):
    """状态枚举基类"""
    pass


class JobStatusEnum(StatusEnum):
    """工作状态枚举"""
    ACCEPTED = "ACCEPTED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    PARTIALLY_COMPLETED = "PARTIALLY_COMPLETED"
    FAILED = "FAILED"


class TaskStatusEnum(StatusEnum):
    """任务状态枚举"""
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


class SubmissionTypeEnum(str, Enum):
    """提交类型枚举"""
    SINGLE_FILE = "SINGLE_FILE"
    ZIP_ARCHIVE = "ZIP_ARCHIVE"


class SortOrderEnum(str, Enum):
    """排序枚举"""
    ASC = "asc"
    DESC = "desc"


class HealthCheckResponse(BaseModel):
    """健康检查响应模型"""
    status: str = Field(description="服务状态")
    timestamp: datetime = Field(default_factory=datetime.now, description="检查时间")
    version: str = Field(description="服务版本")
    database: bool = Field(description="数据库连接状态")
    redis: bool = Field(description="Redis连接状态")
    nfs: bool = Field(description="NFS存储状态")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ValidationErrorResponse(BaseModel):
    """数据验证错误响应模型"""
    success: bool = Field(default=False)
    message: str = Field(default="数据验证失败")
    errors: List[Dict[str, Any]] = Field(description="详细错误信息")


# 工具函数
def create_error_response(
    message: str,
    error_code: Optional[str] = None,
    error_details: Optional[Dict[str, Any]] = None
) -> ErrorResponse:
    """创建错误响应"""
    return ErrorResponse(
        message=message,
        error_code=error_code,
        error_details=error_details
    )


def create_success_response(message: Optional[str] = None) -> BaseResponse:
    """创建成功响应"""
    return BaseResponse(message=message)


def create_pagination_response(
    items: List[T],
    total: int,
    page: int,
    size: int
) -> PaginationResponse[T]:
    """创建分页响应"""
    return PaginationResponse(
        items=items,
        total=total,
        page=page,
        size=size,
        pages=(total + size - 1) // size if total > 0 else 0,
        has_next=page < ((total + size - 1) // size if total > 0 else 0),
        has_prev=page > 1
    )


# 通用查询参数
class BaseQueryParams(BaseModel):
    """基础查询参数"""
    sort_by: Optional[str] = Field(default="created_at", description="排序字段")
    sort_order: SortOrderEnum = Field(default=SortOrderEnum.DESC, description="排序方向")
    
    @validator('sort_by')
    def validate_sort_by(cls, v):
        # 可以在这里验证允许的排序字段
        allowed_fields = ['created_at', 'updated_at', 'status']
        if v and v not in allowed_fields:
            raise ValueError(f'排序字段必须是以下之一: {", ".join(allowed_fields)}')
        return v


class DateRangeParams(BaseModel):
    """日期范围查询参数"""
    start_date: Optional[datetime] = Field(default=None, description="开始日期")
    end_date: Optional[datetime] = Field(default=None, description="结束日期")
    
    @validator('end_date')
    def validate_date_range(cls, v, values):
        start_date = values.get('start_date')
        if start_date and v and v <= start_date:
            raise ValueError('结束日期必须大于开始日期')
        return v


# 响应数据包装器
class ResponseWrapper:
    """响应数据包装器工具类"""
    
    @staticmethod
    def success(data: Any = None, message: str = "操作成功") -> Dict[str, Any]:
        """包装成功响应"""
        return {
            "success": True,
            "message": message,
            "data": data,
            "timestamp": datetime.now().isoformat()
        }
    
    @staticmethod
    def error(message: str, error_code: str = None, details: Any = None) -> Dict[str, Any]:
        """包装错误响应"""
        return {
            "success": False,
            "message": message,
            "error_code": error_code,
            "error_details": details,
            "timestamp": datetime.now().isoformat()
        }
    
    @staticmethod
    def paginated(
        items: List[Any],
        total: int,
        page: int,
        size: int,
        message: str = "查询成功"
    ) -> Dict[str, Any]:
        """包装分页响应"""
        pages = (total + size - 1) // size if total > 0 else 0
        return {
            "success": True,
            "message": message,
            "data": {
                "items": items,
                "pagination": {
                    "total": total,
                    "page": page,
                    "size": size,
                    "pages": pages,
                    "has_next": page < pages,
                    "has_prev": page > 1
                }
            },
            "timestamp": datetime.now().isoformat()
        }