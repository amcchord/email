from datetime import datetime, timezone
from sqlalchemy import String, Boolean, DateTime, BigInteger, Integer, ForeignKey, Text, Float, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database import Base


class AIAnalysis(Base):
    __tablename__ = "ai_analyses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("emails.id", ondelete="CASCADE"), unique=True)
    category: Mapped[str] = mapped_column(String(50), nullable=True)
    # Categories: can_ignore, fyi, urgent, awaiting_reply
    email_type: Mapped[str] = mapped_column(String(20), nullable=True)
    # Email type: work, personal
    conversation_type: Mapped[str] = mapped_column(String(30), nullable=True)
    # Conversation type: scheduling, discussion, notification, transactional, other
    priority: Mapped[int] = mapped_column(default=0)  # 0=low, 1=normal, 2=high, 3=urgent
    summary: Mapped[str] = mapped_column(Text, nullable=True)
    action_items = mapped_column(JSONB, default=list)
    context = mapped_column(JSONB, default=dict)
    sentiment: Mapped[float] = mapped_column(Float, nullable=True)
    key_topics = mapped_column(JSONB, default=list)
    suggested_reply: Mapped[str] = mapped_column(Text, nullable=True)
    reply_options = mapped_column(JSONB, nullable=True)
    # reply_options format: [{"label": "Accept", "intent": "accept", "body": "..."}, ...]
    # intent values: accept, decline, defer, custom, not_relevant
    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    model_used: Mapped[str] = mapped_column(String(100), nullable=True)
    tokens_used: Mapped[int] = mapped_column(default=0)

    # Agentic features
    is_subscription: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_reply: Mapped[bool] = mapped_column(Boolean, default=False)
    expects_reply: Mapped[bool] = mapped_column(Boolean, nullable=True)
    # expects_reply: for sent emails, True if the sender expects a reply from the recipient.
    # NULL = not yet classified, False = no reply expected, True = reply expected.
    needs_reply_ignored: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_reply_snoozed_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    unsubscribe_info = mapped_column(JSONB, nullable=True)
    # unsubscribe_info format: {"method": "email"|"url"|"both", "email": "...", "url": "...", "mailto_subject": "...", "mailto_body": "..."}

    email = relationship("Email", back_populates="ai_analysis")


class ThreadDigest(Base):
    __tablename__ = "thread_digests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("google_accounts.id", ondelete="CASCADE"))
    gmail_thread_id: Mapped[str] = mapped_column(String(255), nullable=False)
    conversation_type: Mapped[str] = mapped_column(String(30), nullable=True)
    # Conversation type: scheduling, discussion, notification, transactional, other
    summary: Mapped[str] = mapped_column(Text, nullable=True)
    resolved_outcome: Mapped[str] = mapped_column(Text, nullable=True)
    # For scheduling: "Meeting confirmed Wed 2pm at Coffee Shop"; null for non-scheduling
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    key_topics = mapped_column(JSONB, default=list)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    participants = mapped_column(JSONB, default=list)
    # List of {"name": "...", "address": "..."} dicts
    subject: Mapped[str] = mapped_column(Text, nullable=True)
    latest_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    model_used: Mapped[str] = mapped_column(String(100), nullable=True)

    account = relationship("GoogleAccount")

    __table_args__ = (
        Index("ix_thread_digests_account_thread", "account_id", "gmail_thread_id", unique=True),
        Index("ix_thread_digests_latest_date", "latest_date"),
        Index("ix_thread_digests_conversation_type", "conversation_type"),
    )


class EmailBundle(Base):
    __tablename__ = "email_bundles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    # Bundles are user-level, not account-level -- they can span multiple accounts
    title: Mapped[str] = mapped_column(Text, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=True)
    key_topics = mapped_column(JSONB, default=list)
    email_ids = mapped_column(JSONB, default=list)
    thread_ids = mapped_column(JSONB, default=list)
    account_ids = mapped_column(JSONB, default=list)
    email_count: Mapped[int] = mapped_column(Integer, default=0)
    thread_count: Mapped[int] = mapped_column(Integer, default=0)
    latest_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    # Status: active, resolved, stale
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user = relationship("User")

    __table_args__ = (
        Index("ix_email_bundles_user_id", "user_id"),
        Index("ix_email_bundles_latest_date", "latest_date"),
        Index("ix_email_bundles_status", "status"),
    )


class UnsubscribeTracking(Base):
    __tablename__ = "unsubscribe_tracking"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    email_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("emails.id", ondelete="CASCADE"))
    sender_domain: Mapped[str] = mapped_column(String(255), index=True)
    sender_address: Mapped[str] = mapped_column(String(255))
    unsubscribe_to: Mapped[str] = mapped_column(String(255), nullable=True)
    method: Mapped[str] = mapped_column(String(20))  # "email" or "url"
    unsubscribed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    emails_received_after: Mapped[int] = mapped_column(Integer, default=0)
    last_email_after_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    user = relationship("User")
    email = relationship("Email")
