"""Add provider metadata to spec cards

Revision ID: 011
Revises: 010
Create Date: 2026-06-04 11:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def json_type():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("delivery_spec_cards") as batch:
        batch.add_column(sa.Column("provider_metadata_json", json_type(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("delivery_spec_cards") as batch:
        batch.drop_column("provider_metadata_json")
