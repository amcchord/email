from datetime import datetime, timezone
from sqlalchemy import String, DateTime, Integer, Text, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database import Base


class TerminalSettings(Base):
    """Per-user e-ink terminal config: shared short URL code + Home Assistant link."""

    __tablename__ = "terminal_settings"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)
    # IANA timezone name (e.g. "America/New_York") used by the e-ink clock
    # renderer so the time on the panel matches the user's wall clock instead
    # of the server's UTC clock.
    timezone: Mapped[str] = mapped_column(
        String(100), nullable=False, default="America/New_York"
    )
    home_assistant_url: Mapped[str] = mapped_column(Text, nullable=True)
    home_assistant_token_encrypted: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user = relationship("User", backref="terminal_settings")


class TerminalDevice(Base):
    """One row per (user, MAC) seen checking in to /terminal/{code}/."""

    __tablename__ = "terminal_devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    mac: Mapped[str] = mapped_column(String(17), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    variant: Mapped[str] = mapped_column(String(32), nullable=True)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False, default="clock")
    content_config = mapped_column(JSONB, nullable=True)
    # Override for the schedule.json `next_checkin_sec`. NULL = use the
    # variant's baseline cadence. Server enforces a 30s floor and a 21600s
    # (6 hour) ceiling.
    refresh_interval_sec: Mapped[int] = mapped_column(Integer, nullable=True)

    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    last_wake_reason: Mapped[str] = mapped_column(String(32), nullable=True)
    last_battery_mv: Mapped[int] = mapped_column(Integer, nullable=True)
    last_battery_pct: Mapped[int] = mapped_column(Integer, nullable=True)
    last_rssi_dbm: Mapped[int] = mapped_column(Integer, nullable=True)
    last_uptime_sec: Mapped[int] = mapped_column(Integer, nullable=True)
    last_boot_count: Mapped[int] = mapped_column(Integer, nullable=True)
    last_fw_version: Mapped[str] = mapped_column(String(64), nullable=True)
    last_image_etag: Mapped[str] = mapped_column(String(128), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    user = relationship("User", backref="terminal_devices")

    __table_args__ = (
        UniqueConstraint("user_id", "mac", name="uq_terminal_devices_user_mac"),
        Index("ix_terminal_devices_user_last_seen", "user_id", "last_seen_at"),
    )
