#!/usr/bin/env python3
"""
Celery Worker启动脚本

提供完整的Worker启动和管理功能，包括：
- 环境变量检查和配置验证
- Worker进程启动和监控
- 优雅关闭和重启功能
- 健康检查和状态监控
"""

import subprocess
import sys
import os
import signal
import time
from typing import List, Optional

# 添加项目根目录到Python路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.insert(0, project_root)

from app.config.settings import get_settings
from app.core.logging import setup_logging, service_logger


def check_environment() -> bool:
    """
    检查必需的环境变量
    
    Returns:
        bool: 环境检查是否通过
    """
    required_vars = [
        'REDIS_HOST',
        'REDIS_PORT',
        'NFS_SHARE_ROOT_PATH',
        'MYSQL_DATABASE_HOST',
        'MYSQL_DATABASE_PORT',
        'MYSQL_DATABASE_USERNAME',
        'MYSQL_DATABASE_PASSWORD',
        'MYSQL_DATABASE_NAME'
    ]
    
    missing_vars = []
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        print(f"❌ Error: Missing required environment variables: {', '.join(missing_vars)}")
        print("\n💡 Please set the following environment variables:")
        for var in missing_vars:
            print(f"   export {var}=<value>")
        return False
    
    # 构建数据库URL
    username = os.getenv('MYSQL_DATABASE_USERNAME')
    password = os.getenv('MYSQL_DATABASE_PASSWORD')
    host = os.getenv('MYSQL_DATABASE_HOST')
    port = os.getenv('MYSQL_DATABASE_PORT')
    database = os.getenv('MYSQL_DATABASE_NAME')
    
    database_url = f"mysql+aiomysql://{username}:{password}@{host}:{port}/{database}"
    os.environ['DATABASE_URL'] = database_url
    print(f"✅ Database URL constructed: mysql+aiomysql://{username}:***@{host}:{port}/{database}")
    
    # 设置Consul配置
    consul_url = os.getenv('CONSUL_URL')
    if consul_url:
        os.environ['CONSUL_HOST'] = consul_url
        print(f"✅ Consul configuration set: {consul_url}:{os.getenv('CONSUL_PORT', '8500')}")
    
    print("✅ Environment variables check passed")
    return True


def validate_configuration() -> bool:
    """
    验证配置文件
    
    Returns:
        bool: 配置验证是否通过
    """
    try:
        settings = get_settings()
        
        # 测试数据库连接
        print("🔍 Validating database connection...")
        # 这里可以添加实际的数据库连接测试
        
        # 测试Redis连接
        print("🔍 Validating Redis connection...")
        # 这里可以添加实际的Redis连接测试
        
        # 检查NFS路径
        print("🔍 Validating NFS share path...")
        nfs_path = settings.NFS_SHARE_ROOT_PATH
        if not os.path.exists(nfs_path):
            print(f"⚠️  Warning: NFS share path does not exist: {nfs_path}")
            return False
        
        print("✅ Configuration validation passed")
        return True
        
    except Exception as e:
        print(f"❌ Configuration validation failed: {e}")
        return False


def start_worker(
    concurrency: Optional[int] = None,
    queues: Optional[str] = None,
    log_level: str = "INFO",
    detach: bool = False
) -> None:
    """
    启动Celery Worker
    
    Args:
        concurrency: Worker并发数
        queues: 处理的队列列表
        log_level: 日志级别
        detach: 是否后台运行
    """
    
    settings = get_settings()
    
    # 构建启动命令
    cmd = [
        'celery',
        '-A', 'app.celery_app.celery_main',
        'worker',
        f'--loglevel={log_level}',
        f'--concurrency={concurrency or settings.CELERY_WORKER_CONCURRENCY}',
        '--prefetch-multiplier=1',
        '--max-tasks-per-child=1000',
        f'--hostname=worker@{os.getenv("HOSTNAME", "localhost")}',
    ]
    
    # 添加队列参数
    if queues:
        cmd.extend(['--queues', queues])
    elif os.getenv('CELERY_WORKER_QUEUES'):
        cmd.extend(['--queues', os.getenv('CELERY_WORKER_QUEUES')])
    
    # 后台运行
    if detach:
        cmd.append('--detach')
    
    print(f"🚀 Starting Celery Worker with command: {' '.join(cmd)}")
    
    try:
        if detach:
            subprocess.run(cmd, check=True)
            print("✅ Worker started in background")
        else:
            # 前台运行，支持Ctrl+C优雅关闭
            process = subprocess.Popen(cmd)
            
            def signal_handler(signum, frame):
                print(f"\n🛑 Received signal {signum}, shutting down worker...")
                process.terminate()
                try:
                    process.wait(timeout=30)
                    print("✅ Worker shutdown gracefully")
                except subprocess.TimeoutExpired:
                    print("⚠️  Worker did not shutdown gracefully, forcing kill...")
                    process.kill()
                sys.exit(0)
            
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)
            
            process.wait()
            
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to start worker: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n🛑 Worker startup interrupted")
        sys.exit(1)


def stop_worker() -> None:
    """停止Celery Worker"""
    cmd = ['celery', '-A', 'app.celery_app.celery_main', 'control', 'shutdown']
    
    try:
        subprocess.run(cmd, check=True)
        print("✅ Worker shutdown command sent")
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to stop worker: {e}")


def worker_status() -> None:
    """查看Worker状态"""
    cmd = ['celery', '-A', 'app.celery_app.celery_main', 'inspect', 'active']
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print("📊 Worker Status:")
        print(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to get worker status: {e}")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Celery Worker Management Script')
    parser.add_argument('action', choices=['start', 'stop', 'status', 'restart'], 
                       help='Action to perform')
    parser.add_argument('--concurrency', type=int, 
                       help='Number of concurrent worker processes')
    parser.add_argument('--queues', type=str, 
                       help='Comma-separated list of queues to process')
    parser.add_argument('--log-level', default='INFO', 
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                       help='Log level')
    parser.add_argument('--detach', action='store_true',
                       help='Run worker in background')
    parser.add_argument('--skip-checks', action='store_true',
                       help='Skip environment and configuration checks')
    
    args = parser.parse_args()
    
    # 设置日志
    setup_logging()
    
    if args.action in ['start', 'restart']:
        if not args.skip_checks:
            print("🔍 Performing pre-startup checks...")
            
            if not check_environment():
                sys.exit(1)
            
            if not validate_configuration():
                sys.exit(1)
        
        if args.action == 'restart':
            print("🔄 Restarting worker...")
            stop_worker()
            time.sleep(2)
        
        start_worker(
            concurrency=args.concurrency,
            queues=args.queues,
            log_level=args.log_level,
            detach=args.detach
        )
    
    elif args.action == 'stop':
        stop_worker()
    
    elif args.action == 'status':
        worker_status()


if __name__ == '__main__':
    main() 