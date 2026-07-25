"""
统一编码检测工具

从 SQLFluffService 和 Celery tasks 中提取重复的编码检测逻辑，
提供统一的文件编码检测和读取接口。

支持的编码（按优先级）：
- utf-8, utf-8-sig, gbk, gb2312, latin-1, cp1252
"""

import logging
from pathlib import Path
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

# 编码检测优先级列表
ENCODING_PRIORITY: List[str] = [
    'utf-8',
    'utf-8-sig',
    'gbk',
    'gb2312',
    'latin-1',
    'cp1252',
]


def detect_file_content(file_path: Path) -> str:
    """
    使用编码检测读取文件全部内容

    按 ENCODING_PRIORITY 顺序尝试解码，返回第一个成功的结果。
    如果所有编码都失败，尝试 UTF-8 替换模式，再失败则使用二进制回退。

    Args:
        file_path: 文件路径（Path 对象）

    Returns:
        str: 文件内容

    Raises:
        UnicodeDecodeError: 所有编码尝试均失败时抛出
    """
    for encoding in ENCODING_PRIORITY:
        try:
            content = file_path.read_text(encoding=encoding)
            # 移除 UTF-8 BOM 标记
            if encoding == 'utf-8' and content and content.startswith('﻿'):
                content = content[1:]
            logger.debug(f"Successfully read file with encoding {encoding}: {file_path}")
            return content
        except UnicodeDecodeError:
            continue
        except Exception as e:
            logger.debug(f"Failed to read with encoding {encoding}: {e}")
            continue

    # 二进制模式回退：检查是否二进制文件
    try:
        raw_content = file_path.read_bytes()
        if b'\x00' in raw_content:
            raise ValueError(f"File appears to be binary, not text: {file_path}")

        # 使用 UTF-8 替换错误字符
        content = raw_content.decode('utf-8', errors='replace')
        logger.warning(f"Read file with UTF-8 replacement mode: {file_path}")
        return content
    except Exception as e:
        raise UnicodeDecodeError(
            'utf-8',
            b'',
            0,
            1,
            f"Failed to decode file with any encoding: {file_path}, error: {e}"
        )


def read_file_content(file_path: str) -> str:
    """
    读取文件全部内容（支持字符串路径）

    Args:
        file_path: 文件路径（字符串）

    Returns:
        str: 文件内容
    """
    return detect_file_content(Path(file_path))


def count_file_lines(file_path: str) -> Optional[int]:
    """
    计算文件行数（自动编码检测）

    Args:
        file_path: 文件路径（字符串）

    Returns:
        Optional[int]: 行数，失败时返回 None
    """
    path = Path(file_path)
    if not path.exists():
        return None

    for encoding in ENCODING_PRIORITY:
        try:
            with open(path, 'r', encoding=encoding) as f:
                line_count = sum(1 for _ in f)
            logger.debug(f"Counted {line_count} lines with encoding {encoding}: {file_path}")
            return line_count
        except UnicodeDecodeError:
            continue

    # UTF-8 替换模式回退
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            line_count = sum(1 for _ in f)
        logger.warning(f"Counted {line_count} lines with UTF-8 replace mode: {file_path}")
        return line_count
    except Exception:
        pass

    return None


def build_line_map(file_path: str) -> Dict[int, str]:
    """
    构建文件行号到行内容的映射

    用于填充 linting_violations 表的 sql_line 字段。

    Args:
        file_path: 文件路径（字符串）

    Returns:
        Dict[int, str]: {line_no: line_content}，行号从 1 开始
    """
    path = Path(file_path)
    if not path.exists():
        return {}

    for encoding in ENCODING_PRIORITY:
        try:
            with open(path, 'r', encoding=encoding) as f:
                lines = f.readlines()
            line_map = {
                idx + 1: line.rstrip('\r\n')
                for idx, line in enumerate(lines)
            }
            logger.debug(f"Built line map with encoding {encoding}: {file_path}")
            return line_map
        except UnicodeDecodeError:
            continue

    # UTF-8 替换模式回退
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        line_map = {
            idx + 1: line.rstrip('\r\n')
            for idx, line in enumerate(lines)
        }
        logger.warning(f"Built line map with UTF-8 replace mode: {file_path}")
        return line_map
    except Exception:
        pass

    return {}


def detect_file_size(file_path: str) -> Optional[int]:
    """
    获取文件大小（字节）

    Args:
        file_path: 文件路径（字符串）

    Returns:
        Optional[int]: 文件大小，不存在时返回 None
    """
    path = Path(file_path)
    if not path.exists():
        return None
    try:
        return path.stat().st_size
    except OSError:
        return None
