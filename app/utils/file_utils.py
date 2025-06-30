"""
文件操作工具类

提供NFS路径操作、文件读写、目录管理、文件验证等功能。
为SQL文件处理和结果存储提供统一的文件操作接口。
"""

import os
import shutil
import zipfile
import tempfile
import mimetypes
from pathlib import Path
from typing import List, Optional, Tuple, Union, Dict, Any
from datetime import datetime
import json

from app.config.settings import settings
from app.core.exceptions import FileException, ZipException
from app.core.logging import file_logger


class FileManager:
    """文件管理器"""
    
    def __init__(self, nfs_root: Optional[str] = None):
        """初始化文件管理器
        
        Args:
            nfs_root: NFS根目录路径，如果为None则使用配置中的路径
        """
        self.nfs_root = Path(nfs_root or settings.NFS_SHARE_ROOT_PATH)
        self._ensure_nfs_root_exists()
        
        # 支持的SQL文件扩展名
        self.sql_extensions = {'.sql', '.SQL'}
        
        # 支持的压缩文件扩展名
        self.archive_extensions = {'.zip', '.ZIP'}
        
        # 最大文件大小（字节）
        self.max_file_size = settings.MAX_FILE_SIZE
        
        # ZIP包中最大文件数
        self.max_zip_files = settings.MAX_ZIP_FILES
    
    def _ensure_nfs_root_exists(self) -> None:
        """确保NFS根目录存在"""
        try:
            self.nfs_root.mkdir(parents=True, exist_ok=True)
            
            # 测试写权限
            test_file = self.nfs_root / '.write_test'
            test_file.write_text('test')
            test_file.unlink()
            
            file_logger.info(f"NFS根目录初始化成功: {self.nfs_root}")
        except Exception as e:
            file_logger.error(f"NFS根目录初始化失败: {e}")
            raise FileException("初始化", str(self.nfs_root), f"NFS根目录不可访问: {e}")
    
    def get_absolute_path(self, relative_path: str) -> Path:
        """获取绝对路径
        
        Args:
            relative_path: 相对于NFS根目录的路径
            
        Returns:
            Path: 绝对路径对象
        """
        return self.nfs_root / relative_path.lstrip('/')
    
    def get_relative_path(self, absolute_path: Union[str, Path]) -> str:
        """获取相对路径
        
        Args:
            absolute_path: 绝对路径
            
        Returns:
            str: 相对于NFS根目录的路径
        """
        abs_path = Path(absolute_path)
        try:
            return str(abs_path.relative_to(self.nfs_root))
        except ValueError:
            # 如果路径不在NFS根目录下，返回原路径
            return str(abs_path)
    
    def create_directory(self, relative_path: str) -> Path:
        """创建目录
        
        Args:
            relative_path: 相对目录路径
            
        Returns:
            Path: 创建的目录路径
        """
        dir_path = self.get_absolute_path(relative_path)
        try:
            dir_path.mkdir(parents=True, exist_ok=True)
            file_logger.debug(f"创建目录: {dir_path}")
            return dir_path
        except Exception as e:
            raise FileException("创建目录", str(dir_path), str(e))
    
    def write_text_file(self, relative_path: str, content: str, encoding: str = 'utf-8') -> Path:
        """写入文本文件
        
        Args:
            relative_path: 相对文件路径
            content: 文件内容
            encoding: 文件编码
            
        Returns:
            Path: 写入的文件路径
        """
        file_path = self.get_absolute_path(relative_path)
        
        try:
            # 确保父目录存在
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 写入文件
            file_path.write_text(content, encoding=encoding)
            
            file_logger.debug(f"写入文件: {file_path}, 大小: {len(content)} 字符")
            return file_path
            
        except Exception as e:
            raise FileException("写入", str(file_path), str(e))
    
    def read_text_file(self, relative_path: str, encoding: str = 'utf-8') -> str:
        """读取文本文件
        
        Args:
            relative_path: 相对文件路径
            encoding: 文件编码
            
        Returns:
            str: 文件内容
        """
        file_path = self.get_absolute_path(relative_path)
        
        if not file_path.exists():
            raise FileException("读取", str(file_path), "文件不存在")
        
        try:
            content = file_path.read_text(encoding=encoding)
            file_logger.debug(f"读取文件: {file_path}, 大小: {len(content)} 字符")
            return content
        except Exception as e:
            raise FileException("读取", str(file_path), str(e))
    
    def write_json_file(self, relative_path: str, data: Any, ensure_ascii: bool = False) -> Path:
        """写入JSON文件
        
        Args:
            relative_path: 相对文件路径
            data: 要写入的数据
            ensure_ascii: 是否确保ASCII编码
            
        Returns:
            Path: 写入的文件路径
        """
        json_content = json.dumps(data, ensure_ascii=ensure_ascii, indent=2, default=str)
        return self.write_text_file(relative_path, json_content)
    
    def read_json_file(self, relative_path: str) -> Any:
        """读取JSON文件
        
        Args:
            relative_path: 相对文件路径
            
        Returns:
            Any: 解析的JSON数据
        """
        content = self.read_text_file(relative_path)
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise FileException("解析JSON", relative_path, str(e))
    
    def copy_file(self, src_relative_path: str, dst_relative_path: str) -> Path:
        """复制文件
        
        Args:
            src_relative_path: 源文件相对路径
            dst_relative_path: 目标文件相对路径
            
        Returns:
            Path: 目标文件路径
        """
        src_path = self.get_absolute_path(src_relative_path)
        dst_path = self.get_absolute_path(dst_relative_path)
        
        if not src_path.exists():
            raise FileException("复制", str(src_path), "源文件不存在")
        
        try:
            # 确保目标目录存在
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            
            shutil.copy2(src_path, dst_path)
            file_logger.debug(f"复制文件: {src_path} -> {dst_path}")
            return dst_path
            
        except Exception as e:
            raise FileException("复制", str(src_path), str(e))
    
    def move_file(self, src_relative_path: str, dst_relative_path: str) -> Path:
        """移动文件
        
        Args:
            src_relative_path: 源文件相对路径
            dst_relative_path: 目标文件相对路径
            
        Returns:
            Path: 目标文件路径
        """
        src_path = self.get_absolute_path(src_relative_path)
        dst_path = self.get_absolute_path(dst_relative_path)
        
        if not src_path.exists():
            raise FileException("移动", str(src_path), "源文件不存在")
        
        try:
            # 确保目标目录存在
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            
            shutil.move(str(src_path), str(dst_path))
            file_logger.debug(f"移动文件: {src_path} -> {dst_path}")
            return dst_path
            
        except Exception as e:
            raise FileException("移动", str(src_path), str(e))
    
    def delete_file(self, relative_path: str) -> None:
        """删除文件
        
        Args:
            relative_path: 相对文件路径
        """
        file_path = self.get_absolute_path(relative_path)
        
        if not file_path.exists():
            file_logger.warning(f"删除文件失败，文件不存在: {file_path}")
            return
        
        try:
            if file_path.is_file():
                file_path.unlink()
            elif file_path.is_dir():
                shutil.rmtree(file_path)
            
            file_logger.debug(f"删除文件: {file_path}")
            
        except Exception as e:
            raise FileException("删除", str(file_path), str(e))
    
    def delete_directory(self, relative_path: str, recursive: bool = False) -> None:
        """删除目录
        
        Args:
            relative_path: 相对目录路径
            recursive: 是否递归删除
        """
        dir_path = self.get_absolute_path(relative_path)
        
        if not dir_path.exists():
            file_logger.warning(f"删除目录失败，目录不存在: {dir_path}")
            return
        
        try:
            if recursive:
                shutil.rmtree(dir_path)
            else:
                dir_path.rmdir()
            
            file_logger.debug(f"删除目录: {dir_path}")
            
        except Exception as e:
            raise FileException("删除目录", str(dir_path), str(e))
    
    def file_exists(self, relative_path: str) -> bool:
        """检查文件是否存在
        
        Args:
            relative_path: 相对文件路径
            
        Returns:
            bool: 文件是否存在
        """
        return self.get_absolute_path(relative_path).exists()
    
    def get_file_size(self, relative_path: str) -> int:
        """获取文件大小
        
        Args:
            relative_path: 相对文件路径
            
        Returns:
            int: 文件大小（字节）
        """
        file_path = self.get_absolute_path(relative_path)
        
        if not file_path.exists():
            raise FileException("获取大小", str(file_path), "文件不存在")
        
        return file_path.stat().st_size
    
    def get_file_info(self, relative_path: str) -> Dict[str, Any]:
        """获取文件信息
        
        Args:
            relative_path: 相对文件路径
            
        Returns:
            Dict[str, Any]: 文件信息
        """
        file_path = self.get_absolute_path(relative_path)
        
        if not file_path.exists():
            raise FileException("获取信息", str(file_path), "文件不存在")
        
        stat = file_path.stat()
        
        return {
            'name': file_path.name,
            'size': stat.st_size,
            'created_time': datetime.fromtimestamp(stat.st_ctime),
            'modified_time': datetime.fromtimestamp(stat.st_mtime),
            'is_file': file_path.is_file(),
            'is_directory': file_path.is_dir(),
            'extension': file_path.suffix.lower(),
            'mime_type': mimetypes.guess_type(str(file_path))[0]
        }
    
    def list_files(self, relative_path: str = "", pattern: str = "*") -> List[Dict[str, Any]]:
        """列出目录中的文件
        
        Args:
            relative_path: 相对目录路径
            pattern: 文件匹配模式
            
        Returns:
            List[Dict[str, Any]]: 文件信息列表
        """
        dir_path = self.get_absolute_path(relative_path)
        
        if not dir_path.exists():
            raise FileException("列出文件", str(dir_path), "目录不存在")
        
        files = []
        try:
            for file_path in dir_path.glob(pattern):
                if file_path.is_file():
                    rel_path = self.get_relative_path(file_path)
                    files.append({
                        'relative_path': rel_path,
                        'name': file_path.name,
                        'size': file_path.stat().st_size,
                        'extension': file_path.suffix.lower(),
                        'is_sql_file': self.is_sql_file(rel_path)
                    })
        except Exception as e:
            raise FileException("列出文件", str(dir_path), str(e))
        
        return files
    
    def is_sql_file(self, relative_path: str) -> bool:
        """检查是否为SQL文件
        
        Args:
            relative_path: 相对文件路径
            
        Returns:
            bool: 是否为SQL文件
        """
        return Path(relative_path).suffix in self.sql_extensions
    
    def is_archive_file(self, relative_path: str) -> bool:
        """检查是否为压缩文件
        
        Args:
            relative_path: 相对文件路径
            
        Returns:
            bool: 是否为压缩文件
        """
        return Path(relative_path).suffix in self.archive_extensions
    
    def _is_valid_sql_file(self, file_path: Path) -> bool:
        """检查是否为有效的SQL文件
        
        Args:
            file_path: 文件路径对象
            
        Returns:
            bool: 是否为有效的SQL文件
        """
        file_name = file_path.name
        
        # 排除系统隐藏文件
        if file_name.startswith('._'):
            file_logger.debug(f"跳过系统隐藏文件: {file_name}")
            return False
        
        # 排除其他隐藏文件
        if file_name.startswith('.'):
            file_logger.debug(f"跳过隐藏文件: {file_name}")
            return False
        
        # 排除临时文件
        if file_name.startswith('~') or file_name.endswith('~'):
            file_logger.debug(f"跳过临时文件: {file_name}")
            return False
        
        # 排除空文件
        try:
            if file_path.stat().st_size == 0:
                file_logger.debug(f"跳过空文件: {file_name}")
                return False
        except OSError:
            return False
        
        # 尝试读取文件前几行来验证是否为文本文件
        try:
            # 尝试以UTF-8编码读取前1024字节
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read(1024)
                # 检查是否包含SQL关键字（简单验证）
                sql_keywords = ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER', 'SHOW', 'DESCRIBE', 'USE']
                content_upper = content.upper()
                has_sql = any(keyword in content_upper for keyword in sql_keywords)
                if not has_sql:
                    file_logger.debug(f"文件不包含SQL关键字: {file_name}")
                return has_sql
        except UnicodeDecodeError:
            file_logger.warning(f"文件编码错误，跳过: {file_name}")
            return False
        except Exception as e:
            file_logger.warning(f"验证文件失败，跳过: {file_name}, 错误: {e}")
            return False
    
    def validate_file_size(self, relative_path: str) -> None:
        """验证文件大小
        
        Args:
            relative_path: 相对文件路径
            
        Raises:
            FileException: 如果文件大小超限
        """
        file_size = self.get_file_size(relative_path)
        if file_size > self.max_file_size:
            raise FileException(
                "验证大小", 
                relative_path, 
                f"文件大小 {file_size} 字节超过限制 {self.max_file_size} 字节"
            )
    
    def extract_zip_file(self, zip_relative_path: str, extract_to: Optional[str] = None) -> Tuple[str, List[str]]:
        """解压ZIP文件
        
        Args:
            zip_relative_path: ZIP文件相对路径
            extract_to: 解压目标路径，如果为None则自动生成
            
        Returns:
            Tuple[str, List[str]]: (解压目录相对路径, SQL文件相对路径列表)
        """
        zip_path = self.get_absolute_path(zip_relative_path)
        
        if not zip_path.exists():
            raise ZipException("解压", zip_relative_path, "ZIP文件不存在")
        
        # 验证文件大小
        self.validate_file_size(zip_relative_path)
        
        # 确定解压目录
        if extract_to is None:
            extract_to = f"temp/{zip_path.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        extract_dir = self.get_absolute_path(extract_to)
        
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_file:
                # 检查ZIP文件完整性
                zip_file.testzip()
                
                # 获取文件列表
                file_list = zip_file.namelist()
                
                # 检查文件数量
                if len(file_list) > self.max_zip_files:
                    raise ZipException(
                        "解压", 
                        zip_relative_path, 
                        f"ZIP文件包含 {len(file_list)} 个文件，超过限制 {self.max_zip_files}"
                    )
                
                # 创建解压目录
                extract_dir.mkdir(parents=True, exist_ok=True)
                
                # 解压文件
                zip_file.extractall(extract_dir)
                
                file_logger.info(f"解压ZIP文件: {zip_path} -> {extract_dir}")
                
                # 查找SQL文件
                sql_files = []
                for file_path in extract_dir.rglob("*"):
                    if file_path.is_file() and file_path.suffix in self.sql_extensions:
                        # 过滤掉系统隐藏文件和临时文件
                        if self._is_valid_sql_file(file_path):
                            rel_path = self.get_relative_path(file_path)
                            sql_files.append(rel_path)
                
                return self.get_relative_path(extract_dir), sql_files
                
        except zipfile.BadZipFile:
            raise ZipException("解压", zip_relative_path, "ZIP文件损坏")
        except Exception as e:
            raise ZipException("解压", zip_relative_path, str(e))
    
    def cleanup_temp_files(self, max_age_hours: int = 24) -> None:
        """清理临时文件
        
        Args:
            max_age_hours: 最大保留时间（小时）
        """
        temp_dir = self.get_absolute_path("temp")
        
        if not temp_dir.exists():
            return
        
        current_time = datetime.now()
        cleaned_count = 0
        
        try:
            for item in temp_dir.iterdir():
                if item.is_file() or item.is_dir():
                    # 检查文件/目录的修改时间
                    modified_time = datetime.fromtimestamp(item.stat().st_mtime)
                    age_hours = (current_time - modified_time).total_seconds() / 3600
                    
                    if age_hours > max_age_hours:
                        if item.is_file():
                            item.unlink()
                        else:
                            shutil.rmtree(item)
                        cleaned_count += 1
            
            file_logger.info(f"清理临时文件完成，删除 {cleaned_count} 个项目")
            
        except Exception as e:
            file_logger.error(f"清理临时文件失败: {e}")


