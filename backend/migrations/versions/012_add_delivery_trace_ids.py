"""Add trace ids to delivery workflow tables

Revision ID: 012
Revises: 011
Create Date: 2026-06-04 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


TRACE_TABLES = [
    "delivery_demand_items",
    "delivery_spec_cards",
    "delivery_gate_checks",
    "delivery_repo_contexts",
    "delivery_impact_analyses",
    "delivery_coding_tasks",
    "delivery_execution_runs",
    "delivery_execution_logs",
    "delivery_merge_request_records",
    "delivery_deploy_records",
    "delivery_verification_records",
]


def upgrade() -> None:
    for table_name in TRACE_TABLES:
        with op.batch_alter_table(table_name) as batch:
            batch.add_column(sa.Column("trace_id", sa.String(length=80), nullable=True))
        op.create_index(f"ix_{table_name}_trace_id", table_name, ["trace_id"])


def downgrade() -> None:
    for table_name in reversed(TRACE_TABLES):
        op.drop_index(f"ix_{table_name}_trace_id", table_name=table_name)
        with op.batch_alter_table(table_name) as batch:
            batch.drop_column("trace_id")
