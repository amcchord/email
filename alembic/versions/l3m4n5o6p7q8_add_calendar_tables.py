"""Add calendar_events and calendar_sync_status tables.

Revision ID: l3m4n5o6p7q8
Revises: k2l3m4n5o6p7
Create Date: 2026-02-13
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "l3m4n5o6p7q8"
down_revision: Union[str, None] = "k2l3m4n5o6p7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "calendar_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("google_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("google_event_id", sa.String(1024), nullable=False),
        sa.Column("calendar_id", sa.String(255), server_default="primary", nullable=False),
        # Core
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        # Times
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("start_date", sa.String(20), nullable=True),
        sa.Column("end_date", sa.String(20), nullable=True),
        sa.Column("timezone", sa.String(100), nullable=True),
        sa.Column("is_all_day", sa.Boolean(), server_default="false", nullable=False),
        # Recurrence
        sa.Column("recurring_event_id", sa.String(1024), nullable=True),
        sa.Column("recurrence_rule", JSONB(), nullable=True),
        # Status
        sa.Column("status", sa.String(50), server_default="confirmed", nullable=False),
        sa.Column("html_link", sa.Text(), nullable=True),
        sa.Column("hangout_link", sa.Text(), nullable=True),
        # Organizer
        sa.Column("organizer_email", sa.String(320), nullable=True),
        sa.Column("organizer_name", sa.String(255), nullable=True),
        sa.Column("organizer_self", sa.Boolean(), server_default="false", nullable=False),
        # Attendees
        sa.Column("attendees", JSONB(), nullable=True),
        # Meta
        sa.Column("visibility", sa.String(50), nullable=True),
        sa.Column("transparency", sa.String(50), nullable=True),
        sa.Column("reminders", JSONB(), nullable=True),
        sa.Column("etag", sa.String(255), nullable=True),
        sa.Column("updated_at_google", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        # Constraints
        sa.UniqueConstraint("account_id", "google_event_id", name="uq_calendar_event_account_google"),
    )
    op.create_index("ix_calendar_events_start_time", "calendar_events", ["start_time"])
    op.create_index("ix_calendar_events_account_start", "calendar_events", ["account_id", "start_time"])

    op.create_table(
        "calendar_sync_status",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("google_accounts.id", ondelete="CASCADE"), unique=True, nullable=False),
        sa.Column("sync_token", sa.Text(), nullable=True),
        sa.Column("last_full_sync", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_incremental_sync", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(50), server_default="idle", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("events_synced", sa.Integer(), server_default="0", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("calendar_sync_status")
    op.drop_index("ix_calendar_events_account_start", table_name="calendar_events")
    op.drop_index("ix_calendar_events_start_time", table_name="calendar_events")
    op.drop_table("calendar_events")
