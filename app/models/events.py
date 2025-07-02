from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any, List
import uuid

@dataclass
class BaseEvent:
    event_id: str
    event_type: str
    timestamp: str
    correlation_id: str
    payload: Dict[str, Any]
    
    @classmethod
    def create(cls, event_type: str, payload: Dict[str, Any], correlation_id: str = None):
        return cls(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            timestamp=datetime.utcnow().isoformat() + "Z",
            correlation_id=correlation_id or str(uuid.uuid4()),
            payload=payload
        )

# 请求事件 - 统一的单文件处理事件
@dataclass 
class SqlCheckRequestedEvent(BaseEvent):
    @classmethod
    def create(cls, 
               job_id: str, 
               sql_file_path: str, 
               file_name: str,
               dialect: str = "ansi", 
               user_id: str = None,
               product_name: str = None,
               rules: Optional[List[str]] = None,
               exclude_rules: Optional[List[str]] = None,
               config_overrides: Optional[Dict[str, Any]] = None,
               batch_id: str = None,
               file_index: int = None,
               total_files: int = None,
               correlation_id: str = None):
        """
        创建SQL检查请求事件（统一的单文件处理格式）
        
        Args:
            job_id: 任务标识
            sql_file_path: SQL文件在共享目录中的路径
            file_name: 文件名
            dialect: SQL方言
            user_id: 用户ID
            product_name: 产品名称
            rules: 启用的规则列表
            exclude_rules: 排除的规则列表  
            config_overrides: 配置覆盖
            batch_id: 批次标识（仅ZIP来源时存在）
            file_index: 文件在批次中的索引（仅ZIP来源时存在）
            total_files: 批次总文件数（仅ZIP来源时存在）
            correlation_id: 关联ID
        """
        payload = {
            "job_id": job_id,
            "sql_file_path": sql_file_path,
            "file_name": file_name,
            "dialect": dialect
        }
        
        # 添加可选的用户信息
        if user_id:
            payload["user_id"] = user_id
        if product_name:
            payload["product_name"] = product_name
            
        # 添加动态规则配置（可选）
        if rules:
            payload["rules"] = rules
        if exclude_rules:
            payload["exclude_rules"] = exclude_rules
        if config_overrides:
            payload["config_overrides"] = config_overrides
            
        # 添加批量处理相关字段（仅在ZIP来源时存在，用于Java服务结果聚合）
        if batch_id:
            payload["batch_id"] = batch_id
        if file_index is not None:
            payload["file_index"] = file_index
        if total_files is not None:
            payload["total_files"] = total_files
            
        return super().create("SqlCheckRequested", payload, correlation_id)

# 开始处理事件
@dataclass
class SqlCheckStartedEvent(BaseEvent):
    @classmethod
    def create(cls, job_id: str, worker_id: str, file_name: str = None, correlation_id: str = None):
        payload = {
            "job_id": job_id,
            "worker_id": worker_id,
            "estimated_duration": 30
        }
        if file_name:
            payload["file_name"] = file_name
            
        return super().create("SqlCheckStarted", payload, correlation_id)

# 处理完成事件
@dataclass
class SqlCheckCompletedEvent(BaseEvent):
    @classmethod
    def create(cls, 
               job_id: str, 
               worker_id: str, 
               result: Dict[str, Any], 
               result_file_path: str, 
               duration: int, 
               file_name: str = None,
               batch_id: str = None,
               file_index: int = None,
               total_files: int = None,
               correlation_id: str = None):
        """
        创建SQL检查完成事件
        
        包含批量处理信息（如果来源于ZIP），用于Java服务结果聚合
        """
        payload = {
            "job_id": job_id,
            "worker_id": worker_id,
            "status": "SUCCESS",
            "result": result,
            "result_file_path": result_file_path,
            "processing_duration": duration
        }
        
        if file_name:
            payload["file_name"] = file_name
            
        # 如果是批量处理，包含批量信息用于Java服务聚合
        if batch_id:
            payload["batch_id"] = batch_id
        if file_index is not None:
            payload["file_index"] = file_index
        if total_files is not None:
            payload["total_files"] = total_files
            
        return super().create("SqlCheckCompleted", payload, correlation_id)

# 处理失败事件
@dataclass
class SqlCheckFailedEvent(BaseEvent):
    @classmethod
    def create(cls, 
               job_id: str, 
               worker_id: str, 
               error: Dict[str, Any], 
               file_name: str = None,
               batch_id: str = None,
               file_index: int = None,
               total_files: int = None,
               correlation_id: str = None):
        """
        创建SQL检查失败事件
        
        包含批量处理信息（如果来源于ZIP），用于Java服务结果聚合
        """
        payload = {
            "job_id": job_id,
            "worker_id": worker_id,
            "status": "FAILED",
            "error": error
        }
        
        if file_name:
            payload["file_name"] = file_name
            
        # 如果是批量处理，包含批量信息用于Java服务聚合
        if batch_id:
            payload["batch_id"] = batch_id
        if file_index is not None:
            payload["file_index"] = file_index
        if total_files is not None:
            payload["total_files"] = total_files
            
        return super().create("SqlCheckFailed", payload, correlation_id)

# Worker监控事件
@dataclass
class WorkerHeartbeatEvent(BaseEvent):
    @classmethod
    def create(cls, worker_id: str, current_tasks: int, total_processed: int, uptime: int):
        payload = {
            "worker_id": worker_id,
            "current_tasks": current_tasks,
            "total_processed": total_processed,
            "uptime_seconds": uptime,
            "status": "BUSY" if current_tasks > 0 else "IDLE"
        }
        return super().create("WorkerHeartbeat", payload) 