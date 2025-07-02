"""
监控事件发布器

负责发布Worker生命周期和状态监控事件，包括启动、心跳、关闭等。
"""

import os
import time
import threading
import json
from app.services.event_service import EventService
from app.models.events import WorkerHeartbeatEvent
from app.core.logging import service_logger

class MonitoringHandler:
    def __init__(self):
        self.event_service = EventService()
        self.logger = service_logger
        self.worker_id = f"worker-{os.getenv('HOSTNAME', 'unknown')}-{os.getpid()}"
        self.start_time = time.time()
        self.current_tasks = 0
        self.total_processed = 0
        self.heartbeat_thread = None
        self.running = False
    
    def start_heartbeat(self):
        """启动心跳发布"""
        if self.running:
            return
            
        self.running = True
        self.heartbeat_thread = threading.Thread(target=self._heartbeat_loop)
        self.heartbeat_thread.daemon = True
        self.heartbeat_thread.start()
        
        # 发布Worker启动事件
        self._publish_worker_started()
    
    def stop_heartbeat(self):
        """停止心跳发布"""
        self.running = False
        if self.heartbeat_thread:
            self.heartbeat_thread.join(timeout=5)
    
    def increment_current_tasks(self):
        """增加当前任务数"""
        self.current_tasks += 1
    
    def decrement_current_tasks(self):
        """减少当前任务数"""
        self.current_tasks = max(0, self.current_tasks - 1)
        self.total_processed += 1
    
    def _publish_worker_started(self):
        """发布Worker启动事件"""
        try:
            event_data = {
                "event_type": "WorkerStarted",
                "worker_id": self.worker_id,
                "hostname": os.getenv('HOSTNAME', 'unknown'),
                "pid": os.getpid(),
                "started_at": time.time(),
                "max_concurrent": 4
            }
            
            self.event_service.redis_client.publish(
                "worker_monitoring", 
                json.dumps(event_data)
            )
            self.logger.info(f"Worker started: {self.worker_id}")
            
        except Exception as e:
            self.logger.error(f"Failed to publish worker started event: {e}")
    
    def _heartbeat_loop(self):
        """心跳循环"""
        while self.running:
            try:
                uptime = int(time.time() - self.start_time)
                
                heartbeat_event = WorkerHeartbeatEvent.create(
                    worker_id=self.worker_id,
                    current_tasks=self.current_tasks,
                    total_processed=self.total_processed,
                    uptime=uptime
                )
                
                self.event_service.publish_event("worker_monitoring", heartbeat_event)
                
                # 每30秒发送一次心跳
                time.sleep(30)
                
            except Exception as e:
                self.logger.error(f"Error in heartbeat: {e}")
                time.sleep(30) 