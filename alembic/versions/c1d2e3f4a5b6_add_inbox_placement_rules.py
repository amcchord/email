"""Add private account-scoped Inbox placement rules.

Revision ID: c1d2e3f4a5b6
Revises: b1c2d3e4f5a6
Create Date: 2026-08-31

The upgrade is additive and performs no email backfill or provider mutation.
The downgrade drops user-created local rules and is therefore data-lossy.
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op


revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "inbox_placement_rules",
        sa.Column("row_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("create_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("match_value", sa.String(length=512), nullable=False),
        sa.Column("placement", sa.String(length=16), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
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
            "scope IN ('conversation', 'sender', 'domain')",
            name="ck_inbox_placement_rules_scope",
        ),
        sa.CheckConstraint(
            "placement IN ('focused', 'other')",
            name="ck_inbox_placement_rules_placement",
        ),
        sa.CheckConstraint(
            "char_length(match_value) BETWEEN 1 AND 512",
            name="ck_inbox_placement_rules_match_value",
        ),
        sa.CheckConstraint(
            "revision > 0",
            name="ck_inbox_placement_rules_revision",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["google_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("row_id"),
        sa.UniqueConstraint(
            "account_id",
            "id",
            name="uq_inbox_placement_rules_account_public_id",
        ),
        sa.UniqueConstraint(
            "account_id",
            "create_id",
            name="uq_inbox_placement_rules_account_create_id",
        ),
        sa.UniqueConstraint(
            "account_id",
            "scope",
            "match_value",
            name="uq_inbox_placement_rules_account_match",
        ),
    )


def downgrade() -> None:
    op.drop_table("inbox_placement_rules")
