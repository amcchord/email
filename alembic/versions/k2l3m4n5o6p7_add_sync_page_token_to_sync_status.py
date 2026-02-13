"""Add sync_page_token column to sync_status for resumable full syncs.

Revision ID: k2l3m4n5o6p7
Revises: j1k2l3m4n5o6
Create Date: 2026-02-13
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "k2l3m4n5o6p7"
down_revision: Union[str, None] = "j1k2l3m4n5o6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sync_status",
        sa.Column("sync_page_token", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sync_status", "sync_page_token")
