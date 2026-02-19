"""Add status, screenshots, llm_log, error_message, marked_spam to unsubscribe_tracking.

Revision ID: s0t1u2v3w4x5
Revises: r9s0t1u2v3w4
Create Date: 2026-02-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "s0t1u2v3w4x5"
down_revision: Union[str, None] = "r9s0t1u2v3w4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from sqlalchemy import inspect as sa_inspect
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    existing = [c["name"] for c in inspector.get_columns("unsubscribe_tracking")]

    if "status" not in existing:
        op.add_column("unsubscribe_tracking", sa.Column("status", sa.String(20), server_default="pending", nullable=False))
    if "screenshots" not in existing:
        op.add_column("unsubscribe_tracking", sa.Column("screenshots", JSONB, nullable=True))
    if "llm_log" not in existing:
        op.add_column("unsubscribe_tracking", sa.Column("llm_log", JSONB, nullable=True))
    if "error_message" not in existing:
        op.add_column("unsubscribe_tracking", sa.Column("error_message", sa.Text(), nullable=True))
    if "marked_spam" not in existing:
        op.add_column("unsubscribe_tracking", sa.Column("marked_spam", sa.Boolean(), server_default="false", nullable=False))


def downgrade() -> None:
    op.drop_column("unsubscribe_tracking", "marked_spam")
    op.drop_column("unsubscribe_tracking", "error_message")
    op.drop_column("unsubscribe_tracking", "llm_log")
    op.drop_column("unsubscribe_tracking", "screenshots")
    op.drop_column("unsubscribe_tracking", "status")
