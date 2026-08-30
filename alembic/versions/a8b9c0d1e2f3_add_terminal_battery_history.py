"""Add sparse terminal battery history for runtime prediction.

Revision ID: a8b9c0d1e2f3
Revises: z7a8b9c0d1e2
Create Date: 2026-08-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, None] = "z7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "terminal_battery_samples" in inspector.get_table_names():
        return
    op.create_table(
        "terminal_battery_samples",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("battery_pct", sa.Integer(), nullable=True),
        sa.Column("battery_mv", sa.Integer(), nullable=True),
        sa.Column("boot_count", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["terminal_devices.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_terminal_battery_samples_device_observed",
        "terminal_battery_samples",
        ["device_id", "observed_at"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "terminal_battery_samples" not in inspector.get_table_names():
        return
    op.drop_index(
        "ix_terminal_battery_samples_device_observed",
        table_name="terminal_battery_samples",
    )
    op.drop_table("terminal_battery_samples")

