"""
SQL文件读取工具

提供多编码支持的SQL文件读取功能，用于HTML报告生成。
支持UTF-8、GBK、GB18030、Latin1等多种编码格式。
"""

from pathlib import Path
from typing import Optional, List, Tuple
import chardet

from app.core.logging import file_logger
from app.config.settings import settings


class SQLFileReader:
    """SQL文件读取器，支持多种编码"""

    # 支持的编码列表，按优先级排序
    ENCODINGS = ['utf-8', 'gbk', 'gb18030', 'gb2312', 'latin1', 'iso-8859-1']

    @classmethod
    def read_sql_file(cls, file_path: str) -> Tuple[Optional[str], Optional[str]]:
        """
        读取SQL文件，自动尝试多种编码

        Args:
            file_path: 文件路径（相对于NFS根目录）

        Returns:
            Tuple[Optional[str], Optional[str]]: (文件内容, 使用的编码)
                如果读取失败，返回 (None, None)
        """
        from app.utils.file_utils import file_manager

        absolute_path = file_manager.get_absolute_path(file_path)

        if not absolute_path.exists():
            file_logger.warning(f"SQL文件不存在: {file_path}")
            return None, None

        # 先尝试使用chardet检测编码
        detected_encoding = cls._detect_encoding(absolute_path)
        if detected_encoding:
            content = cls._try_read_with_encoding(absolute_path, detected_encoding)
            if content is not None:
                file_logger.debug(f"使用检测的编码读取文件: {detected_encoding}, {file_path}")
                return content, detected_encoding

        # 如果检测失败，依次尝试常用编码
        for encoding in cls.ENCODINGS:
            content = cls._try_read_with_encoding(absolute_path, encoding)
            if content is not None:
                file_logger.debug(f"使用编码读取文件成功: {encoding}, {file_path}")
                return content, encoding

        # 所有编码都失败
        file_logger.error(f"无法读取SQL文件（所有编码尝试失败）: {file_path}")
        return None, None

    @classmethod
    def read_sql_file_lines(cls, file_path: str) -> Tuple[Optional[List[str]], Optional[str]]:
        """
        读取SQL文件并返回行列表

        Args:
            file_path: 文件路径（相对于NFS根目录）

        Returns:
            Tuple[Optional[List[str]], Optional[str]]: (行列表, 使用的编码)
                如果读取失败，返回 (None, None)
        """
        content, encoding = cls.read_sql_file(file_path)
        if content is None:
            return None, None

        lines = content.splitlines()
        return lines, encoding

    @classmethod
    def _detect_encoding(cls, file_path: Path) -> Optional[str]:
        """
        使用chardet检测文件编码

        Args:
            file_path: 文件路径对象

        Returns:
            Optional[str]: 检测到的编码名称，如果无法检测返回None
        """
        try:
            with open(file_path, 'rb') as f:
                # 读取前10000字节用于检测
                raw_data = f.read(10000)
                result = chardet.detect(raw_data)

                if result and result['encoding'] and result['confidence'] > 0.7:
                    return result['encoding'].lower()
        except Exception as e:
            file_logger.debug(f"编码检测失败: {file_path}, {e}")

        return None

    @classmethod
    def _try_read_with_encoding(cls, file_path: Path, encoding: str) -> Optional[str]:
        """
        尝试使用指定编码读取文件

        Args:
            file_path: 文件路径对象
            encoding: 编码名称

        Returns:
            Optional[str]: 文件内容，失败返回None
        """
        try:
            with open(file_path, 'r', encoding=encoding, errors='strict') as f:
                content = f.read()
            return content
        except (UnicodeDecodeError, LookupError):
            return None
        except Exception as e:
            file_logger.debug(f"读取文件失败 (编码: {encoding}): {file_path}, {e}")
            return None


def read_sql_file_safe(file_path: str) -> Optional[str]:
    """
    安全读取SQL文件（便捷函数）

    Args:
        file_path: 文件路径（相对于NFS根目录）

    Returns:
        Optional[str]: 文件内容，失败返回None
    """
    content, _ = SQLFileReader.read_sql_file(file_path)
    return content


def read_sql_file_lines_safe(file_path: str) -> Optional[List[str]]:
    """
    安全读取SQL文件行列表（便捷函数）

    Args:
        file_path: 文件路径（相对于NFS根目录）

    Returns:
        Optional[List[str]]: 行列表，失败返回None
    """
    lines, _ = SQLFileReader.read_sql_file_lines(file_path)
    return lines
