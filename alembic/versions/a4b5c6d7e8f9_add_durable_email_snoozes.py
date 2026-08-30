"""Add durable universal email snoozes and inbox-return mail actions.

Revision ID: a4b5c6d7e8f9
Revises: f3a4b5c6d7e8
Create Date: 2026-08-30

The upgrade is additive except for widening the existing mail-action check
constraint to admit the inverse of archive. Downgrade removes snooze lifecycle
history and restores the earlier action constraint; it does not mutate Gmail.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a4b5c6d7e8f9"
down_revision: Union[str, None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_mail_actions_action", "mail_actions", type_="check")
    op.create_check_constraint(
        "ck_mail_actions_action",
        "mail_actions",
        "action IN ('mark_read','mark_unread','star','unstar','archive','unarchive',"
        "'trash','untrash','spam','unspam')",
    )

    op.create_table(
        "email_snoozes",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("email_id", sa.BigInteger(), nullable=True),
        sa.Column("gmail_message_id", sa.String(length=255), nullable=False),
        sa.Column("gmail_thread_id", sa.String(length=255), nullable=False),
        sa.Column("wake_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("time_zone", sa.String(length=64), nullable=False),
        sa.Column("condition", sa.String(length=24), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("status_detail", sa.String(length=64), nullable=True),
        sa.Column("archive_required", sa.Boolean(), nullable=False),
        sa.Column("anchor_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "mail_action_version_at_schedule",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("archive_idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("archive_action_id", sa.BigInteger(), nullable=True),
        sa.Column("return_idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("return_action_id", sa.BigInteger(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
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
        sa.Column("returned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('pending_archive','scheduled','pending_return','returned',"
            "'cancelled','dismissed','failed')",
            name="ck_email_snoozes_state",
        ),
        sa.CheckConstraint(
            "condition IN ('always','if_no_reply')",
            name="ck_email_snoozes_condition",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_email_snoozes_attempt_count"
        ),
        sa.CheckConstraint(
            "(lease_token IS NULL AND lease_expires_at IS NULL) OR "
            "(lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_email_snoozes_lease_shape",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["account_id"], ["google_accounts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["email_id"], ["emails.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["archive_action_id"], ["mail_actions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["return_action_id"], ["mail_actions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_email_snoozes_public_id"),
        sa.UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_email_snoozes_user_idempotency",
        ),
    )
    op.create_index(
        "ix_email_snoozes_user_wake",
        "email_snoozes",
        ["user_id", "wake_at", "id"],
    )
    op.create_index(
        "ix_email_snoozes_due",
        "email_snoozes",
        ["state", "next_attempt_at", "wake_at", "id"],
    )
    op.create_index(
        "uq_email_snoozes_active_email",
        "email_snoozes",
        ["user_id", "email_id"],
        unique=True,
        postgresql_where=sa.text(
            "email_id IS NOT NULL AND state IN "
            "('pending_archive','scheduled','pending_return')"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_email_snoozes_active_email", table_name="email_snoozes")
    op.drop_index("ix_email_snoozes_due", table_name="email_snoozes")
    op.drop_index("ix_email_snoozes_user_wake", table_name="email_snoozes")
    op.drop_table("email_snoozes")

    op.drop_constraint("ck_mail_actions_action", "mail_actions", type_="check")
    op.create_check_constraint(
        "ck_mail_actions_action",
        "mail_actions",
        "action IN ('mark_read','mark_unread','star','unstar','archive',"
        "'trash','untrash','spam','unspam')",
    )
