"""
Violation相关API数据模型

定义与违规项(Violation)相关的Pydantic数据模型。
包括违规项详情、统计响应等模型定义。
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class ViolationResponse(BaseModel):
    """违规项响应模型"""
    id: int = Field(description="违规项ID")
    task_id: str = Field(description="关联的任务ID")
    job_id: str = Field(description="关联的工作ID")
    rule_code: str = Field(description="规则编号")
    rule_name: Optional[str] = Field(default=None, description="规则名称")
    severity: Optional[str] = Field(default=None, description="SQLFluff原始严重度")
    severity_level: Optional[str] = Field(default=None, description="规则分级")
    line_no: Optional[int] = Field(default=None, description="问题所在行号")
    line_pos: Optional[int] = Field(default=None, description="问题所在列号")
    description: Optional[str] = Field(default=None, description="问题描述")
    sql_line: Optional[str] = Field(default=None, description="问题所在的SQL代码行")
    fixable: bool = Field(default=False, description="是否可自动修复")
    created_at: datetime = Field(description="创建时间")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
        schema_extra = {
            "example": {
                "id": 12345,
                "task_id": "task-e0e1f2e3-4f5f-6a6b-7c7d-8e8f9a9b0c0d",
                "job_id": "job-d8b8a7e0-4f7f-4f7b-8f1e-8e6a1e8e6a1e",
                "rule_code": "RF02",
                "rule_name": "references.qualification",
                "severity": "warning",
                "severity_level": "MAJOR",
                "line_no": 8,
                "line_pos": 8,
                "description": "Unqualified reference 'product5' found in select with more than one referenced table/view.",
                "sql_line": "SELECT product5.name, category.name FROM products product5",
                "fixable": False,
                "created_at": "2025-10-21T10:30:15.654321"
            }
        }


class ViolationSimple(BaseModel):
    """简化的违规项模型（用于嵌套在Task响应中）"""
    rule_code: str = Field(description="规则编号")
    rule_name: Optional[str] = Field(default=None, description="规则名称")
    severity_level: Optional[str] = Field(default=None, description="规则分级")
    line_no: Optional[int] = Field(default=None, description="问题所在行号")
    line_pos: Optional[int] = Field(default=None, description="问题所在列号")
    description: Optional[str] = Field(default=None, description="问题描述")
    sql_line: Optional[str] = Field(default=None, description="问题所在的SQL代码行")
    fixable: bool = Field(default=False, description="是否可自动修复")
    
    class Config:
        schema_extra = {
            "example": {
                "rule_code": "RF02",
                "rule_name": "references.qualification",
                "severity_level": "MAJOR",
                "line_no": 8,
                "line_pos": 8,
                "description": "Unqualified reference found",
                "sql_line": "SELECT product5.name",
                "fixable": False
            }
        }


class TaskWithViolations(BaseModel):
    """带违规项的任务模型（用于CSV导出和批量查询）"""
    task_id: str = Field(description="任务ID")
    source_file_path: str = Field(description="源文件路径")
    file_name: str = Field(description="文件名")
    sql_lines: Optional[int] = Field(default=None, description="SQL文件行数")
    total_violations: Optional[int] = Field(default=None, description="违规项总数")
    violations: List[ViolationSimple] = Field(description="违规项列表")
    
    class Config:
        schema_extra = {
            "example": {
                "task_id": "task-e0e1f2e3-4f5f-6a6b-7c7d-8e8f9a9b0c0d",
                "source_file_path": "jobs/job-xxx/file1.sql",
                "file_name": "file1.sql",
                "sql_lines": 120,
                "total_violations": 5,
                "violations": [
                    {
                        "rule_code": "RF02",
                        "severity_level": "MAJOR",
                        "line_no": 8,
                        "description": "Unqualified reference found"
                    }
                ]
            }
        }


class JobViolationsResponse(BaseModel):
    """Job维度的违规项响应（用于CSV生成）"""
    job_id: str = Field(description="工作ID")
    total_tasks: int = Field(description="任务总数")
    total_violations: int = Field(description="违规项总数")
    tasks: List[TaskWithViolations] = Field(description="任务列表（包含违规项）")
    
    class Config:
        schema_extra = {
            "example": {
                "job_id": "job-d8b8a7e0-4f7f-4f7b-8f1e-8e6a1e8e6a1e",
                "total_tasks": 10,
                "total_violations": 45,
                "tasks": [
                    {
                        "task_id": "task-xxx",
                        "source_file_path": "jobs/job-xxx/file1.sql",
                        "file_name": "file1.sql",
                        "sql_lines": 120,
                        "total_violations": 5,
                        "violations": []
                    }
                ]
            }
        }


class RuleStatistics(BaseModel):
    """规则统计模型"""
    rule_code: str = Field(description="规则编号")
    rule_name: Optional[str] = Field(default=None, description="规则名称")
    severity_level: Optional[str] = Field(default=None, description="规则分级")
    count: int = Field(description="触发次数")
    affected_files: int = Field(description="影响的文件数")
    
    class Config:
        schema_extra = {
            "example": {
                "rule_code": "RF02",
                "rule_name": "references.qualification",
                "severity_level": "MAJOR",
                "count": 150,
                "affected_files": 25
            }
        }


class SeverityStatistics(BaseModel):
    """严重级别统计模型"""
    severity_level: str = Field(description="严重级别")
    count: int = Field(description="违规项数量")
    percentage: float = Field(description="占比（百分比）")
    
    class Config:
        schema_extra = {
            "example": {
                "severity_level": "MAJOR",
                "count": 150,
                "percentage": 35.5
            }
        }


class JobStatisticsResponse(BaseModel):
    """Job统计响应模型"""
    job_id: str = Field(description="工作ID")
    total_violations: int = Field(description="违规项总数")
    total_files: int = Field(description="文件总数")
    files_with_violations: int = Field(description="有违规项的文件数")
    
    # 严重级别分布
    severity_distribution: List[SeverityStatistics] = Field(description="严重级别分布")
    
    # 规则热度 TOP 20
    top_rules: List[RuleStatistics] = Field(description="规则触发次数 TOP 20")
    
    class Config:
        schema_extra = {
            "example": {
                "job_id": "job-d8b8a7e0-4f7f-4f7b-8f1e-8e6a1e8e6a1e",
                "total_violations": 450,
                "total_files": 100,
                "files_with_violations": 80,
                "severity_distribution": [
                    {
                        "severity_level": "MAJOR",
                        "count": 150,
                        "percentage": 33.3
                    }
                ],
                "top_rules": [
                    {
                        "rule_code": "RF02",
                        "rule_name": "references.qualification",
                        "severity_level": "MAJOR",
                        "count": 50,
                        "affected_files": 20
                    }
                ]
            }
        }


class ViolationQueryParams(BaseModel):
    """违规项查询参数"""
    severity_level: Optional[str] = Field(default=None, description="过滤严重级别")
    rule_code: Optional[str] = Field(default=None, description="过滤规则编号")
    file_name_pattern: Optional[str] = Field(default=None, description="文件名模式")
    
    class Config:
        schema_extra = {
            "example": {
                "severity_level": "BLOCKER,CRITICAL",
                "rule_code": "RF02,L032",
                "file_name_pattern": "*.sql"
            }
        }

