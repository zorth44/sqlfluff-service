"""
健康检查API路由

提供服务健康状态检查接口，检查数据库、Worker、NFS等依赖服务的连通性。
主要用于负载均衡器和服务发现系统的健康检查。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text
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
    
    # Worker状态检查
    try:
        logger.debug("检查Worker状态")
        from app.models.database import WorkerRegistry
        from datetime import timedelta
        worker_active_threshold = settings.WORKER_HEARTBEAT_INTERVAL * 3
        cutoff = datetime.utcnow() - timedelta(seconds=worker_active_threshold)
        active_workers = db.query(WorkerRegistry).filter(
            WorkerRegistry.status == 'RUNNING',
            WorkerRegistry.heartbeat_at >= cutoff
        ).all()

        worker_info = [
            {
                "worker_id": w.worker_id,
                "hostname": w.hostname,
                "current_tasks": w.current_task_count,
                "last_heartbeat": w.heartbeat_at.isoformat()
            }
            for w in active_workers
        ]

        health_status["checks"]["workers"] = {
            "status": "healthy" if active_workers else "warning",
            "message": f"{len(active_workers)} active worker(s)",
            "workers": worker_info,
            "checked_at": datetime.utcnow().isoformat()
        }
        if not active_workers:
            health_status["status"] = "warning"
        logger.debug(f"Worker状态检查通过: {len(active_workers)} active")
    except Exception as e:
        logger.error(f"Worker状态检查失败: {e}")
        health_status["checks"]["workers"] = {
            "status": "unhealthy",
            "message": f"Worker状态检查失败: {str(e)}",
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
        
        # 使用FileManager的安全权限检查方法
        if not file_manager.check_write_permission():
            raise Exception("NFS写权限检查失败")
        
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
    
    if health_status["status"] == "unhealthy":
        logger.warning("健康检查失败，存在不健康的依赖服务")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=health_status
        )

    logger.info("健康检查通过")
    return health_status


@router.get("/health/ready")
async def readiness_check(db: Session = Depends(get_db)):
    """轻量级就绪检查 - 验证数据库可用（不检查 Worker）"""
    checks: Dict[str, Any] = {}

    try:
        db.execute(text("SELECT 1"))
        checks["database"] = {
            "status": "healthy",
            "message": "数据库连接正常",
            "checked_at": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error(f"就绪检查数据库失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "not_ready",
                "timestamp": datetime.utcnow().isoformat(),
                "service": "sql-linting-service",
                "version": "1.0.0",
                "checks": {
                    "database": {
                        "status": "unhealthy",
                        "message": f"数据库连接失败: {str(e)}",
                        "checked_at": datetime.utcnow().isoformat(),
                    }
                },
            },
        )

    try:
        nfs_root = settings.NFS_SHARE_ROOT_PATH
        if os.path.exists(nfs_root):
            checks["nfs"] = {
                "status": "healthy",
                "message": "NFS路径可访问",
                "path": nfs_root,
                "checked_at": datetime.utcnow().isoformat(),
            }
        else:
            checks["nfs"] = {
                "status": "warning",
                "message": f"NFS路径不存在: {nfs_root}",
                "path": nfs_root,
                "checked_at": datetime.utcnow().isoformat(),
            }
    except Exception as e:
        checks["nfs"] = {
            "status": "warning",
            "message": f"NFS检查失败: {str(e)}",
            "checked_at": datetime.utcnow().isoformat(),
        }

    return {
        "status": "ready",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "sql-linting-service",
        "version": "1.0.0",
        "checks": checks,
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
async def metrics_endpoint(db: Session = Depends(get_db)):
    """Prometheus指标端点"""
    try:
        from app.core.metrics import get_metrics, collect_queue_gauges
        collect_queue_gauges(
            db,
            worker_heartbeat_seconds=settings.WORKER_HEARTBEAT_INTERVAL * 3,
        )
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

    if health_status["status"] == "unhealthy":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=health_status
        )

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