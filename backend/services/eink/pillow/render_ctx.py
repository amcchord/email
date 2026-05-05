"""Rendering context shared across designs.

Why this module exists
----------------------
Every renderer needs four pieces of ambient state: the user's IANA
timezone, the "now" timestamp (UTC + localized), the active palette,
and a way to map a *semantic* accent (heat / cool / alert / ...) to a
concrete RGB tuple from the palette.

Without a single context object these get re-threaded as positional
args through every helper, which is exactly how the appliance-clock
TZ bug shipped in the first place: somebody added an `_hero_*` helper
and forgot to pass `zone` four call sites later.

Layer rules
-----------
* The renderer entry point (``swiss.render_dashboard``,
  ``editorial.render_dashboard``) builds **one** ``RenderContext`` and
  passes it to everything below it. New ambient parameters are added
  to ``RenderContext`` -- they never become an extra positional arg on
  ``_draw_*`` helpers.
* Drawers ask ``ctx.accent("heat")`` instead of reading ``P.red``
  directly. This keeps the colour mapping in one place so a future
  palette/design can re-skin without grepping every renderer.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Literal, Optional
from zoneinfo import ZoneInfo

from .helpers import parse_iso, resolve_zone
from .palette import RGB, Palette


# Semantic colour names. Renderers use these instead of palette colours
# directly so the palette layer can re-map without touching renderers.
AccentKind = Literal[
    "heat",   # active heating signal (red)
    "cool",   # active cooling signal (blue)
    "alert",  # demands attention (red)
    "info",   # neutral info (blue)
    "ok",     # all-clear (green)
    "idle",   # nothing happening (muted)
    "muted",  # de-emphasised text/rules
    "ink",    # default text
    "warn",   # soft warning (yellow if available)
]


_AccentResolver = Callable[[Palette], RGB]


# Map semantic kinds to palette accessors. Keep this list small and
# exhaustive so adding a new kind requires touching this single dict.
_ACCENTS: dict[str, _AccentResolver] = {
    "heat":  lambda p: p.red,
    "cool":  lambda p: p.blue,
    "alert": lambda p: p.red,
    "info":  lambda p: p.blue,
    "ok":    lambda p: p.green,
    "idle":  lambda p: p.muted,
    "muted": lambda p: p.muted,
    "ink":   lambda p: p.ink,
    "warn":  lambda p: p.yellow,
}


@dataclass(frozen=True)
class RenderContext:
    """Ambient state needed by every renderer call."""

    now_utc: datetime
    now_local: datetime
    zone: ZoneInfo
    palette: Palette

    def accent(self, kind: AccentKind) -> RGB:
        """Resolve a semantic accent kind to the palette's RGB tuple."""
        resolver = _ACCENTS.get(kind, _ACCENTS["ink"])
        return resolver(self.palette)


def build_render_context(
    ha: Optional[dict],
    palette: Palette,
    *,
    tz_name: Optional[str] = None,
) -> RenderContext:
    """Build a RenderContext from the same inputs every renderer
    already takes (`ha` shape + palette + tz_name).

    The "now" timestamp is taken from ``ha["fetchedAt"]`` when present
    so cached renders are deterministic, falling back to wall-clock
    UTC. The result is always tz-aware on both attributes.
    """
    zone = resolve_zone(tz_name)
    now_utc = parse_iso((ha or {}).get("fetchedAt")) or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    now_local = now_utc.astimezone(zone)
    return RenderContext(now_utc=now_utc, now_local=now_local, zone=zone, palette=palette)
