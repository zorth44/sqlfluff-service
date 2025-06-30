"""
统一配置管理

基于环境变量的配置系统，支持不同环境(dev/test/prod)的配置。
包含数据库、Redis、NFS、Consul、日志等所有系统配置项。
"""

import os
from typing import Optional, Dict, Any
from pydantic import Field, validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """系统配置类"""
    
    # ============= 基础配置 =============
    APP_NAME: str = "SQL核验服务"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = Field(default="dev", description="运行环境: dev/test/prod")
    DEBUG: bool = Field(default=True, description="调试模式")
    
    # ============= 数据库配置 =============
    DATABASE_URL: str = Field(
        description="MySQL数据库连接字符串",
        env="DATABASE_URL"
    )
    DATABASE_POOL_SIZE: int = Field(default=20, description="数据库连接池大小")
    DATABASE_MAX_OVERFLOW: int = Field(default=30, description="数据库连接池最大溢出")
    DATABASE_POOL_TIMEOUT: int = Field(default=30, description="数据库连接超时时间")
    DATABASE_POOL_RECYCLE: int = Field(default=3600, description="连接回收时间")
    
    # ============= Redis配置 =============
    REDIS_HOST: str = Field(description="Redis主机地址", env="REDIS_HOST")
    REDIS_PORT: int = Field(description="Redis端口", env="REDIS_PORT")
    REDIS_USERNAME: Optional[str] = Field(default=None, description="Redis用户名", env="REDIS_USERNAME")
    REDIS_PASSWORD: Optional[str] = Field(default=None, description="Redis密码", env="REDIS_PASSWORD")
    REDIS_DB_BROKER: int = Field(default=0, description="Celery消息代理使用的Redis数据库", env="REDIS_DB_BROKER")
    REDIS_DB_RESULT: int = Field(default=1, description="Celery结果后端使用的Redis数据库", env="REDIS_DB_RESULT")
    REDIS_MAX_CONNECTIONS: int = Field(default=50, description="Redis最大连接数")
    
    # ============= NFS共享目录配置 =============
    NFS_SHARE_ROOT_PATH: str = Field(
        description="NFS共享目录在服务器上的挂载点",
        env="NFS_SHARE_ROOT_PATH"
    )
    
    # ============= Consul服务发现配置 =============
    CONSUL_HOST: str = Field(default="127.0.0.1", description="Consul Agent主机地址")
    CONSUL_PORT: int = Field(default=8500, description="Consul Agent端口")
    CONSUL_SERVICE_NAME: str = Field(default="sql-linting-service", description="服务名称")
    CONSUL_SERVICE_PORT: int = Field(default=8000, description="服务端口")
    CONSUL_HEALTH_CHECK_INTERVAL: str = Field(default="10s", description="健康检查间隔")
    
    # ============= 日志配置 =============
    LOG_LEVEL: str = Field(default="INFO", description="日志级别")
    LOG_FORMAT: str = Field(default="json", description="日志格式: json/text")
    LOG_FILE_PATH: Optional[str] = Field(default=None, description="日志文件路径")
    LOG_FILE_MAX_SIZE: str = Field(default="100MB", description="日志文件最大大小")
    LOG_FILE_BACKUP_COUNT: int = Field(default=5, description="日志文件备份数量")
    
    # ============= Web服务配置 =============
    WEB_HOST: str = Field(default="0.0.0.0", description="Web服务绑定主机")
    WEB_PORT: int = Field(default=8000, description="Web服务端口")
    WEB_WORKERS: int = Field(default=1, description="Web服务进程数")
    WEB_MAX_REQUEST_SIZE: int = Field(default=16 * 1024 * 1024, description="最大请求大小(字节)")
    ALLOWED_HOSTS: list = Field(default=["*"], description="允许的主机列表")
    
    # ============= Celery Worker配置 =============
    CELERY_WORKER_CONCURRENCY: int = Field(default=4, description="Worker并发数")
    CELERY_WORKER_PREFETCH_MULTIPLIER: int = Field(default=1, description="Worker预取倍数")
    CELERY_TASK_ACKS_LATE: bool = Field(default=True, description="任务延迟确认")
    CELERY_TASK_REJECT_ON_WORKER_LOST: bool = Field(default=True, description="Worker丢失时拒绝任务")
    CELERY_TASK_MAX_RETRIES: int = Field(default=3, description="任务最大重试次数")
    CELERY_TASK_DEFAULT_RETRY_DELAY: int = Field(default=60, description="任务重试延迟(秒)")
    
    # ============= SQLFluff配置 =============
    SQLFLUFF_DIALECT: str = Field(default="mysql", description="SQLFluff方言")
    SQLFLUFF_CONFIG_PATH: Optional[str] = Field(default=None, description="SQLFluff配置文件路径")
    
    # ============= 文件处理配置 =============
    MAX_FILE_SIZE: int = Field(default=50 * 1024 * 1024, description="最大文件大小(字节)")
    MAX_ZIP_FILES: int = Field(default=1000, description="ZIP包中最大文件数")
    TEMP_DIR_CLEANUP_INTERVAL: int = Field(default=3600, description="临时目录清理间隔(秒)")
    
    @validator('ENVIRONMENT')
    def validate_environment(cls, v):
        """验证环境配置"""
        if v not in ['dev', 'test', 'prod']:
            raise ValueError('ENVIRONMENT must be one of: dev, test, prod')
        return v
    
    @validator('LOG_LEVEL')
    def validate_log_level(cls, v):
        """验证日志级别"""
        if v not in ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']:
            raise ValueError('LOG_LEVEL must be one of: DEBUG, INFO, WARNING, ERROR, CRITICAL')
        return v
    
    @validator('LOG_FORMAT')
    def validate_log_format(cls, v):
        """验证日志格式"""
        if v not in ['json', 'text']:
            raise ValueError('LOG_FORMAT must be one of: json, text')
        return v
    
    @validator('DEBUG', pre=True)
    def set_debug_from_environment(cls, v, values):
        """根据环境自动设置调试模式"""
        env = values.get('ENVIRONMENT', 'dev')
        if env == 'prod':
            return False
        return v
    
    def get_database_url(self) -> str:
        """获取数据库连接URL"""
        return self.DATABASE_URL
    
    def get_celery_broker_url(self) -> str:
        """获取Celery Broker Redis连接URL"""
        auth = ""
        if self.REDIS_USERNAME and self.REDIS_PASSWORD:
            auth = f"{self.REDIS_USERNAME}:{self.REDIS_PASSWORD}@"
        elif self.REDIS_PASSWORD:
            auth = f":{self.REDIS_PASSWORD}@"
        
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB_BROKER}"
    
    @property
    def CELERY_BROKER_URL(self) -> str:
        """获取Celery Broker URL（属性形式）"""
        return self.get_celery_broker_url()
    
    def get_celery_result_backend_url(self) -> str:
        """获取Celery Result Backend Redis连接URL"""
        auth = ""
        if self.REDIS_USERNAME and self.REDIS_PASSWORD:
            auth = f"{self.REDIS_USERNAME}:{self.REDIS_PASSWORD}@"
        elif self.REDIS_PASSWORD:
            auth = f":{self.REDIS_PASSWORD}@"
        
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB_RESULT}"
    
    def get_nfs_root_path(self) -> str:
        """获取NFS根路径"""
        return self.NFS_SHARE_ROOT_PATH
    
    def is_development(self) -> bool:
        """是否为开发环境"""
        return self.ENVIRONMENT == 'dev'
    
    def is_production(self) -> bool:
        """是否为生产环境"""
        return self.ENVIRONMENT == 'prod'
    
    def get_consul_config(self) -> Dict[str, Any]:
        """获取Consul配置"""
        return {
            'host': self.CONSUL_HOST,
            'port': self.CONSUL_PORT,
            'service_name': self.CONSUL_SERVICE_NAME,
            'service_port': self.CONSUL_SERVICE_PORT,
            'health_check_interval': self.CONSUL_HEALTH_CHECK_INTERVAL
        }
    
    def get_celery_config(self) -> Dict[str, Any]:
        """获取Celery配置"""
        return {
            'broker_url': self.get_celery_broker_url(),
            'result_backend': self.get_celery_result_backend_url(),
            'worker_concurrency': self.CELERY_WORKER_CONCURRENCY,
            'worker_prefetch_multiplier': self.CELERY_WORKER_PREFETCH_MULTIPLIER,
            'task_acks_late': self.CELERY_TASK_ACKS_LATE,
            'task_reject_on_worker_lost': self.CELERY_TASK_REJECT_ON_WORKER_LOST,
            'task_max_retries': self.CELERY_TASK_MAX_RETRIES,
            'task_default_retry_delay': self.CELERY_TASK_DEFAULT_RETRY_DELAY
        }
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# 全局配置实例
settings = Settings()


def get_settings() -> Settings:
    """获取配置实例（用于依赖注入）"""
    return settings


def load_settings_from_env() -> Settings:
    """从环境变量重新加载配置"""
    return Settings()


# 环境特定的配置验证
def validate_production_config(settings: Settings) -> None:
    """验证生产环境配置"""
    if settings.is_production():
        critical_configs = [
            'DATABASE_URL',
            'REDIS_HOST',
            'NFS_SHARE_ROOT_PATH',
            'CONSUL_HOST'
        ]
        
        for config_name in critical_configs:
            config_value = getattr(settings, config_name)
            if not config_value or config_value in ['localhost', '127.0.0.1']:
                raise ValueError(f"生产环境配置 {config_name} 不能为空或使用本地地址")
        
        if settings.DEBUG:
            raise ValueError("生产环境不能开启DEBUG模式")


# 模块加载时自动调用配置验证
if settings.is_production():
    validate_production_config(settings) 