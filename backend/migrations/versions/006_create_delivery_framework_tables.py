"""Retain delivery framework revision slot

Revision ID: 006
Revises: 005
Create Date: 2026-05-19 10:30:00.000000

"""


revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op.

    The current 005 baseline already creates repo context, impact analysis,
    execution run, and execution log tables. This revision is retained so the
    historical chain remains linear for databases stamped with 006+.
    """


def downgrade() -> None:
    """No-op; 005 owns the framework tables."""
