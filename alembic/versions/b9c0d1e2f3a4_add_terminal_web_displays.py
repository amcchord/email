"""Add scoped browser-display credentials.

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-08-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "b9c0d1e2f3a4"
down_revision: Union[str, None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "terminal_web_displays" in inspector.get_table_names():
        return
    op.create_table(
        "terminal_web_displays",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("view_key", sa.String(length=32), nullable=False),
        sa.Column(
            "design_key",
            sa.String(length=32),
            server_default="",
            nullable=False,
        ),
        sa.Column("profile_key", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "view_key",
            "design_key",
            "profile_key",
            name="uq_terminal_web_displays_user_view",
        ),
    )
    op.create_index(
        "ix_terminal_web_displays_user_id",
        "terminal_web_displays",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_terminal_web_displays_token",
        "terminal_web_displays",
        ["token"],
        unique=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "terminal_web_displays" not in inspector.get_table_names():
        return
    op.drop_index("ix_terminal_web_displays_token", table_name="terminal_web_displays")
    op.drop_index("ix_terminal_web_displays_user_id", table_name="terminal_web_displays")
    op.drop_table("terminal_web_displays")
