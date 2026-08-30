from datetime import timezone

import pytest
from fastapi import HTTPException

from backend.routers.calendar import _calendar_range_utc


def test_calendar_range_preserves_fall_dst_day():
    start, end = _calendar_range_utc(
        "2026-11-01", "2026-11-01", "America/New_York"
    )

    assert start.isoformat() == "2026-11-01T04:00:00+00:00"
    assert end.isoformat() == "2026-11-02T05:00:00+00:00"
    assert (end - start).total_seconds() == 25 * 60 * 60
    assert start.tzinfo == timezone.utc


def test_calendar_range_preserves_spring_dst_day():
    start, end = _calendar_range_utc(
        "2026-03-08", "2026-03-08", "America/New_York"
    )

    assert start.isoformat() == "2026-03-08T05:00:00+00:00"
    assert end.isoformat() == "2026-03-09T04:00:00+00:00"
    assert (end - start).total_seconds() == 23 * 60 * 60


@pytest.mark.parametrize(
    ("start", "end", "tz", "detail"),
    [
        ("2026-08-31", "2026-08-30", "UTC", "End date must not be before start date"),
        ("not-a-date", "2026-08-30", "UTC", "Invalid date format"),
        ("2026-08-30", "2026-08-30", "Mars/Olympus", "Unknown timezone"),
    ],
)
def test_calendar_range_rejects_invalid_inputs(start, end, tz, detail):
    with pytest.raises(HTTPException) as exc_info:
        _calendar_range_utc(start, end, tz)

    assert exc_info.value.status_code == 400
    assert detail in exc_info.value.detail
