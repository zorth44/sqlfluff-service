"""
数据库模型定义

定义linting_jobs和linting_tasks表的SQLAlchemy模型。
包含表结构、关系、索引和约束定义。
"""

from sqlalchemy import Column, Integer, BigInteger, String, Text, DateTime, Enum, ForeignKey, Index, JSON, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
from typing import List, Optional

from app.core.database import Base


class RuleDefinition(Base):
    """
    规则定义表模型，对应表 rule_definitions
    """
    __tablename__ = "rule_definitions"

    rule_code = Column(String(50), primary_key=True, comment="规则编号(放入rules[]的值)")
    rule_name = Column(String(200), nullable=False, comment="规则名称")
    rule_description = Column(Text, nullable=True, comment="规则描述")
    applicable_tech_stack = Column(JSON, nullable=False, comment='适用技术栈["hive","gbase8a","ansi"]')
    source = Column(String(50), nullable=True, default='sqlfluff', comment="来源(开发规范/实施策略/生产总结)")
    verification_method = Column(String(100), nullable=True, comment="规则核验方式(语法检查/格式检查/约定检查)")
    statement_pattern = Column(String(200), nullable=True, comment="适用语句范式")
    severity_level = Column(String(20), nullable=False, default='INFO', comment="规则分级：INFO、MINOR、MAJOR、BLOCKER、CRITICAL")
    is_active = Column(Boolean, nullable=False, default=True, comment="是否启用")
    created_at = Column(DateTime(6), nullable=False, default=func.now())
    updated_at = Column(DateTime(6), nullable=False, default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<RuleDefinition(rule_code='{self.rule_code}', severity_level='{self.severity_level}')>"


class LintingJob(Base):
    """
    核验工作主表模型
    
    记录每个核验工作的基本信息和状态。
    一个Job可以包含多个Task（一对多关系）。
    """
    __tablename__ = "linting_jobs"
    
    # 主键
    id = Column(Integer, primary_key=True, autoincrement=True, comment="自增主键")
    
    # 业务字段
    job_id = Column(
        String(255), 
        unique=True, 
        nullable=False, 
        index=True, 
        comment="对外暴露的UUID工作ID"
    )
    
    status = Column(
        Enum('ACCEPTED', 'PROCESSING', 'COMPLETED', 'PARTIALLY_COMPLETED', 'FAILED', name='job_status_enum'),
        nullable=False,
        default='ACCEPTED',
        comment="工作总体状态"
    )
    
    submission_type = Column(
        Enum('SINGLE_FILE', 'ZIP_ARCHIVE', name='submission_type_enum'),
        nullable=False,
        comment="提交类型"
    )
    
    source_path = Column(
        String(1024),
        nullable=False,
        comment="在NFS共享目录中的源文件相对路径"
    )
    
    dialect = Column(
        String(50),
        nullable=False,
        default='ansi',
        comment="SQLFluff方言，如mysql、postgres、bigquery等"
    )
    
    user_id = Column(
        String(255),
        nullable=False,
        index=True,
        comment="创建工作的用户ID"
    )
    
    product_name = Column(
        String(255),
        nullable=False,
        index=True,
        comment="产品名称"
    )
    
    boc_batch_number = Column(
        String(255),
        nullable=True,
        index=True,
        comment="BOC批次号"
    )
    
    boc_task_number = Column(
        String(255),
        nullable=True,
        index=True,
        comment="BOC任务号"
    )
    
    rules = Column(
        JSON,
        nullable=True,
        comment="用户指定的SQLFluff规则列表，如['RF02', 'L032']"
    )
    
    error_message = Column(
        Text,
        nullable=True,
        comment="工作级别的错误信息（如解压失败）"
    )
    
    # 时间戳字段
    created_at = Column(
        DateTime(6),
        nullable=False,
        default=func.now(),
        comment="创建时间"
    )
    
    updated_at = Column(
        DateTime(6),
        nullable=False,
        default=func.now(),
        onupdate=func.now(),
        comment="最后更新时间"
    )
    
    # 关系定义
    tasks = relationship(
        "LintingTask",
        back_populates="job",
        cascade="all, delete-orphan",  # 级联删除
        lazy="dynamic"  # 延迟加载，返回Query对象
    )
    
    def __repr__(self):
        return f"<LintingJob(job_id='{self.job_id}', status='{self.status}')>"
    
    def to_dict(self):
        """转换为字典格式"""
        return {
            'id': self.id,
            'job_id': self.job_id,
            'status': self.status,
            'submission_type': self.submission_type,
            'source_path': self.source_path,
            'dialect': self.dialect,
            'user_id': self.user_id,
            'product_name': self.product_name,
            'boc_batch_number': self.boc_batch_number,
            'boc_task_number': self.boc_task_number,
            'rules': self.rules,
            'error_message': self.error_message,
            'created_at': self.created_at,
            'updated_at': self.updated_at
        }
    
    @property
    def is_completed(self) -> bool:
        """检查工作是否已完成"""
        return self.status in ['COMPLETED', 'PARTIALLY_COMPLETED', 'FAILED']
    
    @property
    def is_processing(self) -> bool:
        """检查工作是否正在处理中"""
        return self.status == 'PROCESSING'
    
    def get_task_count(self) -> int:
        """获取任务总数"""
        return self.tasks.count()
    
    def get_successful_task_count(self) -> int:
        """获取成功任务数"""
        return self.tasks.filter(LintingTask.status == 'SUCCESS').count()
    
    def get_failed_task_count(self) -> int:
        """获取失败任务数"""
        return self.tasks.filter(LintingTask.status == 'FAILURE').count()


class LintingTask(Base):
    """
    文件处理任务子表模型
    
    记录每个SQL文件的处理任务信息和结果。
    每个Task都关联到一个Job（多对一关系）。
    """
    __tablename__ = "linting_tasks"
    
    # 主键
    id = Column(Integer, primary_key=True, autoincrement=True, comment="自增主键")
    
    # 业务字段
    task_id = Column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        comment="任务的UUID"
    )
    
    job_id = Column(
        String(255),
        ForeignKey('linting_jobs.job_id', ondelete='CASCADE'),
        nullable=False,
        index=True,
        comment="关联到linting_jobs.job_id"
    )
    
    status = Column(
        Enum('PENDING', 'IN_PROGRESS', 'SUCCESS', 'FAILURE', name='task_status_enum'),
        nullable=False,
        default='PENDING',
        comment="单个文件的处理状态"
    )
    
    source_file_path = Column(
        String(1024),
        nullable=False,
        comment="单个SQL文件在NFS共享目录中的相对路径"
    )
    
    result_file_path = Column(
        String(1024),
        nullable=True,
        comment="结果JSON文件在NFS共享目录中的相对路径"
    )
    
    error_message = Column(
        Text,
        nullable=True,
        comment="文件级别的错误信息"
    )
    
    sql_lines = Column(
        Integer,
        nullable=True,
        comment="SQL文件行数"
    )
    
    total_violations = Column(
        Integer,
        nullable=True,
        comment="SQL文件违规项总数"
    )
    
    critical_violations = Column(
        Integer,
        nullable=True,
        comment="SQL文件严重违规项数(BLOCKER和CRITICAL级别)"
    )
    
    # Severity Level 统计字段
    severity_info = Column(
        Integer,
        nullable=True,
        comment="INFO级别违规项数量"
    )
    
    severity_minor = Column(
        Integer,
        nullable=True,
        comment="MINOR级别违规项数量"
    )
    
    severity_major = Column(
        Integer,
        nullable=True,
        comment="MAJOR级别违规项数量"
    )
    
    severity_blocker = Column(
        Integer,
        nullable=True,
        comment="BLOCKER级别违规项数量"
    )
    
    severity_critical = Column(
        Integer,
        nullable=True,
        comment="CRITICAL级别违规项数量"
    )
    
    severity_unknown = Column(
        Integer,
        nullable=True,
        comment="UNKNOWN级别违规项数量"
    )

    # DB-as-Queue Worker 字段
    priority = Column(
        Integer,
        nullable=False,
        default=0,
        comment="任务优先级，数值越大优先级越高"
    )

    claim_id = Column(
        String(255),
        nullable=True,
        comment="Worker 领取标识（格式：worker_id:random_hex）"
    )

    claimed_at = Column(
        DateTime(6),
        nullable=True,
        comment="任务被 Worker 领取的时间"
    )

    retry_count = Column(
        Integer,
        nullable=False,
        default=0,
        comment="已重试次数"
    )

    # 时间戳字段
    created_at = Column(
        DateTime(6),
        nullable=False,
        default=func.now(),
        comment="创建时间"
    )

    updated_at = Column(
        DateTime(6),
        nullable=False,
        default=func.now(),
        onupdate=func.now(),
        comment="最后更新时间"
    )

    # 关系定义
    job = relationship(
        "LintingJob",
        back_populates="tasks"
    )
    
    violations = relationship(
        "LintingViolation",
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="dynamic"
    )
    
    def __repr__(self):
        return f"<LintingTask(task_id='{self.task_id}', status='{self.status}')>"
    
    def to_dict(self):
        """转换为字典格式"""
        return {
            'id': self.id,
            'task_id': self.task_id,
            'job_id': self.job_id,
            'status': self.status,
            'source_file_path': self.source_file_path,
            'result_file_path': self.result_file_path,
            'error_message': self.error_message,
            'sql_lines': self.sql_lines,
            'total_violations': self.total_violations,
            'critical_violations': self.critical_violations,
            'severity_info': self.severity_info,
            'severity_minor': self.severity_minor,
            'severity_major': self.severity_major,
            'severity_blocker': self.severity_blocker,
            'severity_critical': self.severity_critical,
            'severity_unknown': self.severity_unknown,
            'priority': self.priority,
            'claim_id': self.claim_id,
            'claimed_at': self.claimed_at,
            'retry_count': self.retry_count,
            'created_at': self.created_at,
            'updated_at': self.updated_at
        }

    @property
    def is_completed(self) -> bool:
        """检查任务是否已完成"""
        return self.status in ['SUCCESS', 'FAILURE']
    
    @property
    def is_successful(self) -> bool:
        """检查任务是否成功"""
        return self.status == 'SUCCESS'
    
    @property
    def file_name(self) -> str:
        """获取文件名"""
        if self.source_file_path:
            return self.source_file_path.split('/')[-1]
        return ""


