"""Typed views over the shaped Home Assistant payload.

Why this module exists
----------------------
This is the **only** module allowed to read raw fields off the HA
shape (``c.get("action")``, ``wsh.get("remaining")``, ...) and the
**only** module allowed to call the time formatters in
``helpers.py`` (``fmt_clock``, ``fmt_duration``, ``fmt_rel_time``)
against HA timestamps.

Two production bugs led to this layering:

1. **Cooling labelled as heating** -- renderers each asked
   ``c.get("action") == "heating"`` directly and trusted whatever HA
   handed back, even when the user-set ``mode`` was ``cool``. Now they
   read ``ZoneView.state``, which is reconciled by
   ``helpers.derive_hvac_state`` once.

2. **Appliance clocks in UTC** -- renderers called
   ``fmt_clock(...)`` without ``tz=zone``, so washer/dishwasher
   "finishes" times printed in UTC. Now they read
   ``ApplianceView.finish_label`` which is built once with the user's
   IANA zone and is impossible to get wrong downstream.

Layer rules (also documented in backend/services/eink/README.md)
----------------------------------------------------------------
* Renderers consume ``*View`` dataclasses; they don't touch ``ha``
  directly. (Exception: shaped fields that are pure presentation,
  like ``ha.get("temps")`` or ``ha.get("people")``, are still allowed
  -- this module is about state-reconciliation and time correctness.)
* Time strings are pre-formatted in the user's zone here. Drawers
  must never call ``fmt_clock(...)`` against a HA ISO string -- they
  read ``view.finish_label`` instead.
* Adding a new appliance: write a ``_build_<kind>_view`` and register
  it in the ``_APPLIANCE_BUILDERS`` map below; everything else (the
  registry in ``appliances.py``, both designs) picks it up via the
  shared ``ApplianceView`` shape.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from .helpers import (
    HvacState,
    clean_program,
    cooling_zone_count,
    derive_hvac_state,
    floor_cool_count,
    floor_heat_count,
    fmt_clock,
    fmt_duration,
    fmt_rel_time,
    heating_zone_count,
    parse_iso,
    safe_int,
    safe_round,
    title_case,
)

if TYPE_CHECKING:
    from .render_ctx import AccentKind, RenderContext
else:
    AccentKind = str  # runtime fallback to keep this module self-contained


__all__ = [
    "ZoneView",
    "FloorView",
    "HvacSummary",
    "ApplianceView",
    "build_zone_view",
    "build_floor_view",
    "build_floor_views",
    "build_hvac_summary",
    "build_appliance_view",
    "supported_appliance_kinds",
]


# ── HVAC views ─────────────────────────────────────────────────────────


def _state_to_accent(state: HvacState) -> AccentKind:
    """Map a reconciled HVAC state to a semantic accent kind."""
    if state == "heating":
        return "heat"
    if state == "cooling":
        return "cool"
    return "idle"


@dataclass(frozen=True)
class ZoneView:
    """One reconciled climate zone (a single thermostat)."""

    name: str
    state: HvacState                # heating | cooling | idle | off | unknown
    accent_kind: AccentKind         # "heat" | "cool" | "idle"
    current: Optional[float]
    target:  Optional[float]
    chip_label: str                 # "H" / "C" / "" -- empty when idle/off

    @property
    def is_active(self) -> bool:
        return self.state in ("heating", "cooling")


@dataclass(frozen=True)
class FloorView:
    """All zones on one floor, summarised for a single row."""

    key: str
    label: str
    temp: Optional[float]
    state: HvacState                # dominant of the floor's zones
    heat_count: int
    cool_count: int
    accent_kind: AccentKind
    chip_label: str                 # "H{n}" / "C{n}" / "" -- empty when idle


@dataclass(frozen=True)
class HvacSummary:
    """Whole-house HVAC totals + a pre-formatted footer/colophon label."""

    heating: int
    cooling: int
    total: int
    dominant: AccentKind            # "heat" | "cool" | "idle"
    label: str                      # ready for a footer/colophon

    @property
    def is_active(self) -> bool:
        return self.heating > 0 or self.cooling > 0


def build_zone_view(climate: Optional[dict], *, name: str = "") -> ZoneView:
    """Wrap a single shaped climate dict in the reconciled view."""
    state = derive_hvac_state(climate)
    accent = _state_to_accent(state)
    chip = ""
    if state == "heating":
        chip = "H"
    elif state == "cooling":
        chip = "C"
    if not name and climate:
        name = str(climate.get("name") or climate.get("id") or "")
    return ZoneView(
        name=name,
        state=state,
        accent_kind=accent,
        current=_safe_float(climate.get("current") if climate else None),
        target=_safe_float(climate.get("target") if climate else None),
        chip_label=chip,
    )


def build_floor_view(ha: dict, key: str, label: str, temp: Any) -> FloorView:
    """Aggregate the climate zones registered against ``key`` (one of
    'first' / 'second' / 'third' / 'basement') into a single row view.

    The dominant state is whichever direction has more zones; ties go
    to heating (the historical behaviour for safety-critical alerts).
    """
    heat = floor_heat_count(ha, key)
    cool = floor_cool_count(ha, key)
    if heat == 0 and cool == 0:
        state: HvacState = "idle"
    elif heat >= cool:
        state = "heating"
    else:
        state = "cooling"
    accent = _state_to_accent(state)
    chip = ""
    if state == "heating":
        chip = f"H{heat}"
    elif state == "cooling":
        chip = f"C{cool}"
    return FloorView(
        key=key,
        label=label,
        temp=_safe_float(temp),
        state=state,
        heat_count=heat,
        cool_count=cool,
        accent_kind=accent,
        chip_label=chip,
    )


def build_floor_views(ha: dict, floors: list[tuple[str, str]]) -> list[FloorView]:
    """Convenience wrapper for the typical floor list. ``floors`` is a
    list of (key, label) pairs; the temp is pulled from ``ha['temps']``
    by key.
    """
    temps = (ha or {}).get("temps") or {}
    return [build_floor_view(ha, key, label, temps.get(key)) for key, label in floors]


def build_hvac_summary(ha: dict) -> HvacSummary:
    """Whole-house tally plus a pre-formatted label.

    Label rules (chosen so footers/colophons stay readable when both
    directions are active simultaneously, e.g. mixed thermostats):

    * heat > 0 and cool > 0 -> "HEAT {h} - COOL {c}"  (middle dot sep)
    * heat > 0              -> "ZONES HEATING {h}/{total}"
    * cool > 0              -> "ZONES COOLING {c}/{total}"
    * otherwise             -> "HVAC IDLE"
    """
    h = heating_zone_count(ha)
    c = cooling_zone_count(ha)
    total = len((ha or {}).get("allClimates") or [])
    if h > 0 and c > 0:
        dominant: AccentKind = "heat" if h >= c else "cool"
        label = f"HEAT {h} \u00b7 COOL {c}"
    elif h > 0:
        dominant = "heat"
        label = f"ZONES HEATING {h}/{total}"
    elif c > 0:
        dominant = "cool"
        label = f"ZONES COOLING {c}/{total}"
    else:
        dominant = "idle"
        label = "HVAC IDLE"
    return HvacSummary(heating=h, cooling=c, total=total, dominant=dominant, label=label)


# ── Appliance views ────────────────────────────────────────────────────


@dataclass(frozen=True)
class ApplianceView:
    """A timezone-correct, reconciled view of one appliance.

    Renderers compose their headlines/decks by reading the structured
    atoms here -- they MUST NOT call ``fmt_clock`` against HA times
    directly. Per-kind facts that don't fit in the universal fields
    live in ``extras``; see ``_build_*_view`` for each kind's contract.
    """

    kind: str

    # Eyebrow text, in both designs' preferred shapes.
    eyebrow_kicker: str             # editorial: "Laundry · Running"
    eyebrow_label: str              # swiss: "WASHER RUNNING"

    accent_kind: AccentKind

    # Time-localised strings. These are the bug-fix surface: drawers
    # MUST consume these, never re-derive a clock from the HA dict.
    finish_at_local: Optional[datetime] = None
    finish_label: str = ""          # "9:34 AM" or "—"
    remaining_label: str = ""       # "1h12m" or "—"
    relative_label: str = ""        # "in 1h" / "5m ago" / "now" / "—"

    # Universal numeric/text atoms.
    progress_pct: Optional[int] = None
    status_label: str = ""          # title-cased status / verb
    program_label: str = ""         # cleaned program name
    current: Optional[float] = None
    target:  Optional[float] = None

    # Per-kind structured data (door state, freeze-guard, kwh, etc.).
    # Documented per builder below.
    extras: dict[str, Any] = field(default_factory=dict)


# Type alias for builder signatures.
if TYPE_CHECKING:
    _ApplianceBuilder = Any
else:
    _ApplianceBuilder = object  # type: ignore[assignment]


_DASH = "\u2014"


def _safe_float(v: Any) -> Optional[float]:
    if v is None or v == "" or v == "unknown" or v == "unavailable":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _localize(iso: Any, ctx: "RenderContext") -> Optional[datetime]:
    dt = parse_iso(iso) if not isinstance(iso, datetime) else iso
    if dt is None:
        return None
    return dt.astimezone(ctx.zone)


def _clock(iso: Any, ctx: "RenderContext") -> str:
    dt = _localize(iso, ctx)
    if dt is None:
        return _DASH
    return fmt_clock(dt)


def _duration(iso: Any, ctx: "RenderContext") -> str:
    return fmt_duration(iso, ctx.now_utc) or _DASH


def _relative(iso: Any, ctx: "RenderContext") -> str:
    return fmt_rel_time(iso, ctx.now_utc) or _DASH


# ── Per-kind builders ──────────────────────────────────────────────────
#
# Each builder takes (ha, ctx) and returns an ApplianceView. They are
# the contract drawers depend on; the per-kind ``extras`` keys are
# documented inline so adding a drawer or a new design is a copy/paste
# job rather than a treasure hunt.


def _build_sauna_view(ha: dict, ctx: "RenderContext") -> ApplianceView:
    """extras: heaters:int, duration:int, door_open:bool, room_temp:float?,
    room_humidity:int, remaining_deg:int? (deg to climb), freeze_protect:bool=False
    """
    s = ha.get("sauna") or {}
    current = _safe_float(s.get("current"))
    target = _safe_float(s.get("target"))
    remaining_deg: Optional[int] = None
    if target is not None and current is not None:
        remaining_deg = int(max(0, target - current))
    return ApplianceView(
        kind="sauna",
        eyebrow_kicker="Sauna \u00b7 Heating",
        eyebrow_label="SAUNA HEATING",
        accent_kind="alert",
        current=current,
        target=target,
        status_label="Heating",
        extras={
            "heaters": safe_int(s.get("heaters")),
            "duration": safe_int(s.get("duration")),
            "door_open": bool(s.get("door")),
            "room_temp": _safe_float(s.get("roomTemp")),
            "room_humidity": safe_int(s.get("roomHumidity")),
            "remaining_deg": remaining_deg,
        },
    )


def _build_washer_view(ha: dict, ctx: "RenderContext") -> ApplianceView:
    """extras: cycle_no:int, energy_kwh_month:float
    Time fields refer to the cycle's projected finish.
    """
    wsh = ha.get("washer") or {}
    finish_iso = wsh.get("remaining")
    finish_at = _localize(finish_iso, ctx)
    energy = _safe_float(wsh.get("energyMonth")) or 0.0
    return ApplianceView(
        kind="washer",
        eyebrow_kicker="Laundry \u00b7 Running",
        eyebrow_label="WASHER RUNNING",
        accent_kind="info",
        finish_at_local=finish_at,
        finish_label=_clock(finish_iso, ctx),
        remaining_label=_duration(finish_iso, ctx),
        relative_label=_relative(finish_iso, ctx),
        status_label=title_case(wsh.get("status")),
        extras={
            "cycle_no": safe_int(wsh.get("cycles")),
            "energy_kwh_month": energy / 1000.0,
        },
    )


def _build_washer_done_view(ha: dict, ctx: "RenderContext") -> ApplianceView:
    """Time fields refer to when the cycle completed."""
    wsh = ha.get("washer") or {}
    notif = wsh.get("lastNotification") or {}
    at_iso = notif.get("at")
    at_local = _localize(at_iso, ctx)
    return ApplianceView(
        kind="washer-done",
        eyebrow_kicker="Laundry \u00b7 Attention",
        eyebrow_label="WASHER DONE",
        accent_kind="alert",
        finish_at_local=at_local,
        finish_label=_clock(at_iso, ctx),
        remaining_label=_DASH,
        relative_label=_relative(at_iso, ctx),
        status_label="Move to dryer",
        extras={
            "cycle_no": safe_int(wsh.get("cycles")),
        },
    )


def _build_dishwasher_view(ha: dict, ctx: "RenderContext") -> ApplianceView:
    """extras: door_state:str ("closed" / "open" / ...)
    progress_pct populated when HA reports it.
    """
    dw = ha.get("dishwasher") or {}
    finish_iso = dw.get("finishTime")
    finish_at = _localize(finish_iso, ctx)
    prog_raw = dw.get("progress")
    prog_pct = None if prog_raw is None else safe_round(prog_raw)
    program = title_case(clean_program(dw.get("program") or ""))
    door = dw.get("door") or ""
    return ApplianceView(
        kind="dishwasher",
        eyebrow_kicker="Dishwasher \u00b7 Running",
        eyebrow_label="DISHWASHER",
        accent_kind="info",
        finish_at_local=finish_at,
        finish_label=_clock(finish_iso, ctx),
        remaining_label=_duration(finish_iso, ctx),
        relative_label=_relative(finish_iso, ctx),
        progress_pct=prog_pct,
        program_label=program,
        status_label="Running",
        extras={
            "door_state": door,
        },
    )


def _build_pool_view(ha: dict, ctx: "RenderContext") -> ApplianceView:
    """extras: air_temp:float?, freeze_protect:bool, pump_running:bool
    """
    pool = ha.get("pool") or {}
    return ApplianceView(
        kind="pool",
        eyebrow_kicker="Pool \u00b7 Heating",
        eyebrow_label="POOL HEATING",
        accent_kind="alert",
        current=_safe_float(pool.get("current")),
        target=_safe_float(pool.get("target")),
        status_label="Heating",
        extras={
            "air_temp": _safe_float(pool.get("air")),
            "freeze_protect": bool(pool.get("freezeProtect")),
            "pump_running": bool(pool.get("pumpRunning")),
        },
    )


_APPLIANCE_BUILDERS: dict[str, Any] = {
    "sauna":        _build_sauna_view,
    "washer":       _build_washer_view,
    "washer-done":  _build_washer_done_view,
    "dishwasher":   _build_dishwasher_view,
    "pool":         _build_pool_view,
}


def build_appliance_view(ha: dict, kind: str, *, ctx: "RenderContext") -> ApplianceView:
    """Dispatch to the per-kind builder. Unknown kinds get a minimal
    placeholder so a renderer never crashes on a future appliance that
    only one design knows how to draw."""
    builder = _APPLIANCE_BUILDERS.get(kind)
    if builder is None:
        return ApplianceView(
            kind=kind,
            eyebrow_kicker=kind.replace("-", " ").title(),
            eyebrow_label=kind.upper(),
            accent_kind="info",
        )
    return builder(ha, ctx)


def supported_appliance_kinds() -> list[str]:
    """Public list for the registry. Kept here so the registry doesn't
    duplicate the per-kind list."""
    return list(_APPLIANCE_BUILDERS.keys())
