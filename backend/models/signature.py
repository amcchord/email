"""Revisioned rich/plain signatures owned by one connected account."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


class AccountSignature(Base):
    """One optional signature policy for one immutable Google account."""

    __tablename__ = "account_signatures"

    account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("google_accounts.id", ondelete="CASCADE"),
        primary_key=True,
        autoincrement=False,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    include_on_new: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    include_on_replies: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    include_on_forwards: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    body_html: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    body_text: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    sanitizer_version: Mapped[int] = mapped_column(
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

    account = relationship("GoogleAccount", back_populates="signature")

    __table_args__ = (
        CheckConstraint("revision > 0", name="ck_account_signatures_revision"),
        CheckConstraint(
            "sanitizer_version > 0",
            name="ck_account_signatures_sanitizer_version",
        ),
        CheckConstraint(
            "char_length(body_html) <= 50000 AND char_length(body_text) <= 20000",
            name="ck_account_signatures_body_bounds",
        ),
        CheckConstraint(
            "NOT enabled OR (char_length(body_html) > 0 AND char_length(body_text) > 0)",
            name="ck_account_signatures_enabled_body",
        ),
    )
