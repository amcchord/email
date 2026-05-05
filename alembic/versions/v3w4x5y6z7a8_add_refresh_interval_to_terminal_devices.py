"""Add refresh_interval_sec to terminal_devices.

Revision ID: v3w4x5y6z7a8
Revises: u2v3w4x5y6z7
Create Date: 2026-05-04
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "v3w4x5y6z7a8"
down_revision: Union[str, None] = "u2v3w4x5y6z7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from sqlalchemy import inspect as sa_inspect
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    existing = {c["name"] for c in inspector.get_columns("terminal_devices")}
    if "refresh_interval_sec" not in existing:
        op.add_column(
            "terminal_devices",
            sa.Column("refresh_interval_sec", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("terminal_devices", "refresh_interval_sec")
