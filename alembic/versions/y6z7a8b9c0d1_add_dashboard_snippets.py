"""Add dashboard_snippets table for hourly e-ink calm-state content.

Revision ID: y6z7a8b9c0d1
Revises: x5y6z7a8b9c0
Create Date: 2026-05-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "y6z7a8b9c0d1"
down_revision: Union[str, None] = "x5y6z7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from sqlalchemy import inspect as sa_inspect

    bind = op.get_bind()
    inspector = sa_inspect(bind)
    existing_tables = inspector.get_table_names()

    if "dashboard_snippets" not in existing_tables:
        op.create_table(
            "dashboard_snippets",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("date_local", sa.String(length=10), nullable=False),
            sa.Column("hour_local", sa.Integer(), nullable=False),
            sa.Column("tz_name", sa.String(length=100), nullable=False),
            sa.Column("kind", sa.String(length=32), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("byline", sa.Text(), nullable=True),
            sa.Column(
                "generated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.UniqueConstraint(
                "date_local",
                "hour_local",
                name="uq_dashboard_snippets_date_hour",
            ),
        )

    indexes = (
        {ix["name"] for ix in inspector.get_indexes("dashboard_snippets")}
        if "dashboard_snippets" in inspector.get_table_names()
        else set()
    )
    if "ix_dashboard_snippets_date_hour" not in indexes:
        op.create_index(
            "ix_dashboard_snippets_date_hour",
            "dashboard_snippets",
            ["date_local", "hour_local"],
        )


def downgrade() -> None:
    op.drop_index(
        "ix_dashboard_snippets_date_hour",
        table_name="dashboard_snippets",
    )
    op.drop_table("dashboard_snippets")
