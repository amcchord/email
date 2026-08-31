"""Owner-scoped reusable Personal Snippets."""

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
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


class PersonalSnippet(Base):
    """One private reusable body owned by exactly one application user."""

    __tablename__ = "personal_snippets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snippet_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    shortcut: Mapped[str] = mapped_column(String(32), nullable=False)
    body_html: Mapped[str] = mapped_column(Text, nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
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

    user = relationship("User")

    __table_args__ = (
        CheckConstraint("revision > 0", name="ck_personal_snippets_revision"),
        CheckConstraint(
            "shortcut ~ '^[a-z0-9][a-z0-9_-]{0,31}$'",
            name="ck_personal_snippets_shortcut",
        ),
        CheckConstraint(
            "char_length(name) BETWEEN 1 AND 120",
            name="ck_personal_snippets_name",
        ),
        CheckConstraint(
            "char_length(body_text) BETWEEN 1 AND 20000 "
            "AND char_length(body_html) BETWEEN 1 AND 50000",
            name="ck_personal_snippets_body",
        ),
        UniqueConstraint(
            "user_id", "snippet_id", name="uq_personal_snippets_user_public_id"
        ),
        UniqueConstraint(
            "user_id", "shortcut", name="uq_personal_snippets_user_shortcut"
        ),
        Index("ix_personal_snippets_user_name", "user_id", "name", "id"),
    )
