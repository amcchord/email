"""Dashboard auxiliary content (e-ink panel snippets).

The e-ink editorial dashboard's "calm" hero shows a rotating quote or
contextual observation when no appliance is active. To avoid burning AI
calls on every render, a cron worker generates the snippet for the
current local hour (in the terminal's IANA timezone) and persists it
here; the renderer reads the row keyed by ``(date_local, hour_local)``.

A single ``(date_local, hour_local)`` covers all configured terminals
on the assumption that they share one user timezone (mirroring
``TerminalSettings.timezone``). If multi-tz terminals get added later,
this would gain a ``tz_name`` partition key.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class DashboardSnippet(Base):
    """One snippet (quote or observation) for a specific (local date, hour)."""

    __tablename__ = "dashboard_snippets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # YYYY-MM-DD in the configured TerminalSettings timezone. Kept as a
    # string (not DATE) so the (date_local, hour_local) lookup is a
    # single composite index hit and never has to round-trip through
    # postgres time math.
    date_local: Mapped[str] = mapped_column(String(10), nullable=False)
    hour_local: Mapped[int] = mapped_column(Integer, nullable=False)
    # IANA name of the timezone this row was generated against, e.g.
    # "America/New_York". Stored so a tz change in TerminalSettings can
    # be diagnosed from the data.
    tz_name: Mapped[str] = mapped_column(String(100), nullable=False)
    # "quote" or "observation". The renderer uses this to choose the
    # kicker label and whether to wrap the body in curly quotes.
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    byline: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint(
            "date_local",
            "hour_local",
            name="uq_dashboard_snippets_date_hour",
        ),
        Index(
            "ix_dashboard_snippets_date_hour",
            "date_local",
            "hour_local",
        ),
    )