# 全局文件管理器实例
file_manager = FileManager()


# 便捷函数
def get_job_directory(job_id: str) -> str:
    """获取Job的目录路径"""
    return f"jobs/{job_id}"


def get_task_source_path(job_id: str, task_id: str, filename: str) -> str:
    """获取Task源文件路径"""
    return f"{get_job_directory(job_id)}/sources/{task_id}_{filename}"


def get_task_result_path(job_id: str, task_id: str) -> str:
    """获取Task结果文件路径"""
    return f"{get_job_directory(job_id)}/results/{task_id}.json"


def save_sql_content(job_id: str, task_id: str, filename: str, content: str) -> str:
    """保存SQL内容到文件
    
    Args:
        job_id: Job ID
        task_id: Task ID
        filename: 文件名
        content: SQL内容
        
    Returns:
        str: 保存的文件相对路径
    """
    relative_path = get_task_source_path(job_id, task_id, filename)
    file_manager.write_text_file(relative_path, content)
    return relative_path


def save_task_result(job_id: str, task_id: str, result_data: Any) -> str:
    """保存Task结果
    
    Args:
        job_id: Job ID
        task_id: Task ID
        result_data: 结果数据
        
    Returns:
        str: 保存的结果文件相对路径
    """
    relative_path = get_task_result_path(job_id, task_id)
    file_manager.write_json_file(relative_path, result_data)
    return relative_path


