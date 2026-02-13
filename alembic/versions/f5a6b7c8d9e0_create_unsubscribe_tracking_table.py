"""Create unsubscribe_tracking table.

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-02-12
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "f5a6b7c8d9e0"
down_revision: Union[str, None] = "e4f5a6b7c8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from sqlalchemy import inspect as sa_inspect
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    if "unsubscribe_tracking" not in inspector.get_table_names():
        op.create_table(
            "unsubscribe_tracking",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("email_id", sa.BigInteger(), sa.ForeignKey("emails.id", ondelete="CASCADE"), nullable=False),
            sa.Column("sender_domain", sa.String(255), nullable=False, index=True),
            sa.Column("sender_address", sa.String(255), nullable=False),
            sa.Column("unsubscribe_to", sa.String(255), nullable=True),
            sa.Column("method", sa.String(20), nullable=False),
            sa.Column("unsubscribed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("emails_received_after", sa.Integer(), server_default="0", nullable=False),
            sa.Column("last_email_after_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    op.drop_table("unsubscribe_tracking")
