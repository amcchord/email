"""Playful, phase-aware copy for appliance leads + idle-state fallback.

Why this module exists
----------------------
The original lead copy was a fixed pattern -- the washer always said
"<Status>, then spin." which read as "Rinse, then spin." when in the
rinse phase (technically correct, but never any variation). This module
introduces:

* Friendlier status verbs (``rinse`` -> "Rinsing", ``wrinkle_care`` ->
  "Wrinkle care", ...).
* A pool of headline/deck variants per appliance phase. Each cycle shuffles
  its pool, then walks it every ``ROTATION_MINUTES``, so a long phase keeps
  changing and nothing repeats until the pool has been through.
* A curated, computed-fact fallback for the idle "Calm Edition" body
  used when the AI-generated hourly snippet hasn't been produced yet
  (e.g. before the first cron tick, or when no Claude key is set).

Determinism contract
--------------------
``pick_appliance_copy`` MUST return the same variant for the same
``(kind, phase, cycle_seed, rotation slot)`` across processes -- otherwise
the washer headline would shuffle every render bucket and the panel would
churn. We use ``hashlib.sha1`` instead of Python's built-in ``hash()``
which is salted per-interpreter.

Every variant must be true whenever it can be picked: copy may joke, but it
states only what the appliance reports.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Sequence, TYPE_CHECKING, TypeVar

from .helpers import title_case

if TYPE_CHECKING:
    from .ha_view import ApplianceView
    from .render_ctx import RenderContext


_T = TypeVar("_T")

# How often an appliance's or the calm card's copy moves on.
ROTATION_MINUTES = 20
_CALM_ROTATION_MINUTES = 60

__all__ = [
    "WASHER_PHASE_LABELS",
    "DRYER_PHASE_LABELS",
    "DISHWASHER_PROGRESS_PHASES",
    "ROTATION_MINUTES",
    "pick_appliance_copy",
    "sauna_forecast_copy",
    "pool_copy",
    "done_copy",
    "calm_copy",
    "laundry_station",
    "fallback_idle_snippet",
    "FALLBACK_QUOTES",
]


# ── Friendlier status labels ──────────────────────────────────────────
#
# Raw HA washer/dryer status enums come straight out of the LG ThinQ
# integration. The codes are accurate but a bit terse; we want the
# headline noun/verb to read like a magazine, not a state machine.

# The LG ThinQ integration reports washer phases as gerunds
# (``"washing"``, ``"rinsing"``, ``"spinning"``) on some firmwares and as
# nouns (``"wash"``, ``"rinse"``, ``"spin"``) on others. Both spellings
# alias to the same friendly label here so a firmware update can't
# silently drop us back to the bare-default copy.
WASHER_PHASE_LABELS: dict[str, str] = {
    "running": "Washing",
    "wash": "Washing",
    "washing": "Washing",
    "rinse": "Rinsing",
    "rinsing": "Rinsing",
    "spin": "Spinning",
    "spinning": "Spinning",
    "soak": "Soaking",
    "soaking": "Soaking",
    "prewash": "Pre-wash",
    "pre_wash": "Pre-wash",
    "prewashing": "Pre-wash",
    "drain": "Draining",
    "draining": "Draining",
    "rinse_and_spin": "Rinse + spin",
    "rinse_spin": "Rinse + spin",
    "rinsing_and_spinning": "Rinse + spin",
    "detecting": "Sizing up",
    "detergent_amount": "Dosing",
    "weight_sensing": "Weighing",
    "refresh": "Refreshing",
    "refreshing": "Refreshing",
    "tub_clean": "Tub clean",
    "tub_cleaning": "Tub clean",
    "end": "Wrapping up",
    "off": "Off",
    "power_off": "Off",
    "standby": "Standby",
    "initial": "Standing by",
    "pause": "Paused",
    "paused": "Paused",
    "error": "Needs a look",
}


DRYER_PHASE_LABELS: dict[str, str] = {
    "running": "Tumbling",
    "drying": "Drying",
    "dry": "Drying",
    "cooling": "Cooling",
    "cool": "Cooling",
    "wrinkle_care": "Wrinkle care",
    "wrinkle_caring": "Wrinkle care",
    "pause": "Paused",
    "paused": "Paused",
    "end": "Wrapping up",
    "off": "Off",
    "power_off": "Off",
    "standby": "Standby",
    "initial": "Standing by",
    "error": "Needs a look",
}


def friendly_washer_status(raw: Optional[str]) -> str:
    """Map a raw HA washer status to a friendly title-cased label.

    Falls back to ``title_case`` (replaces underscores with spaces) for
    any status the integration starts reporting that we haven't yet
    catalogued.
    """
    if not raw:
        return ""
    key = str(raw).strip().lower()
    mapped = WASHER_PHASE_LABELS.get(key)
    if mapped is not None:
        return mapped
    return title_case(raw)


def friendly_dryer_status(raw: Optional[str]) -> str:
    """Map a raw HA dryer status to a friendly title-cased label."""
    if not raw:
        return ""
    key = str(raw).strip().lower()
    mapped = DRYER_PHASE_LABELS.get(key)
    if mapped is not None:
        return mapped
    return title_case(raw)


# ── Variant pools ──────────────────────────────────────────────────────
#
# Each variant is a 3-tuple: (head_pre, head_italic, deck_template).
#
# * ``head_pre``      renders in the upright hero font.
# * ``head_italic``   renders in the italic-bold hero font; can be empty.
# * ``deck_template`` is a Python ``str.format`` template that consumes
#   the view's pre-localised time strings (``finish``, ``remaining``,
#   ``relative``) plus ``cycle_no`` for laundry. Unused placeholders are
#   tolerated by ``_safe_format`` so a deck can ignore fields it doesn't
#   care about.
#
# A variant with ``when`` set only runs in those parts of the day.


@dataclass(frozen=True)
class _Variant:
    head_pre: str
    head_italic: str
    deck: str
    when: tuple[str, ...] = ()


# Default copy is intentionally bare: no filler adverb in the italic
# tail, no "with patience" / "patiently" style copy. The default only
# shows when the live HA status doesn't match any catalogued phase, so
# it should feel neutral rather than personality-filled.
_WASHER_DEFAULT: _Variant = _Variant(
    head_pre="Washer at work",
    head_italic="",
    deck="Cycle #{cycle_no}, finishing around {finish}.",
)

# Editorial rule for these tables: the italic tail should *add
# information* (the object of the verb, the next step, a positional
# beat in the cycle) -- never a hollow adverb like ", patiently." or
# ", briefly." or ", really.". If you can't write a tail that adds
# something, leave it empty so the headline just terminates on the
# upright clause.

_WASHER_VARIANTS_RAW: dict[str, list[_Variant]] = {
    "wash": [
        _Variant("Sudsing up", " the load.", "Cycle #{cycle_no}, headed for the rinse."),
        _Variant("Washing in earnest.", "", "Cycle #{cycle_no} · finishes around {finish}."),
        _Variant("The drum is", " earning its keep.", "Wash cycle #{cycle_no}; done by {finish}."),
        _Variant("Developing story:", " clothes getting cleaner.", "More by {finish}."),
        _Variant("Round and round", " it goes.", "It stops around {finish}. {remaining} to go."),
        _Variant("{weekday} laundry,", " well underway.", "Load #{cycle_no} on this machine."),
        _Variant("Agitation,", " the good kind.", "Cycle #{cycle_no} · rinse is next."),
        _Variant("The suds", " have the floor.", "{remaining} left · {kwh} kWh this month."),
        _Variant("Filed from the drum:", " all going well.", "Next dispatch at {finish}."),
        _Variant("Hard at work on", " the load.", "No need to check on it until {finish}."),
        _Variant("A {daypart} wash,", " in full swing.", "Done by {finish}, {remaining} from now."),
        _Variant("Up with the laundry.", "", "Cycle #{cycle_no} · out by {finish}.",
                 when=("morning",)),
        _Variant("The night shift", " is washing.", "Out by {finish}, if you're still up.",
                 when=("late-night",)),
    ],
    "prewash": [
        _Variant("Pre-wash first,", " then the real wash.", "Cycle #{cycle_no} · main wash follows."),
        _Variant("Loosening the day", " off the fabric.", "Pre-wash phase · done by {finish}."),
        _Variant("Warming up", " for the main wash.", "{remaining} in all · done by {finish}."),
    ],
    "soak": [
        _Variant("Letting it soak.", "", "Cycle #{cycle_no} · a slow start."),
        _Variant("Steeping the fabric", " in the drum.", "Soak phase · wash to follow."),
        _Variant("Pre-soak, slow soak.", "", "Cycle #{cycle_no} · done by {finish}."),
        _Variant("Long soak,", " short memory.", "Yesterday's stains, leaving by {finish}."),
    ],
    "rinse": [
        _Variant("Chasing out", " the suds.", "Rinse cycle in progress · done by {finish}."),
        _Variant("Rinsing off", " the day.", "Cycle #{cycle_no} · spin comes next."),
        _Variant("Out, suds, out.", "", "Rinsing the load · {remaining} left."),
        _Variant("Clean water,", " fresh start.", "Rinse phase · wraps around {finish}."),
        _Variant("Second rinse?", " The washer knows.", "It's on the job until about {finish}."),
        _Variant("The suds", " are leaving town.", "Spin follows · {remaining} to go."),
        _Variant("Corrections:", " the suds were wrong.", "Rinse under way · finished by {finish}."),
        _Variant("Halfway clean", " is not an option.", "Cycle #{cycle_no} · {remaining} left."),
    ],
    "rinse_and_spin": [
        _Variant("Rinse and spin", " — the home stretch.", "Cycle #{cycle_no} · done by {finish}."),
        _Variant("Almost done,", " almost dry.", "Rinse + spin · {remaining} remaining."),
        _Variant("Last water,", " then the whirl.", "Out by {finish}."),
    ],
    "spin": [
        _Variant("Spinning it dry.", "", "Final spin · finishes {finish}."),
        _Variant("Wringing it out.", "", "Spin cycle · cycle #{cycle_no} · {remaining} left."),
        _Variant("The closing act:", " centrifuge.", "Spinning · unload soon."),
        _Variant("The drum is dancing", " toward done.", "Spin phase · done by {finish}."),
        _Variant("Now at", " full tilt.", "Hold on to the walls · {remaining} left."),
        _Variant("Late edition:", " the spin is on.", "Done by {finish}. Dryer next."),
        _Variant("Gravity,", " temporarily overruled.", "Spinning · {remaining} to go."),
        _Variant("Last dance", " for the drum.", "Have the dryer ready by {finish}."),
    ],
    "drain": [
        _Variant("Draining away", " the wash water.", "Cycle #{cycle_no} · finishes around {finish}."),
        _Variant("Out with the water,", " in with the spin.", "Drain phase · {remaining} left."),
        _Variant("Down the drain,", " on purpose.", "Done by {finish}."),
    ],
    "refresh": [
        _Variant("A quick refresh.", "", "Refresh cycle · done by {finish}."),
        _Variant("A freshen-up", " for the load.", "Refresh phase · {remaining} remaining."),
        _Variant("A second wind", " for the wardrobe.", "Refresh · out by {finish}."),
    ],
    "tub_clean": [
        _Variant("Cleaning the cleaner.", "", "Tub-clean cycle in progress."),
        _Variant("The washer washes", " itself.", "Tub clean · done by {finish}."),
        _Variant("Self-care,", " for a washer.", "Tub clean · {remaining} left."),
    ],
    "detecting": [
        _Variant("Sizing up the load.", "", "Cycle #{cycle_no} · starts shortly."),
        _Variant("Weighing in,", " deciding doses.", "Detecting load · wash to follow."),
        _Variant("First, the weigh-in.", "", "Estimate so far: done by {finish}."),
    ],
    "end": [
        _Variant("Wrapping it up.", "", "Cycle #{cycle_no} · finishing at {finish}."),
        _Variant("Final moments", " of the cycle.", "End phase · unload soon."),
        _Variant("Almost ready", " to unload.", "Cycle #{cycle_no} · done at {finish}."),
    ],
    "pause": [
        _Variant("Paused", " mid-cycle.", "Cycle #{cycle_no} · waiting on a tap."),
        _Variant("Holding the load.", "", "Pause phase · resume to finish."),
        _Variant("Stop the presses,", " and the drum.", "Paused · resume to finish."),
    ],
}


def _alias_variants(
    table: dict[str, list[_Variant]],
    aliases: dict[str, str],
) -> dict[str, list[_Variant]]:
    """Materialise alias keys so a phase like ``"rinsing"`` picks up the
    ``"rinse"`` variant list. Keeping the alias map separate from the
    raw table means a maintainer only has to write the copy once."""
    out = dict(table)
    for src, dst in aliases.items():
        if dst in table and src not in out:
            out[src] = table[dst]
    return out


# Gerund / noun aliases so this module isn't fragile to ThinQ firmware
# tense changes.
_WASHER_PHASE_ALIASES: dict[str, str] = {
    # What the LG washer in this house actually reports for its main phase.
    "running": "wash",
    "washing": "wash",
    "rinsing": "rinse",
    "spinning": "spin",
    "soaking": "soak",
    "draining": "drain",
    "prewashing": "prewash",
    "pre_wash": "prewash",
    "rinsing_and_spinning": "rinse_and_spin",
    "rinse_spin": "rinse_and_spin",
    "refreshing": "refresh",
    "tub_cleaning": "tub_clean",
    "paused": "pause",
}


WASHER_VARIANTS: dict[str, list[_Variant]] = _alias_variants(
    _WASHER_VARIANTS_RAW, _WASHER_PHASE_ALIASES,
)


_DRYER_DEFAULT: _Variant = _Variant(
    head_pre="Dryer running.",
    head_italic="",
    deck="Finishing around {finish}.",
)

_DRYER_VARIANTS_RAW: dict[str, list[_Variant]] = {
    "running": [
        _Variant("Tumbling things dry.", "", "Finishes around {finish} · {remaining} to go."),
        _Variant("Heat, air, motion", " — the trio at work.", "Dryer running · done by {finish}."),
        _Variant("The drum is at it.", "", "Drying in progress · {remaining} remaining."),
        _Variant("Drying the laundry,", " then fold.", "Finishes around {finish}."),
        _Variant("Damp today,", " dry by {finish}.", "That's the whole forecast. {remaining} left."),
        _Variant("Weather report:", " warm in the drum.", "Clearing by {finish}."),
        _Variant("{weekday} laundry", " in the warm stretch.", "{remaining} left · out by {finish}."),
        _Variant("Socks on", " the move.", "Odd numbers not guaranteed · done by {finish}."),
        _Variant("Warm and", " getting warmer.", "Fold-ready by {finish}."),
        _Variant("A {daypart} tumble,", " for the load.", "{remaining} to go."),
        _Variant("The night shift", " is drying.", "Warm laundry by {finish}.", when=("late-night",)),
    ],
    "cooling": [
        _Variant("Cooling the drum", " — easing off the heat.", "Last of the heat · wraps {finish}."),
        _Variant("Letting it settle,", " warm and still.", "Cooling phase · unload soon."),
        _Variant("The heat steps back", " for the cool-down.", "Cooling down · {remaining} left."),
        _Variant("Heat's off;", " the tumble isn't.", "Cooling · done by {finish}."),
        _Variant("Clearing skies", " in the drum.", "Cooling · {remaining} to go."),
    ],
    "wrinkle_care": [
        _Variant("Wrinkle patrol,", " still on duty.", "Tumbling to keep the folds away."),
        _Variant("Smoothing things over", " — literally.", "Wrinkle-care phase · finishes {finish}."),
        _Variant("Anti-wrinkle watch", " continues.", "Wrinkle care · {remaining} left."),
        _Variant("Keeping creases", " at bay.", "Still tumbling \u00b7 done by {finish}."),
        _Variant("Dry, and on guard", " against wrinkles.", "Wrinkle care \u00b7 {remaining} left."),
    ],
    "pause": [
        _Variant("Paused mid-tumble.", "", "Resume to keep drying."),
        _Variant("Holding the heat,", " waiting on you.", "Pause phase · a tap will resume."),
        _Variant("Stop the tumble.", "", "Paused · resume to finish."),
    ],
    "end": [
        _Variant("Drum done,", " folding next.", "Cycle finished at {finish} · {relative}."),
        _Variant("Finished drying,", " ready to unload.", "Done at {finish}."),
    ],
}


_DRYER_PHASE_ALIASES: dict[str, str] = {
    "drying": "running",
    "dry": "running",
    "cool": "cooling",
    "wrinkle_caring": "wrinkle_care",
    "paused": "pause",
}


DRYER_VARIANTS: dict[str, list[_Variant]] = _alias_variants(
    _DRYER_VARIANTS_RAW, _DRYER_PHASE_ALIASES,
)


# Dishwasher progress buckets. Combined with the program name (eyebrow)
# this gives variety without lying about what HA actually reports.
DISHWASHER_PROGRESS_PHASES: dict[str, str] = {
    "starting": "starting",
    "early": "early",
    "mid": "mid",
    "late": "late",
    "finishing": "finishing",
}


def _dishwasher_progress_bucket(progress_pct: Optional[int]) -> str:
    if progress_pct is None:
        return "starting"
    if progress_pct < 10:
        return "starting"
    if progress_pct < 35:
        return "early"
    if progress_pct < 65:
        return "mid"
    if progress_pct < 90:
        return "late"
    return "finishing"


_DISHWASHER_DEFAULT: _Variant = _Variant(
    head_pre="Dishes underway.",
    head_italic="",
    deck="Finishing {relative} ({finish}).",
)

# The dishwasher reports a percentage rather than a phase, so this copy describes
# how far along it is and leaves what it's doing right now to the imagination.
DISHWASHER_VARIANTS: dict[str, list[_Variant]] = {
    "starting": [
        _Variant("{program} cycle", " just began.", "Settling in · finishes {relative}."),
        _Variant("A fresh load", " of dishes.", "{program} cycle · done by {finish}."),
        _Variant("Dishes in,", " door shut.", "{program} · finishing {relative}."),
        _Variant("And they're off:", " the plates.", "{program} · clean by {finish}."),
        _Variant("Dinner's", " last chapter begins.", "{program} · finishing around {finish}.",
                 when=("evening", "late-night")),
    ],
    "early": [
        _Variant("{program}", " in motion.", "Underway · finishes {relative}."),
        _Variant("Plates and water,", " in conversation.", "{program} · {progress}% along."),
        _Variant("Early innings", " for the dishes.", "{progress}% done · done by {finish}."),
        _Variant("The stack", " is under review.", "{program} cycle · finishes at {finish}."),
        _Variant("Off to a clean", " start.", "{progress}% through {program}."),
    ],
    "mid": [
        _Variant("The middle act", " of {program}.", "{progress}% complete · done by {finish}."),
        _Variant("Steady scrubbing,", " unseen.", "{program} cycle · finishes {relative}."),
        _Variant("Around halfway", " through the dishes.", "{program} · {progress}% · done by {finish}."),
        _Variant("Past the first", " few plates, probably.", "{progress}% · {remaining} left."),
        _Variant("Mid-cycle report:", " no complaints.", "{program} · clean by {finish}."),
    ],
    "late": [
        _Variant("Final stretch", " for the dishes.", "{program} · {progress}% · done by {finish}."),
        _Variant("Nearly through", " the stack.", "{program} cycle · finishes {relative}."),
        _Variant("The last lap", " of {program}.", "{progress}% complete · wraps at {finish}."),
        _Variant("Clean is", " within sight.", "{progress}% · {remaining} left."),
    ],
    "finishing": [
        _Variant("Moments from", " done.", "{program} · {progress}% · unload soon."),
        _Variant("Clear the counter:", " dishes inbound.", "{program} · finishes by {finish}."),
        _Variant("Last few minutes", " of {program}.", "{progress}% · out by {finish}."),
        _Variant("Hot plates", " very soon.", "Mind the steam · done by {finish}."),
    ],
}


# ── Deterministic variant picker ──────────────────────────────────────


def _stable_index(seed: str, n: int) -> int:
    """Stable, cross-process index in ``[0, n)`` for ``seed``.

    Python's built-in ``hash()`` is salted per-interpreter (see PEP 456)
    so two backend processes would pick different variants on the same
    cycle. ``sha1`` gives us a portable answer.
    """
    if n <= 1:
        return 0
    digest = hashlib.sha1(seed.encode("utf-8")).digest()
    val = int.from_bytes(digest[:8], "big", signed=False)
    return val % n


def _daypart(now: datetime) -> str:
    hour = now.hour
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "late-night"


def _rotation_slot(now: datetime, minutes: int = ROTATION_MINUTES) -> int:
    return int(now.timestamp() // (minutes * 60))


def _rotate(variants: Sequence[_T], seed: str, slot: int) -> _T:
    """The ``slot``-th item of a shuffle of ``variants`` that is fixed by ``seed``.

    Walking a shuffle rather than hashing each slot means nothing repeats until the
    whole pool has run, and two adjacent slots can never show the same line.
    """
    order = sorted(
        range(len(variants)),
        key=lambda i: hashlib.sha1(f"{seed}|{i}".encode("utf-8")).digest(),
    )
    return variants[order[slot % len(order)]]


def _seed_for_view(view: "ApplianceView", phase: str) -> str:
    """Pick the most stable identifier the view exposes for this cycle.

    Washer: ``cycle_no`` increments on every cycle, so it gives a fresh
    seed per cycle while staying stable mid-cycle.

    Dryer/Dishwasher: HA doesn't expose a cycle counter for these, but
    the projected finish ISO is stable across the cycle and varies
    between cycles, which makes it a good proxy. Falls back to the raw
    status if neither is available.
    """
    kind = view.kind
    if kind == "washer":
        cycle_no = view.extras.get("cycle_no")
        if cycle_no is not None:
            return f"washer|{phase}|{cycle_no}"
        return f"washer|{phase}|{view.finish_label}"
    if kind == "dryer":
        finish = view.finish_label or "no-finish"
        return f"dryer|{phase}|{finish}"
    if kind == "dishwasher":
        finish = view.finish_label or "no-finish"
        return f"dishwasher|{phase}|{finish}"
    return f"{kind}|{phase}"


def _safe_format(template: str, fields: dict[str, Any]) -> str:
    """``str.format`` that tolerates missing keys.

    A deck template may reference ``{finish}``/``{relative}``/``{remaining}``
    even when the view didn't populate all of them; we'd rather emit
    the dash placeholder than blow up the renderer.
    """
    class _Defaulting(dict):
        def __missing__(self, key: str) -> str:
            return "\u2014"

    try:
        return template.format_map(_Defaulting(fields))
    except (IndexError, KeyError, ValueError):
        return template


def pick_appliance_copy(
    view: "ApplianceView",
    ctx: "RenderContext",
) -> dict[str, str]:
    """Return playful copy for an appliance lead.

    Returns a dict with keys ``head_pre``, ``head_italic``, ``deck``.
    Always returns valid strings (empty when irrelevant) so callers can
    feed them straight into the existing ``Run`` builders without
    additional None-checks.
    """
    kind = view.kind
    now = ctx.now_local
    daypart = _daypart(now)

    fields = {
        **_view_fields(view),
        "weekday": now.strftime("%A"),
        "daypart": daypart,
    }

    if kind == "washer":
        raw_phase = view.extras.get("phase") or "wash"
        phase_key = str(raw_phase).strip().lower()
        variants = WASHER_VARIANTS.get(phase_key)
        default = _WASHER_DEFAULT
    elif kind == "dryer":
        raw_phase = view.extras.get("phase") or "running"
        phase_key = str(raw_phase).strip().lower()
        variants = DRYER_VARIANTS.get(phase_key)
        default = _DRYER_DEFAULT
    elif kind == "dishwasher":
        phase_key = _dishwasher_progress_bucket(view.progress_pct)
        variants = DISHWASHER_VARIANTS.get(phase_key)
        default = _DISHWASHER_DEFAULT
    else:
        return {
            "head_pre": view.status_label or view.kind.replace("-", " ").title(),
            "head_italic": "",
            "deck": "",
        }

    pool = [v for v in variants or () if not v.when or daypart in v.when]
    if not pool:
        chosen = default
    else:
        chosen = _rotate(pool, _seed_for_view(view, phase_key), _rotation_slot(now))

    return {
        "head_pre": _safe_format(chosen.head_pre, fields),
        "head_italic": _safe_format(chosen.head_italic, fields),
        "deck": _safe_format(chosen.deck, fields),
    }


def _view_fields(view: "ApplianceView") -> dict[str, Any]:
    """Bag of substitution fields for ``str.format`` templates."""
    program = view.program_label or "The"
    cycle_no = view.extras.get("cycle_no")
    if cycle_no is None:
        cycle_no = 0
    progress = view.progress_pct
    if progress is None:
        progress = 0
    return {
        "finish": view.finish_label or "\u2014",
        "remaining": view.remaining_label or "\u2014",
        "relative": view.relative_label or "\u2014",
        "cycle_no": cycle_no,
        "kwh": f"{float(view.extras.get('energy_kwh_month') or 0.0):.1f}",
        "program": program,
        "progress": progress,
        "status": view.status_label or "",
    }


# ── Laundry phase tracks ───────────────────────────────────────────────


_WASHER_STATIONS: dict[str, int] = {
    "detecting": 0, "detergent_amount": 0, "weight_sensing": 0,
    "prewash": 0, "pre_wash": 0, "prewashing": 0, "soak": 0, "soaking": 0,
    "running": 0, "wash": 0, "washing": 0,
    "rinse": 1, "rinsing": 1, "rinse_and_spin": 1, "rinse_spin": 1, "rinsing_and_spinning": 1,
    "drain": 2, "draining": 2, "spin": 2, "spinning": 2,
}
_DRYER_STATIONS: dict[str, int] = {
    "running": 0, "drying": 0, "dry": 0,
    "cooling": 1, "cool": 1,
    "wrinkle_care": 2, "wrinkle_caring": 2,
}


def laundry_station(kind: str, phase: str, past: Sequence[str] = ()) -> Optional[int]:
    """Which station of the phase track a machine is at, or None if it can't be told.

    A pause or an unrecognized status sits at the last station the cycle's own history
    (``past``, oldest first) shows it reached, rather than claiming a place on the track.
    """
    table = _WASHER_STATIONS if kind == "washer" else _DRYER_STATIONS
    key = (phase or "").strip().lower()
    if key in table:
        return table[key]
    for status in reversed(past):
        if status in table:
            return table[status]
    return None


# ── Sauna, pool and finished-cycle copy ────────────────────────────────
#
# Every "ready" line must name the time: that's the fact the card is for. Copy that
# tells someone to do something (run the fan, unload) keeps saying so in every variant.

_SAUNA_HEADS = (
    ("Ready around ", "{ready}."), ("Hot by ", "{ready}."), ("Towels at ", "{ready}."),
    ("Sweat o'clock: ", "{ready}."), ("Pencil it in: ", "{ready}."),
    ("Sauna by ", "{ready}."), ("The heat arrives ", "{ready}."),
    ("Stones say ", "{ready}."),
)
_SAUNA_NEAR_HEADS = (
    ("Almost there: ", "{ready}."), ("Find a towel: ", "{ready}."),
    ("Nearly hot: ", "{ready}."), ("Water bottle time: ", "{ready}."),
)
_SAUNA_READY_HEADS = (
    ("The sauna is ", "ready."), ("Step right in: ", "it's ready."),
    ("Towel up: ", "it's ready."), ("Good and hot: ", "it's ready."),
    ("Get in. ", "It's ready."),
)
_SAUNA_DECKS = (
    "In {ready_in}. {status}",
    "Room at {room}, {to_go}° to go. {status}",
    "{ready_in} out. The stones are doing the hard part.",
    "{ready_in} to go. Start the water now; thank yourself later.",
    "In {ready_in}. Room at {room} and climbing.",
)
_SAUNA_READY_DECKS = (
    "Room reached {ready_f}° at {ready}. {status}",
    "Hit {ready_f}° at {ready}; holding at {room} now.",
    "At {room} now. It got here at {ready}. {status}",
)


def sauna_forecast_copy(view: "ApplianceView", forecast: dict, ctx: "RenderContext",
                        ready_f: int) -> tuple[str, str, str]:
    """Headline (upright, italic) and deck for a sauna with a heat-up forecast."""
    heaters = view.extras.get("heaters", 0)
    door = "open" if view.extras.get("door_open") else "closed"
    status = f"{heaters} of 3 elements on; door {door}."
    room = view.extras.get("room_temp")
    fields = {
        "ready": forecast["ready_label"] or "—",
        "ready_in": forecast["ready_in"],
        "ready_f": ready_f,
        "room": "—" if room is None else f"{round(room)}°",
        "to_go": "—" if room is None else max(0, round(ready_f - room)),
        "status": status,
    }
    now = ctx.now_local
    slot = _rotation_slot(now)
    seed = f"sauna|{now.strftime('%Y-%m-%d')}"
    if forecast["ready_reached"]:
        head = _rotate(_SAUNA_READY_HEADS, seed, slot)
        deck = _rotate(_SAUNA_READY_DECKS, seed, slot)
        return (_safe_format(head[0], fields), _safe_format(head[1], fields),
                _safe_format(deck, fields))
    if forecast["ready_label"] is None:
        return ("Won't reach ", f"{ready_f}°.", "The room levels off below it at this target.")
    minutes = forecast.get("ready_in_minutes")
    heads = _SAUNA_NEAR_HEADS if minutes is not None and minutes <= 15 else _SAUNA_HEADS
    head = _rotate(heads, seed, slot)
    pre, tail = _safe_format(head[0], fields), _safe_format(head[1], fields)
    if forecast["ends_before_ready"]:
        return (pre, tail, f"Session ends {forecast['ends_before_ready']}, before it's ready.")
    if forecast["fan_state"] == "running":
        return (pre, tail, f"In {forecast['ready_in']}. Evening out the room; "
                           f"fan has {forecast['fan_note']}.")
    if forecast["fan_state"] == "due" and forecast.get("fan_auto"):
        return (pre, tail, f"In {forecast['ready_in']}. The fan starts itself any minute.")
    if forecast["fan_state"] == "due":
        return (pre, tail, f"In {forecast['ready_in']}. Run the fan now, 10 min on Medium.")
    return (pre, tail, _safe_format(_rotate(_SAUNA_DECKS, seed, slot), fields))


_POOL_HEADS = (
    ("Climbing to ", "{target}."), ("Heading for ", "{target}."), ("On its way to ", "{target}."),
    ("Warming toward ", "{target}."), ("Swim-ready at ", "{target}."),
    ("Pool's goal: ", "{target}."),
)
_POOL_DECKS = (
    "Heat exchanger active, water now {water}. Air {air}. {freeze}",
    "Water {water}, with {to_go}° to go. Air {air}. {freeze}",
    "{to_go}° between the water and the goal. {freeze}",
    "Water {water}, air {air}. Patience is a heat exchanger. {freeze}",
)


def pool_copy(view: "ApplianceView", ctx: "RenderContext") -> tuple[str, str, str]:
    """Headline (upright, italic) and deck for a heating pool."""
    def temp(value: Any) -> str:
        return "—" if value is None else f"{round(value)}°"

    current, target = view.current, view.target
    fields = {
        "target": temp(target),
        "water": temp(current),
        "air": temp(view.extras.get("air_temp")),
        "to_go": "—" if current is None or target is None else max(0, round(target - current)),
        "freeze": ("Freeze guard armed." if view.extras.get("freeze_protect")
                   else "No freeze risk."),
    }
    now = ctx.now_local
    slot, seed = _rotation_slot(now), f"pool|{now.strftime('%Y-%m-%d')}"
    head = _rotate(_POOL_HEADS, seed, slot)
    return (_safe_format(head[0], fields), _safe_format(head[1], fields),
            _safe_format(_rotate(_POOL_DECKS, seed, slot), fields))


# Finished-cycle copy gets firmer as the load sits: (minutes since finishing, pool).
_WASHER_DONE: tuple[tuple[int, tuple[tuple[str, str], ...]], ...] = (
    (20, (("Wash complete.", " Move it to the dryer."),
          ("Clean and waiting.", " To the dryer with it."),
          ("That's a wrap.", " Now the dryer."),
          ("Stop the presses:", " dryer's next."))),
    (45, (("Still in the washer.", " Dryer, please."),
          ("The wet load waits.", " Move it to the dryer."),
          ("Clean clothes, idle.", " Over to the dryer."))),
    (10**6, (("Getting musty?", " Move it to the dryer."),
             ("A damp reminder:", " the dryer's right there."),
             ("Second notice:", " move the wet load."))),
)
_DRYER_DONE: tuple[tuple[int, tuple[tuple[str, str], ...]], ...] = (
    (30, (("Drying complete.", " Please unload the dryer."),
          ("Warm and ready.", " Fold while it lasts."),
          ("Fresh out of heat.", " Time to unload."),
          ("All dry.", " Unload the dryer."))),
    (120, (("Cooling in the drum.", " Unload the dryer."),
           ("Wrinkles are forming.", " Unload the dryer."),
           ("The load still waits.", " Time to fold."))),
    (10**6, (("It's been a while.", " Unload the dryer."),
             ("Second notice:", " unload the dryer."),
             ("Long since dry.", " Please fold it."))),
)
_WASHER_DONE_DECKS = (
    "Cycle #{cycle_no} finished {finish} · {relative}.",
    "Finished {finish}. The dryer awaits.",
    "Load #{cycle_no}, clean as of {finish}.",
)
_DRYER_DONE_DECKS = (
    "Finished {finish} · {relative}.",
    "Done since {finish}. Drum's done its work.",
    "Dry as of {finish}, {relative}.",
)


def done_copy(view: "ApplianceView", ctx: "RenderContext") -> dict[str, str]:
    """Copy for a finished washer or dryer. The instruction stands in every variant."""
    now = ctx.now_local
    finished = view.finish_at_local
    waited = (now - finished).total_seconds() / 60 if finished else 0
    tiers = _WASHER_DONE if view.kind == "washer-done" else _DRYER_DONE
    decks = _WASHER_DONE_DECKS if view.kind == "washer-done" else _DRYER_DONE_DECKS
    pool = next(pool for limit, pool in tiers if waited < limit)
    seed = f"{view.kind}|{view.finish_label}"
    slot = _rotation_slot(now)
    pre, italic = _rotate(pool, seed, slot)
    return {
        "head_pre": pre,
        "head_italic": italic,
        "deck": _safe_format(_rotate(decks, seed, slot), _view_fields(view)),
    }


# ── Calm edition ───────────────────────────────────────────────────────


# The calm card can show while a pool heats its last degree, or after a finished load
# has aged off the front page, so most lines claim nothing about what's running.
_CALM_HEADS = (
    ("All quiet on the ", "home front."), ("Nothing to report. ", "Enjoy it."),
    ("No news ", "is good news."), ("The house is ", "at rest."),
    ("Slow news ", "day at home."), ("Silence ", "from the appliances."),
    ("All clear ", "on the front page."),
)
_CALM_MORNING_HEADS = (("A quiet start ", "to the day."),)
_CALM_EVENING_HEADS = (("A quiet evening ", "in the house."), ("Good evening. ", "All's quiet."))
_CALM_NIGHT_HEADS = (("A quiet night ", "in the house."), ("All's quiet. ", "Goodnight."))
_CALM_DECKS = (
    "Nothing on the front page needs you.",
    "No appliance news to report.",
    "The front page is all yours.",
    "This space reserved for the next load of laundry.",
)
# Only while nothing is heating.
_CALM_IDLE_HEADS = (
    ("Every machine ", "is off duty."), ("The machines ", "have turned in."),
)
_CALM_IDLE_DECKS = ("Nothing running, nothing demanding.",)


def calm_copy(ctx: "RenderContext", ha: dict) -> dict[str, str]:
    """Kicker, headline and deck for the calm card; the edition follows the clock."""
    now = ctx.now_local
    daypart = _daypart(now)
    edition = {"morning": "MORNING", "afternoon": "AFTERNOON", "evening": "EVENING",
               "late-night": "LATE"}[daypart]
    heads = list(_CALM_HEADS)
    heads += {"morning": _CALM_MORNING_HEADS, "evening": _CALM_EVENING_HEADS,
              "late-night": _CALM_NIGHT_HEADS}.get(daypart, ())
    decks = list(_CALM_DECKS)
    pool = ha.get("pool") or {}
    if not pool.get("heating"):
        heads += _CALM_IDLE_HEADS
        decks += _CALM_IDLE_DECKS
    cups = (ha.get("coffee") or {}).get("cupsToday")
    if isinstance(cups, (int, float)) and cups > 0:
        decks.append(f"{int(cups)} cup{'s' if cups != 1 else ''} of coffee so far. "
                     "Otherwise, nothing to report.")
    kw = (ha.get("solar") or {}).get("currentKw")
    if isinstance(kw, (int, float)) and kw >= 1:
        decks.append(f"The roof is making {kw:.1f} kW. Nothing's using it for chores.")
    water = pool.get("current")
    if isinstance(water, (int, float)) and not pool.get("heating"):
        decks.append(f"The pool sits at {round(water)}°, with nothing to do.")
    slot = _rotation_slot(now, _CALM_ROTATION_MINUTES)
    seed = f"calm|{now.strftime('%Y-%m')}"
    head_pre, head_italic = _rotate(heads, seed, slot)
    return {
        "kicker": f"THE {edition} EDITION",
        "head_pre": head_pre,
        "head_italic": head_italic,
        "deck": _rotate(decks, seed, slot),
    }


# ── Fallback idle snippet (no DB / no AI) ──────────────────────────────
#
# Used when the dashboard renders the calm state but the per-hour AI
# snippet hasn't landed yet (cron hasn't ticked, Claude key missing,
# DB unreachable). The pool mixes literary observations with one-line
# computed facts so the panel still shows something with hourly variety.


FALLBACK_QUOTES: list[dict[str, str]] = [
    {"text": "The ordinary acts we practice every day at home are of more importance to the soul than their simplicity might suggest.", "byline": "Thomas Moore"},
    {"text": "A house is made of walls and beams; a home is built with love and dreams.", "byline": "Ralph Waldo Emerson"},
    {"text": "There is nothing more truly artistic than to love people.", "byline": "Vincent van Gogh"},
    {"text": "The art of being happy lies in the power of extracting happiness from common things.", "byline": "Henry Ward Beecher"},
    {"text": "There is no place more delightful than one's own fireplace.", "byline": "Cicero"},
    {"text": "Cleaning your house while your kids are still growing up is like shoveling the walk before it stops snowing.", "byline": "Phyllis Diller"},
    {"text": "Where thou art \u2014 that \u2014 is Home.", "byline": "Emily Dickinson"},
    {"text": "Sometimes the most productive thing you can do is relax.", "byline": "Mark Black"},
    {"text": "We shape our buildings; thereafter they shape us.", "byline": "Winston Churchill"},
    {"text": "The best way to find out if you can trust somebody is to trust them.", "byline": "Ernest Hemingway"},
    {"text": "Tea is a religion of the art of life.", "byline": "Kakuz\u014d Okakura"},
    {"text": "Nature does not hurry, yet everything is accomplished.", "byline": "Lao Tzu"},
    {"text": "A clean house is the sign of a misspent life.", "byline": "Anonymous"},
    {"text": "The longer I live, the more beautiful life becomes.", "byline": "Frank Lloyd Wright"},
    {"text": "Domesticity is not a feminine virtue \u2014 it is a human one.", "byline": "Jane O'Reilly"},
    {"text": "The most wasted of all days is one without laughter.", "byline": "E. E. Cummings"},
    {"text": "He is happiest, be he king or peasant, who finds peace in his home.", "byline": "Johann Wolfgang von Goethe"},
    {"text": "Quiet is peace. Tranquility. Quiet is turning down the volume knob on life.", "byline": "Khaled Hosseini"},
    {"text": "There must be quite a few things a hot bath won't cure, but I don't know many of them.", "byline": "Sylvia Plath"},
    {"text": "Have nothing in your house that you do not know to be useful or believe to be beautiful.", "byline": "William Morris"},
    {"text": "Adopt the pace of nature: her secret is patience.", "byline": "Ralph Waldo Emerson"},
    {"text": "Almost everything will work again if you unplug it for a few minutes, including you.", "byline": "Anne Lamott"},
    {"text": "What you do every day matters more than what you do once in a while.", "byline": "Gretchen Rubin"},
    {"text": "The most precious things in life are not those you get for money.", "byline": "Albert Einstein"},
    {"text": "An empty hour is a kindness you give yourself.", "byline": "Anonymous"},
    {"text": "Silence is a source of great strength.", "byline": "Lao Tzu"},
    {"text": "Coffee first. Schemes later.", "byline": "Leanna Renee Hieber"},
    {"text": "A house must be built on solid foundations if it is to last.", "byline": "Sai Baba"},
    {"text": "Be yourself; everyone else is already taken.", "byline": "Oscar Wilde"},
    {"text": "The world is full of magic things, patiently waiting for our senses to grow sharper.", "byline": "W. B. Yeats"},
    {"text": "Even a stopped clock is right twice a day.", "byline": "Marie von Ebner-Eschenbach"},
    {"text": "All happy families resemble one another; each unhappy family is unhappy in its own way.", "byline": "Leo Tolstoy"},
]


_SEASONS = (
    ("Winter", 12, 21),
    ("Spring", 3, 20),
    ("Summer", 6, 21),
    ("Autumn", 9, 22),
    ("Winter", 12, 21),
)


def _season_of(dt: datetime) -> str:
    """Northern-hemisphere meteorological-ish season for ``dt`` (local).

    Boundaries are approximate solstice/equinox dates. Good enough for a
    one-liner like "Spring \u00b7 day 64".
    """
    m = dt.month
    d = dt.day
    if (m == 3 and d >= 20) or m in (4, 5) or (m == 6 and d < 21):
        return "Spring"
    if (m == 6 and d >= 21) or m in (7, 8) or (m == 9 and d < 22):
        return "Summer"
    if (m == 9 and d >= 22) or m in (10, 11) or (m == 12 and d < 21):
        return "Autumn"
    return "Winter"


def _day_of_season(dt: datetime) -> int:
    """1-indexed day-of-season for ``dt`` (local). Approximate."""
    season = _season_of(dt)
    year = dt.year
    if season == "Spring":
        start = datetime(year, 3, 20, tzinfo=dt.tzinfo)
    elif season == "Summer":
        start = datetime(year, 6, 21, tzinfo=dt.tzinfo)
    elif season == "Autumn":
        start = datetime(year, 9, 22, tzinfo=dt.tzinfo)
    else:
        # Winter spans the year boundary.
        if dt.month >= 12:
            start = datetime(year, 12, 21, tzinfo=dt.tzinfo)
        else:
            start = datetime(year - 1, 12, 21, tzinfo=dt.tzinfo)
    return (dt.date() - start.date()).days + 1


def _moon_phase(dt: datetime) -> str:
    """Coarse moon phase label using the canonical 29.530589-day cycle.

    Good enough for a small body line; the user gets variety, not
    astronomical accuracy.
    """
    # Reference: known new moon on 2000-01-06 18:14 UTC.
    ref = datetime(2000, 1, 6, 18, 14, tzinfo=dt.tzinfo)
    days = (dt - ref).total_seconds() / 86400.0
    period = 29.530588853
    phase = (days % period) / period
    if phase < 0.03 or phase > 0.97:
        return "New Moon"
    if phase < 0.22:
        return "Waxing Crescent"
    if phase < 0.28:
        return "First Quarter"
    if phase < 0.47:
        return "Waxing Gibbous"
    if phase < 0.53:
        return "Full Moon"
    if phase < 0.72:
        return "Waning Gibbous"
    if phase < 0.78:
        return "Last Quarter"
    return "Waning Crescent"


def _computed_facts(now_local: datetime) -> list[dict[str, str]]:
    """Compute a small set of contextually-true observations about the day.

    Returned dicts share the ``{"text", "byline"}`` shape with
    ``FALLBACK_QUOTES`` so the picker can union the two pools without
    a separate code path.
    """
    year = now_local.year
    doy = now_local.timetuple().tm_yday
    days_in_year = 366
    if not (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
        days_in_year = 365
    remaining = days_in_year - doy
    season = _season_of(now_local)
    day_of_season = _day_of_season(now_local)
    moon = _moon_phase(now_local)
    weekday = now_local.strftime("%A")
    month_name = now_local.strftime("%B")
    week_no = now_local.isocalendar().week

    return [
        {
            "text": f"Day {doy} of {year}. {remaining} days remain on the calendar.",
            "byline": "by the numbers",
        },
        {
            "text": f"{season} \u00b7 day {day_of_season}. The light is exactly as long as it is.",
            "byline": "by the seasons",
        },
        {
            "text": f"Tonight: {moon}. The sky keeps a steadier schedule than we do.",
            "byline": "by the moon",
        },
        {
            "text": f"It is {weekday}, in the {_ordinal(week_no)} week of the year.",
            "byline": "by the week",
        },
        {
            "text": f"A {month_name} {_ordinal(now_local.day)}. Take it as it comes.",
            "byline": "by the date",
        },
    ]


def _ordinal(n: int) -> str:
    """English ordinal suffix: 1 -> '1st', 22 -> '22nd', ..."""
    if 10 <= (n % 100) <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def fallback_idle_snippet(ctx: "RenderContext") -> dict[str, str]:
    """Deterministic hourly-rotating snippet for the calm lead.

    Picks from the union of ``FALLBACK_QUOTES`` (literary) and
    ``_computed_facts`` (contextual) so the panel cycles through both
    flavours over the day. Returns ``{"kind", "text", "byline"}`` to
    match the AI-generated payload shape.
    """
    now = ctx.now_local
    pool: list[dict[str, str]] = []
    for q in FALLBACK_QUOTES:
        pool.append({"kind": "quote", "text": q["text"], "byline": q.get("byline", "")})
    for f in _computed_facts(now):
        pool.append({"kind": "observation", "text": f["text"], "byline": f.get("byline", "")})

    seed = f"{now.strftime('%Y-%m-%d')}|{now.hour}"
    idx = _stable_index(seed, len(pool))
    return pool[idx]