# 数据库索引定义
# 为了优化查询性能，创建复合索引

# Job表索引
Index('idx_job_status_created', LintingJob.status, LintingJob.created_at)
Index('idx_job_type_status', LintingJob.submission_type, LintingJob.status)
Index('idx_job_user_status', LintingJob.user_id, LintingJob.status)
Index('idx_job_user_created', LintingJob.user_id, LintingJob.created_at)
Index('idx_job_product_status', LintingJob.product_name, LintingJob.status)
Index('idx_job_product_created', LintingJob.product_name, LintingJob.created_at)
Index('idx_job_boc_batch_status', LintingJob.boc_batch_number, LintingJob.status)
Index('idx_job_boc_batch_created', LintingJob.boc_batch_number, LintingJob.created_at)
Index('idx_job_boc_task_status', LintingJob.boc_task_number, LintingJob.status)
Index('idx_job_boc_task_created', LintingJob.boc_task_number, LintingJob.created_at)

# Task表索引
Index('idx_task_job_status', LintingTask.job_id, LintingTask.status)
Index('idx_task_status_created', LintingTask.status, LintingTask.created_at)
Index('idx_task_job_created', LintingTask.job_id, LintingTask.created_at)


# 数据库约束和验证
def validate_job_status_transition(mapper, connection, target):
    """验证Job状态转换的合法性"""
    if target.id:  # 更新操作
        # 可以添加状态转换验证逻辑
        pass


