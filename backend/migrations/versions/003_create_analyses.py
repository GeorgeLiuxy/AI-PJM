"""Create analyses table

Revision ID: 003
Revises: 002
Create Date: 2025-01-01 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create analyses table"""

    op.create_table(
        'analyses',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('item_id', sa.BigInteger(), nullable=False, comment='关联的Item ID（唯一，一个Item只能有一个Analysis）'),
        sa.Column('analysis_type', sa.String(length=50), nullable=False, server_default='impact_assessment', comment='分析类型: impact_assessment（固定值）'),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='pending', comment='状态: pending | running | pending_review | confirmed'),
        sa.Column('business_value_score', sa.Integer(), nullable=True, comment='业务价值评分 (1-5)'),
        sa.Column('technical_impact_score', sa.Integer(), nullable=True, comment='技术影响评分 (1-5)'),
        sa.Column('risk_level', sa.String(length=50), nullable=True, comment='风险等级: low | medium | high'),
        sa.Column('candidate_capabilities_json', postgresql.JSONB(), nullable=True, comment='候选能力列表 (list[str])'),
        sa.Column('candidate_modules_json', postgresql.JSONB(), nullable=True, comment='候选模块列表 (list[str])'),
        sa.Column('similar_cases_json', postgresql.JSONB(), nullable=True, comment='相似案例列表 (list[dict])'),
        sa.Column('ai_recommendation', sa.String(length=50), nullable=True, comment='AI建议结论: do_now | evaluate_first | plan_later | hold'),
        sa.Column('final_recommendation', sa.String(length=50), nullable=True, comment='最终确认结论: do_now | evaluate_first | plan_later | hold'),
        sa.Column('confidence_score', sa.Numeric(5, 2), nullable=True, comment='AI置信度 (0-100)，两位小数'),
        sa.Column('evidence_summary', sa.Text(), nullable=True, comment='AI证据摘要'),
        sa.Column('missing_information', sa.Text(), nullable=True, comment='缺失信息说明'),
        sa.Column('needs_deep_analysis', sa.Boolean(), nullable=True, server_default='false', comment='是否需要深度分析'),
        sa.Column('review_comment', sa.Text(), nullable=True, comment='复核评论'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, comment='更新时间'),
        sa.ForeignKeyConstraint(['item_id'], ['items.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('item_id', name='uq_analyses_item_id')
    )

    # Create indexes
    op.create_index('ix_analyses_item_id', 'analyses', ['item_id'], unique=True)
    op.create_index('ix_analyses_status', 'analyses', ['status'])
    op.create_index('ix_analyses_created_at', 'analyses', ['created_at'])

    # Create check constraints
    op.execute("""
        ALTER TABLE analyses
        ADD CONSTRAINT chk_business_value_score
        CHECK (business_value_score BETWEEN 1 AND 5)
    """)
    op.execute("""
        ALTER TABLE analyses
        ADD CONSTRAINT chk_technical_impact_score
        CHECK (technical_impact_score BETWEEN 1 AND 5)
    """)


def downgrade() -> None:
    """Drop analyses table"""
    op.drop_constraint('chk_technical_impact_score', 'analyses')
    op.drop_constraint('chk_business_value_score', 'analyses')
    op.drop_index('ix_analyses_created_at', table_name='analyses')
    op.drop_index('ix_analyses_status', table_name='analyses')
    op.drop_index('ix_analyses_item_id', table_name='analyses')
    op.drop_table('analyses')
