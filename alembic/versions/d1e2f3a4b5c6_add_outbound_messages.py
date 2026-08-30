"""Add durable, at-most-once outbound messages.

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-08-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "c0d1e2f3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "outbound_messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("send_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("source_email_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text(), none_as_null=True),
            nullable=True,
        ),
        sa.Column(
            "retry_authorized",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("retry_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rfc_message_id", sa.String(length=255), nullable=False),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("execute_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("undo_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("reconcile_count", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('staged','processing','retry_wait','reconciling','sent','failed','cancelled')",
            name="ck_outbound_messages_state",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_outbound_messages_attempt_count"),
        sa.CheckConstraint("max_attempts > 0", name="ck_outbound_messages_max_attempts"),
        sa.CheckConstraint("reconcile_count >= 0", name="ck_outbound_messages_reconcile_count"),
        sa.CheckConstraint(
            "(state = 'processing' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) "
            "OR (state <> 'processing' AND lease_token IS NULL AND lease_expires_at IS NULL)",
            name="ck_outbound_messages_lease_state",
        ),
        sa.CheckConstraint(
            "execute_after >= created_at AND undo_until >= created_at",
            name="ck_outbound_messages_action_times",
        ),
        sa.CheckConstraint(
            "NOT retry_authorized OR "
            "(state = 'failed' AND provider_attempted_at IS NULL AND payload IS NOT NULL "
            "AND failed_at IS NOT NULL AND retry_expires_at IS NOT NULL "
            "AND retry_expires_at > failed_at)",
            name="ck_outbound_messages_retry_authorized",
        ),
        sa.CheckConstraint(
            "retry_authorized OR retry_expires_at IS NULL",
            name="ck_outbound_messages_retry_expiry",
        ),
        sa.CheckConstraint(
            "state <> 'failed' OR retry_authorized OR payload IS NULL",
            name="ck_outbound_messages_failed_payload",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["google_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_email_id"], ["emails.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("send_id", name="uq_outbound_messages_send_id"),
        sa.UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_outbound_messages_user_idempotency",
        ),
    )
    op.create_index(
        "ix_outbound_messages_user_created",
        "outbound_messages",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_outbound_messages_account_created",
        "outbound_messages",
        ["account_id", "created_at"],
    )
    op.create_index(
        "ix_outbound_messages_user_capacity",
        "outbound_messages",
        ["user_id"],
        postgresql_where=sa.text(
            "state IN ('staged','processing','retry_wait','reconciling') OR retry_authorized"
        ),
    )
    op.create_index(
        "ix_outbound_messages_account_capacity",
        "outbound_messages",
        ["account_id"],
        postgresql_where=sa.text(
            "state IN ('staged','processing','retry_wait','reconciling') OR retry_authorized"
        ),
    )
    op.create_index(
        "ix_outbound_messages_retry_expiry",
        "outbound_messages",
        ["retry_expires_at"],
        postgresql_where=sa.text("retry_authorized"),
    )
    op.create_index(
        "ix_outbound_messages_account_state_due",
        "outbound_messages",
        ["account_id", "state", "next_attempt_at"],
    )
    op.create_index(
        "ix_outbound_messages_due_staged",
        "outbound_messages",
        ["execute_after", "id"],
        postgresql_where=sa.text("state = 'staged'"),
    )
    op.create_index(
        "ix_outbound_messages_due_retry",
        "outbound_messages",
        ["next_attempt_at", "id"],
        postgresql_where=sa.text("state IN ('retry_wait','reconciling')"),
    )
    op.create_index(
        "ix_outbound_messages_expired_lease",
        "outbound_messages",
        ["lease_expires_at"],
        postgresql_where=sa.text("state = 'processing'"),
    )


def downgrade() -> None:
    op.drop_index("ix_outbound_messages_expired_lease", table_name="outbound_messages")
    op.drop_index("ix_outbound_messages_due_retry", table_name="outbound_messages")
    op.drop_index("ix_outbound_messages_due_staged", table_name="outbound_messages")
    op.drop_index("ix_outbound_messages_account_state_due", table_name="outbound_messages")
    op.drop_index("ix_outbound_messages_retry_expiry", table_name="outbound_messages")
    op.drop_index("ix_outbound_messages_account_capacity", table_name="outbound_messages")
    op.drop_index("ix_outbound_messages_user_capacity", table_name="outbound_messages")
    op.drop_index("ix_outbound_messages_account_created", table_name="outbound_messages")
    op.drop_index("ix_outbound_messages_user_created", table_name="outbound_messages")
    op.drop_table("outbound_messages")
