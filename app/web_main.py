"""
FastAPI Web服务启动入口

这是FastAPI Web服务的主要入口点，负责：
- 创建FastAPI应用实例
- 配置路由和中间件
- 服务注册和发现
- 启动HTTP服务器
"""

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError, HTTPException
import uvicorn
import asyncio
import time
import uuid
from typing import Union
from contextlib import asynccontextmanager

from app.api.routes import jobs, tasks, health
from app.config.settings import get_settings
from app.core.logging import setup_logging, api_logger
from app.core.exceptions import BaseException as BusinessException, get_http_status_code
from app.core.consul import register_to_consul, deregister_from_consul, start_consul_health_reporting
from app.core.database import engine

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动事件
    api_logger.info("FastAPI应用启动中...")
    
    # 初始化日志系统
    setup_logging()
    
    # 注册到Consul（如果配置了）
    if settings.CONSUL_HOST:
        try:
            success = await register_to_consul()
            if success:
                api_logger.info("服务已注册到Consul")
                # 启动健康状态报告任务
                await start_consul_health_reporting()
                api_logger.info("Consul健康状态报告任务已启动")
            else:
                api_logger.warning("服务注册到Consul失败")
        except Exception as e:
            api_logger.error(f"Consul注册异常: {e}")
    
    api_logger.info("FastAPI应用启动完成")
    
    yield
    
    # 关闭事件
    api_logger.info("FastAPI应用关闭中...")
    
    # 从Consul注销
    if settings.CONSUL_HOST:
        try:
            success = await deregister_from_consul()
            if success:
                api_logger.info("服务已从Consul注销")
            else:
                api_logger.warning("服务从Consul注销失败")
        except Exception as e:
            api_logger.error(f"Consul注销异常: {e}")
    
    # 关闭数据库连接
    try:
        engine.dispose()
        api_logger.info("数据库连接已关闭")
    except Exception as e:
        api_logger.error(f"关闭数据库连接失败: {e}")
    
    api_logger.info("FastAPI应用关闭完成")


def create_app() -> FastAPI:
    """
    创建FastAPI应用实例
    
    Returns:
        FastAPI: 配置完成的FastAPI应用
    """
    # 创建FastAPI应用
    app = FastAPI(
        title="SQL核验服务",
        description="提供SQL文件质量检查服务，支持单文件和批量ZIP包分析",
        version="1.0.0",
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
        openapi_url="/openapi.json" if settings.DEBUG else None,
        lifespan=lifespan
    )
    
    # 配置中间件
    _configure_middleware(app)
    
    # 配置异常处理器
    _configure_exception_handlers(app)
    
    # 注册路由
    _register_routes(app)
    
    api_logger.info("FastAPI应用创建完成")
    return app


def _configure_middleware(app: FastAPI):
    """配置中间件"""
    
    # 信任主机中间件（安全）
    if settings.ALLOWED_HOSTS and settings.ALLOWED_HOSTS != ["*"]:
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=settings.ALLOWED_HOSTS
        )
    
    # CORS中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_HOSTS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Response-Time"]
    )
    
    # 请求ID和日志中间件
    @app.middleware("http")
    async def request_middleware(request: Request, call_next):
        # 生成请求ID
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        
        # 记录请求开始时间
        start_time = time.time()
        
        # 记录请求信息
        api_logger.info(
            f"请求开始: {request.method} {request.url}",
            extra={
                "request_id": request_id,
                "method": request.method,
                "url": str(request.url),
                "user_agent": request.headers.get("user-agent"),
                "remote_addr": request.client.host if request.client else None
            }
        )
        
        # 处理请求
        try:
            response = await call_next(request)
        except Exception as e:
            # 记录未捕获的异常
            api_logger.error(
                f"请求处理异常: {e}",
                extra={"request_id": request_id},
                exc_info=True
            )
            # 返回500错误
            response = JSONResponse(
                status_code=500,
                content={"detail": "内部服务器错误"}
            )
        
        # 计算响应时间
        process_time = time.time() - start_time
        
        # 添加响应头
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{process_time:.4f}s"
        
        # 记录响应信息
        api_logger.info(
            f"请求完成: {response.status_code}",
            extra={
                "request_id": request_id,
                "status_code": response.status_code,
                "response_time": process_time
            }
        )
        
        return response


