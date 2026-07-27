"""
统一日志配置模块

提供结构化日志输出、不同日志级别配置、日志文件轮转功能。
为FastAPI和Celery提供统一的日志格式和配置。
"""

import logging
import logging.handlers
import sys
import json
import os
import time
from datetime import datetime, date, timedelta
from typing import Dict, Any, Optional
from pathlib import Path
from app.config.settings import settings
import traceback
from contextvars import ContextVar

# 模块级变量用于存储上下文过滤器和性能日志记录器
_context_filter: Optional['ContextFilter'] = None
_performance_logger: Optional['PerformanceLogger'] = None


class JSONFormatter(logging.Formatter):
    """JSON格式化器，输出结构化日志"""
    
    def format(self, record):
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "process_id": record.process,
            "thread_id": record.thread,
        }
        
        # 添加额外字段
        if hasattr(record, 'job_id'):
            log_entry['job_id'] = record.job_id
        if hasattr(record, 'task_id'):
            log_entry['task_id'] = record.task_id
        if hasattr(record, 'user_id'):
            log_entry['user_id'] = record.user_id
        if hasattr(record, 'request_id'):
            log_entry['request_id'] = record.request_id
        if hasattr(record, 'correlation_id'):
            log_entry['correlation_id'] = record.correlation_id
            
        # 添加异常信息
        if record.exc_info:
            log_entry['exception'] = {
                'type': record.exc_info[0].__name__,
                'message': str(record.exc_info[1]),
                'traceback': self.formatException(record.exc_info)
            }
            
        # 添加额外属性
        for key, value in record.__dict__.items():
            if key not in log_entry and not key.startswith('_'):
                if isinstance(value, (str, int, float, bool, type(None))):
                    log_entry[key] = value
                else:
                    log_entry[key] = str(value)
                    
        return json.dumps(log_entry, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """文本格式化器"""
    
    def __init__(self):
        super().__init__(
            fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )


class ContextFilter(logging.Filter):
    """上下文过滤器，用于注入上下文信息"""
    
    def __init__(self):
        super().__init__()
        self.context = {}
    
    def filter(self, record):
        # 注入上下文信息
        for key, value in self.context.items():
            setattr(record, key, value)
        return True
    
    def set_context(self, **kwargs):
        """设置上下文信息"""
        self.context.update(kwargs)
    
    def clear_context(self):
        """清除上下文信息"""
        self.context.clear()


class PerformanceLogger:
    """性能日志记录器"""
    
    def __init__(self, logger):
        self.logger = logger
    
    def log_request(self, method: str, path: str, duration: float, status_code: int):
        """记录请求性能"""
        self.logger.info(
            "Request completed",
            extra={
                'event_type': 'request',
                'method': method,
                'path': path,
                'duration_ms': round(duration * 1000, 2),
                'status_code': status_code
            }
        )
    
    def log_sql_analysis(self, file_path: str, duration: float, violation_count: int):
        """记录SQL分析性能"""
        self.logger.info(
            "SQL analysis completed",
            extra={
                'event_type': 'sql_analysis',
                'file_path': file_path,
                'duration_ms': round(duration * 1000, 2),
                'violation_count': violation_count
            }
        )
    
    def log_zip_processing(self, zip_path: str, duration: float, file_count: int):
        """记录ZIP处理性能"""
        self.logger.info(
            "ZIP processing completed",
            extra={
                'event_type': 'zip_processing',
                'zip_path': zip_path,
                'duration_ms': round(duration * 1000, 2),
                'file_count': file_count
            }
        )


def setup_logging() -> None:
    """设置日志系统"""
    global _context_filter, _performance_logger
    
    # 创建上下文过滤器
    context_filter = ContextFilter()
    _context_filter = context_filter
    
    # 创建性能日志记录器
    performance_logger = PerformanceLogger(logging.getLogger("performance"))
    _performance_logger = performance_logger
    
    # 根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper()))
    
    # 清除现有处理器
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(JSONFormatter())
    console_handler.addFilter(context_filter)
    root_logger.addHandler(console_handler)
    
    # 文件处理器（如果配置了）- 使用按日期轮转的处理器
    if settings.LOG_FILE_PATH:
        try:
            # 创建日志目录（如果不存在）
            log_file_path = Path(settings.LOG_FILE_PATH)
            log_file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 获取今天的日期（在检查文件之前）
            today = date.today()
            
            # 检查日志文件是否存在，如果存在且是昨天的，先进行轮转
            # 这样可以确保服务重启时，昨天的日志文件会被正确轮转
            if log_file_path.exists():
                # 获取文件的修改时间
                file_mtime = os.path.getmtime(str(log_file_path))
                file_date = date.fromtimestamp(file_mtime)
                
                # 如果文件是昨天的或更早的，需要轮转
                if file_date < today:
                    # 重命名旧文件，添加日期后缀（使用文件最后修改日期）
                    old_suffix = file_date.strftime('%Y-%m-%d')
                    old_file = Path(f"{settings.LOG_FILE_PATH}.{old_suffix}")
                    
                    # 只有当目标文件不存在时才重命名，避免覆盖
                    if not old_file.exists():
                        try:
                            log_file_path.rename(old_file)
                        except Exception as rename_error:
                            # 如果重命名失败（可能是权限问题），尝试复制后删除
                            try:
                                import shutil
                                shutil.copy2(str(log_file_path), str(old_file))
                                # 清空原文件而不是删除，避免影响正在运行的进程
                                log_file_path.write_text('')
                            except Exception as copy_error:
                                # 如果都失败了，记录警告但继续
                                pass
            
            # 使用 TimedRotatingFileHandler 实现按日期轮转
            # when='midnight' 表示每天午夜轮转
            # backupCount 控制保留的历史日志文件数量
            file_handler = logging.handlers.TimedRotatingFileHandler(
                filename=settings.LOG_FILE_PATH,
                when='midnight',  # 每天午夜轮转
                interval=1,  # 轮转间隔（天）
                backupCount=settings.LOG_FILE_BACKUP_COUNT,  # 保留的历史文件数量
                encoding='utf-8',
                delay=False,  # 不延迟打开文件
                utc=False  # 使用本地时间
            )
            file_handler.setFormatter(JSONFormatter())
            file_handler.addFilter(context_filter)
            root_logger.addHandler(file_handler)
            
            # 重要：立即触发一次轮转检查
            # TimedRotatingFileHandler 的轮转检查是在 emit() 时进行的
            # 通过调用 doRollover() 来确保立即检查（如果文件是昨天的）
            try:
                # 如果文件存在，检查是否需要轮转
                if log_file_path.exists():
                    # 获取当前时间和今天的开始时间（午夜）
                    now = time.time()
                    today_start = time.mktime(today.timetuple())
                    file_mtime = os.path.getmtime(str(log_file_path))
                    
                    # 如果当前时间已经过了午夜，且文件是昨天的，触发轮转
                    if now >= today_start and file_mtime < today_start:
                        # 手动触发轮转
                        file_handler.doRollover()
            except Exception:
                # 忽略错误，TimedRotatingFileHandler 会在第一次写入时自动检查
                pass
        except Exception as e:
            # 如果文件日志设置失败，记录警告但不影响程序运行
            logging.getLogger(__name__).warning(
                f"文件日志设置失败: {e}",
                extra={'extra_data': {'error': str(e)}}
            )
    
    # 设置第三方库日志级别
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
    # SQLFluff 内部会输出解析树等大段文本，避免刷屏拖慢 Worker
    logging.getLogger("sqlfluff").setLevel(logging.WARNING)
    
    logging.info("Logging system initialized", extra={
        'log_level': settings.LOG_LEVEL,
        'log_file': settings.LOG_FILE_PATH or 'console only'
    })


def setup_file_logging(formatter: logging.Formatter, context_filter: ContextFilter) -> None:
    """设置文件日志处理器"""
    try:
        # 创建日志目录
        log_file_path = Path(settings.LOG_FILE_PATH)
        log_file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 解析文件大小
        max_bytes = parse_file_size(settings.LOG_FILE_MAX_SIZE)
        
        # 创建轮转文件处理器
        file_handler = logging.handlers.RotatingFileHandler(
            filename=settings.LOG_FILE_PATH,
            maxBytes=max_bytes,
            backupCount=settings.LOG_FILE_BACKUP_COUNT,
            encoding='utf-8'
        )
        
        file_handler.setFormatter(formatter)
        file_handler.addFilter(context_filter)
        
        # 添加到根日志记录器
        logging.getLogger().addHandler(file_handler)
        
    except Exception as e:
        # 如果文件日志设置失败，记录警告但不影响程序运行
        logging.getLogger(__name__).warning(
            f"文件日志设置失败: {e}",
            extra={'extra_data': {'error': str(e)}}
        )


def setup_third_party_logging() -> None:
    """设置第三方库的日志级别"""
    
    # 根据环境设置不同的日志级别
    if settings.is_production():
        third_party_level = logging.WARNING
    else:
        third_party_level = logging.INFO
    
    # 设置常见第三方库的日志级别
    third_party_loggers = [
        'uvicorn',
        'uvicorn.access',
        'fastapi',
        'sqlalchemy',
        'sqlalchemy.engine',
        'celery',
        'redis',
        'httpx',
        'urllib3',
        # SQLFluff 内部会输出解析树等大段文本，统一压到 WARNING
        'sqlfluff',
    ]
    
    for logger_name in third_party_loggers:
        logging.getLogger(logger_name).setLevel(third_party_level)

    # 无论环境，都避免 sqlfluff 解析树刷屏
    logging.getLogger('sqlfluff').setLevel(logging.WARNING)
    
    # 特殊处理：SQLAlchemy引擎日志
    if settings.is_development():
        # 开发环境下可以看到SQL语句
        logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
    else:
        # 生产环境下关闭SQL语句日志
        logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)


