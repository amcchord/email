"""Durable, user-owned Gmail draft sessions and attachment content."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


DRAFT_SESSION_STATES = (
    "pending",
    "syncing",
    "reconciling",
    "synced",
    "failed",
    "discard_pending",
    "discarded",
    "sending",
)


class DraftSession(Base):
    """One local writing intent mapped to at most one Gmail Draft resource."""

    __tablename__ = "draft_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    client_draft_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
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
    source_email_id_snapshot: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source_gmail_thread_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_message_id_header: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_references_header: Mapped[str | None] = mapped_column(Text, nullable=True)

    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    synced_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload = mapped_column(JSONB(none_as_null=True), nullable=True)
    attachment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attachment_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    # This RFC identity is stable across Gmail's replacement message IDs and
    # is also adopted by a linked outbound send.
    rfc_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_draft_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_create_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    state: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    reconcile_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_operation: Mapped[str | None] = mapped_column(String(16), nullable=True)
    lease_token: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    discard_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    discard_undo_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    linked_send_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
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
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    discarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    attachments = relationship(
        "DraftAttachment",
        back_populates="draft_session",
        cascade="all, delete-orphan",
        order_by="DraftAttachment.sort_order",
    )
    mutations = relationship(
        "DraftMutation",
        back_populates="draft_session",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "state IN ('pending','syncing','reconciling','synced','failed',"
            "'discard_pending','discarded','sending')",
            name="ck_draft_sessions_state",
        ),
        CheckConstraint("revision > 0", name="ck_draft_sessions_revision"),
        CheckConstraint(
            "attachment_count >= 0 AND attachment_bytes >= 0",
            name="ck_draft_sessions_attachment_totals",
        ),
        CheckConstraint(
            "synced_revision IS NULL OR (synced_revision > 0 AND synced_revision <= revision)",
            name="ck_draft_sessions_synced_revision",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_draft_sessions_attempt_count"),
        CheckConstraint("max_attempts > 0", name="ck_draft_sessions_max_attempts"),
        CheckConstraint("reconcile_count >= 0", name="ck_draft_sessions_reconcile_count"),
        CheckConstraint(
            "(state = 'syncing' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL "
            "AND lease_operation IS NOT NULL) OR "
            "(state <> 'syncing' AND lease_token IS NULL AND lease_expires_at IS NULL "
            "AND lease_operation IS NULL)",
            name="ck_draft_sessions_lease_state",
        ),
        CheckConstraint(
            "state NOT IN ('discard_pending','sending') OR "
            "(discard_at IS NOT NULL AND discard_undo_until IS NOT NULL)",
            name="ck_draft_sessions_discard_deadline",
        ),
        CheckConstraint(
            "state <> 'discarded' OR (payload IS NULL AND discarded_at IS NOT NULL)",
            name="ck_draft_sessions_discard_scrubbed",
        ),
        UniqueConstraint(
            "user_id",
            "client_draft_id",
            name="uq_draft_sessions_user_client_id",
        ),
        UniqueConstraint(
            "account_id",
            "rfc_message_id",
            name="uq_draft_sessions_account_rfc_message_id",
        ),
        Index(
            "uq_draft_sessions_account_provider_draft",
            "account_id",
            "provider_draft_id",
            unique=True,
            postgresql_where=text("provider_draft_id IS NOT NULL"),
        ),
        Index(
            "ix_draft_sessions_user_recent",
            "user_id",
            "updated_at",
            "id",
        ),
        Index(
            "ix_draft_sessions_account_due",
            "account_id",
            "state",
            "next_attempt_at",
        ),
        Index(
            "ix_draft_sessions_provider_message",
            "account_id",
            "provider_message_id",
            postgresql_where=text("provider_message_id IS NOT NULL"),
        ),
        Index(
            "ix_draft_sessions_expired_lease",
            "lease_expires_at",
            postgresql_where=text("state = 'syncing'"),
        ),
        Index(
            "ix_draft_sessions_discard_due",
            "discard_at",
            postgresql_where=text("state IN ('discard_pending','sending')"),
        ),
    )


class DraftAttachment(Base):
    """Byte-complete attachment content required to replace a Gmail draft."""

    __tablename__ = "draft_attachments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    draft_session_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("draft_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    attachment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    draft_session = relationship("DraftSession", back_populates="attachments")

    __table_args__ = (
        CheckConstraint("size_bytes >= 0", name="ck_draft_attachments_size"),
        CheckConstraint("sort_order >= 0", name="ck_draft_attachments_sort_order"),
        UniqueConstraint(
            "draft_session_id",
            "attachment_id",
            name="uq_draft_attachments_session_attachment",
        ),
        UniqueConstraint(
            "draft_session_id",
            "sort_order",
            name="uq_draft_attachments_session_order",
        ),
        Index("ix_draft_attachments_session", "draft_session_id"),
    )


class DraftMutation(Base):
    """Content-free receipt for idempotent draft mutations."""

    __tablename__ = "draft_mutations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    draft_session_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("draft_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    mutation_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    draft_session = relationship("DraftSession", back_populates="mutations")

    __table_args__ = (
        CheckConstraint("revision > 0", name="ck_draft_mutations_revision"),
        CheckConstraint(
            "operation IN ('upsert','discard','undo_discard')",
            name="ck_draft_mutations_operation",
        ),
        UniqueConstraint(
            "draft_session_id",
            "mutation_id",
            name="uq_draft_mutations_session_mutation",
        ),
        Index("ix_draft_mutations_created", "draft_session_id", "created_at"),
    )
