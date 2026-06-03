"""Create auth and project access tables

Revision ID: 007
Revises: 006
Create Date: 2026-05-27 10:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def json_type():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "auth_users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_index("ix_auth_users_username", "auth_users", ["username"])
    op.create_index("ix_auth_users_role", "auth_users", ["role"])
    op.create_index("ix_auth_users_status", "auth_users", ["status"])

    op.create_table(
        "auth_projects",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("repository_root", sa.String(length=1000), nullable=True),
        sa.Column("default_branch", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("settings_json", json_type(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_index("ix_auth_projects_key", "auth_projects", ["key"])
    op.create_index("ix_auth_projects_status", "auth_projects", ["status"])

    op.create_table(
        "auth_project_members",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["auth_projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["auth_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "project_id", name="uq_auth_project_members_user_project"),
    )
    op.create_index("ix_auth_project_members_user_id", "auth_project_members", ["user_id"])
    op.create_index("ix_auth_project_members_project_id", "auth_project_members", ["project_id"])
    op.create_index("ix_auth_project_members_role", "auth_project_members", ["role"])

    op.create_table(
        "auth_api_tokens",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("scopes_json", json_type(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["auth_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_auth_api_tokens_user_id", "auth_api_tokens", ["user_id"])
    op.create_index("ix_auth_api_tokens_token_hash", "auth_api_tokens", ["token_hash"])
    op.create_index("ix_auth_api_tokens_revoked_at", "auth_api_tokens", ["revoked_at"])

    with op.batch_alter_table("delivery_demand_items") as batch:
        batch.add_column(sa.Column("project_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("created_by_user_id", sa.BigInteger(), nullable=True))
        batch.create_foreign_key(
            "fk_delivery_demand_items_project_id_auth_projects",
            "auth_projects",
            ["project_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_delivery_demand_items_created_by_user_id_auth_users",
            "auth_users",
            ["created_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index("ix_delivery_demand_items_project_id", "delivery_demand_items", ["project_id"])
    op.create_index(
        "ix_delivery_demand_items_created_by_user_id",
        "delivery_demand_items",
        ["created_by_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_delivery_demand_items_created_by_user_id", table_name="delivery_demand_items")
    op.drop_index("ix_delivery_demand_items_project_id", table_name="delivery_demand_items")
    with op.batch_alter_table("delivery_demand_items") as batch:
        batch.drop_constraint(
            "fk_delivery_demand_items_created_by_user_id_auth_users",
            type_="foreignkey",
        )
        batch.drop_constraint(
            "fk_delivery_demand_items_project_id_auth_projects",
            type_="foreignkey",
        )
        batch.drop_column("created_by_user_id")
        batch.drop_column("project_id")

    op.drop_index("ix_auth_api_tokens_revoked_at", table_name="auth_api_tokens")
    op.drop_index("ix_auth_api_tokens_token_hash", table_name="auth_api_tokens")
    op.drop_index("ix_auth_api_tokens_user_id", table_name="auth_api_tokens")
    op.drop_table("auth_api_tokens")

    op.drop_index("ix_auth_project_members_role", table_name="auth_project_members")
    op.drop_index("ix_auth_project_members_project_id", table_name="auth_project_members")
    op.drop_index("ix_auth_project_members_user_id", table_name="auth_project_members")
    op.drop_table("auth_project_members")

    op.drop_index("ix_auth_projects_status", table_name="auth_projects")
    op.drop_index("ix_auth_projects_key", table_name="auth_projects")
    op.drop_table("auth_projects")

    op.drop_index("ix_auth_users_status", table_name="auth_users")
    op.drop_index("ix_auth_users_role", table_name="auth_users")
    op.drop_index("ix_auth_users_username", table_name="auth_users")
    op.drop_table("auth_users")
