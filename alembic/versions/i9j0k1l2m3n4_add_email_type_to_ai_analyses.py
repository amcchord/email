"""Add email_type column to ai_analyses for work/personal classification.

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-02-13
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "i9j0k1l2m3n4"
down_revision: Union[str, None] = "h8i9j0k1l2m3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ai_analyses",
        sa.Column("email_type", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_analyses", "email_type")
