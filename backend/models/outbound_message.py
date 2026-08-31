"""Durable, at-most-once outbound email operations."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


OUTBOUND_MESSAGE_STATES = (
    "staged",
    "processing",
    "retry_wait",
    "reconciling",
    "sent",
    "failed",
    "cancelled",
)


class OutboundMessage(Base):
    """One accepted send intent and its durable provider outcome."""

    __tablename__ = "outbound_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    send_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    idempotency_key: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("google_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_email_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("emails.id", ondelete="SET NULL"),
        nullable=True,
    )
    draft_session_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("draft_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    client_draft_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    follow_up_requested: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )

    # Payload is intentionally nullable: delivery and cancellation scrub all
    # recipients, bodies, and attachment bytes while retaining safe metadata.
    # A failed operation may retain it only when the server explicitly permits
    # a safe pre-provider retry.
    payload = mapped_column(JSONB(none_as_null=True), nullable=True)
    retry_authorized: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    retry_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    rfc_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    state: Mapped[str] = mapped_column(String(32), nullable=False, default="staged")
    execute_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    undo_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    reconcile_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    lease_token: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "state IN ('staged','processing','retry_wait','reconciling','sent','failed','cancelled')",
            name="ck_outbound_messages_state",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_outbound_messages_attempt_count"),
        CheckConstraint("max_attempts > 0", name="ck_outbound_messages_max_attempts"),
        CheckConstraint("reconcile_count >= 0", name="ck_outbound_messages_reconcile_count"),
        CheckConstraint(
            "(state = 'processing' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) "
            "OR (state <> 'processing' AND lease_token IS NULL AND lease_expires_at IS NULL)",
            name="ck_outbound_messages_lease_state",
        ),
        CheckConstraint(
            "execute_after >= created_at AND undo_until >= created_at",
            name="ck_outbound_messages_action_times",
        ),
        CheckConstraint(
            "NOT retry_authorized OR "
            "(state = 'failed' AND provider_attempted_at IS NULL AND payload IS NOT NULL "
            "AND failed_at IS NOT NULL AND retry_expires_at IS NOT NULL "
            "AND retry_expires_at > failed_at)",
            name="ck_outbound_messages_retry_authorized",
        ),
        CheckConstraint(
            "retry_authorized OR retry_expires_at IS NULL",
            name="ck_outbound_messages_retry_expiry",
        ),
        CheckConstraint(
            "state <> 'failed' OR retry_authorized OR payload IS NULL",
            name="ck_outbound_messages_failed_payload",
        ),
        UniqueConstraint("send_id", name="uq_outbound_messages_send_id"),
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_outbound_messages_user_idempotency",
        ),
        Index("ix_outbound_messages_user_created", "user_id", "created_at"),
        Index("ix_outbound_messages_account_created", "account_id", "created_at"),
        Index(
            "ix_outbound_messages_draft_session",
            "draft_session_id",
            unique=True,
            postgresql_where=text("draft_session_id IS NOT NULL"),
        ),
        Index(
            "ix_outbound_messages_user_capacity",
            "user_id",
            postgresql_where=text(
                "state IN ('staged','processing','retry_wait','reconciling') "
                "OR retry_authorized"
            ),
        ),
        Index(
            "ix_outbound_messages_account_capacity",
            "account_id",
            postgresql_where=text(
                "state IN ('staged','processing','retry_wait','reconciling') "
                "OR retry_authorized"
            ),
        ),
        Index(
            "ix_outbound_messages_retry_expiry",
            "retry_expires_at",
            postgresql_where=text("retry_authorized"),
        ),
        Index("ix_outbound_messages_account_state_due", "account_id", "state", "next_attempt_at"),
        Index(
            "ix_outbound_messages_due_staged",
            "execute_after",
            "id",
            postgresql_where=text("state = 'staged'"),
        ),
        Index(
            "ix_outbound_messages_due_retry",
            "next_attempt_at",
            "id",
            postgresql_where=text("state IN ('retry_wait','reconciling')"),
        ),
        Index(
            "ix_outbound_messages_expired_lease",
            "lease_expires_at",
            postgresql_where=text("state = 'processing'"),
        ),
    )
