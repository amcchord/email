from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import (
    BigInteger,
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


MAIL_ACTION_TYPES = (
    "mark_read",
    "mark_unread",
    "star",
    "unstar",
    "archive",
    "trash",
    "untrash",
    "spam",
    "unspam",
)
MAIL_ACTION_STATES = (
    "staged",
    "processing",
    "retry_wait",
    "applied",
    "failed",
    "cancelled",
)
ACTIVE_MAIL_ACTION_STATES = ("staged", "processing", "retry_wait")


class MailAction(Base):
    """One durable, ordered Gmail label mutation for one email."""

    __tablename__ = "mail_actions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
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
    email_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("emails.id", ondelete="SET NULL"),
        nullable=True,
    )
    gmail_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chain_start_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)

    base_state = mapped_column(JSONB, nullable=False)
    before_state = mapped_column(JSONB, nullable=False)
    after_state = mapped_column(JSONB, nullable=False)
    add_labels = mapped_column(JSONB, nullable=False, default=list)
    remove_labels = mapped_column(JSONB, nullable=False, default=list)

    state: Mapped[str] = mapped_column(String(32), nullable=False, default="staged")
    execute_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    undo_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=8)

    lease_token: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    gmail_history_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

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
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    email = relationship("Email", back_populates="mail_actions")

    __table_args__ = (
        CheckConstraint(
            "action IN ('mark_read','mark_unread','star','unstar','archive','trash','untrash','spam','unspam')",
            name="ck_mail_actions_action",
        ),
        CheckConstraint(
            "state IN ('staged','processing','retry_wait','applied','failed','cancelled')",
            name="ck_mail_actions_state",
        ),
        CheckConstraint("sequence > 0", name="ck_mail_actions_sequence_positive"),
        CheckConstraint(
            "chain_start_sequence > 0 AND chain_start_sequence <= sequence",
            name="ck_mail_actions_chain_sequence",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_mail_actions_attempt_count"),
        CheckConstraint("max_attempts > 0", name="ck_mail_actions_max_attempts"),
        CheckConstraint(
            "jsonb_typeof(base_state) = 'object' AND jsonb_typeof(before_state) = 'object' "
            "AND jsonb_typeof(after_state) = 'object'",
            name="ck_mail_actions_state_json_objects",
        ),
        CheckConstraint(
            "jsonb_typeof(add_labels) = 'array' AND jsonb_typeof(remove_labels) = 'array'",
            name="ck_mail_actions_label_json_arrays",
        ),
        CheckConstraint(
            "(state = 'processing' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) "
            "OR (state <> 'processing' AND lease_token IS NULL AND lease_expires_at IS NULL)",
            name="ck_mail_actions_lease_state",
        ),
        CheckConstraint(
            "execute_after >= created_at AND undo_until >= created_at",
            name="ck_mail_actions_action_times",
        ),
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            "email_id",
            name="uq_mail_actions_user_idempotency_email",
        ),
        UniqueConstraint("email_id", "sequence", name="uq_mail_actions_email_sequence"),
        Index("ix_mail_actions_request_user", "request_id", "user_id"),
        Index("ix_mail_actions_user_created", "user_id", "created_at"),
        Index("ix_mail_actions_account_state_due", "account_id", "state", "next_attempt_at"),
        Index(
            "ix_mail_actions_gmail_active",
            "account_id",
            "gmail_message_id",
            "sequence",
            postgresql_where=text("state IN ('staged','processing','retry_wait')"),
        ),
        Index(
            "ix_mail_actions_due",
            "execute_after",
            "id",
            postgresql_where=text("state IN ('staged','retry_wait')"),
        ),
        Index(
            "ix_mail_actions_expired_lease",
            "lease_expires_at",
            postgresql_where=text("state = 'processing'"),
        ),
    )
