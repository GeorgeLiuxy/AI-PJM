"""Create delivery result tables and actor fields

Revision ID: 010
Revises: 009
Create Date: 2026-05-27 13:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def json_type():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("delivery_demand_items") as batch:
        batch.add_column(sa.Column("manual_approval_status", sa.String(length=50), nullable=True))
        batch.add_column(sa.Column("manual_approval_user_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("manual_approval_ref", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("manual_approval_note", sa.Text(), nullable=True))
        batch.add_column(sa.Column("manual_approval_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key(
            "fk_delivery_demand_items_manual_approval_user_id_auth_users",
            "auth_users",
            ["manual_approval_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_delivery_demand_items_manual_approval_user_id",
        "delivery_demand_items",
        ["manual_approval_user_id"],
    )
    op.create_index(
        "ix_delivery_demand_items_manual_approval_status",
        "delivery_demand_items",
        ["manual_approval_status"],
    )

    op.create_table(
        "delivery_merge_request_records",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("coding_task_id", sa.BigInteger(), nullable=False),
        sa.Column("execution_run_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("review_status", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("source_branch", sa.String(length=500), nullable=False),
        sa.Column("target_branch", sa.String(length=500), nullable=False),
        sa.Column("external_id", sa.String(length=200), nullable=True),
        sa.Column("url", sa.String(length=1000), nullable=True),
        sa.Column("review_summary", sa.Text(), nullable=True),
        sa.Column("review_comments_json", json_type(), nullable=False),
        sa.Column("evidence_json", json_type(), nullable=True),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by_ref", sa.String(length=200), nullable=True),
        sa.Column("reviewed_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("reviewed_by_ref", sa.String(length=200), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["coding_task_id"], ["delivery_coding_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["auth_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["execution_run_id"], ["delivery_execution_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["auth_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_delivery_merge_request_records_coding_task_id",
        "delivery_merge_request_records",
        ["coding_task_id"],
    )
    op.create_index(
        "ix_delivery_merge_request_records_execution_run_id",
        "delivery_merge_request_records",
        ["execution_run_id"],
    )
    op.create_index(
        "ix_delivery_merge_request_records_status",
        "delivery_merge_request_records",
        ["status"],
    )
    op.create_index(
        "ix_delivery_merge_request_records_review_status",
        "delivery_merge_request_records",
        ["review_status"],
    )
    op.create_index(
        "ix_delivery_merge_request_records_created_by_user_id",
        "delivery_merge_request_records",
        ["created_by_user_id"],
    )
    op.create_index(
        "ix_delivery_merge_request_records_reviewed_by_user_id",
        "delivery_merge_request_records",
        ["reviewed_by_user_id"],
    )

    op.create_table(
        "delivery_deploy_records",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("merge_request_id", sa.BigInteger(), nullable=False),
        sa.Column("coding_task_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("environment", sa.String(length=100), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=True),
        sa.Column("evidence_json", json_type(), nullable=True),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by_ref", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["coding_task_id"], ["delivery_coding_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["auth_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["merge_request_id"], ["delivery_merge_request_records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_delivery_deploy_records_merge_request_id", "delivery_deploy_records", ["merge_request_id"])
    op.create_index("ix_delivery_deploy_records_coding_task_id", "delivery_deploy_records", ["coding_task_id"])
    op.create_index("ix_delivery_deploy_records_status", "delivery_deploy_records", ["status"])
    op.create_index(
        "ix_delivery_deploy_records_created_by_user_id",
        "delivery_deploy_records",
        ["created_by_user_id"],
    )

    op.create_table(
        "delivery_verification_records",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("deploy_record_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("verifier_user_id", sa.BigInteger(), nullable=True),
        sa.Column("verifier_ref", sa.String(length=200), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("evidence_links_json", json_type(), nullable=False),
        sa.Column("evidence_json", json_type(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["deploy_record_id"], ["delivery_deploy_records.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["verifier_user_id"], ["auth_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_delivery_verification_records_deploy_record_id",
        "delivery_verification_records",
        ["deploy_record_id"],
    )
    op.create_index("ix_delivery_verification_records_status", "delivery_verification_records", ["status"])
    op.create_index(
        "ix_delivery_verification_records_verifier_user_id",
        "delivery_verification_records",
        ["verifier_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_delivery_verification_records_verifier_user_id", table_name="delivery_verification_records")
    op.drop_index("ix_delivery_verification_records_status", table_name="delivery_verification_records")
    op.drop_index("ix_delivery_verification_records_deploy_record_id", table_name="delivery_verification_records")
    op.drop_table("delivery_verification_records")

    op.drop_index("ix_delivery_deploy_records_created_by_user_id", table_name="delivery_deploy_records")
    op.drop_index("ix_delivery_deploy_records_status", table_name="delivery_deploy_records")
    op.drop_index("ix_delivery_deploy_records_coding_task_id", table_name="delivery_deploy_records")
    op.drop_index("ix_delivery_deploy_records_merge_request_id", table_name="delivery_deploy_records")
    op.drop_table("delivery_deploy_records")

    op.drop_index("ix_delivery_merge_request_records_reviewed_by_user_id", table_name="delivery_merge_request_records")
    op.drop_index("ix_delivery_merge_request_records_created_by_user_id", table_name="delivery_merge_request_records")
    op.drop_index("ix_delivery_merge_request_records_review_status", table_name="delivery_merge_request_records")
    op.drop_index("ix_delivery_merge_request_records_status", table_name="delivery_merge_request_records")
    op.drop_index("ix_delivery_merge_request_records_execution_run_id", table_name="delivery_merge_request_records")
    op.drop_index("ix_delivery_merge_request_records_coding_task_id", table_name="delivery_merge_request_records")
    op.drop_table("delivery_merge_request_records")

    op.drop_index("ix_delivery_demand_items_manual_approval_status", table_name="delivery_demand_items")
    op.drop_index("ix_delivery_demand_items_manual_approval_user_id", table_name="delivery_demand_items")
    with op.batch_alter_table("delivery_demand_items") as batch:
        batch.drop_constraint("fk_delivery_demand_items_manual_approval_user_id_auth_users", type_="foreignkey")
        batch.drop_column("manual_approval_at")
        batch.drop_column("manual_approval_note")
        batch.drop_column("manual_approval_ref")
        batch.drop_column("manual_approval_user_id")
        batch.drop_column("manual_approval_status")