def parse_file_size(size_str: str) -> int:
    """解析文件大小字符串，如 '100MB', '1GB' 等"""
    size_str = size_str.upper().strip()
    
    if size_str.endswith('KB'):
        return int(float(size_str[:-2]) * 1024)
    elif size_str.endswith('MB'):
        return int(float(size_str[:-2]) * 1024 * 1024)
    elif size_str.endswith('GB'):
        return int(float(size_str[:-2]) * 1024 * 1024 * 1024)
    else:
        # 默认按字节处理
        return int(size_str)


def get_logger(name: str) -> logging.Logger:
    """获取日志记录器"""
    return logging.getLogger(name)


def log_with_context(logger: logging.Logger, level: str, message: str, **context):
    """带上下文的日志记录"""
    # 设置上下文
    if _context_filter is not None:
        _context_filter.set_context(**context)
    
    # 记录日志
    log_func = getattr(logger, level.lower())
    log_func(message)
    
    # 清除上下文
    if _context_filter is not None:
        _context_filter.clear_context()


def log_job_event(logger: logging.Logger, event: str, job_id: str, **kwargs):
    """记录Job事件"""
    log_with_context(
        logger, 'info', f"Job {event}",
        job_id=job_id,
        event_type=f'job_{event.lower()}',
        **kwargs
    )