def read_task_result(job_id: str, task_id: str) -> Any:
    """读取Task结果
    
    Args:
        job_id: Job ID
        task_id: Task ID
        
    Returns:
        Any: 结果数据
    """
    relative_path = get_task_result_path(job_id, task_id)
    return file_manager.read_json_file(relative_path)


# ============= 扩展功能：SQL文件和ZIP包处理 =============

def save_sql_content_with_name(job_id: str, file_name: str, content: str) -> str:
    """
    保存SQL内容到指定文件名
    
    Args:
        job_id: Job ID
        file_name: 文件名
        content: SQL内容
        
    Returns:
        str: 保存的文件相对路径
    """
    relative_path = f"jobs/{job_id}/sources/{file_name}"
    file_manager.write_text_file(relative_path, content)
    file_logger.info(f"保存SQL文件: {relative_path}")
    return relative_path


def extract_and_process_zip(job_id: str, zip_path: str) -> Tuple[str, List[str]]:
    """
    解压ZIP文件并处理SQL文件
    
    Args:
        job_id: Job ID
        zip_path: ZIP文件路径
        
    Returns:
        Tuple[str, List[str]]: (解压目录, SQL文件路径列表)
    """
    # 解压到指定目录
    extract_to = f"jobs/{job_id}/extracted"
    extracted_dir, sql_files = file_manager.extract_zip_file(zip_path, extract_to)
    
    # 构造完整的SQL文件路径列表
    sql_file_paths = []
    for sql_file in sql_files:
        full_path = os.path.join(extracted_dir, sql_file).replace('\\', '/')
        sql_file_paths.append(full_path)
    
    file_logger.info(f"ZIP解压完成: {zip_path}, 找到SQL文件: {len(sql_files)}个")
    return extracted_dir, sql_file_paths


