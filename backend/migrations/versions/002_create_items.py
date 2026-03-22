"""Create items and item_suggestions tables

Revision ID: 002
Revises: 001
Create Date: 2025-01-01 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create items and item_suggestions tables"""
    
    # Create items table
    op.create_table(
        'items',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('raw_input', sa.Text(), nullable=False, comment='用户原始输入'),
        sa.Column('source_type', sa.String(length=50), nullable=False, comment='输入来源'),
        sa.Column('title_final', sa.String(length=500), nullable=True, comment='最终确认的标题'),
        sa.Column('final_type', sa.String(length=50), nullable=True, comment='最终确认的类型'),
        sa.Column('final_priority', sa.String(length=50), nullable=True, comment='最终确认的优先级'),
        sa.Column('final_project', sa.String(length=200), nullable=True, comment='最终归属的项目'),
        sa.Column('status', sa.String(length=50), nullable=False, default='draft', comment='状态'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, comment='更新时间'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_items_status', 'items', ['status'])
    op.create_index('ix_items_source_type', 'items', ['source_type'])
    op.create_index('ix_items_created_at', 'items', ['created_at'])
    
    # Create item_suggestions table with JSONB
    op.create_table(
        'item_suggestions',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('item_id', sa.BigInteger(), nullable=False, comment='关联的Item ID（唯一）'),
        sa.Column('title_suggestion', sa.String(length=500), nullable=False, comment='AI建议的标题'),
        sa.Column('type_suggestion', sa.String(length=50), nullable=False, comment='AI建议的类型'),
        sa.Column('priority_suggestion', sa.String(length=50), nullable=False, comment='AI建议的优先级'),
        sa.Column('project_suggestion', sa.String(length=200), nullable=True, comment='AI建议归属的项目'),
        sa.Column('modules_suggestion_json', postgresql.JSONB(), nullable=True, comment='AI建议的影响模块列表 (JSONB)'),
        sa.Column('impact_scope_suggestion', sa.Text(), nullable=True, comment='AI建议的影响范围描述'),
        sa.Column('pending_questions_json', postgresql.JSONB(), nullable=True, comment='AI提出的待确认问题列表 (JSONB)'),
        sa.Column('similar_cases_json', postgresql.JSONB(), nullable=True, comment='AI找到的相似案例列表 (JSONB)'),
        sa.Column('recommendation_suggestion', sa.Text(), nullable=True, comment='AI的建议结论'),
        sa.Column('confidence_score', sa.Numeric(5, 2), nullable=True, comment='AI置信度 (0-100)'),
        sa.Column('evidence_summary', sa.Text(), nullable=True, comment='AI证据摘要'),
        sa.Column('ai_model_version', sa.String(length=100), nullable=True, comment='AI模型版本标识'),
        sa.Column('is_confirmed', sa.Boolean(), nullable=False, default=False, comment='是否已被用户确认'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, comment='创建时间'),
        sa.ForeignKeyConstraint(['item_id'], ['items.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('item_id', name='uq_item_suggestions_item_id')
    )
    op.create_index('ix_item_suggestions_item_id', 'item_suggestions', ['item_id'], unique=True)
    op.create_index('ix_item_suggestions_confidence', 'item_suggestions', ['confidence_score'])


def downgrade() -> None:
    """Drop items and item_suggestions tables"""
    op.drop_index('ix_item_suggestions_confidence', table_name='item_suggestions')
    op.drop_index('ix_item_suggestions_item_id', table_name='item_suggestions')
    op.drop_table('item_suggestions')
    
    op.drop_index('ix_items_created_at', table_name='items')
    op.drop_index('ix_items_source_type', table_name='items')
    op.drop_index('ix_items_status', table_name='items')
    op.drop_table('items')
