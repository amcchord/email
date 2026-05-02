"""Add api_tokens table for read-only public API.

Revision ID: t1u2v3w4x5y6
Revises: s0t1u2v3w4x5
Create Date: 2026-05-02
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "t1u2v3w4x5y6"
down_revision: Union[str, None] = "s0t1u2v3w4x5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from sqlalchemy import inspect as sa_inspect
    bind = op.get_bind()
    inspector = sa_inspect(bind)

    if "api_tokens" not in inspector.get_table_names():
        op.create_table(
            "api_tokens",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.Text(), nullable=False, server_default=""),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("prefix", sa.String(length=12), nullable=False, server_default=""),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        )

    existing_indexes = {ix["name"] for ix in inspector.get_indexes("api_tokens")} if "api_tokens" in inspector.get_table_names() else set()
    if "ix_api_tokens_token_hash" not in existing_indexes:
        op.create_index(
            "ix_api_tokens_token_hash", "api_tokens", ["token_hash"], unique=True
        )
    if "ix_api_tokens_user_id" not in existing_indexes:
        op.create_index("ix_api_tokens_user_id", "api_tokens", ["user_id"])
    if "ix_api_tokens_user_active" not in existing_indexes:
        op.create_index(
            "ix_api_tokens_user_active", "api_tokens", ["user_id", "revoked_at"]
        )


def downgrade() -> None:
    op.drop_index("ix_api_tokens_user_active", table_name="api_tokens")
    op.drop_index("ix_api_tokens_user_id", table_name="api_tokens")
    op.drop_index("ix_api_tokens_token_hash", table_name="api_tokens")
    op.drop_table("api_tokens")
