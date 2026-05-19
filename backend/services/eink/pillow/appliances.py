"""Appliance registry: which appliances exist + when they're "active".

Why this module exists
----------------------
The old ``active.py`` had three responsibilities tangled together:

1. Per-appliance HA-state predicates ("is the washer running?").
2. Severity ranking (which appliance leads the hero).
3. Hard-coded palette colours for every kind.

That meant adding a new appliance touched ``active.py`` *and*
``swiss.py`` *and* ``editorial.py`` -- and forgetting one was the
easiest way to ship the cooling-as-heating bug.

The new contract: each appliance is an ``ApplianceSpec`` row in the
``APPLIANCES`` list with:

* ``kind``       -- string used as the lookup key everywhere.
* ``severity``   -- 1..3, lower leads the hero. Same scheme as before.
* ``accent_kind``-- semantic colour name resolved by ``RenderContext``.
* ``is_active``  -- ``(ha, now_utc) -> bool``.
* ``build_view`` -- ``(ha, ctx) -> ApplianceView``; supplied by
  ``ha_view.build_appliance_view``.

Adding an appliance
-------------------
1. Add fields to ``ha_client.shape_ha_state`` so the raw HA payload
   is shaped into the dict your view builder will read.
2. Write ``_build_<kind>_view`` in ``ha_view.py`` and register it in
   ``_APPLIANCE_BUILDERS``.
3. Add an ``ApplianceSpec`` row below.
4. Add a drawer entry in each design's ``DRAWERS`` dict
   (``swiss.SWISS_DRAWERS`` / ``editorial.EDITORIAL_DRAWERS``).

That's it -- the registry handles "active" detection and dispatch
for both designs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, List, Optional

from .ha_view import (
    ApplianceView,
    build_appliance_view,
    supported_appliance_kinds,
)
from .helpers import parse_iso
from .render_ctx import AccentKind, RenderContext


__all__ = [
    "ApplianceSpec",
    "ActiveAppliance",
    "APPLIANCES",
    "pick_active",
    "build_view_for_kind",
]


_RUNNING_WASHER_STATES_EXCLUDED = {
    "power_off",
    "end",
    "initial",
    "unavailable",
    "unknown",
    None,
    "",
}

_DW_ACTIVE_STATES = {"run", "delayedstart", "pause", "actionrequired", "finished"}


# ── Per-appliance "is active" predicates ───────────────────────────────


def _sauna_active(ha: dict, now: datetime) -> bool:
    s = ha.get("sauna") or {}
    heaters = s.get("heaters") or 0
    return s.get("mode") == "heat" or (isinstance(heaters, (int, float)) and heaters > 0)


def _washer_active(ha: dict, now: datetime) -> bool:
    w = ha.get("washer") or {}
    return (w.get("status") not in _RUNNING_WASHER_STATES_EXCLUDED)


def _washer_done_active(ha: dict, now: datetime) -> bool:
    """The washer is "done" for up to 1h after the completion
    notification, while the washer is still powered on.

    Dismissal signals (any one drops the card):
      * The washer is running again (`_washer_active`).
      * The user powered the washer off -- we have no door sensor, so
        `switch.washer_power` flipping to off is our proxy for "door
        was opened and laundry was unloaded".
      * The dryer was touched in any way (`_dryer_engaged`): running,
        powered on, freshly-on in `initial`, or with a programmed
        `remaining` time. `_dryer_active` alone misses the "user just
        pressed the dryer power button" case.
      * 1 hour has passed since the completion notification. The old
        6h window left the card stuck on screen long after the user
        had clearly moved on.
    """
    if _washer_active(ha, now):
        return False
    if _dryer_engaged(ha, now):
        return False
    wsh = ha.get("washer") or {}
    if not wsh.get("powerOn"):
        return False
    notif = wsh.get("lastNotification") or {}
    if notif.get("type") != "washing_is_complete":
        return False
    at = parse_iso(notif.get("at"))
    if at is None:
        return False
    age_hrs = (now - at).total_seconds() / 3600
    return 0 <= age_hrs < 1


def _dryer_active(ha: dict, now: datetime) -> bool:
    """Same status-enum vocabulary as the washer; `cooling` and
    `wrinkle_care` count as ACTIVE so the running card stays up through
    the post-cycle anti-wrinkle phase (the door's still locked then)."""
    d = ha.get("dryer") or {}
    return (d.get("status") not in _RUNNING_WASHER_STATES_EXCLUDED)


def _dryer_engaged(ha: dict, now: datetime) -> bool:
    """Broader 'user is touching the dryer' signal, used only to
    dismiss the washer-done card.

    `_dryer_active` stays narrow because it also drives the "DRYER
    RUNNING" hero -- we don't want that card to appear just because
    someone pressed power. But for *dismissing* washer-done, any of
    these counts:

      * dryer is running / cooling / wrinkle_care / pause (the
        existing `_dryer_active` check).
      * `switch.dryer_power` is on -- user pressed the power button.
      * status is `initial` -- powered on, awaiting a cycle pick.
      * `remaining` time is set -- a cycle has been programmed.
    """
    if _dryer_active(ha, now):
        return True
    d = ha.get("dryer") or {}
    if d.get("powerOn"):
        return True
    if (d.get("status") or "").lower() == "initial":
        return True
    if d.get("remaining"):
        return True
    return False


def _dryer_done_active(ha: dict, now: datetime) -> bool:
    """The dryer is "done" until the user powers it off (or 6h cap).

    LG dryers stay powered on through `cooling` / `wrinkle_care`, so
    `switch.dryer_power=off` only flips when the user hits the button
    -- a clean "I unloaded it" proxy. The active-dryer predicate above
    takes precedence; this only surfaces when the dryer isn't running.
    """
    if _dryer_active(ha, now):
        return False
    d = ha.get("dryer") or {}
    if not d.get("powerOn"):
        return False
    notif = d.get("lastNotification") or {}
    if notif.get("type") != "drying_is_complete":
        return False
    at = parse_iso(notif.get("at"))
    if at is None:
        return False
    age_hrs = (now - at).total_seconds() / 3600
    return 0 <= age_hrs < 6


def _dishwasher_active(ha: dict, now: datetime) -> bool:
    return ((ha.get("dishwasher") or {}).get("state")) in _DW_ACTIVE_STATES


def _dishwasher_severity(ha: dict) -> int:
    """Promote dishwasher to severity 1 when it needs human attention."""
    if ((ha.get("dishwasher") or {}).get("state")) == "actionrequired":
        return 1
    return 3


def _pool_active(ha: dict, now: datetime) -> bool:
    return bool((ha.get("pool") or {}).get("heating"))


# ── Registry ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ApplianceSpec:
    """Static metadata for one appliance kind.

    The view builder is wrapped from ``ha_view.build_appliance_view``
    so swapping a builder is a one-line change here, not a fan-out.
    """

    kind: str
    severity: int                           # 1..3, lower leads the hero
    accent_kind: AccentKind
    is_active: Callable[[dict, datetime], bool]
    severity_for: Optional[Callable[[dict], int]] = None  # dynamic override

    def build_view(self, ha: dict, ctx: RenderContext) -> ApplianceView:
        return build_appliance_view(ha, self.kind, ctx=ctx)

    def effective_severity(self, ha: dict) -> int:
        if self.severity_for is not None:
            return self.severity_for(ha)
        return self.severity


# Order is irrelevant for behaviour (we sort by severity); kept in the
# ordering most readers expect.
APPLIANCES: List[ApplianceSpec] = [
    ApplianceSpec("sauna",       1, "alert", _sauna_active),
    ApplianceSpec("washer",      2, "info",  _washer_active),
    ApplianceSpec("washer-done", 1, "alert", _washer_done_active),
    ApplianceSpec("dryer",       2, "info",  _dryer_active),
    ApplianceSpec("dryer-done",  1, "alert", _dryer_done_active),
    ApplianceSpec("dishwasher",  3, "info",  _dishwasher_active,
                  severity_for=_dishwasher_severity),
    ApplianceSpec("pool",        3, "alert", _pool_active),
]


# Sanity check: every spec must have a matching view builder. Caught
# at import time so a half-registered appliance can't ship.
_missing_views = [s.kind for s in APPLIANCES if s.kind not in supported_appliance_kinds()]
if _missing_views:                                                        # pragma: no cover
    raise RuntimeError(
        "Appliance specs without a ha_view builder: "
        f"{_missing_views}. Add a _build_<kind>_view to ha_view.py."
    )


# ── Active-list selection ──────────────────────────────────────────────


@dataclass(frozen=True)
class ActiveAppliance:
    """One row of the "what's currently demanding attention" list.

    Carries both the spec (for severity / drawer dispatch) and the
    pre-built view (so renderers don't rebuild it once per cell).
    """

    spec: ApplianceSpec
    view: ApplianceView

    @property
    def kind(self) -> str:
        return self.spec.kind

    @property
    def accent_kind(self) -> AccentKind:
        return self.view.accent_kind or self.spec.accent_kind

    @property
    def severity(self) -> int:
        return self.spec.effective_severity({})  # caller already filtered


def pick_active(ha: dict, ctx: RenderContext) -> List[ActiveAppliance]:
    """Return the currently-active appliances, hero first.

    Replaces the old ``active.pick_active``. Each entry carries the
    pre-built ``ApplianceView`` so drawers don't have to rebuild it.
    """
    if not ha:
        return []
    out: List[ActiveAppliance] = []
    for spec in APPLIANCES:
        try:
            if not spec.is_active(ha, ctx.now_utc):
                continue
        except Exception:                                                 # pragma: no cover
            continue
        view = spec.build_view(ha, ctx)
        out.append(ActiveAppliance(spec=spec, view=view))
    out.sort(key=lambda a: a.spec.effective_severity(ha))
    return out


def build_view_for_kind(ha: dict, kind: str, ctx: RenderContext) -> ApplianceView:
    """Convenience: build a view by kind without going through the
    active list. Useful for designs that have a non-active panel for
    a specific appliance (e.g. the right-rail pool mini in editorial)."""
    return build_appliance_view(ha, kind, ctx=ctx)
