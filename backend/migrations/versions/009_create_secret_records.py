"""Create secret records table

Revision ID: 009
Revises: 008
Create Date: 2026-05-27 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def json_type():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "secret_records",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("key_id", sa.String(length=100), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("value_hash", sa.String(length=128), nullable=False),
        sa.Column("value_mask", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("metadata_json", json_type(), nullable=True),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("updated_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["auth_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["auth_projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["auth_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_secret_records_project_name"),
    )
    op.create_index("ix_secret_records_project_id", "secret_records", ["project_id"])
    op.create_index("ix_secret_records_provider", "secret_records", ["provider"])
    op.create_index("ix_secret_records_status", "secret_records", ["status"])
    op.create_index("ix_secret_records_created_at", "secret_records", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_secret_records_created_at", table_name="secret_records")
    op.drop_index("ix_secret_records_status", table_name="secret_records")
    op.drop_index("ix_secret_records_provider", table_name="secret_records")
    op.drop_index("ix_secret_records_project_id", table_name="secret_records")
    op.drop_table("secret_records")
