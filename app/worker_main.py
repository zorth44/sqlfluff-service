"""
SQLFluff Worker主程序

统一事件驱动架构的Worker实现：
- 事件监听：监听Redis事件
- 任务处理：使用Celery执行SQLFluff分析
- 监控能力：通过Flower监控面板实时查看状态
- 企业级特性：支持可靠性、并发、监控等
"""

import signal
import sys
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from app.config.settings import Settings
from app.core.logging import service_logger
from app.event_handlers.sql_check_handler import SqlCheckHandler

# 获取配置
settings = Settings()

class SQLFluffWorker:
    """SQLFluff Worker主类"""
    
    def __init__(self):
        self.logger = service_logger
        self.sql_check_handler = SqlCheckHandler()
        self.running = False
        self.thread_pool = None
        
        # 生成Worker ID
        self.worker_id = f"worker-{os.getenv('HOSTNAME', 'unknown')}-{os.getpid()}"
        
        # 设置信号处理
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
    
    def start(self):
        """启动Worker"""
        try:
            self.logger.info("🚀 Starting SQLFluff Worker...")
            self.logger.info(f"Worker ID: {self.worker_id}")
            self.logger.info(f"Redis URL: {settings.CELERY_BROKER_URL}")
            self.logger.info(f"Max concurrent tasks: {settings.MAX_CONCURRENT_TASKS}")
            self.logger.info("📊 Monitor via Flower: http://localhost:5555")
            
            # 初始化线程池
            self.thread_pool = ThreadPoolExecutor(
                max_workers=settings.MAX_CONCURRENT_TASKS,
                thread_name_prefix="sql-worker"
            )
            
            self.running = True
            
            # 启动事件监听
            self.logger.info("📡 Starting event listeners...")
            self._start_event_listeners()
            
            self.logger.info("✅ SQLFluff Worker started successfully")
            
            # 保持运行状态
            self._keep_alive()
            
        except Exception as e:
            self.logger.error(f"❌ Failed to start Worker: {e}")
            sys.exit(1)
    
    def stop(self):
        """停止Worker"""
        if not self.running:
            return
            
        self.logger.info("🛑 Stopping SQLFluff Worker...")
        self.running = False
        
        try:
            # 停止线程池
            if self.thread_pool:
                self.logger.info("Shutting down thread pool...")
                self.thread_pool.shutdown(wait=True, timeout=30)
            
            self.logger.info("✅ SQLFluff Worker stopped gracefully")
            
        except Exception as e:
            self.logger.error(f"Error during worker shutdown: {e}")
    
    def _signal_handler(self, signum, frame):
        """信号处理器"""
        self.logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.stop()
        sys.exit(0)
    
    def _start_event_listeners(self):
        """启动事件监听器"""
        try:
            # 启动SQL检查事件监听
            listener_thread = threading.Thread(
                target=self.sql_check_handler.listen_sql_check_events,
                name="sql-check-listener"
            )
            listener_thread.daemon = True
            listener_thread.start()
            
            self.logger.info("Event listeners started")
            
        except Exception as e:
            self.logger.error(f"Failed to start event listeners: {e}")
            raise
    
    def _keep_alive(self):
        """保持Worker运行"""
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.logger.info("Received keyboard interrupt")
            self.stop()

def main():
    """主函数"""
    
    # 创建Worker实例并启动
    worker = SQLFluffWorker()
    worker.start()

if __name__ == "__main__":
    main() 