"""Add conversation_type to ai_analyses, create thread_digests and email_bundles tables.

Revision ID: j1k2l3m4n5o6
Revises: i9j0k1l2m3n4
Create Date: 2026-02-13
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "j1k2l3m4n5o6"
down_revision: Union[str, None] = "i9j0k1l2m3n4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add conversation_type to ai_analyses
    op.add_column(
        "ai_analyses",
        sa.Column("conversation_type", sa.String(length=30), nullable=True),
    )

    # Create thread_digests table
    op.create_table(
        "thread_digests",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("gmail_thread_id", sa.String(length=255), nullable=False),
        sa.Column("conversation_type", sa.String(length=30), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("resolved_outcome", sa.Text(), nullable=True),
        sa.Column("is_resolved", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("key_topics", postgresql.JSONB(), server_default="[]", nullable=True),
        sa.Column("message_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("participants", postgresql.JSONB(), server_default="[]", nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("latest_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model_used", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["google_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_thread_digests_account_thread",
        "thread_digests",
        ["account_id", "gmail_thread_id"],
        unique=True,
    )
    op.create_index(
        "ix_thread_digests_latest_date",
        "thread_digests",
        ["latest_date"],
    )
    op.create_index(
        "ix_thread_digests_conversation_type",
        "thread_digests",
        ["conversation_type"],
    )

    # Create email_bundles table
    op.create_table(
        "email_bundles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("key_topics", postgresql.JSONB(), server_default="[]", nullable=True),
        sa.Column("email_ids", postgresql.JSONB(), server_default="[]", nullable=True),
        sa.Column("thread_ids", postgresql.JSONB(), server_default="[]", nullable=True),
        sa.Column("account_ids", postgresql.JSONB(), server_default="[]", nullable=True),
        sa.Column("email_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("thread_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("latest_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_email_bundles_user_id", "email_bundles", ["user_id"])
    op.create_index("ix_email_bundles_latest_date", "email_bundles", ["latest_date"])
    op.create_index("ix_email_bundles_status", "email_bundles", ["status"])


def downgrade() -> None:
    op.drop_index("ix_email_bundles_status", table_name="email_bundles")
    op.drop_index("ix_email_bundles_latest_date", table_name="email_bundles")
    op.drop_index("ix_email_bundles_user_id", table_name="email_bundles")
    op.drop_table("email_bundles")

    op.drop_index("ix_thread_digests_conversation_type", table_name="thread_digests")
    op.drop_index("ix_thread_digests_latest_date", table_name="thread_digests")
    op.drop_index("ix_thread_digests_account_thread", table_name="thread_digests")
    op.drop_table("thread_digests")

    op.drop_column("ai_analyses", "conversation_type")
