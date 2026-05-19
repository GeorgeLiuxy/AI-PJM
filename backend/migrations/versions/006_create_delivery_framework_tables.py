"""Create delivery v2 framework tables

Revision ID: 006
Revises: 005
Create Date: 2026-05-19 10:30:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "delivery_repo_contexts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("demand_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("source_refs_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("discovered_files_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("dependency_refs_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("provider_metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["demand_id"], ["delivery_demand_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_delivery_repo_contexts_demand_id", "delivery_repo_contexts", ["demand_id"])
    op.create_index("ix_delivery_repo_contexts_status", "delivery_repo_contexts", ["status"])

    op.create_table(
        "delivery_impact_analyses",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("demand_id", sa.BigInteger(), nullable=False),
        sa.Column("repo_context_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("impacted_areas_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("affected_files_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("recommendations_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("risk_level", sa.String(length=20), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("provider_metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["demand_id"], ["delivery_demand_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["repo_context_id"], ["delivery_repo_contexts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_delivery_impact_analyses_demand_id", "delivery_impact_analyses", ["demand_id"])
    op.create_index("ix_delivery_impact_analyses_repo_context_id", "delivery_impact_analyses", ["repo_context_id"])
    op.create_index("ix_delivery_impact_analyses_status", "delivery_impact_analyses", ["status"])
    op.create_index("ix_delivery_impact_analyses_risk_level", "delivery_impact_analyses", ["risk_level"])

    op.create_table(
        "delivery_execution_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("coding_task_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("executor_type", sa.String(length=50), nullable=False),
        sa.Column("trigger_mode", sa.String(length=50), nullable=False),
        sa.Column("worktree_path", sa.String(length=1000), nullable=True),
        sa.Column("branch_name", sa.String(length=500), nullable=True),
        sa.Column("commit_sha", sa.String(length=100), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("evidence_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["coding_task_id"], ["delivery_coding_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_delivery_execution_runs_coding_task_id", "delivery_execution_runs", ["coding_task_id"])
    op.create_index("ix_delivery_execution_runs_status", "delivery_execution_runs", ["status"])
    op.create_index("ix_delivery_execution_runs_executor_type", "delivery_execution_runs", ["executor_type"])

    op.create_table(
        "delivery_execution_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("execution_run_id", sa.BigInteger(), nullable=False),
        sa.Column("level", sa.String(length=50), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("event_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["execution_run_id"], ["delivery_execution_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_delivery_execution_logs_execution_run_id", "delivery_execution_logs", ["execution_run_id"])
    op.create_index("ix_delivery_execution_logs_level", "delivery_execution_logs", ["level"])


def downgrade() -> None:
    op.drop_index("ix_delivery_execution_logs_level", table_name="delivery_execution_logs")
    op.drop_index("ix_delivery_execution_logs_execution_run_id", table_name="delivery_execution_logs")
    op.drop_table("delivery_execution_logs")
    op.drop_index("ix_delivery_execution_runs_executor_type", table_name="delivery_execution_runs")
    op.drop_index("ix_delivery_execution_runs_status", table_name="delivery_execution_runs")
    op.drop_index("ix_delivery_execution_runs_coding_task_id", table_name="delivery_execution_runs")
    op.drop_table("delivery_execution_runs")
    op.drop_index("ix_delivery_impact_analyses_risk_level", table_name="delivery_impact_analyses")
    op.drop_index("ix_delivery_impact_analyses_status", table_name="delivery_impact_analyses")
    op.drop_index("ix_delivery_impact_analyses_repo_context_id", table_name="delivery_impact_analyses")
    op.drop_index("ix_delivery_impact_analyses_demand_id", table_name="delivery_impact_analyses")
    op.drop_table("delivery_impact_analyses")
    op.drop_index("ix_delivery_repo_contexts_status", table_name="delivery_repo_contexts")
    op.drop_index("ix_delivery_repo_contexts_demand_id", table_name="delivery_repo_contexts")
    op.drop_table("delivery_repo_contexts")
