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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


SNOOZE_ACTIVE_STATES = ("pending_archive", "scheduled", "pending_return")
SNOOZE_STATES = (*SNOOZE_ACTIVE_STATES, "returned", "cancelled", "dismissed", "failed")
SNOOZE_CONDITIONS = ("always", "if_no_reply")


class EmailSnooze(Base):
    """One durable, owner-scoped request to hide and later return an email."""

    __tablename__ = "email_snoozes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, unique=True)
    idempotency_key: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("google_accounts.id", ondelete="CASCADE"), nullable=False
    )
    email_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("emails.id", ondelete="SET NULL"), nullable=True
    )
    gmail_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    gmail_thread_id: Mapped[str] = mapped_column(String(255), nullable=False)

    wake_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    time_zone: Mapped[str] = mapped_column(String(64), nullable=False)
    condition: Mapped[str] = mapped_column(String(24), nullable=False, default="always")
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    status_detail: Mapped[str | None] = mapped_column(String(64), nullable=True)
    archive_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    anchor_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mail_action_version_at_schedule: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )

    archive_idempotency_key: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    archive_action_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("mail_actions.id", ondelete="SET NULL"), nullable=True
    )
    return_idempotency_key: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    return_action_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("mail_actions.id", ondelete="SET NULL"), nullable=True
    )

    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_token: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    email = relationship("Email", back_populates="snoozes")
    account = relationship("GoogleAccount")
    archive_action = relationship("MailAction", foreign_keys=[archive_action_id])
    return_action = relationship("MailAction", foreign_keys=[return_action_id])

    __table_args__ = (
        CheckConstraint(
            "state IN ('pending_archive','scheduled','pending_return','returned','cancelled','dismissed','failed')",
            name="ck_email_snoozes_state",
        ),
        CheckConstraint(
            "condition IN ('always','if_no_reply')",
            name="ck_email_snoozes_condition",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_email_snoozes_attempt_count"),
        CheckConstraint(
            "(lease_token IS NULL AND lease_expires_at IS NULL) OR "
            "(lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_email_snoozes_lease_shape",
        ),
        UniqueConstraint(
            "user_id", "idempotency_key", name="uq_email_snoozes_user_idempotency"
        ),
        Index("ix_email_snoozes_user_wake", "user_id", "wake_at", "id"),
        Index("ix_email_snoozes_due", "state", "next_attempt_at", "wake_at", "id"),
        Index(
            "uq_email_snoozes_active_email",
            "user_id",
            "email_id",
            unique=True,
            postgresql_where=text(
                "email_id IS NOT NULL AND state IN ('pending_archive','scheduled','pending_return')"
            ),
        ),
    )