def find_all_sql_files(directory_path: str) -> List[str]:
    """
    递归查找目录下的所有SQL文件
    
    Args:
        directory_path: 目录路径（相对于NFS根目录）
        
    Returns:
        List[str]: SQL文件路径列表
    """
    try:
        files = file_manager.list_files(directory_path, "*.sql")
        sql_files = []
        
        for file_info in files:
            if file_info['is_file'] and file_manager.is_sql_file(file_info['path']):
                sql_files.append(file_info['path'])
        
        file_logger.debug(f"找到SQL文件: {len(sql_files)}个, 目录: {directory_path}")
        return sql_files
        
    except Exception as e:
        file_logger.error(f"查找SQL文件失败: {directory_path}, 错误: {e}")
        return []


def generate_analysis_result_path(job_id: str, task_id: str, file_name: str = None) -> str:
    """
    生成分析结果文件路径
    
    Args:
        job_id: Job ID
        task_id: Task ID
        file_name: 原文件名（可选）
        
    Returns:
        str: 结果文件路径
    """
    if file_name:
        # 保留原文件名，但改为.json扩展名
        name_without_ext = os.path.splitext(file_name)[0]
        result_name = f"{name_without_ext}_result.json"
    else:
        result_name = f"{task_id}_result.json"
    
    return f"jobs/{job_id}/results/{result_name}"


