"""Low-level helpers (parsing + formatting + HVAC reconciliation).

This module is the **lowest** layer of the eink renderer stack. It
holds pure functions:

* ``parse_iso`` / ``fmt_clock`` / ``fmt_rel_time`` / ``fmt_duration``
  -- timezone-aware time parsing and formatting.
* ``derive_hvac_state`` and the ``floor_*_count`` / ``*_zone_count``
  counters -- the single source of truth for whether a HA climate zone
  is heating, cooling, or idle. Reconciles ``state`` (mode) with
  ``hvac_action`` so a stale HA action can never push the wrong colour
  to the renderer.
* Misc display formatters (``fmt_temp``, ``compass``, ``title_case``).

Renderers should not call these helpers directly. They consume the
typed views in ``ha_view.py`` instead, which call these helpers once
in a tz-correct way and expose the results as pre-formatted strings
on ``FloorView`` / ``ZoneView`` / ``ApplianceView``. See
``backend/services/eink/README.md`` for the full layering rules.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Literal, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


HvacState = Literal["heating", "cooling", "idle", "off", "unknown"]

_HEAT_MODES = {"heat", "heat_cool", "auto"}
_COOL_MODES = {"cool", "heat_cool", "auto", "fan_only", "dry"}


WEATHER_LABEL = {
    "partlycloudy": "Partly Cloudy",
    "mostlycloudy": "Mostly Cloudy",
    "clear-night": "Clear Night",
    "sunny": "Sunny",
    "cloudy": "Cloudy",
    "rainy": "Rainy",
    "snowy": "Snowy",
    "windy": "Windy",
    "fog": "Fog",
    "lightning": "Lightning",
    "lightning-rainy": "Thunderstorm",
    "pouring": "Pouring",
    "hail": "Hail",
    "snowy-rainy": "Sleet",
}

_COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def resolve_zone(tz_name: Optional[str]) -> ZoneInfo:
    if not tz_name:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(tz_name.strip())
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def to_float(v: Any) -> Optional[float]:
    if v is None or v == "" or v == "unknown" or v == "unavailable":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s or s in ("unknown", "unavailable"):
        return None
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
    try:
        # HA emits "2024-06-01T12:34:56+00:00" or with "Z".
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None
    # Naive strings (rare from HA, but possible) are treated as UTC so any
    # downstream `.astimezone(zone)` call is well-defined.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def fmt_temp(v: Any) -> str:
    f = to_float(v)
    if f is None:
        return "\u2014"  # em dash
    return f"{round(f)}\u00b0"


def fmt_time(dt: datetime) -> str:
    # JS: toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
    # -> '8:42 AM'. Python equivalent below; lstrip drops the leading zero.
    s = dt.strftime("%I:%M %p").lstrip("0")
    return s


def fmt_time_short_24(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def fmt_date(dt: datetime) -> str:
    # toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })
    # -> 'Monday, May 4'.
    day = dt.day  # numeric, no leading zero
    return f"{dt.strftime('%A')}, {dt.strftime('%B')} {day}"


def fmt_date_short(dt: datetime) -> str:
    # 'MON, MAY 04, 2026'
    return dt.strftime("%a, %b %d, %Y").upper()


def fmt_clock(iso_or_dt: Any, tz: Optional[Any] = None) -> str:
    """Format an ISO datetime (or datetime object) as '8:42 AM'.

    If `tz` (a ZoneInfo) is provided, the value is converted to that zone
    before formatting. HA's sun.next_rising / sensor.sun_next_setting
    entities always come back as UTC-offset ISO strings -- without this
    conversion the printed time is off by the UTC offset.
    """
    if iso_or_dt is None:
        return "\u2014"
    if isinstance(iso_or_dt, datetime):
        dt = iso_or_dt
    else:
        dt = parse_iso(str(iso_or_dt))
    if dt is None:
        return "\u2014"
    if tz is not None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(tz)
    return fmt_time(dt)


def fmt_rel_time(iso: Any, now: Optional[datetime] = None) -> Optional[str]:
    t = parse_iso(iso) if not isinstance(iso, datetime) else iso
    if t is None:
        return None
    n = now or datetime.now(timezone.utc)
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    if n.tzinfo is None:
        n = n.replace(tzinfo=timezone.utc)
    ms = (t - n).total_seconds() * 1000
    if ms < 0:
        m = round(-ms / 60000)
        if m < 1:
            return "just now"
        if m < 60:
            return f"{m}m ago"
        h = round(m / 60)
        if h < 24:
            return f"{h}h ago"
        return f"{round(h/24)}d ago"
    m = round(ms / 60000)
    if m < 1:
        return "now"
    if m < 60:
        return f"in {m}m"
    return f"in {round(m/60)}h"


def fmt_duration(iso: Any, now: Optional[datetime] = None) -> Optional[str]:
    t = parse_iso(iso) if not isinstance(iso, datetime) else iso
    if t is None:
        return None
    n = now or datetime.now(timezone.utc)
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    if n.tzinfo is None:
        n = n.replace(tzinfo=timezone.utc)
    ms = (t - n).total_seconds() * 1000
    if ms <= 0:
        return None
    m = round(ms / 60000)
    if m < 60:
        return f"{m}m"
    h = m // 60
    rem = m % 60
    return f"{h}h{rem}m" if rem else f"{h}h"


def compass(deg: Any) -> str:
    f = to_float(deg)
    if f is None:
        return ""
    return _COMPASS[round((f % 360) / 45) % 8]


def clean_program(p: Any) -> str:
    if not p:
        return ""
    return str(p).replace("dishcare_dishwasher_program_", "").replace("_", " ")


def title_case(s: Any) -> str:
    if not s:
        return ""
    return re.sub(
        r"\b\w",
        lambda m: m.group(0).upper(),
        str(s).replace("_", " "),
    )


def fmt_weather(state: Any) -> str:
    if not state:
        return ""
    return WEATHER_LABEL.get(state, title_case(str(state).replace("-", " ")))


def derive_hvac_state(climate: Optional[dict]) -> HvacState:
    """Reconcile HA `state` (mode) with `hvac_action`.

    HA sometimes leaves a stale `hvac_action` on the entity (e.g. reporting
    `heating` on a thermostat the user has switched to `cool`). The mode is
    the source of truth for which directions are even possible, so we clamp
    the action against the mode here. Anything that can't be reconciled
    falls back to a safe `idle` / `off` / `unknown` rather than asserting a
    direction.
    """
    if not climate:
        return "unknown"
    mode = (climate.get("mode") or "").lower()
    action = (climate.get("action") or "").lower()
    if mode == "off":
        return "off"
    if mode in {"unavailable", ""} and not action:
        return "unknown"
    if action == "heating" and mode in _HEAT_MODES:
        return "heating"
    if action == "cooling" and mode in _COOL_MODES:
        return "cooling"
    if action in {"idle", "off"}:
        return "idle"
    if action == "fan":
        return "idle"
    if not action:
        return "idle"
    return "unknown"


def floor_heat_count(ha: dict, key: str) -> int:
    fa = (ha or {}).get("floorActivity") or {}
    return sum(1 for c in (fa.get(key) or []) if derive_hvac_state(c) == "heating")


def floor_cool_count(ha: dict, key: str) -> int:
    fa = (ha or {}).get("floorActivity") or {}
    return sum(1 for c in (fa.get(key) or []) if derive_hvac_state(c) == "cooling")


def heating_zone_count(ha: dict) -> int:
    return sum(
        1
        for c in (ha or {}).get("allClimates") or []
        if derive_hvac_state(c) == "heating"
    )


def cooling_zone_count(ha: dict) -> int:
    return sum(
        1
        for c in (ha or {}).get("allClimates") or []
        if derive_hvac_state(c) == "cooling"
    )


def safe_round(v: Any, default: int = 0) -> int:
    f = to_float(v)
    if f is None:
        return default
    return int(round(f))


def safe_int(v: Any, default: int = 0) -> int:
    f = to_float(v)
    if f is None:
        return default
    return int(f)


def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def lerp_pct(val: float, lo: float, hi: float) -> float:
    if hi == lo:
        return 0.5
    return clamp((val - lo) / (hi - lo))
