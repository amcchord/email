from datetime import datetime, timezone
from sqlalchemy import String, DateTime, BigInteger, ForeignKey, Text, Float
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database import Base


class AIAnalysis(Base):
    __tablename__ = "ai_analyses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("emails.id", ondelete="CASCADE"), unique=True)
    category: Mapped[str] = mapped_column(String(50), nullable=True)
    # Categories: needs_response, can_ignore, fyi, urgent, awaiting_reply
    priority: Mapped[int] = mapped_column(default=0)  # 0=low, 1=normal, 2=high, 3=urgent
    summary: Mapped[str] = mapped_column(Text, nullable=True)
    action_items = mapped_column(JSONB, default=list)
    context = mapped_column(JSONB, default=dict)
    sentiment: Mapped[float] = mapped_column(Float, nullable=True)
    key_topics = mapped_column(JSONB, default=list)
    suggested_reply: Mapped[str] = mapped_column(Text, nullable=True)
    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    model_used: Mapped[str] = mapped_column(String(100), nullable=True)
    tokens_used: Mapped[int] = mapped_column(default=0)

    email = relationship("Email", back_populates="ai_analysis")
