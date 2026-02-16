"""Add needs_reply_ignored and needs_reply_snoozed_until to ai_analyses.

Revision ID: q8r9s0t1u2v3
Revises: p7q8r9s0t1u2
Create Date: 2026-02-16
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "q8r9s0t1u2v3"
down_revision: Union[str, None] = "p7q8r9s0t1u2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ai_analyses",
        sa.Column("needs_reply_ignored", sa.Boolean, server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "ai_analyses",
        sa.Column("needs_reply_snoozed_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_analyses", "needs_reply_snoozed_until")
    op.drop_column("ai_analyses", "needs_reply_ignored")
