"""
SQL检查API路由

实现SQL实时检查功能的HTTP接口。
"""

from fastapi import APIRouter, HTTPException, status
from typing import Optional, List, Dict, Any
from collections import defaultdict

from app.schemas.sql import SQLCheckRequest, SQLCheckResponse, SQLViolation
from app.services.sqlfluff_service import SQLFluffService
from app.config.settings import get_settings
from app.core.exceptions import SQLFluffException
from app.core.logging import api_logger

router = APIRouter()
settings = get_settings()


def get_rules_for_dialect(dialect: str) -> Optional[List[str]]:
    """
    根据方言获取对应的规则列表
    
    Args:
        dialect: SQL方言 (hive 或 gbase8a)
        
    Returns:
        Optional[List[str]]: 规则列表，如果环境变量为空则返回None使用默认规则
    """
    if dialect == "hive":
        rules_str = settings.HIVE_RULES
    elif dialect == "gbase8a":
        rules_str = settings.GBASE8A_RULES
    else:
        return None
    
    # 如果环境变量为空，返回None使用默认规则
    if not rules_str or not rules_str.strip():
        return None
    
    # 解析逗号分隔的规则字符串
    rules = [rule.strip() for rule in rules_str.split(",") if rule.strip()]
    return rules if rules else None


def merge_violations_by_line(violations: List[SQLViolation]) -> List[Dict[str, Any]]:
    """
    将相同line_no的违规项合并成一个项目
    
    Args:
        violations: 原始违规项列表
        
    Returns:
        List[Dict[str, Any]]: 合并后的违规项列表，相同line_no的项目会被合并
    """
    if not violations:
        return []
    
    # 按line_no分组
    grouped_violations = defaultdict(list)
    for violation in violations:
        grouped_violations[violation.line_no].append(violation)
    
    # 合并每组违规项
    merged_results = []
    for line_no, violation_group in grouped_violations.items():
        # 提取各字段的值
        line_pos_values = []
        code_values = []
        description_values = []
        rule_values = []
        severity_level_values = []
        
        for violation in violation_group:
            line_pos_values.append(str(violation.line_pos))
            code_values.append(violation.code)
            description_values.append(violation.description)
            rule_values.append(violation.rule)
            # 处理None值
            severity_level_str = str(violation.severity_level) if violation.severity_level is not None else "null"
            severity_level_values.append(severity_level_str)
        
        # 合并成字符串，用逗号分隔
        merged_violation = {
            "line_no": line_no,
            "line_pos": ",".join(line_pos_values),
            "code": ",".join(code_values),
            "description": ",".join(description_values),
            "rule": ",".join(rule_values),
            "severity_level": ",".join(severity_level_values)
        }
        
        merged_results.append(merged_violation)
    
    # 按line_no排序
    merged_results.sort(key=lambda x: x["line_no"])
    
    return merged_results


@router.post("/check", response_model=SQLCheckResponse, status_code=status.HTTP_200_OK)
async def check_sql(request: SQLCheckRequest):
    """
    检查SQL语法和规范
    
    对提供的SQL内容进行实时检查，返回违规项列表。
    支持hive和gbase8a两种方言，规则通过环境变量配置。
    
    Args:
        request: SQL检查请求，包含SQL内容和方言
        
    Returns:
        SQLCheckResponse: 检查结果，包含违规项列表
        
    Raises:
        HTTPException: 
            - 400: 请求参数无效
            - 500: 服务内部错误
    """
    try:
        api_logger.info(f"SQL检查请求: dialect={request.dialect}, sql_length={len(request.sql_content)}")
        
        # 获取对应方言的规则
        rules = get_rules_for_dialect(request.dialect.value)
        api_logger.debug(f"使用规则: {rules}")
        
        # 创建SQLFluff服务实例
        sqlfluff_service = SQLFluffService()
        
        # 执行SQL内容分析
        result = sqlfluff_service.analyze_sql_content(
            sql_content=request.sql_content,
            file_name="query.sql",  # 固定文件名
            dialect=request.dialect.value,
            rules=rules,
            db_session=None  # 不需要数据库会话
        )
        
        # 提取violations部分
        violations_data = result.get("violations", [])
        
        # 转换为响应模型
        violations = []
        for violation_data in violations_data:
            try:
                violation = SQLViolation(
                    line_no=violation_data.get("line_no", 0),
                    line_pos=violation_data.get("line_pos", 0),
                    code=violation_data.get("code", "UNKNOWN"),
                    description=violation_data.get("description", ""),
                    rule=violation_data.get("rule", "unknown"),
                    severity=violation_data.get("severity", "warning"),
                    severity_level=violation_data.get("severity_level", None),
                    fixable=violation_data.get("fixable", False)
                )
                violations.append(violation)
            except Exception as e:
                api_logger.warning(f"转换违规项失败: {violation_data}, 错误: {e}")
                # 创建一个基础的违规项
                violations.append(SQLViolation(
                    line_no=0,
                    line_pos=0,
                    code="CONVERSION_ERROR",
                    description=f"违规项转换失败: {str(e)}",
                    rule="system",
                    severity="warning",
                    severity_level=None,
                    fixable=False
                ))
        
        api_logger.info(f"SQL检查完成: 发现 {len(violations)} 个违规项")
        
        # 合并相同line_no的违规项
        merged_violations = merge_violations_by_line(violations)
        api_logger.info(f"合并后剩余 {len(merged_violations)} 个违规项")
        
        return SQLCheckResponse(violations=merged_violations)
        
    except SQLFluffException as e:
        api_logger.error(f"SQLFluff分析失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"SQL分析失败: {str(e)}"
        )
    except Exception as e:
        api_logger.error(f"SQL检查接口异常: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"服务内部错误: {str(e)}"
        )
