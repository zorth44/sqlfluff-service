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
    
    # ============= Redis配置 =============
    REDIS_HOST: str = Field(description="Redis主机地址", env="REDIS_HOST")
    REDIS_PORT: int = Field(description="Redis端口", env="REDIS_PORT")
    REDIS_USERNAME: Optional[str] = Field(default=None, description="Redis用户名", env="REDIS_USERNAME")
    REDIS_PASSWORD: Optional[str] = Field(default=None, description="Redis密码", env="REDIS_PASSWORD")
    REDIS_DB_BROKER: int = Field(default=0, description="Celery消息代理使用的Redis数据库", env="REDIS_DB_BROKER")
    REDIS_DB_RESULT: int = Field(default=1, description="Celery结果后端使用的Redis数据库", env="REDIS_DB_RESULT")
    REDIS_MAX_CONNECTIONS: int = Field(default=50, description="Redis最大连接数")
    
    # Redis集群配置
    REDIS_CLUSTER_ENABLED: bool = Field(default=False, description="是否启用Redis集群模式", env="REDIS_CLUSTER_ENABLED")
    REDIS_CLUSTER_NODES: Optional[str] = Field(default=None, description="Redis集群节点列表(格式: host1:port1,host2:port2)", env="REDIS_CLUSTER_NODES")
    REDIS_CLUSTER_KEY_PREFIX: str = Field(default="{celery}:", description="Redis集群键前缀，解决cross-slot问题", env="REDIS_CLUSTER_KEY_PREFIX")
    REDIS_CLUSTER_DISABLE_PIPELINE: bool = Field(default=True, description="是否禁用Redis集群管道操作（解决MovedError）", env="REDIS_CLUSTER_DISABLE_PIPELINE")
    
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
    
    def get_celery_broker_url(self) -> str:
        """获取Celery Broker Redis连接URL"""
        from urllib.parse import quote_plus
        
        # 如果启用了集群模式，使用自定义的集群传输
        if self.REDIS_CLUSTER_ENABLED and self.REDIS_CLUSTER_NODES:
            # 解析第一个节点作为broker URL，使用自定义传输协议
            first_node = self.REDIS_CLUSTER_NODES.split(',')[0].strip()
            host, port = first_node.split(':')
            
            auth = ""
            if self.REDIS_USERNAME and self.REDIS_PASSWORD:
                username = quote_plus(self.REDIS_USERNAME)
                password = quote_plus(self.REDIS_PASSWORD)
                auth = f"{username}:{password}@"
            elif self.REDIS_PASSWORD:
                password = quote_plus(self.REDIS_PASSWORD)
                auth = f":{password}@"
            
            # 仍使用标准redis协议，但配置会禁用管道操作
            return f"redis://{auth}{host}:{port}/{self.REDIS_DB_BROKER}"
        
        # 单节点模式
        auth = ""
        if self.REDIS_USERNAME and self.REDIS_PASSWORD:
            # URL编码用户名和密码以处理特殊字符
            username = quote_plus(self.REDIS_USERNAME)
            password = quote_plus(self.REDIS_PASSWORD)
            auth = f"{username}:{password}@"
        elif self.REDIS_PASSWORD:
            # URL编码密码以处理特殊字符
            password = quote_plus(self.REDIS_PASSWORD)
            auth = f":{password}@"
        
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB_BROKER}"
    
    @property
    def CELERY_BROKER_URL(self) -> str:
        """获取Celery Broker URL（属性形式）"""
        return self.get_celery_broker_url()
    
    def get_celery_result_backend_url(self) -> str:
        """获取Celery Result Backend Redis连接URL"""
        from urllib.parse import quote_plus
        
        # 如果启用了集群模式，需要使用自定义backend类，这里返回标准格式
        if self.REDIS_CLUSTER_ENABLED and self.REDIS_CLUSTER_NODES:
            # 集群模式下，result backend由celery_main.py中的自定义类处理
            # 这里返回标准URL格式，实际连接由RedisClusterBackend管理
            first_node = self.REDIS_CLUSTER_NODES.split(',')[0].strip()
            host, port = first_node.split(':')
            
            auth = ""
            if self.REDIS_USERNAME and self.REDIS_PASSWORD:
                username = quote_plus(self.REDIS_USERNAME)
                password = quote_plus(self.REDIS_PASSWORD)
                auth = f"{username}:{password}@"
            elif self.REDIS_PASSWORD:
                password = quote_plus(self.REDIS_PASSWORD)
                auth = f":{password}@"
            
            return f"redis://{auth}{host}:{port}/{self.REDIS_DB_RESULT}"
        
        # 单节点模式
        auth = ""
        if self.REDIS_USERNAME and self.REDIS_PASSWORD:
            # URL编码用户名和密码以处理特殊字符
            username = quote_plus(self.REDIS_USERNAME)
            password = quote_plus(self.REDIS_PASSWORD)
            auth = f"{username}:{password}@"
        elif self.REDIS_PASSWORD:
            # URL编码密码以处理特殊字符
            password = quote_plus(self.REDIS_PASSWORD)
            auth = f":{password}@"
        
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB_RESULT}"
    
    def get_celery_broker_cluster_url(self) -> str:
        """获取Celery Broker Redis集群连接URL"""
        from urllib.parse import quote_plus
        
        # 如果启用了集群模式，返回集群格式URL
        if self.REDIS_CLUSTER_ENABLED and self.REDIS_CLUSTER_NODES:
            # 解析第一个节点作为broker URL，使用集群格式
            first_node = self.REDIS_CLUSTER_NODES.split(',')[0].strip()
            host, port = first_node.split(':')
            
            auth = ""
            if self.REDIS_USERNAME and self.REDIS_PASSWORD:
                username = quote_plus(self.REDIS_USERNAME)
                password = quote_plus(self.REDIS_PASSWORD)
                auth = f"{username}:{password}@"
            elif self.REDIS_PASSWORD:
                password = quote_plus(self.REDIS_PASSWORD)
                auth = f":{password}@"
            
            return f"redis+cluster://{auth}{host}:{port}/{self.REDIS_DB_BROKER}"
        
        # 如果没有启用集群，返回标准URL
        return self.get_celery_broker_url()
    
    def get_redis_cluster_nodes(self) -> List[Dict[str, str]]:
        """获取Redis集群节点列表"""
        if not self.REDIS_CLUSTER_ENABLED or not self.REDIS_CLUSTER_NODES:
            return []
        
        nodes = []
        for node_str in self.REDIS_CLUSTER_NODES.split(','):
            node_str = node_str.strip()
            if ':' in node_str:
                host, port = node_str.split(':', 1)
                nodes.append({'host': host.strip(), 'port': int(port.strip())})
        
        return nodes
    
    def get_celery_redis_cluster_settings(self) -> Dict[str, Any]:
        """获取Celery Redis集群设置（用于CELERY_REDIS_CLUSTER_SETTINGS）"""
        if not self.REDIS_CLUSTER_ENABLED or not self.REDIS_CLUSTER_NODES:
            return {}
        
        # 为 redis-py 5.x 创建正确的 startup_nodes 格式
        from redis.cluster import ClusterNode
        
        startup_nodes = []
        for node_str in self.REDIS_CLUSTER_NODES.split(','):
            node_str = node_str.strip()
            if ':' in node_str:
                host, port = node_str.split(':', 1)
                # 使用 ClusterNode 对象而不是字典
                startup_nodes.append(ClusterNode(host.strip(), int(port.strip())))
        
        cluster_settings = {
            'startup_nodes': startup_nodes,
            'decode_responses': True,
            'skip_full_coverage_check': True,
            'max_connections_per_node': 10,
            # 明确禁用管道相关功能
            'readonly_mode': False,
            'reinitialize_steps': 10,
            'cluster_error_retry_attempts': 3,
            # 连接池配置
            'connection_pool_kwargs': {
                'retry_on_timeout': True,
                'socket_timeout': 5,
                'socket_connect_timeout': 5,
                'health_check_interval': 30,
            }
        }
        
        # 添加认证信息
        if self.REDIS_PASSWORD:
            cluster_settings['password'] = self.REDIS_PASSWORD
            # 更新连接池配置中的认证信息
            cluster_settings['connection_pool_kwargs']['password'] = self.REDIS_PASSWORD
            
        if self.REDIS_USERNAME:
            cluster_settings['username'] = self.REDIS_USERNAME
            cluster_settings['connection_pool_kwargs']['username'] = self.REDIS_USERNAME
        
        return cluster_settings
    
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
        # 检查Redis配置
        if not settings.REDIS_HOST or settings.REDIS_HOST in ['localhost', '127.0.0.1']:
            raise ValueError("生产环境配置 REDIS_HOST 不能为空或使用本地地址")
        
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