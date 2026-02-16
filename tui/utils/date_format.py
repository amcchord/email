"""Relative date formatting utilities."""

from __future__ import annotations

from datetime import datetime, timezone


def relative_date(dt: datetime | str | None) -> str:
    """Format a datetime as a human-friendly relative string.

    Accepts a datetime object (assumed UTC if naive) or an ISO format string.

    Returns strings like:
        - "just now" (< 1 minute)
        - "2m ago" (< 1 hour)
        - "1h ago" (< 24 hours)
        - "yesterday"
        - "2d ago" (< 7 days)
        - "Feb 14" (same year)
        - "Feb 14, 2024" (different year)
    """
    if dt is None:
        return ""

    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return dt

    now = datetime.now(timezone.utc)

    # Make naive datetimes UTC-aware
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    diff = now - dt
    total_seconds = diff.total_seconds()

    if total_seconds < 0:
        # Future date
        return _format_absolute(dt, now)

    if total_seconds < 60:
        return "just now"

    minutes = int(total_seconds // 60)
    if minutes < 60:
        return f"{minutes}m ago"

    hours = int(total_seconds // 3600)
    if hours < 24:
        return f"{hours}h ago"

    days = int(total_seconds // 86400)
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days}d ago"

    return _format_absolute(dt, now)


def _format_absolute(dt: datetime, now: datetime) -> str:
    """Format a date as an absolute string."""
    month = dt.strftime("%b")
    day = dt.day
    if dt.year == now.year:
        return f"{month} {day}"
    return f"{month} {day}, {dt.year}"
