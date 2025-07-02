"""
事件驱动Worker服务启动入口

Worker完全脱离数据库依赖，通过Redis事件进行通信。
基于统一的单文件处理模式，支持动态规则配置。

负责：
- 订阅SQL检查请求事件
- 执行SQLFluff分析（支持动态规则）
- 发布处理结果事件
- 发布Worker状态监控事件
"""

import signal
import sys
import threading
import time
from app.celery_app import event_listener
from app.event_handlers.monitoring_handler import MonitoringHandler
from app.core.logging import setup_logging, service_logger

class EventDrivenWorker:
    """事件驱动Worker服务"""
    
    def __init__(self):
        self.event_listener = event_listener
        self.monitoring = MonitoringHandler()
        self.running = False
        self.monitoring_thread = None
        
    def start(self):
        """启动Worker"""
        self.running = True
        service_logger.info("Starting Event-Driven SQL Processing Worker...")
        
        # 启动监控心跳（在独立线程中运行）
        self.monitoring_thread = threading.Thread(target=self._start_monitoring)
        self.monitoring_thread.start()
        
        # 设置信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        try:
            # 启动事件监听（这将阻塞主线程）
            self.event_listener.listen_events()
        except KeyboardInterrupt:
            service_logger.info("Received interrupt signal")
        finally:
            self.stop()
    
    def stop(self):
        """停止Worker"""
        if not self.running:
            return
            
        service_logger.info("Stopping Event-Driven Worker...")
        self.running = False
        
        # 停止监控
        if self.monitoring:
            self.monitoring.stop_heartbeat()
        
        # 等待监控线程结束
        if self.monitoring_thread and self.monitoring_thread.is_alive():
            self.monitoring_thread.join(timeout=5)
            
    def _start_monitoring(self):
        """在独立线程中启动监控"""
        try:
            self.monitoring.start_heartbeat()
            
            # 保持监控线程运行
            while self.running:
                time.sleep(1)
                
        except Exception as e:
            service_logger.error(f"Monitoring thread error: {e}")
    
    def _signal_handler(self, signum, frame):
        """信号处理器"""
        service_logger.info(f"Received signal {signum}")
        self.stop()
        sys.exit(0)

def main():
    """Worker主启动函数"""
    setup_logging()
    
    service_logger.info("=" * 60)
    service_logger.info("SQLFluff Event-Driven Worker Starting")
    service_logger.info("Architecture: Event-Driven (No Database Dependencies)")
    service_logger.info("Processing Mode: Unified Single-File Processing")
    service_logger.info("Features: Dynamic Rules Configuration")
    service_logger.info("=" * 60)
    
    worker = EventDrivenWorker()
    worker.start()


# 保持向后兼容的函数（暂时保留）
def create_celery_app():
    """创建Celery应用实例（已废弃，保留兼容性）"""
    service_logger.warning("create_celery_app() is deprecated - Worker is now event-driven")
    return None


if __name__ == "__main__":
    main() 