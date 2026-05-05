"""Add timezone to terminal_settings.

Revision ID: x5y6z7a8b9c0
Revises: w4x5y6z7a8b9
Create Date: 2026-05-04
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "x5y6z7a8b9c0"
down_revision: Union[str, None] = "w4x5y6z7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from sqlalchemy import inspect as sa_inspect
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    if "terminal_settings" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("terminal_settings")}
    if "timezone" not in existing:
        # IANA timezone name (e.g. "America/New_York"). Used by the e-ink
        # clock renderer so the displayed time matches the user's wall clock
        # rather than the server's UTC clock. Default keeps existing rows
        # working without a manual backfill; users can change it in the
        # E-Ink Terminals admin tab.
        op.add_column(
            "terminal_settings",
            sa.Column(
                "timezone",
                sa.String(length=100),
                nullable=False,
                server_default="America/New_York",
            ),
        )


def downgrade() -> None:
    op.drop_column("terminal_settings", "timezone")
