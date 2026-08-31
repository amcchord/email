"""Add revisioned per-account signatures.

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
Create Date: 2026-08-31

The upgrade is additive and requires no backfill: an absent row is the safe,
disabled revision-zero default. The downgrade intentionally drops user-created
signature content and is therefore data-lossy.
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op


revision: str = "f9a0b1c2d3e4"
down_revision: Union[str, None] = "e8f9a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "account_signatures",
        sa.Column("account_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("include_on_new", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("include_on_replies", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("include_on_forwards", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("body_html", sa.Text(), nullable=False, server_default=""),
        sa.Column("body_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("sanitizer_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
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
        sa.CheckConstraint("revision > 0", name="ck_account_signatures_revision"),
        sa.CheckConstraint(
            "sanitizer_version > 0",
            name="ck_account_signatures_sanitizer_version",
        ),
        sa.CheckConstraint(
            "char_length(body_html) <= 50000 AND char_length(body_text) <= 20000",
            name="ck_account_signatures_body_bounds",
        ),
        sa.CheckConstraint(
            "NOT enabled OR (char_length(body_html) > 0 AND char_length(body_text) > 0)",
            name="ck_account_signatures_enabled_body",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["google_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("account_id"),
    )


def downgrade() -> None:
    op.drop_table("account_signatures")
