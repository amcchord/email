"""Add automatic follow-up policy and durable intent persistence.

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-08-31

The upgrade is additive and requires no backfill beyond safe server defaults on
existing outbound messages and snoozes. The downgrade intentionally drops all
automatic follow-up policy, intent, and snooze-origin history and is data-lossy.
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op


revision: str = "e8f9a0b1c2d3"
down_revision: Union[str, None] = "d7e8f9a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "outbound_messages",
        sa.Column(
            "follow_up_requested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.create_table(
        "account_follow_up_policies",
        sa.Column("account_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "delay_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("3"),
        ),
        sa.Column(
            "wake_local_time",
            sa.String(length=5),
            nullable=False,
            server_default=sa.text("'09:00'"),
        ),
        sa.Column(
            "time_zone",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("'UTC'"),
        ),
        sa.Column(
            "weekdays_only",
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
            "delay_days BETWEEN 1 AND 30",
            name="ck_account_follow_up_policies_delay_days",
        ),
        sa.CheckConstraint(
            "wake_local_time ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'",
            name="ck_account_follow_up_policies_wake_local_time",
        ),
        sa.CheckConstraint(
            "char_length(time_zone) BETWEEN 1 AND 64",
            name="ck_account_follow_up_policies_time_zone",
        ),
        sa.CheckConstraint(
            "revision > 0",
            name="ck_account_follow_up_policies_revision",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["google_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("account_id"),
    )
    op.create_index(
        "ix_account_follow_up_policies_user_account",
        "account_follow_up_policies",
        ["user_id", "account_id"],
    )

    op.create_table(
        "outbound_follow_up_intents",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("outbound_message_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("snooze_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "state",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'awaiting_delivery'"),
        ),
        sa.Column("requested_via", sa.String(length=16), nullable=False),
        sa.Column("delay_days", sa.Integer(), nullable=False),
        sa.Column("wake_local_time", sa.String(length=5), nullable=False),
        sa.Column("time_zone", sa.String(length=64), nullable=False),
        sa.Column("weekdays_only", sa.Boolean(), nullable=False),
        sa.Column(
            "post_send_archive",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("wake_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("rfc_message_id", sa.String(length=255), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("status_detail", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('awaiting_delivery','pending_sync','scheduled','superseded',"
            "'skipped','cancelled','failed')",
            name="ck_outbound_follow_up_intents_state",
        ),
        sa.CheckConstraint(
            "requested_via IN ('policy','explicit')",
            name="ck_outbound_follow_up_intents_requested_via",
        ),
        sa.CheckConstraint(
            "delay_days BETWEEN 1 AND 30",
            name="ck_outbound_follow_up_intents_delay_days",
        ),
        sa.CheckConstraint(
            "wake_local_time ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'",
            name="ck_outbound_follow_up_intents_wake_local_time",
        ),
        sa.CheckConstraint(
            "char_length(time_zone) BETWEEN 1 AND 64",
            name="ck_outbound_follow_up_intents_time_zone",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_outbound_follow_up_intents_attempt_count",
        ),
        sa.CheckConstraint(
            "(lease_token IS NULL AND lease_expires_at IS NULL) OR "
            "(lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_outbound_follow_up_intents_lease_shape",
        ),
        sa.CheckConstraint(
            "wake_at IS NULL OR delivered_at IS NOT NULL",
            name="ck_outbound_follow_up_intents_wake_delivery",
        ),
        sa.CheckConstraint(
            "state <> 'scheduled' OR (snooze_id IS NOT NULL AND scheduled_at IS NOT NULL)",
            name="ck_outbound_follow_up_intents_scheduled_shape",
        ),
        sa.CheckConstraint(
            "state <> 'cancelled' OR cancelled_at IS NOT NULL",
            name="ck_outbound_follow_up_intents_cancelled_at",
        ),
        sa.CheckConstraint(
            "state <> 'failed' OR failed_at IS NOT NULL",
            name="ck_outbound_follow_up_intents_failed_at",
        ),
        sa.ForeignKeyConstraint(
            ["outbound_message_id"],
            ["outbound_messages.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["google_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["snooze_id"],
            ["email_snoozes.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "public_id",
            name="uq_outbound_follow_up_intents_public_id",
        ),
        sa.UniqueConstraint(
            "outbound_message_id",
            name="uq_outbound_follow_up_intents_outbound_message",
        ),
    )
    op.create_index(
        "ix_outbound_follow_up_intents_user_created",
        "outbound_follow_up_intents",
        ["user_id", "created_at", "id"],
    )
    op.create_index(
        "ix_outbound_follow_up_intents_account_state_wake",
        "outbound_follow_up_intents",
        ["account_id", "state", "wake_at", "id"],
    )
    op.create_index(
        "ix_outbound_follow_up_intents_due",
        "outbound_follow_up_intents",
        ["state", "next_attempt_at", "id"],
    )
    op.create_index(
        "ix_outbound_follow_up_intents_expired_lease",
        "outbound_follow_up_intents",
        ["lease_expires_at"],
        postgresql_where=sa.text("lease_token IS NOT NULL"),
    )

    op.add_column(
        "email_snoozes",
        sa.Column(
            "origin",
            sa.String(length=24),
            nullable=False,
            server_default=sa.text("'manual'"),
        ),
    )
    op.add_column(
        "email_snoozes",
        sa.Column("origin_outbound_id", sa.BigInteger(), nullable=True),
    )
    op.create_check_constraint(
        "ck_email_snoozes_origin",
        "email_snoozes",
        "origin IN ('manual','automatic_follow_up')",
    )
    op.create_foreign_key(
        "fk_email_snoozes_origin_outbound_id",
        "email_snoozes",
        "outbound_messages",
        ["origin_outbound_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "uq_email_snoozes_origin_outbound",
        "email_snoozes",
        ["origin_outbound_id"],
        unique=True,
        postgresql_where=sa.text("origin_outbound_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_email_snoozes_origin_outbound",
        table_name="email_snoozes",
    )
    op.drop_constraint(
        "fk_email_snoozes_origin_outbound_id",
        "email_snoozes",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_email_snoozes_origin",
        "email_snoozes",
        type_="check",
    )
    op.drop_column("email_snoozes", "origin_outbound_id")
    op.drop_column("email_snoozes", "origin")

    op.drop_index(
        "ix_outbound_follow_up_intents_expired_lease",
        table_name="outbound_follow_up_intents",
    )
    op.drop_index(
        "ix_outbound_follow_up_intents_due",
        table_name="outbound_follow_up_intents",
    )
    op.drop_index(
        "ix_outbound_follow_up_intents_account_state_wake",
        table_name="outbound_follow_up_intents",
    )
    op.drop_index(
        "ix_outbound_follow_up_intents_user_created",
        table_name="outbound_follow_up_intents",
    )
    op.drop_table("outbound_follow_up_intents")

    op.drop_index(
        "ix_account_follow_up_policies_user_account",
        table_name="account_follow_up_policies",
    )
    op.drop_table("account_follow_up_policies")
    op.drop_column("outbound_messages", "follow_up_requested")
