"""create_linting_violations_table

Revision ID: abc123456789
Revises: ffd49b17f727
Create Date: 2025-10-21 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = 'abc123456789'
down_revision: Union[str, Sequence[str], None] = 'ffd49b17f727'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 创建 linting_violations 表
    op.create_table(
        'linting_violations',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False, comment='自增主键'),
        sa.Column('task_id', sa.String(length=255), nullable=False, comment='关联linting_tasks.task_id'),
        sa.Column('job_id', sa.String(length=255), nullable=False, comment='冗余字段，关联linting_jobs.job_id'),
        sa.Column('rule_code', sa.String(length=50), nullable=False, comment='规则编号，如RF02、L032'),
        sa.Column('rule_name', sa.String(length=200), nullable=True, comment='规则名称'),
        sa.Column('severity', sa.String(length=20), nullable=True, comment='SQLFluff原始严重度：critical/warning'),
        sa.Column('severity_level', sa.String(length=20), nullable=True, comment='规则分级：INFO/MINOR/MAJOR/BLOCKER/CRITICAL'),
        sa.Column('line_no', sa.Integer(), nullable=True, comment='问题所在行号'),
        sa.Column('line_pos', sa.Integer(), nullable=True, comment='问题所在列号'),
        sa.Column('description', sa.Text(), nullable=True, comment='问题描述'),
        sa.Column('sql_line', sa.Text(), nullable=True, comment='问题所在的SQL代码行'),
        sa.Column('fixable', sa.Boolean(), nullable=True, default=False, comment='是否可自动修复'),
        sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP(6)'), comment='创建时间'),
        sa.PrimaryKeyConstraint('id'),
        comment='SQL检查结果明细表，存储每个文件的具体违规项'
    )
    
    # 创建索引
    op.create_index('idx_task_id', 'linting_violations', ['task_id'])
    op.create_index('idx_job_rule', 'linting_violations', ['job_id', 'rule_code'])
    op.create_index('idx_job_severity', 'linting_violations', ['job_id', 'severity_level', 'id'])
    op.create_index('idx_task_basic', 'linting_violations', ['task_id', 'rule_code', 'severity_level'])
    op.create_index('idx_rule_stats', 'linting_violations', ['rule_code', 'severity_level', 'job_id'])
    op.create_index('idx_created', 'linting_violations', ['created_at'])


def downgrade() -> None:
    """Downgrade schema."""
    # 删除索引
    op.drop_index('idx_created', table_name='linting_violations')
    op.drop_index('idx_rule_stats', table_name='linting_violations')
    op.drop_index('idx_task_basic', table_name='linting_violations')
    op.drop_index('idx_job_severity', table_name='linting_violations')
    op.drop_index('idx_job_rule', table_name='linting_violations')
    op.drop_index('idx_task_id', table_name='linting_violations')
    
    # 删除表
    op.drop_table('linting_violations')

