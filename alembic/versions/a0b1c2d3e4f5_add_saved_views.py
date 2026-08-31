"""Add private revisioned Saved Views.

Revision ID: a0b1c2d3e4f5
Revises: f9a0b1c2d3e4
Create Date: 2026-08-31

The upgrade is additive and needs no backfill. Saved Views store only a bounded
search definition and ownership metadata, never message results or content.
Account deletion cascades account-scoped views rather than broadening them to
all accounts. The downgrade drops user-created Saved Views and is data-lossy.
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op


revision: str = "a0b1c2d3e4f5"
down_revision: Union[str, None] = "f9a0b1c2d3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "saved_views",
        sa.Column("row_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("create_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("query", sa.String(length=512), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
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
        sa.CheckConstraint("revision > 0", name="ck_saved_views_revision"),
        sa.CheckConstraint("position >= 0", name="ck_saved_views_position"),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 80",
            name="ck_saved_views_name",
        ),
        sa.CheckConstraint(
            "char_length(query) BETWEEN 1 AND 512",
            name="ck_saved_views_query",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["google_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("row_id"),
        sa.UniqueConstraint(
            "user_id", "id", name="uq_saved_views_user_public_id"
        ),
        sa.UniqueConstraint(
            "user_id", "create_id", name="uq_saved_views_user_client_create_id"
        ),
        sa.UniqueConstraint(
            "user_id", "position", name="uq_saved_views_user_position"
        ),
    )
    op.create_index(
        "uq_saved_views_user_name_ci",
        "saved_views",
        ["user_id", sa.text("lower(name)")],
        unique=True,
    )
    op.create_index(
        "ix_saved_views_user_order",
        "saved_views",
        ["user_id", "position", "row_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_saved_views_user_order",
        table_name="saved_views",
    )
    op.drop_index(
        "uq_saved_views_user_name_ci",
        table_name="saved_views",
    )
    op.drop_table("saved_views")