def log_task_event(logger: logging.Logger, event: str, task_id: str, job_id: str, **kwargs):
    """记录Task事件"""
    log_with_context(
        logger, 'info', f"Task {event}",
        task_id=task_id,
        job_id=job_id,
        event_type=f'task_{event.lower()}',
        **kwargs
    )


def log_error_with_context(logger: logging.Logger, error: Exception, context: Dict[str, Any]):
    """记录带上下文的错误"""
    log_with_context(
        logger, 'error', f"Error occurred: {str(error)}",
        error_type=type(error).__name__,
        error_message=str(error),
        traceback=traceback.format_exc(),
        **context
    )


def log_performance_metric(metric_name: str, value: float, unit: str = "ms", **labels):
    """记录性能指标"""
    if _performance_logger is not None:
        logger = logging.getLogger("performance")
        log_with_context(
            logger, 'info', f"Performance metric: {metric_name}",
            metric_name=metric_name,
            metric_value=value,
            metric_unit=unit,
            event_type='performance_metric',
            **labels
        )


# 预定义的日志记录器
app_logger = get_logger('app')
api_logger = get_logger('api')
worker_logger = get_logger('worker')
database_logger = get_logger('database')
sqlfluff_logger = get_logger('sqlfluff')
file_logger = get_logger('file')
service_logger = get_logger('service')


# 模块加载时自动设置日志
setup_logging() 