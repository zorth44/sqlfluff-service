"""
事件驱动SQL处理任务 - Celery实现

统一的单文件处理模式，基于事件驱动+Celery混合架构。
- 通过Redis事件触发Celery任务
- 保留Celery的企业级特性：重试、监控、并发、可靠性
- 无论是单SQL提交还是ZIP包提交，都被转换为统一的单文件处理事件
"""

import os
import time
from typing import Dict, Any
from celery import current_task
from celery.exceptions import Retry
from app.celery_app.celery_main import celery_app
from app.services.sqlfluff_service import SQLFluffService
from app.services.event_service import EventService
from app.utils.file_utils import FileManager
from app.models.events import SqlCheckCompletedEvent, SqlCheckFailedEvent
from app.core.logging import service_logger


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_sql_check_event(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    统一的SQL文件处理任务 - Celery版本
    
    ✅ Celery企业级特性：
    - 自动重试机制 (max_retries=3)
    - 任务状态跟踪 (bind=True)
    - 异常处理和监控
    - 分布式任务队列
    - 负载均衡和并发控制
    
    处理逻辑：
    1. 从事件获取文件路径
    2. 读取SQL文件内容
    3. 执行SQLFluff分析（支持动态规则配置）
    4. 发布结果事件
    
    无需关心是否来源于批量，Java服务负责结果聚合
    
    Args:
        event_data: 事件数据，包含SQL文件路径和执行配置
        
    Returns:
        Dict[str, Any]: 处理结果摘要
    """
    start_time = time.time()
    payload = event_data['payload']
    job_id = payload['job_id']
    correlation_id = event_data['correlation_id']
    task_id = self.request.id  # Celery任务ID
    
    # 初始化服务
    sqlfluff_service = SQLFluffService()
    event_service = EventService()
    file_manager = FileManager()
    worker_id = f"worker-{os.getenv('HOSTNAME', 'unknown')}-{os.getpid()}"
    
    try:
        # 更新Celery任务状态为处理中
        self.update_state(
            state='PROGRESS',
            meta={
                'job_id': job_id, 
                'status': 'processing',
                'current_step': 'reading_file'
            }
        )
        
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
        
        service_logger.info(f"[Celery] Processing SQL file: {file_name} (job: {job_id}, task: {task_id})")
        
        # 从共享目录读取SQL文件内容
        if not file_manager.file_exists(sql_file_path):
            raise FileNotFoundError(f"SQL文件不存在: {sql_file_path}")
            
        sql_content = file_manager.read_text_file(sql_file_path)
        
        # 更新任务状态
        self.update_state(
            state='PROGRESS',
            meta={
                'job_id': job_id,
                'status': 'analyzing', 
                'current_step': 'sqlfluff_analysis'
            }
        )
        
        # 执行SQLFluff分析（使用动态规则配置）
        result = sqlfluff_service.analyze_sql_content_with_rules(
            sql_content=sql_content,
            file_name=file_name,
            dialect=dialect,
            rules=rules,
            exclude_rules=exclude_rules,
            config_overrides=config_overrides
        )
        
        # 保存结果到NFS（按文件维度）
        result_path = f"results/{job_id}/{file_name}_result.json"
        file_manager.write_json_file(result_path, result)
        
        # 计算处理时间
        duration = int(time.time() - start_time)
        
        # 更新任务状态
        self.update_state(
            state='PROGRESS',
            meta={
                'job_id': job_id,
                'status': 'publishing_result',
                'current_step': 'event_publishing'
            }
        )
        
        # 发布完成事件（不写数据库！包含批量信息供Java服务聚合）
        completed_payload = {
            "job_id": job_id,
            "file_name": file_name,
            "status": "SUCCESS", 
            "result": result,
            "result_file_path": result_path,
            "processing_duration": duration,
            "worker_id": worker_id,
            "celery_task_id": task_id  # Celery任务ID，便于跟踪
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
            worker_id=worker_id,
            result=result,
            result_file_path=result_path,
            duration=duration,
            file_name=file_name,
            batch_id=batch_id,
            file_index=file_index,
            total_files=total_files,
            correlation_id=correlation_id
        )
        
        event_service.publish_event("sql_check_events", completed_event)
        
        service_logger.info(f"[Celery] SQL check completed: {job_id}, file: {file_name}, duration: {duration}s, task: {task_id}")
        
        # 更新Celery任务为成功状态
        self.update_state(
            state='SUCCESS',
            meta={
                'job_id': job_id,
                'file_name': file_name,
                'processing_duration': duration,
                'violations_count': result.get('summary', {}).get('total_violations', 0),
                'result_path': result_path
            }
        )
        
        return {
            'job_id': job_id,
            'file_name': file_name,
            'status': 'SUCCESS',
            'duration': duration,
            'task_id': task_id
        }
        
    except Exception as e:
        service_logger.error(f"[Celery] SQL check failed: {job_id}, error: {e}, task: {task_id}")
        
        # Celery重试机制
        if self.request.retries < self.max_retries:
            service_logger.warning(f"[Celery] Retrying task {task_id}, attempt {self.request.retries + 1}/{self.max_retries}")
            # 使用指数退避重试
            retry_delay = 60 * (2 ** self.request.retries)
            raise self.retry(countdown=retry_delay, exc=e)
        
        # 重试耗尽，发布失败事件
        batch_id = payload.get('batch_id')
        file_index = payload.get('file_index')
        total_files = payload.get('total_files')
        
        failed_event = SqlCheckFailedEvent.create(
            job_id=job_id,
            worker_id=worker_id,
            error={
                "error_code": "PROCESSING_ERROR",
                "error_message": str(e),
                "error_details": str(e.__class__.__name__),
                "task_id": task_id,
                "retries_exhausted": True
            },
            file_name=payload.get('file_name', 'unknown'),
            batch_id=batch_id,
            file_index=file_index,
            total_files=total_files,
            correlation_id=correlation_id
        )
        
        event_service.publish_event("sql_check_events", failed_event)
        
        # 更新Celery任务为失败状态
        self.update_state(
            state='FAILURE',
            meta={
                'job_id': job_id,
                'error': str(e),
                'retries': self.request.retries,
                'task_id': task_id
            }
        )
        
        # 重新抛出异常，让Celery记录失败
        raise


@celery_app.task(bind=True)
def get_task_status(self, task_id: str) -> Dict[str, Any]:
    """
    获取任务状态 - Celery监控接口
    
    Args:
        task_id: Celery任务ID
        
    Returns:
        Dict[str, Any]: 任务状态信息
    """
    try:
        result = celery_app.AsyncResult(task_id)
        return {
            'task_id': task_id,
            'status': result.status,
            'result': result.result,
            'info': result.info,
            'successful': result.successful(),
            'failed': result.failed()
        }
    except Exception as e:
        service_logger.error(f"Error getting task status: {e}")
        return {
            'task_id': task_id,
            'status': 'UNKNOWN',
            'error': str(e)
        }


# 健康检查任务
@celery_app.task
def health_check() -> Dict[str, Any]:
    """Worker健康检查任务"""
    return {
        'status': 'healthy',
        'worker_id': f"worker-{os.getenv('HOSTNAME', 'unknown')}-{os.getpid()}",
        'timestamp': time.time()
    }


service_logger.info("Celery tasks loaded with event-driven architecture") 