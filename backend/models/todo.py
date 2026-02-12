from datetime import datetime, timezone
from sqlalchemy import String, Integer, BigInteger, ForeignKey, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database import Base


class TodoItem(Base):
    __tablename__ = "todo_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    email_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("emails.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, done, dismissed
    source: Mapped[str] = mapped_column(String(20), default="manual")  # ai_action_item, manual

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    # AI draft action fields
    ai_draft_status: Mapped[str] = mapped_column(String(20), nullable=True)  # null, drafting, ready, approved, sent
    ai_draft_body: Mapped[str] = mapped_column(Text, nullable=True)
    ai_draft_to: Mapped[str] = mapped_column(Text, nullable=True)

    user = relationship("User")
    email = relationship("Email")