def save_analysis_result(job_id: str, task_id: str, result_data: Dict[str, Any], 
                        file_name: str = None) -> str:
    """
    保存分析结果到JSON文件
    
    Args:
        job_id: Job ID
        task_id: Task ID
        result_data: 分析结果数据
        file_name: 原文件名（可选）
        
    Returns:
        str: 保存的结果文件路径
    """
    result_path = generate_analysis_result_path(job_id, task_id, file_name)
    
    # 添加保存时间戳
    result_data_with_timestamp = {
        **result_data,
        "saved_at": datetime.now().isoformat(),
        "task_id": task_id,
        "job_id": job_id
    }
    
    file_manager.write_json_file(result_path, result_data_with_timestamp)
    file_logger.info(f"保存分析结果: {result_path}")
    return result_path


def load_analysis_result(result_path: str) -> Dict[str, Any]:
    """
    从JSON文件加载分析结果
    
    Args:
        result_path: 结果文件路径
        
    Returns:
        Dict[str, Any]: 分析结果数据
    """
    result_data = file_manager.read_json_file(result_path)
    file_logger.debug(f"加载分析结果: {result_path}")
    return result_data


def cleanup_job_temp_files(job_id: str, max_age_hours: int = 24) -> None:
    """
    清理Job的临时文件
    
    Args:
        job_id: Job ID
        max_age_hours: 文件最大存活时间（小时）
    """
    try:
        # 清理解压目录
        extracted_dir = f"jobs/{job_id}/extracted"
        if file_manager.file_exists(extracted_dir):
            # 检查目录年龄
            dir_info = file_manager.get_file_info(extracted_dir)
            if dir_info:
                created_time = dir_info.get('created_time', datetime.now())
                age_hours = (datetime.now() - created_time).total_seconds() / 3600
                
                if age_hours > max_age_hours:
                    file_manager.delete_directory(extracted_dir, recursive=True)
                    file_logger.info(f"清理过期临时目录: {extracted_dir}")
        
        # 可以添加更多清理逻辑...
        
    except Exception as e:
        file_logger.error(f"清理临时文件失败: {job_id}, 错误: {e}")


