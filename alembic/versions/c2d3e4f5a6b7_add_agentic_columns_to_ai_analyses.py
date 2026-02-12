"""Add agentic columns (is_subscription, needs_reply, unsubscribe_info) to ai_analyses.

Revision ID: c2d3e4f5a6b7
Revises: b1a2c3d4e5f6
Create Date: 2026-02-12
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, None] = "b1a2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ai_analyses", sa.Column("is_subscription", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("ai_analyses", sa.Column("needs_reply", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("ai_analyses", sa.Column("unsubscribe_info", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_analyses", "unsubscribe_info")
    op.drop_column("ai_analyses", "needs_reply")
    op.drop_column("ai_analyses", "is_subscription")
