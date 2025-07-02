"""
SQL检查事件处理器

负责处理SQL检查请求事件，执行SQLFluff分析并发布结果事件。
完全基于事件驱动架构，无需数据库依赖。
"""

import os
import time
from datetime import datetime
from app.services.sqlfluff_service import SQLFluffService
from app.services.event_service import EventService
from app.utils.file_utils import FileManager
from app.models.events import (
    SqlCheckCompletedEvent, SqlCheckFailedEvent
)
from app.core.logging import service_logger

class SqlCheckHandler:
    def __init__(self):
        self.sqlfluff_service = SQLFluffService()
        self.event_service = EventService()
        self.file_manager = FileManager()
        self.logger = service_logger
        self.worker_id = f"worker-{os.getenv('HOSTNAME', 'unknown')}-{os.getpid()}"
        
    def handle_sql_check_requested(self, event_data):
        """
        处理SQL检查请求事件（统一的单文件处理）
        
        处理逻辑：
        1. 从事件获取文件路径和配置信息
        2. 从共享目录读取SQL文件内容
        3. 执行SQLFluff分析（支持动态规则配置）
        4. 保存结果到NFS
        5. 发布结果事件（包含批量信息用于Java服务聚合）
        """
        start_time = time.time()
        payload = event_data['payload']
        job_id = payload['job_id']
        correlation_id = event_data.get('correlation_id', 'unknown')
        file_name = payload['file_name']
        
        try:
            self.logger.info(f"Processing SQL check request: {job_id}, file: {file_name}")
            
            # 从事件获取所有必要信息
            sql_file_path = payload['sql_file_path']
            dialect = payload.get('dialect', 'ansi')
            
            # 动态规则配置（可选）
            rules = payload.get('rules')
            exclude_rules = payload.get('exclude_rules')  
            config_overrides = payload.get('config_overrides', {})
            
            # 批量处理信息（用于结果聚合）
            batch_id = payload.get('batch_id')
            file_index = payload.get('file_index')
            total_files = payload.get('total_files')
            
            # 从共享目录读取SQL文件内容
            self.logger.debug(f"Reading SQL file: {sql_file_path}")
            if not self.file_manager.file_exists(sql_file_path):
                raise FileNotFoundError(f"SQL文件不存在: {sql_file_path}")
                
            sql_content = self.file_manager.read_text_file(sql_file_path)
            
            # 执行SQL分析（使用动态规则配置）
            self.logger.info(f"Analyzing SQL with dialect: {dialect}, rules: {rules}, exclude: {exclude_rules}")
            analysis_result = self.sqlfluff_service.analyze_sql_content_with_rules(
                sql_content=sql_content,
                file_name=file_name,
                dialect=dialect,
                rules=rules,
                exclude_rules=exclude_rules,
                config_overrides=config_overrides
            )
            
            # 保存结果到NFS（按文件维度）
            result_path = f"results/{job_id}/{file_name}_result.json"
            self.file_manager.write_json_file(result_path, analysis_result)
            
            # 计算处理时间
            duration = time.time() - start_time
            
            # 发布完成事件（包含批量信息用于Java服务聚合）
            completed_event = SqlCheckCompletedEvent.create(
                job_id=job_id,
                file_name=file_name,
                status="SUCCESS",
                result=analysis_result,
                result_file_path=result_path,
                processing_duration=duration,
                worker_id=self.worker_id,
                batch_id=batch_id,
                file_index=file_index,
                total_files=total_files
            )
            self.event_service.publish_event("sql_check_events", completed_event)
            
            self.logger.info(f"SQL check completed: {job_id}, file: {file_name}, duration: {duration:.2f}s")
            
        except Exception as e:
            self.logger.error(f"SQL check failed: {job_id}, file: {file_name}, error: {e}")
            
            # 获取批量信息（用于失败事件聚合）
            batch_id = payload.get('batch_id')
            file_index = payload.get('file_index')
            total_files = payload.get('total_files')
            
            # 发布失败事件（包含批量信息用于Java服务聚合）
            failed_event = SqlCheckFailedEvent.create(
                job_id=job_id,
                file_name=file_name,
                error={
                    "error_code": "PROCESSING_ERROR",
                    "error_message": str(e),
                    "error_details": str(e.__class__.__name__)
                },
                worker_id=self.worker_id,
                batch_id=batch_id,
                file_index=file_index,
                total_files=total_files
            )
            self.event_service.publish_event("sql_check_events", failed_event)
            
            # 重新抛出异常，让上层处理重试逻辑
            raise

    def listen_sql_check_events(self):
        """
        监听SQL检查事件
        
        从Redis订阅SQL检查请求事件，并处理
        """
        try:
            self.logger.info("🎧 Starting SQL check event listener...")
            self.logger.info("📡 Listening on Redis channel: sql_check_requests")
            
            # 订阅Redis事件
            pubsub = self.event_service.redis_client.pubsub()
            pubsub.subscribe(['sql_check_requests'])
            
            for message in pubsub.listen():
                if message['type'] == 'message':
                    try:
                        import json
                        event_data = json.loads(message['data'])
                        
                        if event_data.get('event_type') == 'SqlCheckRequested':
                            self.handle_sql_check_requested(event_data)
                        else:
                            self.logger.warning(f"Unknown event type: {event_data.get('event_type')}")
                            
                    except json.JSONDecodeError as e:
                        self.logger.error(f"Failed to parse event data: {e}")
                    except Exception as e:
                        self.logger.error(f"Error processing event: {e}")
                        
        except Exception as e:
            self.logger.error(f"Event listener error: {e}")
            raise 