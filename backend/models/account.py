from datetime import datetime, timezone
from sqlalchemy import String, Boolean, DateTime, Integer, ForeignKey, Text, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database import Base


class GoogleAccount(Base):
    __tablename__ = "google_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=True)
    encrypted_access_token: Mapped[str] = mapped_column(Text, nullable=True)
    encrypted_refresh_token: Mapped[str] = mapped_column(Text, nullable=True)
    token_expiry: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[str] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user = relationship("User", back_populates="google_accounts")
    sync_status = relationship("SyncStatus", back_populates="account", uselist=False, cascade="all, delete-orphan")
    emails = relationship("Email", back_populates="account", cascade="all, delete-orphan")
    labels = relationship("EmailLabel", back_populates="account", cascade="all, delete-orphan")


class SyncStatus(Base):
    __tablename__ = "sync_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("google_accounts.id", ondelete="CASCADE"), unique=True)
    last_history_id: Mapped[str] = mapped_column(String(100), nullable=True)
    last_full_sync: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    last_incremental_sync: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    messages_synced: Mapped[int] = mapped_column(BigInteger, default=0)
    total_messages: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(50), default="idle")  # idle, syncing, error, completed
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    current_phase: Mapped[str] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    account = relationship("GoogleAccount", back_populates="sync_status")
