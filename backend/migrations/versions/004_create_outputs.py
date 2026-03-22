"""Create outputs table

Revision ID: 004
Revises: 003
Create Date: 2025-01-01 03:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        'outputs',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('item_id', sa.BigInteger(), nullable=False),
        sa.Column('analysis_id', sa.BigInteger(), nullable=True),
        sa.Column('output_type', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='pending_confirm'),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('adopted_target', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('adopted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['analysis_id'], ['analyses.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['item_id'], ['items.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('item_id', 'output_type', name='uq_outputs_item_type')
    )
    op.create_index('ix_outputs_item_id', 'outputs', ['item_id'])
    op.create_index('ix_outputs_status', 'outputs', ['status'])
    op.create_index('ix_outputs_output_type', 'outputs', ['output_type'])
    op.create_index('ix_outputs_created_at', 'outputs', ['created_at'])

def downgrade() -> None:
    op.drop_index('ix_outputs_created_at', table_name='outputs')
    op.drop_index('ix_outputs_output_type', table_name='outputs')
    op.drop_index('ix_outputs_status', table_name='outputs')
    op.drop_index('ix_outputs_item_id', table_name='outputs')
    op.drop_table('outputs')
