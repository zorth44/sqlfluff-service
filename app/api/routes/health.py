"""
健康检查API路由

提供服务健康状态检查接口，检查数据库、Redis、NFS等依赖服务的连通性。
主要用于负载均衡器和服务发现系统的健康检查。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text
import redis
import os
from typing import Dict, Any
from datetime import datetime
import psutil

from app.core.database import get_db
from app.core.logging import get_logger
from app.config.settings import get_settings
from app.utils.file_utils import FileManager

router = APIRouter()
settings = get_settings()
logger = get_logger(__name__)


@router.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """完整的健康检查"""
    health_status = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
        "service": "sql-linting-service",
        "checks": {}
    }
    
    # 数据库检查
    try:
        logger.debug("检查数据库连接")
        db.execute(text("SELECT 1"))
        health_status["checks"]["database"] = {
            "status": "healthy",
            "message": "数据库连接正常",
            "checked_at": datetime.utcnow().isoformat()
        }
        logger.debug("数据库连接检查通过")
    except Exception as e:
        logger.error(f"数据库连接检查失败: {e}")
        health_status["checks"]["database"] = {
            "status": "unhealthy",
            "message": f"数据库连接失败: {str(e)}",
            "checked_at": datetime.utcnow().isoformat()
        }
        health_status["status"] = "unhealthy"
    
    # Redis检查
    try:
        logger.debug("检查Redis连接")
        redis_client = redis.Redis.from_url(settings.CELERY_BROKER_URL)
        redis_client.ping()
        health_status["checks"]["redis"] = {
            "status": "healthy",
            "message": "Redis连接正常",
            "checked_at": datetime.utcnow().isoformat()
        }
        logger.debug("Redis连接检查通过")
    except Exception as e:
        logger.error(f"Redis连接检查失败: {e}")
        health_status["checks"]["redis"] = {
            "status": "unhealthy",
            "message": f"Redis连接失败: {str(e)}",
            "checked_at": datetime.utcnow().isoformat()
        }
        health_status["status"] = "unhealthy"
    
    # NFS检查
    try:
        logger.debug("检查NFS挂载")
        file_manager = FileManager()
        nfs_root = settings.NFS_SHARE_ROOT_PATH
        
        # 检查NFS根目录是否存在
        if not os.path.exists(nfs_root):
            raise Exception(f"NFS根目录不存在: {nfs_root}")
        
        # 检查是否可以创建测试文件
        test_file_path = os.path.join(nfs_root, "health_check_test")
        with open(test_file_path, "w") as f:
            f.write("health check test")
        
        # 读取测试文件
        with open(test_file_path, "r") as f:
            content = f.read()
            if content != "health check test":
                raise Exception("NFS读写测试失败")
        
        # 删除测试文件
        os.remove(test_file_path)
        
        health_status["checks"]["nfs"] = {
            "status": "healthy",
            "message": "NFS挂载正常",
            "path": nfs_root,
            "checked_at": datetime.utcnow().isoformat()
        }
        logger.debug("NFS挂载检查通过")
        
    except Exception as e:
        logger.error(f"NFS挂载检查失败: {e}")
        health_status["checks"]["nfs"] = {
            "status": "unhealthy",
            "message": f"NFS挂载失败: {str(e)}",
            "checked_at": datetime.utcnow().isoformat()
        }
        health_status["status"] = "unhealthy"
    
    # 检查磁盘空间
    try:
        logger.debug("检查磁盘空间")
        nfs_root = settings.NFS_SHARE_ROOT_PATH
        statvfs = os.statvfs(nfs_root)
        
        # 计算可用空间（GB）
        available_bytes = statvfs.f_frsize * statvfs.f_bavail
        total_bytes = statvfs.f_frsize * statvfs.f_blocks
        available_gb = available_bytes / (1024 ** 3)
        total_gb = total_bytes / (1024 ** 3)
        usage_percent = ((total_bytes - available_bytes) / total_bytes) * 100
        
        # 检查是否空间不足（使用率超过90%）
        if usage_percent > 90:
            raise Exception(f"磁盘空间不足，使用率: {usage_percent:.1f}%")
        
        health_status["checks"]["disk_space"] = {
            "status": "healthy",
            "message": f"磁盘空间充足，使用率: {usage_percent:.1f}%",
            "available_gb": round(available_gb, 2),
            "total_gb": round(total_gb, 2),
            "usage_percent": round(usage_percent, 1),
            "checked_at": datetime.utcnow().isoformat()
        }
        logger.debug("磁盘空间检查通过")
        
    except Exception as e:
        logger.error(f"磁盘空间检查失败: {e}")
        health_status["checks"]["disk_space"] = {
            "status": "unhealthy",
            "message": f"磁盘空间检查失败: {str(e)}",
            "checked_at": datetime.utcnow().isoformat()
        }
        health_status["status"] = "unhealthy"
    
    # 系统资源检查
    try:
        # CPU使用率
        cpu_percent = psutil.cpu_percent(interval=1)
        
        # 内存使用率
        memory = psutil.virtual_memory()
        
        # 磁盘使用率
        disk = psutil.disk_usage('/')
        
        health_status["checks"]["system_resources"] = {
            "status": "healthy" if cpu_percent < 90 and memory.percent < 90 else "warning",
            "message": "System resources check",
            "cpu_usage_percent": round(cpu_percent, 2),
            "memory_usage_percent": round(memory.percent, 2),
            "disk_usage_percent": round((disk.used / disk.total) * 100, 2),
            "memory_available_gb": round(memory.available / (1024**3), 2)
        }
        
        # 如果资源使用率过高，标记为警告
        if cpu_percent > 90 or memory.percent > 90:
            health_status["status"] = "warning"
            
    except Exception as e:
        health_status["checks"]["system_resources"] = {
            "status": "unknown",
            "error": str(e),
            "message": "System resources check failed"
        }
        logger.error(f"System resources health check failed: {e}")
        health_status["status"] = "unhealthy"
    
    # 应用配置检查
    try:
        config_status = {
            "status": "healthy",
            "message": "Application configuration check",
            "environment": settings.ENVIRONMENT,
            "debug_mode": settings.DEBUG,
            "log_level": settings.LOG_LEVEL
        }
        
        # 检查关键配置
        required_configs = [
            "DATABASE_URL",
            "CELERY_BROKER_URL", 
            "NFS_SHARE_ROOT_PATH"
        ]
        
        missing_configs = []
        for config in required_configs:
            if not getattr(settings, config, None):
                missing_configs.append(config)
        
        if missing_configs:
            config_status["status"] = "unhealthy"
            config_status["error"] = f"Missing required configurations: {missing_configs}"
            health_status["status"] = "unhealthy"
        
        health_status["checks"]["configuration"] = config_status
        
    except Exception as e:
        health_status["checks"]["configuration"] = {
            "status": "unhealthy",
            "error": str(e),
            "message": "Configuration check failed"
        }
        health_status["status"] = "unhealthy"
        logger.error(f"Configuration health check failed: {e}")
    
    # 记录健康检查结果
    if health_status["status"] == "healthy":
        logger.info("Health check passed", extra={
            "health_status": health_status["status"],
            "checks_count": len(health_status["checks"])
        })
    else:
        logger.warning("Health check failed", extra={
            "health_status": health_status["status"],
            "failed_checks": [
                name for name, check in health_status["checks"].items() 
                if check.get("status") == "unhealthy"
            ]
        })
    
    # 如果有任何检查失败，返回503状态码
    if health_status["status"] != "healthy":
        logger.warning("健康检查失败，存在不健康的依赖服务")
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=health_status
        )
    
    logger.info("健康检查通过")
    return health_status


@router.get("/health/ready")
async def readiness_check():
    """轻量级就绪检查 - 快速响应"""
    return {
        "status": "ready",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "sql-linting-service",
        "version": "1.0.0"
    }


@router.get("/health/live")
async def liveness_check():
    """轻量级存活检查 - 快速响应"""
    return {
        "status": "alive",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "sql-linting-service",
        "version": "1.0.0"
    }


@router.get("/health/metrics")
async def metrics_endpoint():
    """Prometheus指标端点"""
    try:
        from app.core.metrics import get_metrics
        return get_metrics()
    except ImportError:
        return {"error": "Metrics not available"}


@router.get("/health/info")
async def service_info():
    """服务信息"""
    return {
        "service_name": "sql-linting-service",
        "version": "1.0.0",
        "description": "SQL code quality analysis service",
        "environment": settings.ENVIRONMENT,
        "features": [
            "SQL file analysis",
            "ZIP package processing", 
            "Async task processing",
            "RESTful API",
            "Prometheus metrics",
            "Health monitoring"
        ],
        "endpoints": {
            "api_docs": "/docs",
            "health_check": "/api/v1/health",
            "metrics": "/api/v1/health/metrics"
        }
    }


@router.get("/health/dependencies")
async def dependencies_status():
    """
    依赖服务状态
    
    返回所有外部依赖服务的状态信息，用于运维监控。
    """
    dependencies = {
        "database": {
            "name": "MySQL数据库",
            "type": "database",
            "required": True,
            "description": "主数据库，存储Job和Task信息"
        },
        "redis": {
            "name": "Redis消息队列",
            "type": "cache/queue",
            "required": True,
            "description": "Celery消息代理，用于任务队列"
        },
        "nfs": {
            "name": "NFS共享存储",
            "type": "storage",
            "required": True,
            "description": "共享文件存储，存储SQL文件和分析结果"
        },
        "sqlfluff": {
            "name": "SQLFluff分析引擎",
            "type": "library",
            "required": True,
            "description": "SQL质量分析核心引擎"
        }
    }
    
    return {
        "dependencies": dependencies,
        "timestamp": datetime.utcnow().isoformat()
    }


# 添加快速健康检查端点供Consul使用
@router.get("/health/quick")
async def quick_health_check(db: Session = Depends(get_db)):
    """快速健康检查 - 仅检查核心服务"""
    health_status = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
        "service": "sql-linting-service",
        "checks": {}
    }
    
    # 仅检查数据库连接（最关键的依赖）
    try:
        logger.debug("快速检查数据库连接")
        db.execute(text("SELECT 1"))
        health_status["checks"]["database"] = {
            "status": "healthy",
            "message": "数据库连接正常"
        }
        logger.debug("数据库连接检查通过")
    except Exception as e:
        logger.error(f"数据库连接检查失败: {e}")
        health_status["checks"]["database"] = {
            "status": "unhealthy",
            "message": f"数据库连接失败: {str(e)}"
        }
        health_status["status"] = "unhealthy"
    
    return health_status

# 添加最简单的健康检查端点
@router.get("/health/simple")
async def simple_health_check():
    """最简单的健康检查 - 仅检查服务是否运行"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "sql-linting-service",
        "version": "1.0.0"
    } 