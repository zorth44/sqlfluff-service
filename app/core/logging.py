"""
统一日志配置模块

提供结构化日志输出、不同日志级别配置、日志文件按日轮转与 gzip 压缩。
为 FastAPI Web 与 DB Worker 提供统一的日志格式和配置。
"""

import gzip
import logging
import logging.handlers
import sys
import json
import os
import re
import shutil
import time
import traceback
from datetime import datetime, date
from typing import Dict, Any, Optional, List
from pathlib import Path
from app.config.settings import settings

# 模块级变量用于存储上下文过滤器和性能日志记录器
_context_filter: Optional['ContextFilter'] = None
_performance_logger: Optional['PerformanceLogger'] = None


class GzipTimedRotatingFileHandler(logging.handlers.TimedRotatingFileHandler):
    """按日轮转；轮转时 gzip 压缩，并按 backupCount 清理历史文件（含 .gz）。"""

    # 匹配 YYYY-MM-DD 与 YYYY-MM-DD.gz（兼容尚未压缩的旧轮转文件）
    _BACKUP_EXT_MATCH = re.compile(r"^\d{4}-\d{2}-\d{2}(\.\w+)?(\.gz)?$", re.ASCII)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.namer = self._gzip_namer
        self.rotator = self._gzip_rotator

    @staticmethod
    def _gzip_namer(default_name: str) -> str:
        return default_name + ".gz"

    @staticmethod
    def _gzip_rotator(source: str, dest: str) -> None:
        with open(source, "rb") as f_in:
            with gzip.open(dest, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        os.remove(source)

    def getFilesToDelete(self) -> List[str]:
        """确定超过 backupCount 的历史文件（含未压缩与 .gz）。"""
        dir_name, base_name = os.path.split(self.baseFilename)
        prefix = base_name + "."
        plen = len(prefix)
        result = []
        try:
            file_names = os.listdir(dir_name)
        except OSError:
            return []
        for file_name in file_names:
            if file_name[:plen] == prefix:
                suffix = file_name[plen:]
                if self._BACKUP_EXT_MATCH.match(suffix):
                    result.append(os.path.join(dir_name, file_name))
        if len(result) < self.backupCount:
            return []
        result.sort()
        return result[: len(result) - self.backupCount]


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


def create_formatter() -> logging.Formatter:
    """根据 LOG_FORMAT 配置创建标准输出格式化器。"""
    if settings.LOG_FORMAT.lower() == "text":
        return TextFormatter()
    return JSONFormatter()


def create_file_formatter() -> logging.Formatter:
    """创建本地日志文件格式化器。

    本地滚动日志的首要用途是供人工排障，因此不受 ``LOG_FORMAT``
    影响，始终保持为易读的文本格式。``LOG_FORMAT`` 仅控制标准输出，
    以便日志采集系统按需接收 JSON 或文本。
    """
    return TextFormatter()


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

    console_formatter = create_formatter()
    
    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_formatter)
    console_handler.addFilter(context_filter)
    root_logger.addHandler(console_handler)
    
    # 文件处理器：按日轮转 + gzip 压缩 + 按 backupCount 保留
    if settings.LOG_FILE_PATH:
        try:
            log_file_path = Path(settings.LOG_FILE_PATH)
            log_file_path.parent.mkdir(parents=True, exist_ok=True)

            file_handler = GzipTimedRotatingFileHandler(
                filename=settings.LOG_FILE_PATH,
                when='midnight',
                interval=1,
                backupCount=settings.LOG_FILE_BACKUP_COUNT,
                encoding='utf-8',
                delay=False,
                utc=False,
            )
            file_handler.setFormatter(create_file_formatter())
            file_handler.addFilter(context_filter)
            root_logger.addHandler(file_handler)

            # 启动时若当前日志仍是跨日之前的内容，走 handler 轮转（含 gzip）
            if log_file_path.exists():
                today_start = time.mktime(date.today().timetuple())
                if os.path.getmtime(str(log_file_path)) < today_start:
                    file_handler.doRollover()
        except Exception as e:
            logging.getLogger(__name__).warning(
                f"文件日志设置失败: {e}",
                extra={'extra_data': {'error': str(e)}}
            )
    
    # 设置第三方库日志级别（高频噪音默认压到 WARNING）
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
    logging.getLogger("watchfiles").setLevel(logging.WARNING)
    logging.getLogger("watchfiles.main").setLevel(logging.WARNING)
    # SQLFluff 内部会输出解析树等大段文本，避免刷屏拖慢 Worker
    logging.getLogger("sqlfluff").setLevel(logging.WARNING)
    
    logging.info("Logging system initialized", extra={
        'log_level': settings.LOG_LEVEL,
        'log_format': settings.LOG_FORMAT,
        'log_file': settings.LOG_FILE_PATH or 'console only'
    })


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
    
    # SQL 语句仅在显式开启 DATABASE_ECHO 时输出
    if settings.DATABASE_ECHO:
        logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
    else:
        logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)


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
