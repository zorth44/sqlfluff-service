"""
数据库连接和会话管理

提供SQLAlchemy数据库引擎、会话管理和依赖注入功能。
支持连接池、健康检查和异常处理。
"""

from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool
from sqlalchemy.exc import DisconnectionError
from typing import Generator
import logging

from app.config.settings import get_settings

logger = logging.getLogger(__name__)

# 获取配置
settings = get_settings()

# 数据库引擎配置
engine = create_engine(
    settings.get_database_url(),
    # 连接池配置
    poolclass=QueuePool,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    pool_timeout=settings.DATABASE_POOL_TIMEOUT,
    pool_recycle=settings.DATABASE_POOL_RECYCLE,
    pool_pre_ping=True,  # 启用连接健康检查
    # MySQL特定配置
    connect_args={
        "charset": "utf8mb4",
        "connect_timeout": 60,
        "read_timeout": 60,
        "write_timeout": 60,
        "autocommit": False,  # 确保事务控制
    },
    # SQL 回显独立开关；勿与 DEBUG 绑定（Worker 轮询会刷屏）
    echo=settings.DATABASE_ECHO,
    echo_pool=False,
    # 事务隔离级别 - 使用READ_COMMITTED避免幻读问题
    isolation_level="READ_COMMITTED",
)

# 会话工厂
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,  # 防止对象在提交后过期
)

# 数据模型基类
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """
    数据库会话依赖注入函数
    
    用于FastAPI的Depends()注入，自动管理数据库会话的生命周期。
    确保会话在请求结束后正确关闭。
    
    Yields:
        Session: SQLAlchemy数据库会话
    """
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        logger.error(f"数据库会话错误: {e}")
        db.rollback()
        raise
    finally:
        db.close()


def create_database_session() -> Session:
    """
    创建独立的数据库会话
    
    用于非Web环境（如Celery Worker）中创建数据库会话。
    需要手动管理会话的生命周期。
    
    Returns:
        Session: SQLAlchemy数据库会话
    """
    return SessionLocal()


def test_database_connection() -> bool:
    """
    测试数据库连接
    
    用于健康检查和启动时的连接验证。
    
    Returns:
        bool: 连接是否成功
    """
    try:
        from sqlalchemy import text
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        logger.info("数据库连接测试成功")
        return True
    except Exception as e:
        logger.error(f"数据库连接测试失败: {e}")
        return False


def close_database_connections():
    """
    关闭所有数据库连接
    
    用于应用程序关闭时清理资源。
    """
    try:
        engine.dispose()
        logger.info("数据库连接已关闭")
    except Exception as e:
        logger.error(f"关闭数据库连接时出错: {e}")


# 数据库连接池事件监听器
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """数据库连接建立时的配置"""
    # 对于MySQL，设置会话级别的配置
    try:
        cursor = dbapi_connection.cursor()
        # 设置事务隔离级别为READ_COMMITTED
        cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
        # 设置自动提交为OFF
        cursor.execute("SET SESSION autocommit = 0")
        # 设置SQL模式
        cursor.execute("SET SESSION sql_mode = 'STRICT_TRANS_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO'")
        cursor.close()
        logger.debug("MySQL会话配置已设置")
    except Exception as e:
        logger.warning(f"设置MySQL会话配置失败: {e}")


@event.listens_for(engine, "checkout")
def ping_connection(dbapi_connection, connection_record, connection_proxy):
    """连接池检出连接时的健康检查"""
    connection_record.info['pid'] = id(dbapi_connection)


@event.listens_for(engine, "checkin")
def checkin_connection(dbapi_connection, connection_record):
    """连接池归还连接时的清理"""
    pass


@event.listens_for(engine, "invalidate")
def invalidate_connection(dbapi_connection, connection_record, exception):
    """连接失效时的处理"""
    logger.warning(f"数据库连接失效: {exception}")


# 数据库会话上下文管理器
class DatabaseSessionManager:
    """数据库会话上下文管理器"""
    
    def __init__(self):
        self.session: Session = None
    
    def __enter__(self) -> Session:
        self.session = create_database_session()
        return self.session
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.session.rollback()
        else:
            self.session.commit()
        self.session.close() 