"""
事件数据模型

定义系统中使用的事件结构。
"""

import json
from datetime import datetime
from typing import Dict, Any, Optional, List

class BaseEvent:
    """基础事件类"""
    
    def __init__(self, event_type: str, payload: Dict[str, Any]):
        self.event_id = f"evt-{datetime.now().timestamp()}"
        self.event_type = event_type
        self.timestamp = datetime.now().isoformat()
        self.payload = payload
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "payload": self.payload
        }
    
    def to_json(self) -> str:
        """转换为JSON字符串"""
        return json.dumps(self.to_dict())
    
    @classmethod
    def create(cls, event_type: str, **kwargs) -> 'BaseEvent':
        """创建事件实例"""
        return cls(event_type, kwargs)

class SqlCheckRequestedEvent(BaseEvent):
    """SQL检查请求事件"""
    
    @classmethod
    def create(cls, job_id: str, sql_file_path: str, file_name: str, 
              dialect: str = "ansi", user_id: Optional[str] = None,
              product_name: Optional[str] = None, batch_id: Optional[str] = None,
              file_index: Optional[int] = None, total_files: Optional[int] = None,
              rules: Optional[List[str]] = None, exclude_rules: Optional[List[str]] = None,
              config_overrides: Optional[Dict[str, Any]] = None) -> 'BaseEvent':
        """
        创建SQL检查请求事件
        
        Args:
            job_id: 任务ID
            sql_file_path: SQL文件路径（在共享存储中）
            file_name: 文件名
            dialect: SQL方言
            user_id: 用户ID
            product_name: 产品名称
            batch_id: 批次ID（仅ZIP来源）
            file_index: 文件索引（仅ZIP来源）
            total_files: 总文件数（仅ZIP来源）
            rules: 启用的规则列表
            exclude_rules: 排除的规则列表
            config_overrides: 配置覆盖
        """
        payload = {
            "job_id": job_id,
            "sql_file_path": sql_file_path,
            "file_name": file_name,
            "dialect": dialect
        }
        
        # 添加可选字段
        if user_id:
            payload["user_id"] = user_id
        if product_name:
            payload["product_name"] = product_name
        if batch_id:
            payload["batch_id"] = batch_id
        if file_index is not None:
            payload["file_index"] = file_index
        if total_files is not None:
            payload["total_files"] = total_files
        if rules:
            payload["rules"] = rules
        if exclude_rules:
            payload["exclude_rules"] = exclude_rules
        if config_overrides:
            payload["config_overrides"] = config_overrides
            
        return super().create("SqlCheckRequested", **payload)

class SqlCheckCompletedEvent(BaseEvent):
    """SQL检查完成事件"""
    
    @classmethod
    def create(cls, job_id: str, file_name: str, status: str, result: Dict[str, Any],
              result_file_path: str, processing_duration: float, worker_id: str,
              batch_id: Optional[str] = None, file_index: Optional[int] = None,
              total_files: Optional[int] = None) -> 'BaseEvent':
        """
        创建SQL检查完成事件
        
        Args:
            job_id: 任务ID
            file_name: 文件名
            status: 处理状态
            result: 分析结果
            result_file_path: 结果文件路径
            processing_duration: 处理耗时
            worker_id: Worker ID
            batch_id: 批次ID（仅ZIP来源）
            file_index: 文件索引（仅ZIP来源）
            total_files: 总文件数（仅ZIP来源）
        """
        payload = {
            "job_id": job_id,
            "file_name": file_name,
            "status": status,
            "result": result,
            "result_file_path": result_file_path,
            "processing_duration": processing_duration,
            "worker_id": worker_id
        }
        
        # 添加批次信息
        if batch_id:
            payload["batch_id"] = batch_id
        if file_index is not None:
            payload["file_index"] = file_index
        if total_files is not None:
            payload["total_files"] = total_files
            
        return super().create("SqlCheckCompleted", **payload)

class SqlCheckFailedEvent(BaseEvent):
    """SQL检查失败事件"""
    
    @classmethod
    def create(cls, job_id: str, file_name: str, error: Dict[str, str], 
              worker_id: str, batch_id: Optional[str] = None,
              file_index: Optional[int] = None, total_files: Optional[int] = None) -> 'BaseEvent':
        """
        创建SQL检查失败事件
        
        Args:
            job_id: 任务ID
            file_name: 文件名
            error: 错误信息
            worker_id: Worker ID
            batch_id: 批次ID（仅ZIP来源）
            file_index: 文件索引（仅ZIP来源）
            total_files: 总文件数（仅ZIP来源）
        """
        payload = {
            "job_id": job_id,
            "file_name": file_name,
            "status": "FAILED",
            "error": error,
            "worker_id": worker_id
        }
        
        # 添加批次信息
        if batch_id:
            payload["batch_id"] = batch_id
        if file_index is not None:
            payload["file_index"] = file_index
        if total_files is not None:
            payload["total_files"] = total_files
            
        return super().create("SqlCheckFailed", **payload) 