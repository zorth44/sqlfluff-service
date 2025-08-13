"""
规则分级映射器：按方言加载 rule_code -> severity_level 的映射，带进程内缓存。
"""

from __future__ import annotations

from typing import Dict, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.core.logging import service_logger
from app.models.database import RuleDefinition
from app.config.settings import get_settings


settings = get_settings()


class _CacheEntry:
    def __init__(self, mapping: Dict[str, str], expires_at: datetime):
        self.mapping = mapping
        self.expires_at = expires_at

    def is_valid(self) -> bool:
        return datetime.utcnow() < self.expires_at


class RuleSeverityMapper:
    """
    提供基于 `rule_definitions` 表的规则分级映射加载与缓存功能。
    缓存键：方言（与 job.dialect 一致）。
    """

    _cache: Dict[str, _CacheEntry] = {}

    @classmethod
    def get_mapping_for_dialect(cls, db: Session, dialect: str) -> Dict[str, str]:
        """
        获取指定方言的 rule_code -> severity_level 映射。
        先查进程内缓存；过期或没有则从数据库加载并刷新缓存。
        """
        try:
            ttl_seconds = max(10, int(settings.RULE_SEVERITY_CACHE_TTL_SECONDS))
        except Exception:
            ttl_seconds = 600

        if settings.RULE_SEVERITY_ENABLED is False:
            return {}

        cache_entry = cls._cache.get(dialect)
        if cache_entry and cache_entry.is_valid():
            return cache_entry.mapping

        # 加载数据库并进行 Python 层过滤（避免 JSON_CONTAINS 的方言差异）
        try:
            records = (
                db.query(RuleDefinition)
                .filter(RuleDefinition.is_active == True)  # noqa: E712
                .all()
            )

            mapping: Dict[str, str] = {}
            for rec in records:
                try:
                    tech_stack = rec.applicable_tech_stack or []
                    if isinstance(tech_stack, dict):
                        # 兼容可能的对象格式，取 values 展开
                        tech_stack = list(tech_stack.values())
                    if not isinstance(tech_stack, (list, tuple, set)):
                        tech_stack = []

                    if dialect in tech_stack or "all" in tech_stack or "ansi" in tech_stack:
                        # 命中此方言或通用
                        mapping[rec.rule_code] = rec.severity_level
                except Exception as rec_err:
                    service_logger.debug(f"跳过无效rule_definitions记录: {rec} err={rec_err}")

            cls._cache[dialect] = _CacheEntry(
                mapping=mapping,
                expires_at=datetime.utcnow() + timedelta(seconds=ttl_seconds),
            )
            service_logger.debug(f"加载分级映射: dialect={dialect}, size={len(mapping)}")
            return mapping
        except Exception as e:
            service_logger.warning(f"加载规则分级映射失败，将使用空映射: {e}")
            return {}

    @classmethod
    def clear_cache(cls, dialect: Optional[str] = None):
        if dialect:
            cls._cache.pop(dialect, None)
        else:
            cls._cache.clear()