def validate_task_status_transition(mapper, connection, target):
    """验证Task状态转换的合法性"""
    if target.id:  # 更新操作
        # 可以添加状态转换验证逻辑
        pass


# 事件监听器（如果需要的话）
from sqlalchemy import event

@event.listens_for(LintingJob, 'before_update')
def job_before_update(mapper, connection, target):
    """Job更新前的处理"""
    target.updated_at = func.now()


@event.listens_for(LintingTask, 'before_update')
def task_before_update(mapper, connection, target):
    """Task更新前的处理"""
    target.updated_at = func.now()


# 批量操作辅助函数
class JobQueryHelper:
    """Job查询辅助类"""
    
    @staticmethod
    def get_active_jobs(session):
        """获取活跃的Job"""
        return session.query(LintingJob).filter(
            LintingJob.status.in_(['ACCEPTED', 'PROCESSING'])
        )
    
    @staticmethod
    def get_completed_jobs(session):
        """获取已完成的Job"""
        return session.query(LintingJob).filter(
            LintingJob.status.in_(['COMPLETED', 'PARTIALLY_COMPLETED', 'FAILED'])
        )
    
    @staticmethod
    def get_jobs_by_date_range(session, start_date, end_date):
        """按日期范围获取Job"""
        return session.query(LintingJob).filter(
            LintingJob.created_at >= start_date,
            LintingJob.created_at <= end_date
        )


class TaskQueryHelper:
    """Task查询辅助类"""
    
    @staticmethod
    def get_pending_tasks(session):
        """获取待处理的Task"""
        return session.query(LintingTask).filter(
            LintingTask.status == 'PENDING'
        )
    
    @staticmethod
    def get_tasks_by_job(session, job_id):
        """按Job ID获取Task"""
        return session.query(LintingTask).filter(
            LintingTask.job_id == job_id
        )
    
    @staticmethod
    def get_failed_tasks(session):
        """获取失败的Task"""
        return session.query(LintingTask).filter(
            LintingTask.status == 'FAILURE'
        )


