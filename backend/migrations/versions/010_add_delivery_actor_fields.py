"""Add structured actor fields to delivery records

Revision ID: 010
Revises: 009
Create Date: 2026-05-27 13:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


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

    with op.batch_alter_table("delivery_merge_request_records") as batch:
        batch.add_column(sa.Column("created_by_user_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("created_by_ref", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("reviewed_by_user_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("reviewed_by_ref", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key(
            "fk_delivery_merge_request_records_created_by_user_id_auth_users",
            "auth_users",
            ["created_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_delivery_merge_request_records_reviewed_by_user_id_auth_users",
            "auth_users",
            ["reviewed_by_user_id"],
            ["id"],
            ondelete="SET NULL",
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

    with op.batch_alter_table("delivery_deploy_records") as batch:
        batch.add_column(sa.Column("created_by_user_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("created_by_ref", sa.String(length=200), nullable=True))
        batch.create_foreign_key(
            "fk_delivery_deploy_records_created_by_user_id_auth_users",
            "auth_users",
            ["created_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_delivery_deploy_records_created_by_user_id",
        "delivery_deploy_records",
        ["created_by_user_id"],
    )

    with op.batch_alter_table("delivery_verification_records") as batch:
        batch.add_column(sa.Column("verifier_user_id", sa.BigInteger(), nullable=True))
        batch.create_foreign_key(
            "fk_delivery_verification_records_verifier_user_id_auth_users",
            "auth_users",
            ["verifier_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_delivery_verification_records_verifier_user_id",
        "delivery_verification_records",
        ["verifier_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_delivery_verification_records_verifier_user_id", table_name="delivery_verification_records")
    with op.batch_alter_table("delivery_verification_records") as batch:
        batch.drop_constraint("fk_delivery_verification_records_verifier_user_id_auth_users", type_="foreignkey")
        batch.drop_column("verifier_user_id")

    op.drop_index("ix_delivery_deploy_records_created_by_user_id", table_name="delivery_deploy_records")
    with op.batch_alter_table("delivery_deploy_records") as batch:
        batch.drop_constraint("fk_delivery_deploy_records_created_by_user_id_auth_users", type_="foreignkey")
        batch.drop_column("created_by_ref")
        batch.drop_column("created_by_user_id")

    op.drop_index("ix_delivery_merge_request_records_reviewed_by_user_id", table_name="delivery_merge_request_records")
    op.drop_index("ix_delivery_merge_request_records_created_by_user_id", table_name="delivery_merge_request_records")
    with op.batch_alter_table("delivery_merge_request_records") as batch:
        batch.drop_constraint("fk_delivery_merge_request_records_reviewed_by_user_id_auth_users", type_="foreignkey")
        batch.drop_constraint("fk_delivery_merge_request_records_created_by_user_id_auth_users", type_="foreignkey")
        batch.drop_column("reviewed_at")
        batch.drop_column("reviewed_by_ref")
        batch.drop_column("reviewed_by_user_id")
        batch.drop_column("created_by_ref")
        batch.drop_column("created_by_user_id")

    op.drop_index("ix_delivery_demand_items_manual_approval_status", table_name="delivery_demand_items")
    op.drop_index("ix_delivery_demand_items_manual_approval_user_id", table_name="delivery_demand_items")
    with op.batch_alter_table("delivery_demand_items") as batch:
        batch.drop_constraint("fk_delivery_demand_items_manual_approval_user_id_auth_users", type_="foreignkey")
        batch.drop_column("manual_approval_at")
        batch.drop_column("manual_approval_note")
        batch.drop_column("manual_approval_ref")
        batch.drop_column("manual_approval_user_id")
        batch.drop_column("manual_approval_status")
