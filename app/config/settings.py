"""
统一配置管理

基于环境变量的配置系统，支持不同环境(dev/test/prod)的配置。
包含数据库、Redis、NFS、Consul、日志等所有系统配置项。
"""

import os
from typing import Optional, Dict, Any, List
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
        default="",
        description="MySQL数据库连接字符串",
        env="DATABASE_URL"
    )
    # 分离的数据库配置变量
    MYSQL_DATABASE_HOST: Optional[str] = Field(default=None, description="MySQL数据库主机", env="MYSQL_DATABASE_HOST")
    MYSQL_DATABASE_PORT: Optional[int] = Field(default=None, description="MySQL数据库端口", env="MYSQL_DATABASE_PORT")
    MYSQL_DATABASE_USERNAME: Optional[str] = Field(default=None, description="MySQL数据库用户名", env="MYSQL_DATABASE_USERNAME")
    MYSQL_DATABASE_PASSWORD: Optional[str] = Field(default=None, description="MySQL数据库密码", env="MYSQL_DATABASE_PASSWORD")
    MYSQL_DATABASE_NAME: Optional[str] = Field(default=None, description="MySQL数据库名称", env="MYSQL_DATABASE_NAME")
    
    DATABASE_POOL_SIZE: int = Field(default=20, description="数据库连接池大小")
    DATABASE_MAX_OVERFLOW: int = Field(default=30, description="数据库连接池最大溢出")
    DATABASE_POOL_TIMEOUT: int = Field(default=30, description="数据库连接超时时间")
    DATABASE_POOL_RECYCLE: int = Field(default=3600, description="连接回收时间")
    # 默认关闭：Worker 轮询/心跳会高频打 SQL，跟 DEBUG 绑在一起会严重刷屏
    DATABASE_ECHO: bool = Field(default=False, description="是否打印 SQLAlchemy SQL 语句", env="DATABASE_ECHO")
    
    # ============= Worker 配置（DB-as-Queue） =============
    WORKER_CONCURRENCY: int = Field(default=4, description="Worker 并发线程数", env="WORKER_CONCURRENCY")
    WORKER_POLL_INTERVAL: float = Field(default=2.0, description="无任务时轮询间隔(秒)", env="WORKER_POLL_INTERVAL")
    WORKER_HEARTBEAT_INTERVAL: int = Field(default=30, description="Worker 心跳间隔(秒)", env="WORKER_HEARTBEAT_INTERVAL")
    WORKER_ZOMBIE_TIMEOUT: int = Field(default=600, description="Worker 心跳超时(秒)", env="WORKER_ZOMBIE_TIMEOUT")
    WORKER_TASK_TIMEOUT: int = Field(default=1800, description="单任务超时(秒)", env="WORKER_TASK_TIMEOUT")
    WORKER_ZOMBIE_SWEEP_INTERVAL: int = Field(default=120, description="僵尸扫描间隔(秒)", env="WORKER_ZOMBIE_SWEEP_INTERVAL")
    WORKER_MAX_RETRIES: int = Field(default=3, description="任务最大重试次数", env="WORKER_MAX_RETRIES")
    
    # ============= NFS共享目录配置 =============
    NFS_SHARE_ROOT_PATH: str = Field(
        description="NFS共享目录在服务器上的挂载点",
        env="NFS_SHARE_ROOT_PATH"
    )
    
    # ============= Consul服务发现配置 =============
    CONSUL_HOST: str = Field(default="127.0.0.1", description="Consul Agent主机地址", env="CONSUL_HOST")
    CONSUL_PORT: int = Field(default=8500, description="Consul Agent端口", env="CONSUL_PORT")
    CONSUL_SERVICE_NAME: str = Field(default="sql-linting-service", description="服务名称")
    CONSUL_SERVICE_PORT: int = Field(default=8000, description="服务端口")
    CONSUL_SERVICE_IP: Optional[str] = Field(default=None, description="服务注册IP地址，未设置时自动检测", env="CONSUL_SERVICE_IP")
    CONSUL_SERVICE_ID: Optional[str] = Field(default=None, description="服务实例ID（可选，默认自动生成：服务名-主机名-端口）", env="CONSUL_SERVICE_ID")
    CONSUL_HEALTH_CHECK_INTERVAL: str = Field(default="10s", description="健康检查间隔")
    
    # ============= 日志配置 =============
    LOG_LEVEL: str = Field(default="INFO", description="日志级别")
    LOG_FORMAT: str = Field(default="json", description="日志格式: json/text")
    LOG_FILE_PATH: Optional[str] = Field(default=None, description="日志文件路径")
    LOG_FILE_BACKUP_COUNT: int = Field(
        default=14,
        description="按日轮转后保留的历史日志天数（含 gzip 压缩文件）",
    )
    
    # ============= Web服务配置 =============
    WEB_HOST: str = Field(default="0.0.0.0", description="Web服务绑定主机")
    WEB_PORT: int = Field(default=8000, description="Web服务端口")
    WEB_WORKERS: int = Field(default=1, description="Web服务进程数")
    WEB_MAX_REQUEST_SIZE: int = Field(default=16 * 1024 * 1024, description="最大请求大小(字节)")
    ALLOWED_HOSTS: list = Field(default=["*"], description="允许的主机列表")
    
    # ============= SQLFluff配置 =============
    SQLFLUFF_DIALECT: str = Field(default="mysql", description="SQLFluff方言")
    SQLFLUFF_CONFIG_PATH: Optional[str] = Field(default=None, description="SQLFluff配置文件路径")

    # SQL检查接口配置
    HIVE_RULES: str = Field(default="", description="Hive方言规则列表，逗号分隔", env="HIVE_RULES")
    GBASE8A_RULES: str = Field(default="", description="GBase8a方言规则列表，逗号分隔", env="GBASE8A_RULES")
    
    # ============= 文件处理配置 =============
    MAX_FILE_SIZE: int = Field(default=50 * 1024 * 1024, description="最大文件大小(字节)")
    MAX_ZIP_FILES: int = Field(default=1000, description="ZIP包中最大文件数")
    TEMP_DIR_CLEANUP_INTERVAL: int = Field(default=3600, description="临时目录清理间隔(秒)")
    NFS_PERMISSION_CHECK: bool = Field(default=False, description="是否在初始化时检查NFS写权限")
    
    # ============= 任务处理配置 =============
    MAX_CONCURRENT_TASKS: int = Field(default=8, description="最大并发任务数", env="MAX_CONCURRENT_TASKS")
    
    # ============= 规则分级配置 =============
    RULE_SEVERITY_ENABLED: bool = Field(default=True, description="是否启用规则分级映射功能", env="RULE_SEVERITY_ENABLED")
    RULE_SEVERITY_CACHE_TTL_SECONDS: int = Field(default=600, description="规则分级映射缓存TTL时间（秒）", env="RULE_SEVERITY_CACHE_TTL_SECONDS")

    # ============= HTML报告导出配置 =============
    EXPORT_HTML_FILE_LIMIT: int = Field(default=100, description="HTML报告导出最大文件数限制", env="EXPORT_HTML_FILE_LIMIT")
    EXPORT_HTML_CONTEXT_LINES: int = Field(default=3, description="违规项上下文显示行数", env="EXPORT_HTML_CONTEXT_LINES")
    
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
    
    @validator('CONSUL_HOST', pre=True)
    def set_consul_host_from_url(cls, v):
        """如果提供了CONSUL_URL，则使用它作为CONSUL_HOST"""
        consul_url = os.getenv('CONSUL_URL')
        if consul_url:
            return consul_url
        return v
    
    def get_database_url(self) -> str:
        """获取数据库连接URL"""
        # 如果已经设置了DATABASE_URL，直接使用
        if self.DATABASE_URL:
            return self.DATABASE_URL
        
        # 否则从分离的配置变量构建
        if all([
            self.MYSQL_DATABASE_HOST,
            self.MYSQL_DATABASE_PORT,
            self.MYSQL_DATABASE_USERNAME,
            self.MYSQL_DATABASE_PASSWORD,
            self.MYSQL_DATABASE_NAME
        ]):
            from urllib.parse import quote_plus
            # URL编码用户名和密码以处理特殊字符
            username = quote_plus(self.MYSQL_DATABASE_USERNAME)
            password = quote_plus(self.MYSQL_DATABASE_PASSWORD)
            return f"mysql+pymysql://{username}:{password}@{self.MYSQL_DATABASE_HOST}:{self.MYSQL_DATABASE_PORT}/{self.MYSQL_DATABASE_NAME}"
        
        # 如果两种配置都没有提供，返回默认值或抛出错误
        raise ValueError("Database configuration is incomplete. Please provide either DATABASE_URL or all MySQL database configuration variables.")
    
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
    
    def get_worker_config(self) -> Dict[str, Any]:
        """获取Worker配置"""
        return {
            'concurrency': self.WORKER_CONCURRENCY,
            'poll_interval': self.WORKER_POLL_INTERVAL,
            'heartbeat_interval': self.WORKER_HEARTBEAT_INTERVAL,
            'zombie_timeout': self.WORKER_ZOMBIE_TIMEOUT,
            'task_timeout': self.WORKER_TASK_TIMEOUT,
            'zombie_sweep_interval': self.WORKER_ZOMBIE_SWEEP_INTERVAL,
            'max_retries': self.WORKER_MAX_RETRIES,
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
        # 检查NFS配置
        if not settings.NFS_SHARE_ROOT_PATH:
            raise ValueError("生产环境配置 NFS_SHARE_ROOT_PATH 不能为空")

        # 检查Consul配置
        if not settings.CONSUL_HOST or settings.CONSUL_HOST in ['localhost', '127.0.0.1']:
            raise ValueError("生产环境配置 CONSUL_HOST 不能为空或使用本地地址")

        # 检查数据库配置 - 支持两种方式
        has_database_url = bool(settings.DATABASE_URL)
        has_separate_db_config = all([
            settings.MYSQL_DATABASE_HOST,
            settings.MYSQL_DATABASE_PORT,
            settings.MYSQL_DATABASE_USERNAME,
            settings.MYSQL_DATABASE_PASSWORD,
            settings.MYSQL_DATABASE_NAME
        ])

        if not has_database_url and not has_separate_db_config:
            raise ValueError("生产环境必须提供数据库配置：要么设置DATABASE_URL，要么设置所有MySQL配置变量")

        # 如果使用分离的配置，检查主机不能是本地地址
        if has_separate_db_config and settings.MYSQL_DATABASE_HOST in ['localhost', '127.0.0.1']:
            raise ValueError("生产环境配置 MYSQL_DATABASE_HOST 不能使用本地地址")

        if settings.DEBUG:
            raise ValueError("生产环境不能开启DEBUG模式")


# 模块加载时自动调用配置验证
if settings.is_production():
    validate_production_config(settings) 