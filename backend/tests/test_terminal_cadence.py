"""Tests for wall-clock alignment of e-ink check-ins.

``aligned_next_checkin_sec`` turns a flat cadence into the gap until the next
UTC boundary that is a multiple of the cadence, so hourly devices wake on :00
and 15-min devices wake on :00/:15/:30/:45 regardless of boot time.
"""
from __future__ import annotations

from datetime import datetime, timezone

from backend.services.terminal.variants import aligned_next_checkin_sec


def _utc(year, month, day, hour, minute, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


def test_hourly_aligns_to_top_of_hour():
    # 10:07:00 with an hourly cadence -> 53 min until 11:00.
    now = _utc(2026, 6, 5, 10, 7, 0)
    assert aligned_next_checkin_sec(now, 3600) == 53 * 60


def test_quarter_hour_aligns_to_next_quarter():
    # 10:07:00 with a 15-min cadence -> 8 min until 10:15.
    now = _utc(2026, 6, 5, 10, 7, 0)
    assert aligned_next_checkin_sec(now, 900) == 8 * 60


def test_exactly_on_boundary_returns_full_interval():
    # On a boundary we sleep a full interval, never 0.
    now = _utc(2026, 6, 5, 10, 0, 0)
    assert aligned_next_checkin_sec(now, 3600) == 3600
    assert aligned_next_checkin_sec(now, 900) == 900


def test_woke_a_few_seconds_early_is_clamped_to_floor():
    # 10:59:57, hourly: only 3s to 11:00 -> clamp to the 30s floor instead of a
    # sub-floor sleep. The device re-aligns on the next check-in.
    now = _utc(2026, 6, 5, 10, 59, 57)
    assert aligned_next_checkin_sec(now, 3600) == 30


def test_result_never_exceeds_ceiling():
    now = _utc(2026, 6, 5, 0, 0, 0)
    # A 6h cadence on the boundary would be 21600 = the ceiling exactly.
    assert aligned_next_checkin_sec(now, 21600) == 21600


def test_fractional_now_is_truncated_not_rounded():
    # Sub-second time shouldn't push us past the boundary math.
    now = datetime(2026, 6, 5, 10, 7, 0, 500000, tzinfo=timezone.utc)
    assert aligned_next_checkin_sec(now, 900) == 8 * 60
