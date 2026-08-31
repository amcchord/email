"""Add private reusable Personal Snippets.

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
Create Date: 2026-08-30

The upgrade is additive and requires no backfill. The downgrade intentionally
drops user-created snippet content and is therefore data-lossy.
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op


revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, None] = "c6d7e8f9a0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "personal_snippets",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("snippet_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("shortcut", sa.String(length=32), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column(
            "revision",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "revision > 0",
            name="ck_personal_snippets_revision",
        ),
        sa.CheckConstraint(
            "shortcut ~ '^[a-z0-9][a-z0-9_-]{0,31}$'",
            name="ck_personal_snippets_shortcut",
        ),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 120",
            name="ck_personal_snippets_name",
        ),
        sa.CheckConstraint(
            "char_length(body_text) BETWEEN 1 AND 20000 "
            "AND char_length(body_html) BETWEEN 1 AND 50000",
            name="ck_personal_snippets_body",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "snippet_id",
            name="uq_personal_snippets_user_public_id",
        ),
        sa.UniqueConstraint(
            "user_id",
            "shortcut",
            name="uq_personal_snippets_user_shortcut",
        ),
    )
    op.create_index(
        "ix_personal_snippets_user_name",
        "personal_snippets",
        ["user_id", "name", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_personal_snippets_user_name",
        table_name="personal_snippets",
    )
    op.drop_table("personal_snippets")
