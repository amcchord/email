from datetime import datetime, timezone
from sqlalchemy import (
    String, Boolean, DateTime, Integer, ForeignKey, Text, BigInteger,
    Index, Column,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database import Base


class Email(Base):
    __tablename__ = "emails"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("google_accounts.id", ondelete="CASCADE"))
    gmail_message_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    gmail_thread_id: Mapped[str] = mapped_column(String(255), index=True)
    gmail_history_id: Mapped[str] = mapped_column(String(100), nullable=True)

    subject: Mapped[str] = mapped_column(Text, nullable=True, default="")
    from_address: Mapped[str] = mapped_column(Text, nullable=True)
    from_name: Mapped[str] = mapped_column(Text, nullable=True)
    to_addresses = mapped_column(JSONB, default=list)
    cc_addresses = mapped_column(JSONB, default=list)
    bcc_addresses = mapped_column(JSONB, default=list)
    reply_to: Mapped[str] = mapped_column(Text, nullable=True)

    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    snippet: Mapped[str] = mapped_column(Text, nullable=True)
    body_text: Mapped[str] = mapped_column(Text, nullable=True)
    body_html: Mapped[str] = mapped_column(Text, nullable=True)

    labels = mapped_column(JSONB, default=list)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    is_starred: Mapped[bool] = mapped_column(Boolean, default=False)
    is_trash: Mapped[bool] = mapped_column(Boolean, default=False)
    is_spam: Mapped[bool] = mapped_column(Boolean, default=False)
    is_draft: Mapped[bool] = mapped_column(Boolean, default=False)
    is_sent: Mapped[bool] = mapped_column(Boolean, default=False)

    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=True)
    has_attachments: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_headers = mapped_column(JSONB, nullable=True)
    message_id_header: Mapped[str] = mapped_column(Text, nullable=True)
    in_reply_to: Mapped[str] = mapped_column(Text, nullable=True)
    references_header: Mapped[str] = mapped_column(Text, nullable=True)

    search_vector = Column(TSVECTOR)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    account = relationship("GoogleAccount", back_populates="emails")
    attachments = relationship("Attachment", back_populates="email", cascade="all, delete-orphan")
    ai_analysis = relationship("AIAnalysis", back_populates="email", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_emails_account_date", "account_id", "date"),
        Index("ix_emails_thread", "account_id", "gmail_thread_id"),
        Index("ix_emails_search", "search_vector", postgresql_using="gin"),
    )


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("emails.id", ondelete="CASCADE"))
    gmail_attachment_id: Mapped[str] = mapped_column(Text, nullable=True)
    filename: Mapped[str] = mapped_column(Text, nullable=True)
    content_type: Mapped[str] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=True)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=True)
    is_inline: Mapped[bool] = mapped_column(Boolean, default=False)
    content_id: Mapped[str] = mapped_column(Text, nullable=True)

    email = relationship("Email", back_populates="attachments")


class EmailLabel(Base):
    __tablename__ = "email_labels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("google_accounts.id", ondelete="CASCADE"))
    gmail_label_id: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    label_type: Mapped[str] = mapped_column(String(50), nullable=True)  # system, user
    color_bg: Mapped[str] = mapped_column(String(20), nullable=True)
    color_text: Mapped[str] = mapped_column(String(20), nullable=True)
    messages_total: Mapped[int] = mapped_column(Integer, default=0)
    messages_unread: Mapped[int] = mapped_column(Integer, default=0)

    account = relationship("GoogleAccount", back_populates="labels")

    __table_args__ = (
        Index("ix_labels_account_gmail", "account_id", "gmail_label_id", unique=True),
    )
