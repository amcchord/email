from datetime import datetime, timezone
from sqlalchemy import String, DateTime, Integer, Text, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database import Base


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    prefix: Mapped[str] = mapped_column(String(12), nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    user = relationship("User", backref="api_tokens")

    __table_args__ = (
        Index("ix_api_tokens_user_active", "user_id", "revoked_at"),
    )
