from datetime import datetime, timezone
from sqlalchemy import (
    String, Boolean, DateTime, Integer, ForeignKey, Text, BigInteger,
    UniqueConstraint, Index,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database import Base


class CalendarEvent(Base):
    __tablename__ = "calendar_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("google_accounts.id", ondelete="CASCADE")
    )
    google_event_id: Mapped[str] = mapped_column(String(1024))
    calendar_id: Mapped[str] = mapped_column(String(255), default="primary")

    # Core
    summary: Mapped[str] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    location: Mapped[str] = mapped_column(Text, nullable=True)

    # Times
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    start_date: Mapped[str] = mapped_column(String(20), nullable=True)  # For all-day events (YYYY-MM-DD)
    end_date: Mapped[str] = mapped_column(String(20), nullable=True)
    timezone: Mapped[str] = mapped_column(String(100), nullable=True)
    is_all_day: Mapped[bool] = mapped_column(Boolean, default=False)

    # Recurrence
    recurring_event_id: Mapped[str] = mapped_column(String(1024), nullable=True)
    recurrence_rule: Mapped[dict] = mapped_column(JSONB, nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(50), default="confirmed")  # confirmed/tentative/cancelled
    html_link: Mapped[str] = mapped_column(Text, nullable=True)
    hangout_link: Mapped[str] = mapped_column(Text, nullable=True)

    # Organizer
    organizer_email: Mapped[str] = mapped_column(String(320), nullable=True)
    organizer_name: Mapped[str] = mapped_column(String(255), nullable=True)
    organizer_self: Mapped[bool] = mapped_column(Boolean, default=False)

    # Attendees
    attendees: Mapped[list] = mapped_column(JSONB, nullable=True)

    # Meta
    visibility: Mapped[str] = mapped_column(String(50), nullable=True)
    transparency: Mapped[str] = mapped_column(String(50), nullable=True)
    reminders: Mapped[dict] = mapped_column(JSONB, nullable=True)
    etag: Mapped[str] = mapped_column(String(255), nullable=True)
    updated_at_google: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    account = relationship("GoogleAccount", back_populates="calendar_events")

    __table_args__ = (
        UniqueConstraint("account_id", "google_event_id", name="uq_calendar_event_account_google"),
        Index("ix_calendar_events_start_time", "start_time"),
        Index("ix_calendar_events_account_start", "account_id", "start_time"),
    )


class CalendarSyncStatus(Base):
    __tablename__ = "calendar_sync_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("google_accounts.id", ondelete="CASCADE"), unique=True
    )
    sync_token: Mapped[str] = mapped_column(Text, nullable=True)
    last_full_sync: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    last_incremental_sync: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="idle")  # idle, syncing, error, completed
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    events_synced: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    account = relationship("GoogleAccount", back_populates="calendar_sync_status")
