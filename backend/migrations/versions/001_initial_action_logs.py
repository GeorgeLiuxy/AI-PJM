"""Initial action_logs table

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create action_logs table"""
    op.create_table(
        'action_logs',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('biz_type', sa.String(length=50), nullable=False, comment='Business entity type: item | analysis | output'),
        sa.Column('biz_id', sa.BigInteger(), nullable=False, comment='Business entity ID'),
        sa.Column('action_type', sa.String(length=100), nullable=False, comment='Action type'),
        sa.Column('operator_type', sa.String(length=50), nullable=False, comment='Operator type: user | ai | system'),
        sa.Column('operator_ref', sa.String(length=200), nullable=True, comment='Operator reference'),
        sa.Column('from_status', sa.String(length=100), nullable=True, comment='Previous status'),
        sa.Column('to_status', sa.String(length=100), nullable=True, comment='New status'),
        sa.Column('action_payload', postgresql.JSONB(), nullable=True, comment='Action payload'),
        sa.Column('comment', sa.Text(), nullable=True, comment='Additional comment'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, comment='Timestamp'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes
    op.create_index('ix_action_logs_biz', 'action_logs', ['biz_type', 'biz_id'])
    op.create_index('ix_action_logs_created_at', 'action_logs', ['created_at'])
    op.create_index('ix_action_logs_operator', 'action_logs', ['operator_type', 'operator_ref'])


def downgrade() -> None:
    """Drop action_logs table"""
    op.drop_index('ix_action_logs_operator', table_name='action_logs')
    op.drop_index('ix_action_logs_created_at', table_name='action_logs')
    op.drop_index('ix_action_logs_biz', table_name='action_logs')
    op.drop_table('action_logs')
