"""
统一数据库会话管理

提供 context manager 用于 Worker 中的 DB 会话管理，
确保正确的 commit / rollback / close 生命周期。
"""

from contextlib import contextmanager
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
import logging

logger = logging.getLogger(__name__)


@contextmanager
def managed_db_session() -> Session:
    """
    统一的数据库会话 context manager

    用法:
        with managed_db_session() as db:
            task = db.query(...).first()
            task.status = 'SUCCESS'
            # db.commit() 由 context manager 自动调用

    在 __exit__ 时：
    - 正常退出：自动 commit
    - 异常退出：自动 rollback
    - 无论如何：自动 close
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    else:
        db.commit()
    finally:
        db.close()