def get_file_content_preview(file_path: str, max_lines: int = 10) -> str:
    """
    获取文件内容预览
    
    Args:
        file_path: 文件路径
        max_lines: 最大行数
        
    Returns:
        str: 文件内容预览
    """
    try:
        content = file_manager.read_text_file(file_path)
        lines = content.split('\n')
        
        if len(lines) <= max_lines:
            return content
        else:
            preview_lines = lines[:max_lines]
            preview_lines.append(f"... (省略 {len(lines) - max_lines} 行)")
            return '\n'.join(preview_lines)
            
    except Exception as e:
        file_logger.error(f"获取文件预览失败: {file_path}, 错误: {e}")
        return f"无法预览文件: {e}"


def validate_sql_file_content(file_path: str) -> Dict[str, Any]:
    """
    验证SQL文件内容的基本格式
    
    Args:
        file_path: SQL文件路径
        
    Returns:
        Dict[str, Any]: 验证结果
    """
    try:
        if not file_manager.file_exists(file_path):
            return {
                "is_valid": False,
                "error": "文件不存在"
            }
        
        content = file_manager.read_text_file(file_path)
        
        # 基本验证
        if not content.strip():
            return {
                "is_valid": False,
                "error": "文件内容为空"
            }
        
        # 检查是否包含SQL关键字
        sql_keywords = ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER', 'DROP']
        content_upper = content.upper()
        has_sql_keywords = any(keyword in content_upper for keyword in sql_keywords)
        
        if not has_sql_keywords:
            return {
                "is_valid": False,
                "error": "文件不包含有效的SQL关键字"
            }
        
        file_info = file_manager.get_file_info(file_path)
        
        return {
            "is_valid": True,
            "file_size": file_info.get("size", 0),
            "line_count": len(content.split('\n')),
            "character_count": len(content),
            "encoding": "utf-8"
        }
        
    except Exception as e:
        return {
            "is_valid": False,
            "error": str(e)
        }