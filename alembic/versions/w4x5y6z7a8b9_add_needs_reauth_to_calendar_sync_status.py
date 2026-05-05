"""Add needs_reauth to calendar_sync_status.

Revision ID: w4x5y6z7a8b9
Revises: v3w4x5y6z7a8
Create Date: 2026-05-04
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "w4x5y6z7a8b9"
down_revision: Union[str, None] = "v3w4x5y6z7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from sqlalchemy import inspect as sa_inspect
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    existing = {c["name"] for c in inspector.get_columns("calendar_sync_status")}
    if "needs_reauth" not in existing:
        op.add_column(
            "calendar_sync_status",
            sa.Column(
                "needs_reauth",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    op.drop_column("calendar_sync_status", "needs_reauth")
