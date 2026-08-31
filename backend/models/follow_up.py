"""Persistence for account follow-up policy and outbound follow-up intent."""

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


FOLLOW_UP_INTENT_STATES = (
    "awaiting_delivery",
    "pending_sync",
    "scheduled",
    "superseded",
    "skipped",
    "cancelled",
    "failed",
)
FOLLOW_UP_REQUEST_SOURCES = ("policy", "explicit")


class AccountFollowUpPolicy(Base):
    """One revisioned automatic follow-up policy per connected account."""

    __tablename__ = "account_follow_up_policies"

    account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("google_accounts.id", ondelete="CASCADE"),
        primary_key=True,
        autoincrement=False,
    )
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    delay_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
        server_default=text("3"),
    )
    wake_local_time: Mapped[str] = mapped_column(
        String(5),
        nullable=False,
        default="09:00",
        server_default=text("'09:00'"),
    )
    time_zone: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="UTC",
        server_default=text("'UTC'"),
    )
    weekdays_only: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

    account = relationship("GoogleAccount")
    user = relationship("User")

    __table_args__ = (
        CheckConstraint(
            "delay_days BETWEEN 1 AND 30",
            name="ck_account_follow_up_policies_delay_days",
        ),
        CheckConstraint(
            "wake_local_time ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'",
            name="ck_account_follow_up_policies_wake_local_time",
        ),
        CheckConstraint(
            "char_length(time_zone) BETWEEN 1 AND 64",
            name="ck_account_follow_up_policies_time_zone",
        ),
        CheckConstraint(
            "revision > 0",
            name="ck_account_follow_up_policies_revision",
        ),
        Index(
            "ix_account_follow_up_policies_user_account",
            "user_id",
            "account_id",
        ),
    )


class OutboundFollowUpIntent(Base):
    """One durable follow-up outcome for an accepted outbound message."""

    __tablename__ = "outbound_follow_up_intents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    outbound_message_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("outbound_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
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
    snooze_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("email_snoozes.id", ondelete="SET NULL"),
        nullable=True,
    )

    state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="awaiting_delivery",
        server_default=text("'awaiting_delivery'"),
    )
    requested_via: Mapped[str] = mapped_column(String(16), nullable=False)
    delay_days: Mapped[int] = mapped_column(Integer, nullable=False)
    wake_local_time: Mapped[str] = mapped_column(String(5), nullable=False)
    time_zone: Mapped[str] = mapped_column(String(64), nullable=False)
    weekdays_only: Mapped[bool] = mapped_column(Boolean, nullable=False)
    post_send_archive: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )

    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    wake_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rfc_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lease_token: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    status_detail: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    outbound_message = relationship("OutboundMessage")
    account = relationship("GoogleAccount")
    user = relationship("User")
    snooze = relationship("EmailSnooze")

    __table_args__ = (
        CheckConstraint(
            "state IN ('awaiting_delivery','pending_sync','scheduled','superseded',"
            "'skipped','cancelled','failed')",
            name="ck_outbound_follow_up_intents_state",
        ),
        CheckConstraint(
            "requested_via IN ('policy','explicit')",
            name="ck_outbound_follow_up_intents_requested_via",
        ),
        CheckConstraint(
            "delay_days BETWEEN 1 AND 30",
            name="ck_outbound_follow_up_intents_delay_days",
        ),
        CheckConstraint(
            "wake_local_time ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'",
            name="ck_outbound_follow_up_intents_wake_local_time",
        ),
        CheckConstraint(
            "char_length(time_zone) BETWEEN 1 AND 64",
            name="ck_outbound_follow_up_intents_time_zone",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_outbound_follow_up_intents_attempt_count",
        ),
        CheckConstraint(
            "(lease_token IS NULL AND lease_expires_at IS NULL) OR "
            "(lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_outbound_follow_up_intents_lease_shape",
        ),
        CheckConstraint(
            "wake_at IS NULL OR delivered_at IS NOT NULL",
            name="ck_outbound_follow_up_intents_wake_delivery",
        ),
        CheckConstraint(
            "state <> 'scheduled' OR (snooze_id IS NOT NULL AND scheduled_at IS NOT NULL)",
            name="ck_outbound_follow_up_intents_scheduled_shape",
        ),
        CheckConstraint(
            "state <> 'cancelled' OR cancelled_at IS NOT NULL",
            name="ck_outbound_follow_up_intents_cancelled_at",
        ),
        CheckConstraint(
            "state <> 'failed' OR failed_at IS NOT NULL",
            name="ck_outbound_follow_up_intents_failed_at",
        ),
        UniqueConstraint(
            "public_id",
            name="uq_outbound_follow_up_intents_public_id",
        ),
        UniqueConstraint(
            "outbound_message_id",
            name="uq_outbound_follow_up_intents_outbound_message",
        ),
        Index(
            "ix_outbound_follow_up_intents_user_created",
            "user_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_outbound_follow_up_intents_account_state_wake",
            "account_id",
            "state",
            "wake_at",
            "id",
        ),
        Index(
            "ix_outbound_follow_up_intents_due",
            "state",
            "next_attempt_at",
            "id",
        ),
        Index(
            "ix_outbound_follow_up_intents_expired_lease",
            "lease_expires_at",
            postgresql_where=text("lease_token IS NOT NULL"),
        ),
    )