def _configure_exception_handlers(app: FastAPI):
    """配置异常处理器"""
    
    @app.exception_handler(BusinessException)
    async def business_exception_handler(request: Request, exc: BusinessException):
        """业务异常处理器"""
        request_id = getattr(request.state, 'request_id', 'unknown')
        
        api_logger.warning(
            f"业务异常: {exc.detail}",
            extra={
                "request_id": request_id,
                "error_code": exc.error_code.code,
                "context": exc.context
            }
        )
        
        status_code = get_http_status_code(exc.error_code)
        return JSONResponse(
            status_code=status_code,
            content={
                "detail": exc.detail,
                "error_code": exc.error_code.code,
                "request_id": request_id
            }
        )
    
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """请求验证异常处理器"""
        request_id = getattr(request.state, 'request_id', 'unknown')
        
        api_logger.warning(
            f"请求验证失败: {exc.errors()}",
            extra={"request_id": request_id}
        )
        
        return JSONResponse(
            status_code=422,
            content={
                "detail": "请求参数验证失败",
                "errors": exc.errors(),
                "request_id": request_id
            }
        )
    
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        """HTTP异常处理器"""
        request_id = getattr(request.state, 'request_id', 'unknown')
        
        # 根据状态码确定日志级别
        if exc.status_code >= 500:
            api_logger.error(f"HTTP错误: {exc.detail}", extra={"request_id": request_id})
        else:
            api_logger.warning(f"HTTP错误: {exc.detail}", extra={"request_id": request_id})
        
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.detail,
                "request_id": request_id
            }
        )
    
    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """通用异常处理器"""
        request_id = getattr(request.state, 'request_id', 'unknown')
        
        api_logger.error(
            f"未处理异常: {exc}",
            extra={"request_id": request_id},
            exc_info=True
        )
        
        return JSONResponse(
            status_code=500,
            content={
                "detail": "内部服务器错误",
                "request_id": request_id
            }
        )


def _register_routes(app: FastAPI):
    """注册路由"""
    
    # API v1路由
    app.include_router(
        jobs.router,
        prefix="/api/v1",
        tags=["jobs"],
        responses={
            404: {"description": "资源不存在"},
            422: {"description": "请求参数错误"},
            500: {"description": "内部服务器错误"}
        }
    )
    
    app.include_router(
        tasks.router,
        prefix="/api/v1",
        tags=["tasks"],
        responses={
            404: {"description": "资源不存在"},
            422: {"description": "请求参数错误"},
            500: {"description": "内部服务器错误"}
        }
    )
    
    app.include_router(
        health.router,
        prefix="/api/v1",
        tags=["health"],
        responses={
            503: {"description": "服务不可用"}
        }
    )
    
    # 根路径
    @app.get("/", include_in_schema=False)
    async def root():
        """根路径重定向到API文档"""
        return {
            "message": "SQL核验服务 API",
            "version": "1.0.0",
            "docs_url": "/docs" if settings.DEBUG else None,
            "health_check": "/api/v1/health"
        }


# 创建应用实例
app = create_app()


# ============= 开发服务器启动 =============

def start_dev_server():
    """启动开发服务器"""
    uvicorn.run(
        "app.web_main:app",
        host=settings.WEB_HOST,
        port=settings.WEB_PORT,
        reload=settings.DEBUG,
        log_level="info",
        access_log=True
    )


if __name__ == "__main__":
    print("SQL核验服务 - FastAPI Web服务")
    print(f"环境: {settings.ENVIRONMENT}")
    print(f"调试模式: {settings.DEBUG}")
    print(f"监听地址: {settings.WEB_HOST}:{settings.WEB_PORT}")
    print("正在启动服务...")
    
    start_dev_server() 