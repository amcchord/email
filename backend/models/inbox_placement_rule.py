"""Private account-scoped rules for the deterministic Split Inbox projection."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


class InboxPlacementRule(Base):
    """One exact local placement instruction for one connected account."""

    __tablename__ = "inbox_placement_rules"

    row_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, default=uuid4
    )
    create_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("google_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    match_value: Mapped[str] = mapped_column(String(512), nullable=False)
    placement: Mapped[str] = mapped_column(String(16), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
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

    account = relationship("GoogleAccount")

    __table_args__ = (
        CheckConstraint(
            "scope IN ('conversation', 'sender', 'domain')",
            name="ck_inbox_placement_rules_scope",
        ),
        CheckConstraint(
            "placement IN ('focused', 'other')",
            name="ck_inbox_placement_rules_placement",
        ),
        CheckConstraint(
            "char_length(match_value) BETWEEN 1 AND 512",
            name="ck_inbox_placement_rules_match_value",
        ),
        CheckConstraint(
            "revision > 0",
            name="ck_inbox_placement_rules_revision",
        ),
        UniqueConstraint(
            "account_id",
            "id",
            name="uq_inbox_placement_rules_account_public_id",
        ),
        UniqueConstraint(
            "account_id",
            "create_id",
            name="uq_inbox_placement_rules_account_create_id",
        ),
        UniqueConstraint(
            "account_id",
            "scope",
            "match_value",
            name="uq_inbox_placement_rules_account_match",
        ),
    )
