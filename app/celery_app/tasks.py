"""
事件驱动SQL处理任务

统一的单文件处理模式，完全基于事件驱动架构。
无论是单SQL提交还是ZIP包提交，都被转换为统一的单文件处理事件。
"""

import os
import time
from typing import Dict, Any
from app.services.sqlfluff_service import SQLFluffService
from app.services.event_service import EventService
from app.utils.file_utils import FileManager
from app.models.events import SqlCheckCompletedEvent, SqlCheckFailedEvent
from app.core.logging import service_logger

class SqlCheckEventProcessor:
    """SQL检查事件处理器（模拟Celery任务的功能）"""
    
    def __init__(self):
        self.sqlfluff_service = SQLFluffService()
        self.event_service = EventService()
        self.file_manager = FileManager()
        self.logger = service_logger
        self.worker_id = f"worker-{os.getenv('HOSTNAME', 'unknown')}-{os.getpid()}"
        
    def process_sql_check_event(self, event_data: Dict[str, Any]) -> None:
        """
        统一的SQL文件处理任务
        
        处理逻辑：
        1. 从事件获取文件路径
        2. 读取SQL文件内容
        3. 执行SQLFluff分析（支持动态规则配置）
        4. 发布结果事件
        
        无需关心是否来源于批量，Java服务负责结果聚合
        
        Args:
            event_data: 事件数据，包含SQL文件路径和执行配置
        """
        start_time = time.time()
        payload = event_data['payload']
        job_id = payload['job_id']
        correlation_id = event_data['correlation_id']
        
        try:
            # 从事件获取文件路径和配置信息
            sql_file_path = payload['sql_file_path']
            file_name = payload['file_name']
            dialect = payload.get('dialect', 'ansi')
            
            # 动态规则配置（可选）
            rules = payload.get('rules')
            exclude_rules = payload.get('exclude_rules')
            config_overrides = payload.get('config_overrides', {})
            
            # 批量处理信息（仅用于Java服务结果聚合）
            batch_id = payload.get('batch_id')
            file_index = payload.get('file_index')
            total_files = payload.get('total_files')
            
            self.logger.info(f"Processing SQL file: {file_name} (job: {job_id})")
            
            # 从共享目录读取SQL文件内容
            if not self.file_manager.file_exists(sql_file_path):
                raise FileNotFoundError(f"SQL文件不存在: {sql_file_path}")
                
            sql_content = self.file_manager.read_text_file(sql_file_path)
            
            # 执行SQLFluff分析（使用动态规则配置）
            result = self.sqlfluff_service.analyze_sql_content_with_rules(
                sql_content=sql_content,
                file_name=file_name,
                dialect=dialect,
                rules=rules,
                exclude_rules=exclude_rules,
                config_overrides=config_overrides
            )
            
            # 保存结果到NFS（按文件维度）
            result_path = f"results/{job_id}/{file_name}_result.json"
            self.file_manager.write_json_file(result_path, result)
            
            # 计算处理时间
            duration = int(time.time() - start_time)
            
            # 发布完成事件（不写数据库！包含批量信息供Java服务聚合）
            completed_payload = {
                "job_id": job_id,
                "file_name": file_name,
                "status": "SUCCESS", 
                "result": result,
                "result_file_path": result_path,
                "processing_duration": duration,
                "worker_id": self.worker_id
            }
            
            # 如果是批量处理，包含批量信息
            if batch_id:
                completed_payload.update({
                    "batch_id": batch_id,
                    "file_index": file_index,
                    "total_files": total_files
                })
            
            completed_event = SqlCheckCompletedEvent.create(
                job_id=job_id,
                worker_id=self.worker_id,
                result=result,
                result_file_path=result_path,
                duration=duration,
                file_name=file_name,
                batch_id=batch_id,
                file_index=file_index,
                total_files=total_files,
                correlation_id=correlation_id
            )
            
            self.event_service.publish_event("sql_check_events", completed_event)
            
            self.logger.info(f"SQL check completed: {job_id}, file: {file_name}, duration: {duration}s")
            
        except Exception as e:
            self.logger.error(f"SQL check failed: {job_id}, error: {e}")
            
            # 获取批量信息（用于失败事件聚合）
            batch_id = payload.get('batch_id')
            file_index = payload.get('file_index')
            total_files = payload.get('total_files')
            
            # 发布失败事件
            failed_payload = {
                "job_id": job_id,
                "file_name": payload.get('file_name', 'unknown'),
                "status": "FAILED",
                "error": {
                    "error_code": "PROCESSING_ERROR",
                    "error_message": str(e),
                    "error_details": str(e.__class__.__name__)
                },
                "worker_id": self.worker_id
            }
            
            # 如果是批量处理，包含批量信息
            if batch_id:
                failed_payload.update({
                    "batch_id": batch_id,
                    "file_index": file_index,
                    "total_files": total_files
                })
                
            failed_event = SqlCheckFailedEvent.create(
                job_id=job_id,
                worker_id=self.worker_id,
                error=failed_payload["error"],
                file_name=payload.get('file_name', 'unknown'),
                batch_id=batch_id,
                file_index=file_index,
                total_files=total_files,
                correlation_id=correlation_id
            )
            
            self.event_service.publish_event("sql_check_events", failed_event)
            
            # 重新抛出异常，让事件处理器决定是否重试
            raise

# 全局处理器实例
sql_processor = SqlCheckEventProcessor()

def process_sql_check_event(event_data: Dict[str, Any]) -> None:
    """
    全局函数接口，供事件监听器调用
    
    这个函数替代了原来的Celery任务，提供相同的功能但基于事件驱动
    """
    return sql_processor.process_sql_check_event(event_data)

# 保留的警告信息
service_logger.info("Event-driven SQL processing tasks loaded. Celery tasks are deprecated.") 