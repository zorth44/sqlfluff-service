"""
Severity Level统计工具

提供违规项按严重等级分类统计的通用函数。
"""

from typing import Dict, List, Any
from app.core.logging import service_logger


def calculate_severity_statistics(violations: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    统计violations列表中各个severity_level的数量
    
    Args:
        violations: 违规项列表，每个违规项应包含 'severity_level' 字段
        
    Returns:
        Dict[str, int]: 各严重等级的统计结果，包含以下键：
            - INFO: INFO级别违规数量
            - MINOR: MINOR级别违规数量
            - MAJOR: MAJOR级别违规数量
            - BLOCKER: BLOCKER级别违规数量
            - CRITICAL: CRITICAL级别违规数量
            - UNKNOWN: 未知或缺失severity_level的违规数量
    
    Note:
        - 如果violation没有severity_level字段或值为None/null，会归类为UNKNOWN
        - 如果severity_level的值不在预定义的等级中，也会归类为UNKNOWN
        - 统计过程中的错误不会抛出异常，而是记录日志并将对应violation归类为UNKNOWN
    """
    # 初始化统计计数器
    statistics = {
        "INFO": 0,
        "MINOR": 0,
        "MAJOR": 0,
        "BLOCKER": 0,
        "CRITICAL": 0,
        "UNKNOWN": 0
    }
    
    # 统计每个violation的severity_level
    for idx, violation in enumerate(violations):
        try:
            severity_level = violation.get('severity_level')
            
            # 处理不同的severity_level值
            if severity_level is None or severity_level == "null":
                statistics["UNKNOWN"] += 1
            elif severity_level in statistics:
                statistics[severity_level] += 1
            else:
                # 对于未知的severity_level值，归类为UNKNOWN
                service_logger.debug(f"未知的severity_level值: {severity_level}，归类为UNKNOWN")
                statistics["UNKNOWN"] += 1
                
        except Exception as e:
            # 单个violation的统计错误不应该影响整体，记录为UNKNOWN
            service_logger.warning(f"统计第{idx}个violation的severity_level时出错: {e}，归类为UNKNOWN")
            statistics["UNKNOWN"] += 1
    
    return statistics


def calculate_severity_statistics_from_result(analysis_result: Dict[str, Any]) -> Dict[str, int]:
    """
    从SQLFluff分析结果中提取violations并统计severity_level
    
    Args:
        analysis_result: SQLFluff分析结果字典，应包含 'violations' 字段
        
    Returns:
        Dict[str, int]: 各严重等级的统计结果
        
    Note:
        如果analysis_result中没有violations字段，返回全部为0的统计结果
    """
    violations = analysis_result.get('violations', [])
    
    if not violations:
        service_logger.debug("analysis_result中没有violations或violations为空")
    
    return calculate_severity_statistics(violations)

