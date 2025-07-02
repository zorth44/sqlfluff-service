"""
数据库模型定义

定义linting_jobs和linting_tasks表的SQLAlchemy模型。
包含表结构、关系、索引和约束定义。
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, Enum, ForeignKey, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
from typing import List, Optional

from app.core.database import Base


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
        comment="Celery任务的UUID"
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