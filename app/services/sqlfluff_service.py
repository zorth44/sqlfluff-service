"""
SQLFluff集成服务

集成SQLFluff引擎，实现SQL文件的质量分析功能。
提供统一的SQL分析接口，支持多种SQL方言和自定义规则配置。
"""

import sqlfluff
from sqlfluff.core import Linter
from typing import Dict, List, Any, Optional
from datetime import datetime
import os
from pathlib import Path

from app.core.exceptions import SQLFluffException
from app.core.logging import service_logger
from app.utils.file_utils import FileManager
from app.config.settings import get_settings

settings = get_settings()


class SQLFluffService:
    """SQLFluff集成服务类"""
    
    def __init__(self):
        self.file_manager = FileManager()
        self.logger = service_logger
        self.default_dialect = settings.SQLFLUFF_DIALECT
        # 用于缓存不同方言的Linter实例
        self._linter_cache: Dict[str, Linter] = {}
    
    def _get_linter(self, dialect: Optional[str] = None) -> Linter:
        """
        获取指定方言的Linter实例，使用缓存机制提高性能
        
        Args:
            dialect: SQL方言，如果为None则使用默认方言
            
        Returns:
            Linter: 对应方言的Linter实例
        """
        if dialect is None:
            dialect = self.default_dialect
            
        # 从缓存中获取或创建新的Linter
        if dialect not in self._linter_cache:
            try:
                self._linter_cache[dialect] = Linter(dialect=dialect)
                self.logger.debug(f"创建新的Linter实例: {dialect}")
            except Exception as e:
                self.logger.error(f"创建Linter失败，方言: {dialect}, 错误: {e}")
                raise SQLFluffException("创建Linter", dialect, str(e))
        
        return self._linter_cache[dialect]
    
    def analyze_sql_file(self, file_path: str, dialect: Optional[str] = None) -> Dict[str, Any]:
        """
        分析单个SQL文件
        
        Args:
            file_path: SQL文件路径（可以是相对路径或绝对路径）
            dialect: SQL方言，如果为None则使用默认方言
            
        Returns:
            Dict[str, Any]: 分析结果
        """
        try:
            # 处理文件路径 - 如果是绝对路径，转换为相对路径
            if os.path.isabs(file_path):
                # 如果是绝对路径，尝试转换为相对路径
                try:
                    relative_path = self.file_manager.get_relative_path(file_path)
                except ValueError:
                    # 如果无法转换为相对路径，使用绝对路径
                    relative_path = file_path
            else:
                relative_path = file_path
            
            # 验证文件存在
            if not self.file_manager.file_exists(relative_path):
                raise SQLFluffException("分析SQL文件", relative_path, "文件不存在")
            
            # 读取文件内容（增强编码处理）
            sql_content = self._read_sql_file_with_encoding_detection(relative_path)
            
            # 获取文件信息
            file_info = self._get_file_info(relative_path)
            
            # 执行分析
            result = self.analyze_sql_content(sql_content, os.path.basename(file_path), dialect)
            
            # 更新文件信息
            result['file_info'].update(file_info)
            
            self.logger.debug(f"SQL文件分析完成: {relative_path}, 方言: {dialect or self.default_dialect}")
            return result
            
        except Exception as e:
            self.logger.error(f"分析SQL文件失败: {file_path}, 方言: {dialect}, 错误: {e}")
            if isinstance(e, SQLFluffException):
                raise
            raise SQLFluffException("分析SQL文件", file_path, str(e))
    
    def analyze_sql_content(self, sql_content: str, file_name: str = "query.sql", dialect: Optional[str] = None) -> Dict[str, Any]:
        """
        分析SQL内容字符串
        
        Args:
            sql_content: SQL内容
            file_name: 文件名（用于结果中显示）
            dialect: SQL方言，如果为None则使用默认方言
            
        Returns:
            Dict[str, Any]: 分析结果
        """
        try:
            # 获取对应方言的Linter
            linter = self._get_linter(dialect)
            used_dialect = dialect or self.default_dialect
            
            # 执行Linting
            lint_result = linter.lint_string(sql_content)
            
            # 格式化结果
            formatted_result = self._format_lint_result(lint_result, sql_content, file_name, used_dialect, linter)
            
            self.logger.debug(f"SQL内容分析完成: {file_name}, 方言: {used_dialect}")
            return formatted_result
            
        except Exception as e:
            self.logger.error(f"分析SQL内容失败: {file_name}, 方言: {dialect}, 错误: {e}")
            raise SQLFluffException("分析SQL内容", file_name, str(e))
    
    def get_supported_dialects(self) -> List[str]:
        """
        获取支持的SQL方言列表
        
        Returns:
            List[str]: 支持的方言列表
        """
        try:
            import sqlfluff
            # 使用正确的API获取方言列表
            dialect_tuples = sqlfluff.list_dialects()
            return [dialect.label for dialect in dialect_tuples]
        except Exception as e:
            self.logger.error(f"获取支持的方言失败: {e}")
            # 返回常见的方言作为fallback
            return [
                "mysql", "postgres", "sqlite", "bigquery", "snowflake", 
                "redshift", "oracle", "tsql", "ansi"
            ]
    
    def validate_config(self, dialect: Optional[str] = None) -> Dict[str, Any]:
        """
        验证SQLFluff配置
        
        Args:
            dialect: 要验证的SQL方言，如果为None则使用默认方言
            
        Returns:
            Dict[str, Any]: 配置验证结果
        """
        try:
            used_dialect = dialect or self.default_dialect
            linter = self._get_linter(used_dialect)
            
            validation_result = {
                "is_valid": True,
                "dialect": used_dialect,
                "rules_enabled": len(linter.rule_tuples()),
                "config_source": "default",
                "errors": []
            }
            
            # 检查自定义配置文件
            if settings.SQLFLUFF_CONFIG_PATH:
                config_path = Path(settings.SQLFLUFF_CONFIG_PATH)
                if config_path.exists():
                    validation_result["config_source"] = str(config_path)
                else:
                    validation_result["errors"].append(f"配置文件不存在: {config_path}")
                    validation_result["is_valid"] = False
            
            # 验证方言
            supported_dialects = self.get_supported_dialects()
            if used_dialect not in supported_dialects:
                validation_result["errors"].append(f"不支持的方言: {used_dialect}")
                validation_result["is_valid"] = False
            
            return validation_result
            
        except Exception as e:
            self.logger.error(f"验证配置失败: {e}")
            return {
                "is_valid": False,
                "errors": [str(e)]
            }
    
    def clear_linter_cache(self):
        """
        清空Linter缓存，在需要重新加载配置时使用
        """
        self._linter_cache.clear()
        self.logger.info("Linter缓存已清空")
    
    def get_cached_dialects(self) -> List[str]:
        """
        获取当前缓存中的方言列表
        
        Returns:
            List[str]: 已缓存的方言列表
        """
        return list(self._linter_cache.keys())
    
    # 私有方法
    
    def _read_sql_file_with_encoding_detection(self, relative_path: str) -> str:
        """
        使用编码检测来读取SQL文件
        
        Args:
            relative_path: 相对文件路径
            
        Returns:
            str: 文件内容
            
        Raises:
            SQLFluffException: 文件读取失败
        """
        abs_path = self.file_manager.get_absolute_path(relative_path)
        
        # 常见的编码格式，按优先级排序
        encodings = ['utf-8', 'utf-8-sig', 'gbk', 'gb2312', 'latin-1', 'cp1252']
        
        for encoding in encodings:
            try:
                with open(abs_path, 'r', encoding=encoding) as f:
                    content = f.read()
                    self.logger.debug(f"成功使用 {encoding} 编码读取文件: {relative_path}")
                    return content
            except UnicodeDecodeError:
                continue
            except Exception as e:
                self.logger.warning(f"使用 {encoding} 编码读取文件失败: {relative_path}, 错误: {e}")
                continue
        
        # 如果所有编码都失败，尝试以二进制模式读取并检查文件内容
        try:
            with open(abs_path, 'rb') as f:
                raw_content = f.read()
                
            # 检查是否为二进制文件
            if b'\x00' in raw_content:
                raise SQLFluffException(
                    "读取SQL文件", 
                    relative_path, 
                    "文件似乎是二进制文件，不是文本文件"
                )
            
            # 尝试使用errors='replace'来读取
            try:
                content = raw_content.decode('utf-8', errors='replace')
                self.logger.warning(f"使用UTF-8替换错误字符读取文件: {relative_path}")
                return content
            except Exception:
                raise SQLFluffException(
                    "读取SQL文件", 
                    relative_path, 
                    "无法解码文件内容，请检查文件编码"
                )
                
        except Exception as e:
            raise SQLFluffException("读取SQL文件", relative_path, f"文件读取失败: {str(e)}")
    
    def _format_lint_result(self, lint_result, sql_content: str, file_name: str, dialect: str, linter: Linter) -> Dict[str, Any]:
        """格式化分析结果为标准JSON格式"""
        try:
            violations = []
            critical_count = 0
            warning_count = 0
            
            # 处理违规项 - SQLFluff返回的是一个复杂的结构
            # 需要找到其中的SQLLintError列表
            lint_errors = []
            
            # 遍历lint_result，找到SQLLintError对象
            for item in lint_result:
                # 检查是否是SQLLintError对象列表
                if isinstance(item, list):
                    for sub_item in item:
                        if hasattr(sub_item, 'line_no') and hasattr(sub_item, 'description'):
                            lint_errors.append(sub_item)
                # 检查是否是单个SQLLintError对象
                elif hasattr(item, 'line_no') and hasattr(item, 'description'):
                    lint_errors.append(item)
                # 记录调试信息
                else:
                    self.logger.debug(f"跳过非违规项: {type(item)} - {item}")
            
            # 如果没有找到SQLLintError，记录原始数据用于调试
            if not lint_errors:
                self.logger.warning(f"未找到SQLLintError对象，原始数据类型: {[type(item) for item in lint_result]}")
                self.logger.debug(f"原始lint_result内容: {lint_result}")
            
            # 处理找到的违规项
            for violation in lint_errors:
                try:
                    # 获取rule信息
                    rule_code = "UNKNOWN"
                    rule_name = "unknown"
                    
                    if hasattr(violation, 'rule') and violation.rule:
                        if hasattr(violation.rule, 'code'):
                            rule_code = violation.rule.code
                        if hasattr(violation.rule, 'name'):
                            rule_name = violation.rule.name
                    
                    violation_dict = {
                        "line_no": getattr(violation, 'line_no', 0),
                        "line_pos": getattr(violation, 'line_pos', 0),
                        "code": rule_code,
                        "description": getattr(violation, 'description', 'No description'),
                        "rule": rule_name,
                        "severity": self._get_violation_severity(violation),
                        "fixable": getattr(violation, 'fixable', False)
                    }
                    
                    violations.append(violation_dict)
                    
                    # 统计严重程度
                    if violation_dict["severity"] == "critical":
                        critical_count += 1
                    else:
                        warning_count += 1
                        
                except Exception as e:
                    self.logger.error(f"处理违规项失败: {violation}, 错误: {e}")
            
            # 计算摘要
            total_violations = len(violations)
            file_passed = total_violations == 0
            
            # 获取文件基本信息
            lines = sql_content.split('\n')
            line_count = len(lines)
            
            # 构造结果
            result = {
                "violations": violations,
                "summary": {
                    "total_violations": total_violations,
                    "critical_violations": critical_count,
                    "warning_violations": warning_count,
                    "file_passed": file_passed,
                    "success_rate": 0 if total_violations > 0 else 100
                },
                "file_info": {
                    "file_name": file_name,
                    "file_size": len(sql_content.encode('utf-8')),
                    "line_count": line_count,
                    "character_count": len(sql_content)
                },
                "analysis_metadata": {
                    "sqlfluff_version": sqlfluff.__version__,
                    "dialect": dialect,
                    "analysis_time": datetime.now().isoformat(),
                    "rules_applied": len(linter.rule_tuples())
                }
            }
            
            return result
            
        except Exception as e:
            self.logger.error(f"格式化分析结果失败: {e}")
            # 返回错误结果
            return {
                "violations": [],
                "summary": {
                    "total_violations": 0,
                    "critical_violations": 0,
                    "warning_violations": 0,
                    "file_passed": False,
                    "error": str(e)
                },
                "file_info": {
                    "file_name": file_name,
                    "file_size": len(sql_content.encode('utf-8')) if sql_content else 0,
                    "line_count": len(sql_content.split('\n')) if sql_content else 0
                },
                "analysis_metadata": {
                    "sqlfluff_version": sqlfluff.__version__,
                    "dialect": dialect,
                    "analysis_time": datetime.now().isoformat(),
                    "error": str(e)
                }
            }
    
    def _get_violation_severity(self, violation) -> str:
        """获取违规项严重程度"""
        try:
            # 根据规则代码判断严重程度
            if hasattr(violation, 'rule') and violation.rule:
                rule_code = violation.rule.code
                
                # 关键错误（影响SQL执行）
                critical_rules = ['L001', 'L002', 'L003', 'L008', 'L009']
                if rule_code in critical_rules:
                    return "critical"
            
            # 默认为警告
            return "warning"
            
        except Exception:
            return "warning"
    
    def _get_file_info(self, file_path: str) -> Dict[str, Any]:
        """获取文件基本信息"""
        try:
            file_info = self.file_manager.get_file_info(file_path)
            return {
                "file_name": file_info.get("name", "unknown"),
                "file_size": file_info.get("size", 0),
                "last_modified": file_info.get("modified_time", datetime.now()).isoformat()
            }
        except Exception as e:
            self.logger.warning(f"获取文件信息失败: {file_path}, {e}")
            return {
                "file_name": os.path.basename(file_path),
                "file_size": 0,
                "last_modified": datetime.now().isoformat()
            } 