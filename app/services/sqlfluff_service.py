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
                linter = Linter(dialect=dialect)
                
                # 手动过滤插件规则以解决SQLFluff 3.4.1中方言过滤的问题
                filtered_linter = self._filter_rules_by_dialect(linter, dialect)
                
                self._linter_cache[dialect] = filtered_linter
                self.logger.debug(f"创建新的Linter实例: {dialect}")
            except Exception as e:
                self.logger.error(f"创建Linter失败，方言: {dialect}, 错误: {e}")
                raise SQLFluffException("创建Linter", dialect, str(e))
        
        return self._linter_cache[dialect]
    
    def _filter_rules_by_dialect(self, linter: Linter, current_dialect: str) -> Linter:
        """
        手动过滤规则，确保只有适用于当前方言的规则被应用
        
        这是为了解决SQLFluff 3.4.1中插件规则方言过滤失效的问题
        
        Args:
            linter: 原始Linter实例
            current_dialect: 当前使用的方言
            
        Returns:
            Linter: 过滤后的Linter实例
        """
        try:
            # 获取所有规则
            all_rules = linter.rule_tuples()
            rules_to_exclude = []
            
            for rule in all_rules:
                # 检查规则是否需要被排除
                should_exclude = False
                
                # 方法1: 检查规则类的方言属性（适用于大多数插件规则）
                if hasattr(rule, '_rule_class'):
                    rule_class = rule._rule_class
                    if hasattr(rule_class, 'dialects') and rule_class.dialects:
                        dialects = rule_class.dialects
                        # 如果规则指定了方言限制，且当前方言不在其中，则排除
                        if isinstance(dialects, (set, list, tuple)):
                            if current_dialect not in dialects:
                                should_exclude = True
                        elif isinstance(dialects, str):
                            if current_dialect != dialects:
                                should_exclude = True
                
                # 方法2: 直接检查规则对象的方言属性（备用方法）
                if not should_exclude and hasattr(rule, 'dialects') and rule.dialects:
                    dialects = rule.dialects
                    if isinstance(dialects, (set, list, tuple)):
                        if current_dialect not in dialects:
                            should_exclude = True
                    elif isinstance(dialects, str):
                        if current_dialect != dialects:
                            should_exclude = True
                
                # 方法3: 基于规则代码的特殊处理（针对已知的自定义规则）
                if not should_exclude and 'HiveCustom' in rule.code:
                    # HiveCustom规则只应该在hive方言中应用
                    if current_dialect != 'hive':
                        should_exclude = True
                        self.logger.debug(f"基于规则代码排除规则: {rule.code} (当前方言: {current_dialect})")
                
                if should_exclude:
                    rules_to_exclude.append(rule.code)
                    self.logger.debug(f"规则 {rule.code} 被标记为排除 (方言: {current_dialect})")
            
            # 如果有规则需要排除，创建新的linter
            if rules_to_exclude:
                self.logger.info(f"为方言 {current_dialect} 排除了以下规则: {rules_to_exclude}")
                
                from sqlfluff.core import Linter
                filtered_linter = Linter(
                    dialect=current_dialect,
                    exclude_rules=rules_to_exclude
                )
                
                self.logger.debug(f"已为方言 {current_dialect} 过滤规则，排除了 {len(rules_to_exclude)} 个规则")
                return filtered_linter
            
            # 如果没有规则需要过滤，返回原始linter
            self.logger.debug(f"方言 {current_dialect} 无需过滤规则")
            return linter
            
        except Exception as e:
            self.logger.warning(f"规则过滤失败，使用原始linter: {e}")
            return linter
    
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
    
    def analyze_sql_content_with_rules(
        self, 
        sql_content: str, 
        file_name: str = "query.sql", 
        dialect: Optional[str] = None,
        rules: Optional[List[str]] = None,
        exclude_rules: Optional[List[str]] = None,
        config_overrides: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        分析SQL内容，支持动态规则配置
        
        Args:
            sql_content: SQL内容
            file_name: 文件名（用于结果中显示）
            dialect: SQL方言，如果为None则使用默认方言
            rules: 启用的规则列表，如["L001", "L032", "LT01"]
            exclude_rules: 排除的规则列表，如["L016", "L034"]
            config_overrides: 其他配置覆盖，如{"max_line_length": 120}
            
        Returns:
            Dict[str, Any]: 分析结果
        """
        try:
            used_dialect = dialect or self.default_dialect
            
            # 🔥 使用SQLFluff简单API进行动态配置
            lint_result = None
            
            # 如果有额外的配置覆盖，使用FluffConfig
            if config_overrides or rules or exclude_rules:
                from sqlfluff.core import FluffConfig
                
                # 构建配置字典
                configs = {
                    "core": {
                        "dialect": used_dialect,
                        **(config_overrides or {})
                    }
                }
                
                # 如果有规则配置，也添加到配置中
                if rules:
                    configs["core"]["rules"] = rules
                if exclude_rules:
                    configs["core"]["exclude_rules"] = exclude_rules
                    
                config = FluffConfig(configs=configs)
                lint_result = sqlfluff.lint(sql_content, config=config)
            else:
                # 使用默认配置
                lint_result = sqlfluff.lint(sql_content, dialect=used_dialect)
            
            # 格式化结果（使用简单API格式化方法）
            formatted_result = self._format_sqlfluff_simple_result(
                lint_result, sql_content, file_name, used_dialect
            )
            
            # 添加规则配置信息到结果中
            formatted_result["analysis_metadata"].update({
                "rules_enabled": rules if rules else "all",
                "rules_excluded": exclude_rules if exclude_rules else "none",
                "config_overrides": config_overrides if config_overrides else {}
            })
            
            self.logger.debug(f"动态规则SQL分析完成: {file_name}, 方言: {used_dialect}, 规则: {rules}")
            return formatted_result
            
        except Exception as e:
            self.logger.error(f"动态规则SQL分析失败: {file_name}, 错误: {e}")
            raise SQLFluffException("动态规则SQL分析", file_name, str(e))

    def analyze_sql_content(self, sql_content: str, file_name: str = "query.sql", dialect: Optional[str] = None) -> Dict[str, Any]:
        """
        分析SQL内容字符串（保持向后兼容）
        
        Args:
            sql_content: SQL内容
            file_name: 文件名（用于结果中显示）
            dialect: SQL方言，如果为None则使用默认方言
            
        Returns:
            Dict[str, Any]: 分析结果
        """
        return self.analyze_sql_content_with_rules(sql_content, file_name, dialect)

    def _original_analyze_sql_content(self, sql_content: str, file_name: str = "query.sql", dialect: Optional[str] = None) -> Dict[str, Any]:
        """
        原始的分析SQL内容方法（使用Linter）
        """
        try:
            # 获取对应方言的Linter
            linter = self._get_linter(dialect)
            used_dialect = dialect or self.default_dialect
            
            # 执行分析
            lint_result = linter.lint_string(sql_content)
            
            # 尝试获取解析树
            parse_tree = None
            try:
                from sqlfluff import parse
                parse_result = parse(sql_content, dialect=used_dialect)
                if parse_result:
                    parse_tree = parse_result
            except Exception as e:
                self.logger.debug(f"获取解析树失败: {e}")
            
            # 格式化结果
            result = self._format_lint_result(
                lint_result, sql_content, file_name, used_dialect, linter, parse_tree
            )
            
            self.logger.debug(f"SQL内容分析完成: {file_name}, 方言: {used_dialect}")
            return result
            
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
    
    def _format_lint_result(self, lint_result, sql_content: str, file_name: str, dialect: str, linter: Linter, parse_tree: Optional[Dict] = None) -> Dict[str, Any]:
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
            
            # 添加解析树信息（如果可用）
            if parse_tree:
                # 现在parse_tree应该总是通过_extract_parse_tree_info处理过的dict格式
                result["parse_tree"] = {
                    "description": "SQLFluff解析树，显示SQL语句的语法结构",
                    "tree_info": parse_tree
                }
            
            return result
            
        except Exception as e:
            self.logger.error(f"格式化分析结果失败: {e}")
            # 返回错误结果
            error_result = {
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
            
            # 如果有解析树，也包含在错误结果中
            if parse_tree:
                # 现在parse_tree应该总是通过_extract_parse_tree_info处理过的dict格式
                error_result["parse_tree"] = {
                    "description": "SQLFluff解析树，显示SQL语句的语法结构",
                    "tree_info": parse_tree
                }
            
            return error_result
    
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
    
    def _extract_parse_tree_info(self, parse_tree) -> Dict[str, Any]:
        """
        从SQLFluff解析树中提取结构化信息
        
        Args:
            parse_tree: SQLFluff解析树对象
            
        Returns:
            Dict[str, Any]: 格式化的解析树信息
        """
        try:
            if not parse_tree:
                return None
            
            # 获取完整的解析树结构（类似日志中的格式）
            detailed_tree = self._get_detailed_tree_structure(parse_tree)
            
            # 获取基本的字符串表示
            tree_str = str(parse_tree)
            
            # 提取关键信息
            tree_info = {
                "tree_type": parse_tree.__class__.__name__ if hasattr(parse_tree, '__class__') else "unknown",
                "raw_tree": tree_str,
                "detailed_structure": detailed_tree,  # 新增：详细的解析树结构
                "contains_unparsable": "unparsable" in detailed_tree.lower() if detailed_tree else False,
                "has_syntax_errors": False
            }
            
            # 检查是否有语法错误
            if hasattr(parse_tree, 'get_error_segments'):
                try:
                    error_segments = parse_tree.get_error_segments()
                    if error_segments:
                        tree_info["has_syntax_errors"] = True
                        tree_info["error_segments"] = [str(seg) for seg in error_segments]
                except Exception:
                    pass
            
            # 尝试获取更详细的结构信息
            if hasattr(parse_tree, 'segments'):
                try:
                    tree_info["segment_count"] = len(parse_tree.segments)
                except Exception:
                    pass
            
            # 检查是否包含不可解析的段
            if detailed_tree and "unparsable" in detailed_tree.lower():
                tree_info["contains_unparsable"] = True
                tree_info["has_syntax_errors"] = True
            
            return tree_info
            
        except Exception as e:
            self.logger.error(f"提取解析树信息失败: {e}")
            return {
                "error": f"解析树信息提取失败: {str(e)}",
                "raw_tree": str(parse_tree) if parse_tree else "None"
            }
    
    def _get_detailed_tree_structure(self, parse_tree) -> str:
        """
        获取详细的解析树结构，尝试生成类似SQLFluff日志的格式
        
        Args:
            parse_tree: SQLFluff解析树对象
            
        Returns:
            str: 格式化的解析树字符串
        """
        try:
            if not parse_tree:
                return ""
            
            # 尝试多种方法获取详细的解析树结构
            detailed_structure = None
            
            # 方法1: 尝试使用_pretty_format方法（SQLFluff内部可能有）
            if hasattr(parse_tree, '_pretty_format'):
                try:
                    detailed_structure = parse_tree._pretty_format()
                    self.logger.debug("使用_pretty_format方法获取解析树")
                except Exception as e:
                    self.logger.debug(f"_pretty_format方法失败: {e}")
            
            # 方法2: 尝试使用render方法，但传入适当的参数
            if not detailed_structure and hasattr(parse_tree, 'render'):
                try:
                    # 一些SQLFluff版本的render方法支持format参数
                    detailed_structure = parse_tree.render(format='tree')
                    self.logger.debug("使用render(format='tree')方法获取解析树")
                except Exception as e:
                    try:
                        detailed_structure = parse_tree.render()
                        self.logger.debug("使用render()方法获取解析树")
                    except Exception as e2:
                        self.logger.debug(f"render方法失败: {e}, {e2}")
            
            # 方法3: 尝试访问内部的tree属性或方法
            if not detailed_structure:
                try:
                    # 尝试访问可能的内部属性
                    if hasattr(parse_tree, '_tree_repr'):
                        detailed_structure = parse_tree._tree_repr()
                    elif hasattr(parse_tree, 'tree'):
                        if callable(parse_tree.tree):
                            detailed_structure = parse_tree.tree()
                        else:
                            detailed_structure = str(parse_tree.tree)
                    self.logger.debug("使用内部树表示方法获取解析树")
                except Exception as e:
                    self.logger.debug(f"内部方法失败: {e}")
            
            # 方法4: 使用自定义的递归格式化
            if not detailed_structure:
                try:
                    detailed_structure = self._format_parse_tree_recursive(parse_tree, 0)
                    self.logger.debug("使用自定义递归方法获取解析树")
                except Exception as e:
                    self.logger.debug(f"自定义递归方法失败: {e}")
                    detailed_structure = str(parse_tree)
            
            return detailed_structure if detailed_structure else str(parse_tree)
            
        except Exception as e:
            self.logger.debug(f"生成详细解析树结构失败: {e}")
            return f"解析树结构生成失败: {str(e)}"
    
    def _format_parse_tree_recursive(self, segment, level: int = 0) -> str:
        """
        递归格式化解析树，精确模拟SQLFluff日志输出格式
        
        Args:
            segment: 解析树段
            level: 缩进级别
            
        Returns:
            str: 格式化的解析树字符串
        """
        lines = []
        indent = "    " * level
        
        try:
            # 获取位置信息
            pos_info = ""
            if hasattr(segment, 'pos_marker') and segment.pos_marker:
                try:
                    line_no = getattr(segment.pos_marker, 'line_no', 1)
                    line_pos = getattr(segment.pos_marker, 'line_pos', 1) 
                    pos_info = f"[L: {line_no:3d}, P: {line_pos:3d}]"
                except:
                    pos_info = "[L:  ?, P:  ?]"
            
            # 获取段类型名称，保持下划线格式
            segment_type = segment.__class__.__name__
            # 转换CamelCase到snake_case
            import re
            segment_type = re.sub(r'([A-Z])', r'_\1', segment_type).lower().strip('_')
            segment_type = segment_type.replace('_segment', '')
            
            # 特殊类型名称映射
            type_mappings = {
                'file': 'file',
                'statement': 'statement', 
                'delete_statement': 'delete_statement',
                'from_clause': 'from_clause',
                'from_expression': 'from_expression',
                'from_expression_element': 'from_expression_element',
                'table_expression': 'table_expression',
                'table_reference': 'table_reference',
                'alias_expression': 'alias_expression',
                'keyword': 'keyword',
                'whitespace': 'whitespace',
                'identifier': 'naked_identifier',  # SQLFluff常用naked_identifier
                'unparsable': 'unparsable',
                'word': 'word',
                'equals': 'equals',
                'numeric_literal': 'numeric_literal',
                'semicolon': 'semicolon',
                'end_of_file': '[META] end_of_file'
            }
            
            final_segment_type = type_mappings.get(segment_type, segment_type)
            
            # 判断是否是叶子节点（只有叶子节点显示原始内容）
            is_leaf = not (hasattr(segment, 'segments') and segment.segments)
            
            # 获取原始内容（只在叶子节点显示）
            raw_content = ""
            if is_leaf and hasattr(segment, 'raw') and segment.raw is not None:
                raw_content = repr(segment.raw)  # 使用repr保留引号
            
            # 特殊处理unparsable段
            if 'unparsable' in segment.__class__.__name__.lower():
                raw_content = "!! Expected: 'Nothing else in FileSegment.'"
            
            # 构建行内容
            line_content = f"{pos_info}      |{indent}{final_segment_type}:"
            if raw_content:
                spaces_needed = max(1, 50 - len(f"{indent}{final_segment_type}:"))
                line_content += " " * spaces_needed + raw_content
                
            lines.append(line_content)
            
            # 递归处理子段
            if hasattr(segment, 'segments') and segment.segments:
                for child_segment in segment.segments:
                    # 处理META段
                    if hasattr(child_segment, '__class__') and 'meta' in child_segment.__class__.__name__.lower():
                        meta_type = child_segment.__class__.__name__.replace('Segment', '').lower()
                        meta_pos = ""
                        if hasattr(child_segment, 'pos_marker') and child_segment.pos_marker:
                            try:
                                line_no = getattr(child_segment.pos_marker, 'line_no', 1)
                                line_pos = getattr(child_segment.pos_marker, 'line_pos', 1)
                                meta_pos = f"[L: {line_no:3d}, P: {line_pos:3d}]"
                            except:
                                meta_pos = "[L:  ?, P:  ?]"
                        lines.append(f"{meta_pos}      |{indent}    [META] {meta_type}:")
                    else:
                        # 递归处理普通段
                        child_lines = self._format_parse_tree_recursive(child_segment, level + 1)
                        if child_lines.strip():
                            lines.append(child_lines)
            
        except Exception as e:
            lines.append(f"{indent}Error formatting segment: {str(e)}")
        
        return '\n'.join(lines)

    def _format_sqlfluff_simple_result(self, lint_result, sql_content: str, file_name: str, dialect: str) -> Dict[str, Any]:
        """格式化SQLFluff简单API结果为标准JSON格式"""
        try:
            violations = []
            critical_count = 0
            warning_count = 0
            
            # SQLFluff简单API返回的是违规项字典列表
            for violation in lint_result:
                violation_dict = {
                    "line_no": violation.get("line_no", 0),
                    "line_pos": violation.get("line_pos", 0),
                    "code": violation.get("code", "UNKNOWN"),
                    "description": violation.get("description", "No description"),
                    "rule": violation.get("code", "unknown"),
                    "severity": self._get_violation_severity_from_code(violation.get("code", "")),
                    "fixable": False  # 简单API不提供fixable信息
                }
                
                violations.append(violation_dict)
                
                # 统计严重程度
                if violation_dict["severity"] == "critical":
                    critical_count += 1
                else:
                    warning_count += 1
            
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
                    "api_type": "simple_api"
                }
            }
            
            return result
            
        except Exception as e:
            self.logger.error(f"格式化SQLFluff结果失败: {e}")
            raise SQLFluffException("格式化SQLFluff结果", file_name, str(e))

    def _get_violation_severity_from_code(self, rule_code: str) -> str:
        """根据规则代码判断严重程度"""
        try:
            # 关键错误（影响SQL执行）
            critical_rules = ['L001', 'L002', 'L003', 'L008', 'L009', 'PRS01', 'TMP01']
            if rule_code in critical_rules:
                return "critical"
            
            # 默认为警告
            return "warning"
            
        except Exception:
            return "warning"