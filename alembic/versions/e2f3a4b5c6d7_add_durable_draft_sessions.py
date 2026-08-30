"""Add durable Gmail draft sessions.

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-08-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "draft_sessions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("client_draft_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("source_email_id", sa.BigInteger(), nullable=True),
        sa.Column("source_email_id_snapshot", sa.BigInteger(), nullable=True),
        sa.Column("source_gmail_thread_id", sa.String(length=255), nullable=True),
        sa.Column("source_message_id_header", sa.Text(), nullable=True),
        sa.Column("source_references_header", sa.Text(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("synced_revision", sa.Integer(), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text(), none_as_null=True), nullable=True),
        sa.Column("attachment_count", sa.Integer(), nullable=False),
        sa.Column("attachment_bytes", sa.BigInteger(), nullable=False),
        sa.Column("rfc_message_id", sa.String(length=255), nullable=False),
        sa.Column("provider_draft_id", sa.String(length=255), nullable=True),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("provider_create_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("reconcile_count", sa.Integer(), nullable=False),
        sa.Column("lease_operation", sa.String(length=16), nullable=True),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discard_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discard_undo_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("linked_send_id", sa.Uuid(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discarded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('pending','syncing','reconciling','synced','failed',"
            "'discard_pending','discarded','sending')",
            name="ck_draft_sessions_state",
        ),
        sa.CheckConstraint("revision > 0", name="ck_draft_sessions_revision"),
        sa.CheckConstraint("attachment_count >= 0 AND attachment_bytes >= 0", name="ck_draft_sessions_attachment_totals"),
        sa.CheckConstraint(
            "synced_revision IS NULL OR (synced_revision > 0 AND synced_revision <= revision)",
            name="ck_draft_sessions_synced_revision",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_draft_sessions_attempt_count"),
        sa.CheckConstraint("max_attempts > 0", name="ck_draft_sessions_max_attempts"),
        sa.CheckConstraint("reconcile_count >= 0", name="ck_draft_sessions_reconcile_count"),
        sa.CheckConstraint(
            "(state = 'syncing' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL "
            "AND lease_operation IS NOT NULL) OR "
            "(state <> 'syncing' AND lease_token IS NULL AND lease_expires_at IS NULL "
            "AND lease_operation IS NULL)",
            name="ck_draft_sessions_lease_state",
        ),
        sa.CheckConstraint(
            "state NOT IN ('discard_pending','sending') OR "
            "(discard_at IS NOT NULL AND discard_undo_until IS NOT NULL)",
            name="ck_draft_sessions_discard_deadline",
        ),
        sa.CheckConstraint(
            "state <> 'discarded' OR (payload IS NULL AND discarded_at IS NOT NULL)",
            name="ck_draft_sessions_discard_scrubbed",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["google_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_email_id"], ["emails.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "client_draft_id", name="uq_draft_sessions_user_client_id"),
        sa.UniqueConstraint("account_id", "rfc_message_id", name="uq_draft_sessions_account_rfc_message_id"),
    )
    op.create_index("uq_draft_sessions_account_provider_draft", "draft_sessions", ["account_id", "provider_draft_id"], unique=True, postgresql_where=sa.text("provider_draft_id IS NOT NULL"))
    op.create_index("ix_draft_sessions_user_recent", "draft_sessions", ["user_id", "updated_at", "id"])
    op.create_index("ix_draft_sessions_account_due", "draft_sessions", ["account_id", "state", "next_attempt_at"])
    op.create_index("ix_draft_sessions_provider_message", "draft_sessions", ["account_id", "provider_message_id"], postgresql_where=sa.text("provider_message_id IS NOT NULL"))
    op.create_index("ix_draft_sessions_expired_lease", "draft_sessions", ["lease_expires_at"], postgresql_where=sa.text("state = 'syncing'"))
    op.create_index("ix_draft_sessions_discard_due", "draft_sessions", ["discard_at"], postgresql_where=sa.text("state IN ('discard_pending','sending')"))

    op.create_table(
        "draft_attachments",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("draft_session_id", sa.BigInteger(), nullable=False),
        sa.Column("attachment_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("size_bytes >= 0", name="ck_draft_attachments_size"),
        sa.CheckConstraint("sort_order >= 0", name="ck_draft_attachments_sort_order"),
        sa.ForeignKeyConstraint(["draft_session_id"], ["draft_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("draft_session_id", "attachment_id", name="uq_draft_attachments_session_attachment"),
        sa.UniqueConstraint("draft_session_id", "sort_order", name="uq_draft_attachments_session_order"),
    )
    op.create_index("ix_draft_attachments_session", "draft_attachments", ["draft_session_id"])

    op.create_table(
        "draft_mutations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("draft_session_id", sa.BigInteger(), nullable=False),
        sa.Column("mutation_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("revision > 0", name="ck_draft_mutations_revision"),
        sa.CheckConstraint("operation IN ('upsert','discard','undo_discard')", name="ck_draft_mutations_operation"),
        sa.ForeignKeyConstraint(["draft_session_id"], ["draft_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("draft_session_id", "mutation_id", name="uq_draft_mutations_session_mutation"),
    )
    op.create_index("ix_draft_mutations_created", "draft_mutations", ["draft_session_id", "created_at"])

    op.add_column("outbound_messages", sa.Column("draft_session_id", sa.BigInteger(), nullable=True))
    op.add_column("outbound_messages", sa.Column("client_draft_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_outbound_messages_draft_session_id",
        "outbound_messages",
        "draft_sessions",
        ["draft_session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_outbound_messages_draft_session",
        "outbound_messages",
        ["draft_session_id"],
        unique=True,
        postgresql_where=sa.text("draft_session_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_outbound_messages_draft_session", table_name="outbound_messages")
    op.drop_constraint("fk_outbound_messages_draft_session_id", "outbound_messages", type_="foreignkey")
    op.drop_column("outbound_messages", "client_draft_id")
    op.drop_column("outbound_messages", "draft_session_id")
    op.drop_index("ix_draft_mutations_created", table_name="draft_mutations")
    op.drop_table("draft_mutations")
    op.drop_index("ix_draft_attachments_session", table_name="draft_attachments")
    op.drop_table("draft_attachments")
    op.drop_index("ix_draft_sessions_discard_due", table_name="draft_sessions")
    op.drop_index("ix_draft_sessions_expired_lease", table_name="draft_sessions")
    op.drop_index("ix_draft_sessions_provider_message", table_name="draft_sessions")
    op.drop_index("ix_draft_sessions_account_due", table_name="draft_sessions")
    op.drop_index("ix_draft_sessions_user_recent", table_name="draft_sessions")
    op.drop_index("uq_draft_sessions_account_provider_draft", table_name="draft_sessions")
    op.drop_table("draft_sessions")
