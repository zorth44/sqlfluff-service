"""add_severity_level_fields_to_linting_tasks

Revision ID: ffd49b17f727
Revises: f95de669fc99
Create Date: 2025-10-10 15:22:58.090802

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ffd49b17f727'
down_revision: Union[str, Sequence[str], None] = 'f95de669fc99'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 添加 severity level 统计字段到 linting_tasks 表
    op.add_column('linting_tasks', sa.Column('severity_info', sa.Integer(), nullable=True, comment='INFO级别违规项数量'))
    op.add_column('linting_tasks', sa.Column('severity_minor', sa.Integer(), nullable=True, comment='MINOR级别违规项数量'))
    op.add_column('linting_tasks', sa.Column('severity_major', sa.Integer(), nullable=True, comment='MAJOR级别违规项数量'))
    op.add_column('linting_tasks', sa.Column('severity_blocker', sa.Integer(), nullable=True, comment='BLOCKER级别违规项数量'))
    op.add_column('linting_tasks', sa.Column('severity_critical', sa.Integer(), nullable=True, comment='CRITICAL级别违规项数量'))
    op.add_column('linting_tasks', sa.Column('severity_unknown', sa.Integer(), nullable=True, comment='UNKNOWN级别违规项数量'))


def downgrade() -> None:
    """Downgrade schema."""
    # 删除 severity level 统计字段
    op.drop_column('linting_tasks', 'severity_unknown')
    op.drop_column('linting_tasks', 'severity_critical')
    op.drop_column('linting_tasks', 'severity_blocker')
    op.drop_column('linting_tasks', 'severity_major')
    op.drop_column('linting_tasks', 'severity_minor')
    op.drop_column('linting_tasks', 'severity_info')
