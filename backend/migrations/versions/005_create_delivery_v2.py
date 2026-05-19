"""Create delivery v2 tables

Revision ID: 005
Revises: 004
Create Date: 2026-05-19 10:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "delivery_demand_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("raw_input", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("requester_ref", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("risk_level", sa.String(length=20), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("context_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_delivery_demand_items_status", "delivery_demand_items", ["status"])
    op.create_index("ix_delivery_demand_items_risk_level", "delivery_demand_items", ["risk_level"])
    op.create_index("ix_delivery_demand_items_created_at", "delivery_demand_items", ["created_at"])

    op.create_table(
        "delivery_spec_cards",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("demand_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("user_story", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("acceptance_criteria_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("constraints_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("risks_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("open_questions_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["demand_id"], ["delivery_demand_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_delivery_spec_cards_demand_id", "delivery_spec_cards", ["demand_id"])
    op.create_index("ix_delivery_spec_cards_status", "delivery_spec_cards", ["status"])

    op.create_table(
        "delivery_gate_checks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("demand_id", sa.BigInteger(), nullable=False),
        sa.Column("gate_type", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("evidence_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["demand_id"], ["delivery_demand_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_delivery_gate_checks_demand_id", "delivery_gate_checks", ["demand_id"])
    op.create_index("ix_delivery_gate_checks_gate_type", "delivery_gate_checks", ["gate_type"])
    op.create_index("ix_delivery_gate_checks_status", "delivery_gate_checks", ["status"])

    op.create_table(
        "delivery_coding_tasks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("demand_id", sa.BigInteger(), nullable=False),
        sa.Column("spec_card_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("task_prompt", sa.Text(), nullable=False),
        sa.Column("allowed_paths_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("forbidden_actions_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("required_checks_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expected_evidence_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["demand_id"], ["delivery_demand_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["spec_card_id"], ["delivery_spec_cards.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_delivery_coding_tasks_demand_id", "delivery_coding_tasks", ["demand_id"])
    op.create_index("ix_delivery_coding_tasks_spec_card_id", "delivery_coding_tasks", ["spec_card_id"])
    op.create_index("ix_delivery_coding_tasks_status", "delivery_coding_tasks", ["status"])


def downgrade() -> None:
    op.drop_index("ix_delivery_coding_tasks_status", table_name="delivery_coding_tasks")
    op.drop_index("ix_delivery_coding_tasks_spec_card_id", table_name="delivery_coding_tasks")
    op.drop_index("ix_delivery_coding_tasks_demand_id", table_name="delivery_coding_tasks")
    op.drop_table("delivery_coding_tasks")
    op.drop_index("ix_delivery_gate_checks_status", table_name="delivery_gate_checks")
    op.drop_index("ix_delivery_gate_checks_gate_type", table_name="delivery_gate_checks")
    op.drop_index("ix_delivery_gate_checks_demand_id", table_name="delivery_gate_checks")
    op.drop_table("delivery_gate_checks")
    op.drop_index("ix_delivery_spec_cards_status", table_name="delivery_spec_cards")
    op.drop_index("ix_delivery_spec_cards_demand_id", table_name="delivery_spec_cards")
    op.drop_table("delivery_spec_cards")
    op.drop_index("ix_delivery_demand_items_created_at", table_name="delivery_demand_items")
    op.drop_index("ix_delivery_demand_items_risk_level", table_name="delivery_demand_items")
    op.drop_index("ix_delivery_demand_items_status", table_name="delivery_demand_items")
    op.drop_table("delivery_demand_items")
