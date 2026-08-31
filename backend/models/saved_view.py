"""Private revisioned Saved Views owned by one application user."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class SavedView(Base):
    """One content-free search definition in an owner's private collection."""

    __tablename__ = "saved_views"

    row_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, default=uuid4
    )
    create_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("google_accounts.id", ondelete="CASCADE"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    query: Mapped[str] = mapped_column(String(512), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
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

    __table_args__ = (
        CheckConstraint("revision > 0", name="ck_saved_views_revision"),
        CheckConstraint("position >= 0", name="ck_saved_views_position"),
        CheckConstraint(
            "char_length(name) BETWEEN 1 AND 80",
            name="ck_saved_views_name",
        ),
        CheckConstraint(
            "char_length(query) BETWEEN 1 AND 512",
            name="ck_saved_views_query",
        ),
        UniqueConstraint(
            "user_id", "id", name="uq_saved_views_user_public_id"
        ),
        UniqueConstraint(
            "user_id",
            "create_id",
            name="uq_saved_views_user_client_create_id",
        ),
        UniqueConstraint(
            "user_id", "position", name="uq_saved_views_user_position"
        ),
        Index(
            "uq_saved_views_user_name_ci",
            "user_id",
            func.lower(name),
            unique=True,
        ),
        Index(
            "ix_saved_views_user_order",
            "user_id",
            "position",
            "row_id",
        ),
    )
