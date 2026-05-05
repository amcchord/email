"""Add terminal_settings and terminal_devices for the e-ink display protocol.

Revision ID: u2v3w4x5y6z7
Revises: t1u2v3w4x5y6
Create Date: 2026-05-04
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "u2v3w4x5y6z7"
down_revision: Union[str, None] = "t1u2v3w4x5y6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from sqlalchemy import inspect as sa_inspect
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    existing_tables = inspector.get_table_names()

    if "terminal_settings" not in existing_tables:
        op.create_table(
            "terminal_settings",
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("code", sa.String(length=16), nullable=False),
            sa.Column("home_assistant_url", sa.Text(), nullable=True),
            sa.Column("home_assistant_token_encrypted", sa.Text(), nullable=True),
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
        )

    settings_indexes = (
        {ix["name"] for ix in inspector.get_indexes("terminal_settings")}
        if "terminal_settings" in inspector.get_table_names()
        else set()
    )
    if "ix_terminal_settings_code" not in settings_indexes:
        op.create_index(
            "ix_terminal_settings_code", "terminal_settings", ["code"], unique=True
        )

    if "terminal_devices" not in existing_tables:
        op.create_table(
            "terminal_devices",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("mac", sa.String(length=17), nullable=False),
            sa.Column("name", sa.Text(), nullable=False, server_default=""),
            sa.Column("variant", sa.String(length=32), nullable=True),
            sa.Column(
                "content_type",
                sa.String(length=32),
                nullable=False,
                server_default="clock",
            ),
            sa.Column("content_config", JSONB, nullable=True),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_wake_reason", sa.String(length=32), nullable=True),
            sa.Column("last_battery_mv", sa.Integer(), nullable=True),
            sa.Column("last_battery_pct", sa.Integer(), nullable=True),
            sa.Column("last_rssi_dbm", sa.Integer(), nullable=True),
            sa.Column("last_uptime_sec", sa.Integer(), nullable=True),
            sa.Column("last_boot_count", sa.Integer(), nullable=True),
            sa.Column("last_fw_version", sa.String(length=64), nullable=True),
            sa.Column("last_image_etag", sa.String(length=128), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.UniqueConstraint("user_id", "mac", name="uq_terminal_devices_user_mac"),
        )

    devices_indexes = (
        {ix["name"] for ix in inspector.get_indexes("terminal_devices")}
        if "terminal_devices" in inspector.get_table_names()
        else set()
    )
    if "ix_terminal_devices_user_id" not in devices_indexes:
        op.create_index(
            "ix_terminal_devices_user_id", "terminal_devices", ["user_id"]
        )
    if "ix_terminal_devices_user_last_seen" not in devices_indexes:
        op.create_index(
            "ix_terminal_devices_user_last_seen",
            "terminal_devices",
            ["user_id", "last_seen_at"],
        )


def downgrade() -> None:
    op.drop_index("ix_terminal_devices_user_last_seen", table_name="terminal_devices")
    op.drop_index("ix_terminal_devices_user_id", table_name="terminal_devices")
    op.drop_table("terminal_devices")
    op.drop_index("ix_terminal_settings_code", table_name="terminal_settings")
    op.drop_table("terminal_settings")
