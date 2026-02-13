"""Add retry_after column to sync_status.

Revision ID: g7h8i9j0k1l2
Revises: a1b2c3d4e5f7
Create Date: 2026-02-12
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "g7h8i9j0k1l2"
down_revision: Union[str, None] = "a1b2c3d4e5f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sync_status", sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("sync_status", "retry_after")
