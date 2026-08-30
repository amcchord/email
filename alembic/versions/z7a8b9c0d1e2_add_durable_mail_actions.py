"""Add durable, ordered mail action outbox.

Revision ID: z7a8b9c0d1e2
Revises: y6z7a8b9c0d1
Create Date: 2026-08-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "z7a8b9c0d1e2"
down_revision: Union[str, None] = "y6z7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "emails",
        sa.Column(
            "mail_action_version",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    op.create_table(
        "mail_actions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("email_id", sa.BigInteger(), nullable=True),
        sa.Column("gmail_message_id", sa.String(length=255), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("chain_start_sequence", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("base_state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("before_state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("after_state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("add_labels", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("remove_labels", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("execute_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("undo_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("gmail_history_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "action IN ('mark_read','mark_unread','star','unstar','archive','trash','untrash','spam','unspam')",
            name="ck_mail_actions_action",
        ),
        sa.CheckConstraint(
            "state IN ('staged','processing','retry_wait','applied','failed','cancelled')",
            name="ck_mail_actions_state",
        ),
        sa.CheckConstraint("sequence > 0", name="ck_mail_actions_sequence_positive"),
        sa.CheckConstraint(
            "chain_start_sequence > 0 AND chain_start_sequence <= sequence",
            name="ck_mail_actions_chain_sequence",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_mail_actions_attempt_count"),
        sa.CheckConstraint("max_attempts > 0", name="ck_mail_actions_max_attempts"),
        sa.CheckConstraint(
            "jsonb_typeof(base_state) = 'object' AND jsonb_typeof(before_state) = 'object' "
            "AND jsonb_typeof(after_state) = 'object'",
            name="ck_mail_actions_state_json_objects",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(add_labels) = 'array' AND jsonb_typeof(remove_labels) = 'array'",
            name="ck_mail_actions_label_json_arrays",
        ),
        sa.CheckConstraint(
            "(state = 'processing' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) "
            "OR (state <> 'processing' AND lease_token IS NULL AND lease_expires_at IS NULL)",
            name="ck_mail_actions_lease_state",
        ),
        sa.CheckConstraint(
            "execute_after >= created_at AND undo_until >= created_at",
            name="ck_mail_actions_action_times",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["google_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["email_id"], ["emails.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email_id", "sequence", name="uq_mail_actions_email_sequence"),
        sa.UniqueConstraint(
            "user_id",
            "idempotency_key",
            "email_id",
            name="uq_mail_actions_user_idempotency_email",
        ),
    )
    op.create_index("ix_mail_actions_request_user", "mail_actions", ["request_id", "user_id"])
    op.create_index("ix_mail_actions_user_created", "mail_actions", ["user_id", "created_at"])
    op.create_index(
        "ix_mail_actions_account_state_due",
        "mail_actions",
        ["account_id", "state", "next_attempt_at"],
    )
    op.create_index(
        "ix_mail_actions_gmail_active",
        "mail_actions",
        ["account_id", "gmail_message_id", "sequence"],
        postgresql_where=sa.text("state IN ('staged','processing','retry_wait')"),
    )
    op.create_index(
        "ix_mail_actions_due",
        "mail_actions",
        ["execute_after", "id"],
        postgresql_where=sa.text("state IN ('staged','retry_wait')"),
    )
    op.create_index(
        "ix_mail_actions_expired_lease",
        "mail_actions",
        ["lease_expires_at"],
        postgresql_where=sa.text("state = 'processing'"),
    )


def downgrade() -> None:
    op.drop_index("ix_mail_actions_expired_lease", table_name="mail_actions")
    op.drop_index("ix_mail_actions_due", table_name="mail_actions")
    op.drop_index("ix_mail_actions_gmail_active", table_name="mail_actions")
    op.drop_index("ix_mail_actions_account_state_due", table_name="mail_actions")
    op.drop_index("ix_mail_actions_user_created", table_name="mail_actions")
    op.drop_index("ix_mail_actions_request_user", table_name="mail_actions")
    op.drop_table("mail_actions")
    op.drop_column("emails", "mail_action_version")
