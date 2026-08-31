"""Index attachment ownership joins by email.

Revision ID: b1c2d3e4f5a6
Revises: a0b1c2d3e4f5
Create Date: 2026-08-31

The upgrade is additive and backfills no application data. The index makes
account-scoped attachment metadata queries predictable without storing any new
message or attachment content. The downgrade drops only the index.
"""

from collections.abc import Sequence
from typing import Union

from alembic import op


revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "a0b1c2d3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_attachments_email_id",
        "attachments",
        ["email_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_attachments_email_id", table_name="attachments")
