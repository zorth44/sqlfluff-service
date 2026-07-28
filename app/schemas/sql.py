"""
SQL检查API数据模型

定义SQL检查接口的请求和响应模型。
"""

from pydantic import BaseModel, Field, validator
from typing import List, Dict, Any, Optional
from enum import Enum


class SQLDialectEnum(str, Enum):
    """支持的SQL方言枚举"""
    HIVE = "hive"
    GBASE8A = "gbase8a"


class SQLCheckRequest(BaseModel):
    """SQL检查请求模型"""
    sql_content: str = Field(
        ...,
        description="SQL内容（最多 1 MiB 字符）",
        min_length=1,
        max_length=1024 * 1024,
    )
    dialect: SQLDialectEnum = Field(..., description="SQL方言，必须是 hive 或 gbase8a")
    
    @validator('sql_content')
    def validate_sql_content(cls, v):
        """验证SQL内容"""
        if not v or not v.strip():
            raise ValueError('SQL内容不能为空')
        # 不使用strip()，保留原始的换行符以符合SQLFluff的LT12规则
        return v
    
    class Config:
        schema_extra = {
            "example": {
                "sql_content": "SELECT * FROM users WHERE id = 1;",
                "dialect": "hive"
            }
        }


class SQLViolation(BaseModel):
    """SQL违规项模型"""
    line_no: int = Field(..., description="行号")
    line_pos: int = Field(..., description="行内位置")
    code: str = Field(..., description="规则代码")
    description: str = Field(..., description="违规描述")
    rule: str = Field(..., description="规则名称")
    severity: str = Field(..., description="严重程度")
    severity_level: Optional[str] = Field(None, description="严重等级")
    fixable: bool = Field(..., description="是否可修复")
    
    class Config:
        schema_extra = {
            "example": {
                "line_no": 1,
                "line_pos": 8,
                "code": "L003",
                "description": "Expected 1 space after 'SELECT' keyword.",
                "rule": "layout",
                "severity": "warning",
                "severity_level": "MINOR",
                "fixable": True
            }
        }


class SQLCheckResponse(BaseModel):
    """SQL检查响应模型"""
    violations: List[Dict[str, Any]] = Field(..., description="违规项列表（相同行号的项目已合并）")
    
    class Config:
        schema_extra = {
            "example": {
                "violations": [
                    {
                        "line_no": 1,
                        "line_pos": "8,12",
                        "code": "L003,L001",
                        "description": "Expected 1 space after 'SELECT' keyword.,Missing whitespace after comma",
                        "rule": "layout.spacing,layout.spacing",
                        "severity_level": "null,null"
                    }
                ]
            }
        }
