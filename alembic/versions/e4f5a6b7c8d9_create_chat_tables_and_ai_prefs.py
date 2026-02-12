"""Create chat_conversations, chat_messages tables and add ai_preferences to users.

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-02-12
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "e4f5a6b7c8d9"
down_revision: Union[str, None] = "d3e4f5a6b7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Chat conversations table
    op.create_table(
        "chat_conversations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_chat_conversations_user", "chat_conversations", ["user_id"])

    # Chat messages table
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "conversation_id", sa.BigInteger(),
            sa.ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("plan", JSONB, nullable=True),
        sa.Column("task_results", JSONB, nullable=True),
        sa.Column("tokens_used", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_chat_messages_conversation", "chat_messages", ["conversation_id"])

    # Add ai_preferences JSONB column to users
    op.add_column("users", sa.Column("ai_preferences", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("users", "ai_preferences")
    op.drop_index("ix_chat_messages_conversation")
    op.drop_table("chat_messages")
    op.drop_index("ix_chat_conversations_user")
    op.drop_table("chat_conversations")
