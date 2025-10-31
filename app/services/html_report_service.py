"""
HTML报告生成服务

负责生成Job的HTML格式报告，支持侧边栏导航和交互式违规项查看。
提供Fragment和Standalone两种HTML格式输出。
"""

from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from pathlib import Path
import os

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct

from app.models.database import LintingJob, LintingTask, LintingViolation
from app.core.logging import api_logger
from app.config.settings import settings
from app.utils.sql_file_reader import SQLFileReader


class HtmlReportService:
    """HTML报告生成服务"""

    def __init__(self):
        """初始化服务"""
        # 设置Jinja2模板环境
        template_dir = Path(__file__).parent.parent / "templates"
        self.jinja_env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=select_autoescape(['html', 'xml']),
            trim_blocks=True,
            lstrip_blocks=True
        )

    async def generate_html_report(
        self,
        job_id: str,
        db: Session,
        standalone: bool = False
    ) -> Tuple[str, str]:
        """
        生成HTML报告

        Args:
            job_id: Job ID
            db: 数据库会话
            standalone: 是否生成独立的HTML文档

        Returns:
            Tuple[str, str]: (HTML内容, 错误信息)
                如果成功，错误信息为None
                如果超出文件限制，返回(None, error_json)
        """
        api_logger.info(f"开始生成HTML报告: {job_id}, standalone={standalone}")

        # 1. 验证Job是否存在
        job = db.query(LintingJob).filter(LintingJob.job_id == job_id).first()
        if not job:
            return None, self._generate_error_response("JOB_NOT_FOUND", job_id)

        # 2. 检查文件数量限制
        task_count = db.query(func.count(LintingTask.task_id)).filter(
            LintingTask.job_id == job_id
        ).scalar()

        if task_count > settings.EXPORT_HTML_FILE_LIMIT:
            return None, self._generate_error_response(
                "LIMIT_EXCEEDED",
                job_id,
                task_count,
                settings.EXPORT_HTML_FILE_LIMIT
            )

        # 3. 查询数据
        report_data = await self._prepare_report_data(job_id, job, db)

        # 4. 渲染HTML模板
        try:
            if standalone:
                template = self.jinja_env.get_template("html_report_standalone.jinja2")
            else:
                template = self.jinja_env.get_template("html_report_fragment.jinja2")

            html_content = template.render(**report_data)
            api_logger.info(f"HTML报告生成成功: {job_id}, 大小: {len(html_content)} 字符")
            return html_content, None

        except Exception as e:
            api_logger.error(f"HTML模板渲染失败: {job_id}, {e}")
            return None, self._generate_error_response("RENDER_ERROR", job_id, str(e))

    async def _prepare_report_data(
        self,
        job_id: str,
        job: LintingJob,
        db: Session
    ) -> Dict[str, Any]:
        """
        准备报告数据

        Args:
            job_id: Job ID
            job: Job对象
            db: 数据库会话

        Returns:
            Dict[str, Any]: 报告数据
        """
        # 查询所有Task和Violations
        query = db.query(
            LintingTask,
            LintingViolation
        ).outerjoin(
            LintingViolation,
            LintingTask.task_id == LintingViolation.task_id
        ).filter(
            LintingTask.job_id == job_id
        ).order_by(
            LintingTask.source_file_path,
            LintingViolation.line_no
        )

        results = query.all()

        # 构建文件树和违规项数据
        files_data = {}
        total_violations = 0
        all_severities = set()

        for task, violation in results:
            task_id = task.task_id

            if task_id not in files_data:
                # 读取SQL文件内容
                sql_lines, encoding = self._read_sql_file_safe(task.source_file_path)

                files_data[task_id] = {
                    'task_id': task_id,
                    'source_file_path': task.source_file_path,
                    'file_name': os.path.basename(task.source_file_path) if task.source_file_path else '',
                    'sql_lines': sql_lines if sql_lines else [],
                    'total_lines': len(sql_lines) if sql_lines else 0,
                    'total_violations': 0,
                    'violations': [],
                    'read_error': sql_lines is None
                }

            # 添加violation
            if violation:
                violation_data = {
                    'violation_id': violation.id,
                    'task_id': task_id,
                    'rule_code': violation.rule_code,
                    'rule_name': violation.rule_name or violation.rule_code,
                    'severity_level': violation.severity_level or 'INFO',
                    'line_no': violation.line_no,
                    'column_no': violation.line_pos,
                    'description': violation.description or '',
                }

                files_data[task_id]['violations'].append(violation_data)
                files_data[task_id]['total_violations'] += 1
                total_violations += 1
                all_severities.add(violation.severity_level or 'INFO')

        # 按文件名排序
        sorted_files = sorted(files_data.values(), key=lambda x: x['file_name'])

        # 对每个文件的违规项按行号排序
        for file_data in sorted_files:
            file_data['violations'].sort(key=lambda x: x['line_no'])

        # 统计严重级别分布
        severity_stats = self._calculate_severity_distribution(db, job_id)

        # 构建报告数据
        report_data = {
            'job_id': job_id,
            'created_at': job.created_at.strftime('%Y-%m-%d %H:%M:%S') if job.created_at else '',
            'files': sorted_files,
            'summary': {
                'total_files': len(files_data),
                'total_violations': total_violations,
                'files_with_violations': sum(1 for f in files_data.values() if f['total_violations'] > 0),
                'severity_distribution': severity_stats
            },
            'severity_filters': self._get_severity_filters(all_severities)
        }

        return report_data

    def _read_sql_file_safe(self, file_path: str) -> Tuple[Optional[List[str]], Optional[str]]:
        """
        安全读取SQL文件

        Args:
            file_path: 文件路径

        Returns:
            Tuple[Optional[List[str]], Optional[str]]: (行列表, 编码)
        """
        try:
            lines, encoding = SQLFileReader.read_sql_file_lines(file_path)
            return lines, encoding
        except Exception as e:
            api_logger.warning(f"读取SQL文件失败: {file_path}, {e}")
            return None, None

    def _calculate_severity_distribution(self, db: Session, job_id: str) -> List[Dict[str, Any]]:
        """
        计算严重级别分布

        Args:
            db: 数据库会话
            job_id: Job ID

        Returns:
            List[Dict[str, Any]]: 严重级别统计列表
        """
        severity_query = db.query(
            LintingViolation.severity_level,
            func.count(LintingViolation.id).label('count')
        ).filter(
            LintingViolation.job_id == job_id
        ).group_by(
            LintingViolation.severity_level
        ).all()

        severity_order = ['CRITICAL', 'BLOCKER', 'MAJOR', 'MINOR', 'INFO']
        severity_map = {sev: count for sev, count in severity_query}

        distribution = []
        for severity in severity_order:
            count = severity_map.get(severity, 0)
            if count > 0:
                distribution.append({
                    'severity_level': severity,
                    'count': count
                })

        return distribution

    def _get_severity_filters(self, all_severities: set) -> List[Dict[str, Any]]:
        """
        获取严重级别过滤器配置

        Args:
            all_severities: 所有出现的严重级别

        Returns:
            List[Dict[str, Any]]: 过滤器配置
        """
        severity_order = ['CRITICAL', 'BLOCKER', 'MAJOR', 'MINOR', 'INFO']
        filters = []

        for severity in severity_order:
            if severity in all_severities or not all_severities:
                filters.append({
                    'value': severity,
                    'label': severity,
                    'checked': True
                })

        return filters

    def _generate_error_response(
        self,
        error_type: str,
        job_id: str,
        *args
    ) -> str:
        """
        生成JSON错误响应

        Args:
            error_type: 错误类型
            job_id: Job ID
            *args: 额外参数

        Returns:
            str: JSON错误字符串
        """
        import json

        if error_type == "JOB_NOT_FOUND":
            return json.dumps({
                "status": "error",
                "error_type": "JOB_NOT_FOUND",
                "message": "工作不存在",
                "job_id": job_id
            }, ensure_ascii=False)

        elif error_type == "LIMIT_EXCEEDED":
            total_files, limit = args
            return json.dumps({
                "status": "error",
                "error_type": "LIMIT_EXCEEDED",
                "message": "文件数量超过限制",
                "job_id": job_id,
                "total_files": total_files,
                "limit": limit
            }, ensure_ascii=False)

        elif error_type == "RENDER_ERROR":
            error_message = args[0]
            return json.dumps({
                "status": "error",
                "error_type": "RENDER_ERROR",
                "message": f"报告生成失败: {error_message}",
                "job_id": job_id
            }, ensure_ascii=False)

        else:
            return json.dumps({
                "status": "error",
                "error_type": "UNKNOWN_ERROR",
                "message": "未知错误",
                "job_id": job_id
            }, ensure_ascii=False)


# 全局服务实例
html_report_service = HtmlReportService()
