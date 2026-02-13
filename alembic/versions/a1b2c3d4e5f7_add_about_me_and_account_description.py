"""Add about_me to users and description to google_accounts.

Revision ID: a1b2c3d4e5f7
Revises: f5a6b7c8d9e0
Create Date: 2026-02-12
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "a1b2c3d4e5f7"
down_revision: Union[str, None] = "f5a6b7c8d9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("about_me", sa.Text(), nullable=True))
    op.add_column("google_accounts", sa.Column("description", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("google_accounts", "description")
    op.drop_column("users", "about_me")
