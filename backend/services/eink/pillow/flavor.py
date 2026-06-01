"""Playful, phase-aware copy for appliance leads + idle-state fallback.

Why this module exists
----------------------
The original lead copy was a fixed pattern -- the washer always said
"<Status>, then spin." which read as "Rinse, then spin." when in the
rinse phase (technically correct, but never any variation). This module
introduces:

* Friendlier status verbs (``rinse`` -> "Rinsing", ``wrinkle_care`` ->
  "Wrinkle care", ...).
* A small pool of playful headline/deck variants per appliance phase,
  picked deterministically so the panel doesn't flicker between
  renders but a new cycle reliably picks a fresh variant.
* A curated, computed-fact fallback for the idle "Calm Edition" body
  used when the AI-generated hourly snippet hasn't been produced yet
  (e.g. before the first cron tick, or when no Claude key is set).

Determinism contract
--------------------
``pick_appliance_copy`` MUST return the same variant for the same
``(kind, phase, cycle_seed)`` tuple across processes -- otherwise the
washer headline would shuffle every render bucket and the panel would
churn. We use ``hashlib.sha1`` instead of Python's built-in ``hash()``
which is salted per-interpreter.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, TYPE_CHECKING

from .helpers import title_case

if TYPE_CHECKING:
    from .ha_view import ApplianceView
    from .render_ctx import RenderContext


__all__ = [
    "WASHER_PHASE_LABELS",
    "DRYER_PHASE_LABELS",
    "DISHWASHER_PROGRESS_PHASES",
    "pick_appliance_copy",
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
# The lists are small on purpose: 3-4 variants per phase is plenty for
# perceived variety without making it impossible to maintain copy
# coherence with the rest of the design.


@dataclass(frozen=True)
class _Variant:
    head_pre: str
    head_italic: str
    deck: str


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
        _Variant(
            head_pre="Sudsing up",
            head_italic=" the load.",
            deck="Cycle #{cycle_no}, headed for the rinse.",
        ),
        _Variant(
            head_pre="Washing in earnest.",
            head_italic="",
            deck="Cycle #{cycle_no} \u00b7 finishes around {finish}.",
        ),
        _Variant(
            head_pre="Soaking the soiled.",
            head_italic="",
            deck="Cycle #{cycle_no}, {remaining} left to go.",
        ),
        _Variant(
            head_pre="The drum is",
            head_italic=" earning its keep.",
            deck="Wash cycle #{cycle_no}; done by {finish}.",
        ),
    ],
    "prewash": [
        _Variant(
            head_pre="Pre-wash first",
            head_italic=", then the real wash.",
            deck="Cycle #{cycle_no} \u00b7 main wash follows.",
        ),
        _Variant(
            head_pre="Loosening the day",
            head_italic=" off the fabric.",
            deck="Pre-wash phase \u00b7 done by {finish}.",
        ),
    ],
    "soak": [
        _Variant(
            head_pre="Letting it soak.",
            head_italic="",
            deck="Cycle #{cycle_no} \u00b7 a slow start.",
        ),
        _Variant(
            head_pre="Steeping the fabric",
            head_italic=" in warm water.",
            deck="Soak phase \u00b7 wash to follow.",
        ),
        _Variant(
            head_pre="Pre-soak, slow soak.",
            head_italic="",
            deck="Cycle #{cycle_no} \u00b7 done by {finish}.",
        ),
    ],
    "rinse": [
        _Variant(
            head_pre="Chasing out",
            head_italic=" the suds.",
            deck="Rinse cycle in progress \u00b7 done by {finish}.",
        ),
        _Variant(
            head_pre="Rinsing off",
            head_italic=" the day.",
            deck="Cycle #{cycle_no} \u00b7 spin comes next.",
        ),
        _Variant(
            head_pre="Out, suds, out.",
            head_italic="",
            deck="Rinsing the load \u00b7 {remaining} left.",
        ),
        _Variant(
            head_pre="Clean water,",
            head_italic=" fresh start.",
            deck="Rinse phase \u00b7 wraps around {finish}.",
        ),
    ],
    "rinse_and_spin": [
        _Variant(
            head_pre="Rinse and spin",
            head_italic=" \u2014 the home stretch.",
            deck="Cycle #{cycle_no} \u00b7 done by {finish}.",
        ),
        _Variant(
            head_pre="Almost done,",
            head_italic=" almost dry.",
            deck="Rinse + spin \u00b7 {remaining} remaining.",
        ),
    ],
    "spin": [
        _Variant(
            head_pre="Spinning it dry.",
            head_italic="",
            deck="Final spin \u00b7 finishes {finish}.",
        ),
        _Variant(
            head_pre="Wringing it out.",
            head_italic="",
            deck="Spin cycle \u00b7 cycle #{cycle_no} \u00b7 {remaining} left.",
        ),
        _Variant(
            head_pre="The closing act:",
            head_italic=" centrifuge.",
            deck="Spinning \u00b7 unload soon.",
        ),
        _Variant(
            head_pre="The drum is dancing",
            head_italic=" toward done.",
            deck="Spin phase \u00b7 done by {finish}.",
        ),
    ],
    "drain": [
        _Variant(
            head_pre="Draining away",
            head_italic=" the wash water.",
            deck="Cycle #{cycle_no} \u00b7 finishes around {finish}.",
        ),
        _Variant(
            head_pre="Out with the water,",
            head_italic=" in with the spin.",
            deck="Drain phase \u00b7 {remaining} left.",
        ),
    ],
    "refresh": [
        _Variant(
            head_pre="A quick refresh.",
            head_italic="",
            deck="Refresh cycle \u00b7 done by {finish}.",
        ),
        _Variant(
            head_pre="A freshen-up",
            head_italic=" for the load.",
            deck="Refresh phase \u00b7 {remaining} remaining.",
        ),
    ],
    "tub_clean": [
        _Variant(
            head_pre="Cleaning the cleaner.",
            head_italic="",
            deck="Tub-clean cycle in progress.",
        ),
        _Variant(
            head_pre="The washer washes",
            head_italic=" itself.",
            deck="Tub clean \u00b7 done by {finish}.",
        ),
    ],
    "detecting": [
        _Variant(
            head_pre="Sizing up the load.",
            head_italic="",
            deck="Cycle #{cycle_no} \u00b7 starts shortly.",
        ),
        _Variant(
            head_pre="Weighing in,",
            head_italic=" deciding doses.",
            deck="Detecting load \u00b7 wash to follow.",
        ),
    ],
    "end": [
        _Variant(
            head_pre="Wrapping it up.",
            head_italic="",
            deck="Cycle #{cycle_no} \u00b7 finishing at {finish}.",
        ),
        _Variant(
            head_pre="Final moments",
            head_italic=" of the cycle.",
            deck="End phase \u00b7 unload soon.",
        ),
        _Variant(
            head_pre="Almost ready",
            head_italic=" to unload.",
            deck="Cycle #{cycle_no} \u00b7 done at {finish}.",
        ),
    ],
    "pause": [
        _Variant(
            head_pre="Paused",
            head_italic=" mid-cycle.",
            deck="Cycle #{cycle_no} \u00b7 waiting on a tap.",
        ),
        _Variant(
            head_pre="Holding the load.",
            head_italic="",
            deck="Pause phase \u00b7 resume to finish.",
        ),
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
        _Variant(
            head_pre="Tumbling things dry.",
            head_italic="",
            deck="Finishes around {finish} \u00b7 {remaining} to go.",
        ),
        _Variant(
            head_pre="Heat, air, motion",
            head_italic=" \u2014 the trio at work.",
            deck="Dryer running \u00b7 done by {finish}.",
        ),
        _Variant(
            head_pre="The drum is at it.",
            head_italic="",
            deck="Drying in progress \u00b7 {remaining} remaining.",
        ),
        _Variant(
            head_pre="Drying the laundry,",
            head_italic=" then fold.",
            deck="Finishes around {finish}.",
        ),
    ],
    "cooling": [
        _Variant(
            head_pre="Cooling the drum",
            head_italic=" \u2014 easing off the heat.",
            deck="Last of the heat \u00b7 wraps {finish}.",
        ),
        _Variant(
            head_pre="Letting it settle,",
            head_italic=" warm and still.",
            deck="Cooling phase \u00b7 unload soon.",
        ),
        _Variant(
            head_pre="The heat steps back",
            head_italic=" for the cool-down.",
            deck="Cooling down \u00b7 {remaining} left.",
        ),
    ],
    "wrinkle_care": [
        _Variant(
            head_pre="Wrinkle patrol,",
            head_italic=" still on duty.",
            deck="Tumbling to keep the folds away.",
        ),
        _Variant(
            head_pre="Smoothing things over",
            head_italic=" \u2014 literally.",
            deck="Wrinkle-care phase \u00b7 finishes {finish}.",
        ),
        _Variant(
            head_pre="Anti-wrinkle watch",
            head_italic=" continues.",
            deck="Wrinkle care \u00b7 {remaining} left.",
        ),
    ],
    "pause": [
        _Variant(
            head_pre="Paused mid-tumble.",
            head_italic="",
            deck="Resume to keep drying.",
        ),
        _Variant(
            head_pre="Holding the heat,",
            head_italic=" waiting on you.",
            deck="Pause phase \u00b7 a tap will resume.",
        ),
    ],
    "end": [
        _Variant(
            head_pre="Drum done,",
            head_italic=" folding next.",
            deck="Cycle finished at {finish} \u00b7 {relative}.",
        ),
        _Variant(
            head_pre="Finished drying,",
            head_italic=" ready to unload.",
            deck="Done at {finish}.",
        ),
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
    head_pre="Dishes underway",
    head_italic=", patiently.",
    deck="Finishing {relative} ({finish}).",
)

DISHWASHER_VARIANTS: dict[str, list[_Variant]] = {
    "starting": [
        _Variant(
            head_pre="{program} cycle",
            head_italic=" just began.",
            deck="Settling in \u00b7 finishes {relative}.",
        ),
        _Variant(
            head_pre="A fresh load",
            head_italic=" of dishes.",
            deck="{program} cycle \u00b7 done by {finish}.",
        ),
        _Variant(
            head_pre="Water on, dishes in",
            head_italic=".",
            deck="{program} \u00b7 finishing {relative}.",
        ),
    ],
    "early": [
        _Variant(
            head_pre="{program}",
            head_italic=" in motion.",
            deck="Underway \u00b7 finishes {relative}.",
        ),
        _Variant(
            head_pre="Soaping the stack",
            head_italic=", warming up.",
            deck="{program} cycle \u00b7 finishes at {finish}.",
        ),
        _Variant(
            head_pre="Plates and water",
            head_italic=", in conversation.",
            deck="{program} \u00b7 {progress}% along.",
        ),
    ],
    "mid": [
        _Variant(
            head_pre="Halfway through",
            head_italic=" the dishes.",
            deck="{program} \u00b7 {progress}% \u00b7 done by {finish}.",
        ),
        _Variant(
            head_pre="Steady scrubbing",
            head_italic=", unseen.",
            deck="{program} cycle \u00b7 finishes {relative}.",
        ),
        _Variant(
            head_pre="The middle act",
            head_italic=" of {program}.",
            deck="{progress}% complete \u00b7 done by {finish}.",
        ),
    ],
    "late": [
        _Variant(
            head_pre="Final scrub",
            head_italic=", almost there.",
            deck="{program} \u00b7 {progress}% \u00b7 done by {finish}.",
        ),
        _Variant(
            head_pre="Rinsing the racks",
            head_italic=", nearly done.",
            deck="{program} cycle \u00b7 finishes {relative}.",
        ),
        _Variant(
            head_pre="The last lap",
            head_italic=" of {program}.",
            deck="{progress}% complete \u00b7 wraps at {finish}.",
        ),
    ],
    "finishing": [
        _Variant(
            head_pre="Drying the dishes",
            head_italic=", the last task.",
            deck="{program} \u00b7 {progress}% \u00b7 unload soon.",
        ),
        _Variant(
            head_pre="Final dry",
            head_italic=" in progress.",
            deck="{program} \u00b7 finishes by {finish}.",
        ),
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
    del ctx  # currently unused; reserved so future copy can read tz/time

    kind = view.kind

    fields = _view_fields(view)

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

    if not variants:
        chosen = default
    else:
        seed = _seed_for_view(view, phase_key)
        idx = _stable_index(seed, len(variants))
        chosen = variants[idx]

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
        "program": program,
        "progress": progress,
        "status": view.status_label or "",
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