class WorkerRegistry(Base):
    """
    Worker 注册表模型

    记录所有 Worker 实例的心跳和状态信息，
    用于僵尸检测和监控。
    """
    __tablename__ = "worker_registry"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="自增主键")
    worker_id = Column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        comment="Worker 唯一标识（hostname_pid）"
    )
    hostname = Column(
        String(255),
        nullable=False,
        comment="Worker 所在主机名"
    )
    pid = Column(
        Integer,
        nullable=False,
        comment="Worker 进程 ID"
    )
    status = Column(
        Enum('RUNNING', 'STOPPED', 'DEAD', name='worker_status_enum'),
        nullable=False,
        default='RUNNING',
        comment="Worker 运行状态"
    )
    heartbeat_at = Column(
        DateTime(6),
        nullable=False,
        default=func.now(),
        comment="最后心跳时间"
    )
    current_task_count = Column(
        Integer,
        nullable=False,
        default=0,
        comment="当前处理中的任务数"
    )
    total_tasks_processed = Column(
        Integer,
        nullable=False,
        default=0,
        comment="累计已完成任务数"
    )
    started_at = Column(
        DateTime(6),
        nullable=False,
        default=func.now(),
        comment="Worker 启动时间"
    )
    stopped_at = Column(
        DateTime(6),
        nullable=True,
        comment="Worker 停止时间"
    )

    def __repr__(self):
        return f"<WorkerRegistry(worker_id='{self.worker_id}', status='{self.status}')>"


class LintingViolation(Base):
    """
    SQL检查结果明细表模型
    
    存储每个SQL文件的具体违规项（violations），
    用于支持CSV报告生成和统计分析。
    """
    __tablename__ = "linting_violations"
    
    # 主键
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="自增主键")
    
    # 关联字段
    task_id = Column(
        String(255),
        ForeignKey('linting_tasks.task_id', ondelete='CASCADE'),
        nullable=False,
        index=True,
        comment="关联linting_tasks.task_id"
    )
    
    job_id = Column(
        String(255),
        nullable=False,
        index=True,
        comment="冗余字段，关联linting_jobs.job_id"
    )
    
    # 规则信息
    rule_code = Column(
        String(50),
        nullable=False,
        comment="规则编号，如RF02、L032"
    )
    
    rule_name = Column(
        String(200),
        nullable=True,
        comment="规则名称"
    )
    
    # 严重程度
    severity = Column(
        String(20),
        nullable=True,
        comment="SQLFluff原始严重度：critical/warning"
    )
    
    severity_level = Column(
        String(20),
        nullable=True,
        comment="规则分级：INFO/MINOR/MAJOR/BLOCKER/CRITICAL"
    )
    
    # 位置信息
    line_no = Column(
        Integer,
        nullable=True,
        comment="问题所在行号"
    )
    
    line_pos = Column(
        Integer,
        nullable=True,
        comment="问题所在列号"
    )
    
    # 问题详情
    description = Column(
        Text,
        nullable=True,
        comment="问题描述"
    )
    
    sql_line = Column(
        Text,
        nullable=True,
        comment="问题所在的SQL代码行"
    )
    
    # 其他属性
    fixable = Column(
        Boolean,
        default=False,
        comment="是否可自动修复"
    )
    
    is_appealed = Column(
        Boolean,
        default=False,
        comment="是否被申诉：0-未申诉，1-已申诉"
    )
    
    support = Column(
        Text,
        nullable=True,
        comment="规则支持信息，描述对应violation如何解决的信息（来自修改后的SQLFluff）"
    )
    
    # 时间戳
    created_at = Column(
        DateTime(6),
        nullable=False,
        default=func.now(),
        comment="创建时间"
    )
    
    # 关系定义
    task = relationship(
        "LintingTask",
        back_populates="violations"
    )
    
    def __repr__(self):
        return f"<LintingViolation(id={self.id}, task_id='{self.task_id}', rule_code='{self.rule_code}')>"
    
    def to_dict(self):
        """转换为字典格式"""
        return {
            'id': self.id,
            'task_id': self.task_id,
            'job_id': self.job_id,
            'rule_code': self.rule_code,
            'rule_name': self.rule_name,
            'severity': self.severity,
            'severity_level': self.severity_level,
            'line_no': self.line_no,
            'line_pos': self.line_pos,
            'description': self.description,
            'sql_line': self.sql_line,
            'fixable': self.fixable,
            'is_appealed': self.is_appealed,
            'support': self.support,
            'created_at': self.created_at
        } 