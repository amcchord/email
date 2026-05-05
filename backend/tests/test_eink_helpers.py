"""Tests for the HA-state and time helpers in ``eink/pillow/helpers.py``.

Focused on the two robustness wins that motivated the refactor:

1. ``derive_hvac_state`` reconciles HA's ``state`` (mode) with
   ``hvac_action`` so a stale/cross-purpose attribute can no longer cause
   a "heating" label when the system is actually cooling (and vice versa).
2. ``fmt_clock`` and ``parse_iso`` convert UTC timestamps into the user's
   IANA timezone instead of leaving naive / UTC wall-clock values.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from backend.services.eink.pillow.helpers import (
    cooling_zone_count,
    derive_hvac_state,
    floor_cool_count,
    floor_heat_count,
    fmt_clock,
    heating_zone_count,
    parse_iso,
)


# ── derive_hvac_state ─────────────────────────────────────────────────


def test_heating_when_mode_and_action_agree():
    assert derive_hvac_state({"mode": "heat", "action": "heating"}) == "heating"
    assert derive_hvac_state({"mode": "auto", "action": "heating"}) == "heating"
    assert derive_hvac_state({"mode": "heat_cool", "action": "heating"}) == "heating"


def test_cooling_when_mode_and_action_agree():
    assert derive_hvac_state({"mode": "cool", "action": "cooling"}) == "cooling"
    assert derive_hvac_state({"mode": "auto", "action": "cooling"}) == "cooling"
    assert derive_hvac_state({"mode": "heat_cool", "action": "cooling"}) == "cooling"


def test_stale_action_is_clamped_against_mode():
    """The bug we are guarding against: HA reports ``hvac_action='heating'``
    on a thermostat the user has switched to ``cool``. Without
    reconciliation the floor cell would proudly show "heating"."""
    assert derive_hvac_state({"mode": "cool", "action": "heating"}) == "unknown"
    assert derive_hvac_state({"mode": "heat", "action": "cooling"}) == "unknown"
    assert derive_hvac_state({"mode": "off", "action": "heating"}) == "off"


def test_idle_and_off_states():
    assert derive_hvac_state({"mode": "heat", "action": "idle"}) == "idle"
    assert derive_hvac_state({"mode": "cool", "action": "idle"}) == "idle"
    assert derive_hvac_state({"mode": "off", "action": "off"}) == "off"
    assert derive_hvac_state({"mode": "off"}) == "off"
    assert derive_hvac_state({"mode": "heat", "action": "fan"}) == "idle"


def test_missing_or_empty_inputs():
    assert derive_hvac_state(None) == "unknown"
    assert derive_hvac_state({}) == "unknown"
    assert derive_hvac_state({"mode": "heat"}) == "idle"
    assert derive_hvac_state({"mode": "unavailable"}) == "unknown"


def test_case_insensitive():
    assert derive_hvac_state({"mode": "HEAT", "action": "Heating"}) == "heating"
    assert derive_hvac_state({"mode": "Cool", "action": "COOLING"}) == "cooling"


# ── floor / zone counters ─────────────────────────────────────────────


def _ha_with_climates(*climates: dict) -> dict:
    return {
        "allClimates": list(climates),
        "floorActivity": {"first": list(climates)},
    }


def test_floor_heat_count_only_counts_reconciled_heating():
    ha = _ha_with_climates(
        {"mode": "heat", "action": "heating"},
        {"mode": "cool", "action": "heating"},  # stale, should NOT count
        {"mode": "heat", "action": "idle"},
    )
    assert floor_heat_count(ha, "first") == 1
    assert heating_zone_count(ha) == 1


def test_floor_cool_count_only_counts_reconciled_cooling():
    ha = _ha_with_climates(
        {"mode": "cool", "action": "cooling"},
        {"mode": "cool", "action": "cooling"},
        {"mode": "heat", "action": "cooling"},  # stale, should NOT count
    )
    assert floor_cool_count(ha, "first") == 2
    assert cooling_zone_count(ha) == 2


def test_counters_handle_missing_keys():
    assert floor_heat_count({}, "first") == 0
    assert floor_cool_count({}, "first") == 0
    assert heating_zone_count({}) == 0
    assert cooling_zone_count({}) == 0


# ── parse_iso / fmt_clock timezone behaviour ──────────────────────────


def test_parse_iso_stamps_naive_strings_as_utc():
    """HA usually emits offset-aware ISO strings, but we still need a
    well-defined timezone for `astimezone` to work downstream."""
    naive = parse_iso("2026-05-05T13:34:00")
    assert naive is not None
    assert naive.tzinfo is not None
    assert naive.utcoffset() == timezone.utc.utcoffset(naive)


def test_parse_iso_handles_z_suffix_and_offset():
    z = parse_iso("2026-05-05T13:34:00Z")
    plus = parse_iso("2026-05-05T13:34:00+00:00")
    assert z == plus
    assert z is not None and z.tzinfo is not None


def test_parse_iso_returns_none_for_unknown():
    assert parse_iso(None) is None
    assert parse_iso("") is None
    assert parse_iso("unknown") is None
    assert parse_iso("unavailable") is None
    assert parse_iso("not-a-date") is None


def test_fmt_clock_converts_utc_into_user_zone():
    ny = ZoneInfo("America/New_York")
    # 2026-05-05 is in EDT (UTC-4); 13:34 UTC is 09:34 local.
    assert fmt_clock("2026-05-05T13:34:00+00:00", tz=ny) == "9:34 AM"


def test_fmt_clock_treats_naive_iso_as_utc_when_zone_provided():
    ny = ZoneInfo("America/New_York")
    assert fmt_clock("2026-05-05T13:34:00", tz=ny) == "9:34 AM"


def test_fmt_clock_no_tz_falls_back_to_current_offset():
    """Without a tz arg the clock formats the instant in whatever zone the
    datetime already carries. Sun rows always pass tz=zone; appliance rows
    must do the same after the renderer fix."""
    dt = datetime(2026, 5, 5, 13, 34, tzinfo=timezone.utc)
    assert fmt_clock(dt) == "1:34 PM"


def test_fmt_clock_em_dash_for_missing():
    assert fmt_clock(None) == "\u2014"
    assert fmt_clock("unknown") == "\u2014"
