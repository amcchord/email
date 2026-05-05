"""Top-level dispatcher for the Pillow e-ink renderer.

Caches recent (design, palette, tz, ha-hash) renders in-process -- the
device polls every ~60s and multiple BMP variants may request within the
same bucket, so caching saves ~10-30 ms of redundant Pillow work. The
cache invalidates on any HA shape change.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Optional, Tuple

from PIL import Image

from .palette import Palette, get_palette
from .helpers import resolve_zone

logger = logging.getLogger(__name__)


# ── TTL cache ──────────────────────────────────────────────────────────

_CACHE_MAX_AGE_SEC = 60.0
_CACHE_MAX_ENTRIES = 32

_cache: "dict[Tuple[str, str, str, str], Tuple[bytes, float, Tuple[int, int]]]" = {}


def _ha_hash(ha: Optional[dict]) -> str:
    if ha is None:
        return "none"
    copy = {k: v for k, v in ha.items() if k != "fetchedAt"}
    blob = json.dumps(copy, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def _cache_get(key) -> Optional[Image.Image]:
    entry = _cache.get(key)
    if not entry:
        return None
    raw, expires_at, size = entry
    if expires_at < time.time():
        _cache.pop(key, None)
        return None
    return Image.frombytes("RGB", size, raw)


def _cache_put(key, img: Image.Image) -> None:
    if len(_cache) >= _CACHE_MAX_ENTRIES:
        oldest = min(_cache.items(), key=lambda kv: kv[1][1])[0]
        _cache.pop(oldest, None)
    _cache[key] = (img.tobytes(), time.time() + _CACHE_MAX_AGE_SEC, img.size)


# ── Main entrypoint ────────────────────────────────────────────────────


CANVAS_SIZE = (800, 480)


def render_eink_image(
    design: str,
    palette: str,
    ha_shape: Optional[dict],
    *,
    tz_name: Optional[str] = None,
    use_cache: bool = True,
) -> Image.Image:
    """Render the chosen design to a 800x480 RGB Pillow image.

    `design`  : 'editorial' | 'swiss' (unknown -> editorial)
    `palette` : 'six' | 'bw' (unknown -> six)
    `ha_shape`: HAShape dict; None falls through to the calm/quiet state.
    `tz_name` : IANA timezone for the clock in the masthead/header.
    """
    design = (design or "editorial").lower()
    if design not in ("editorial", "swiss"):
        design = "editorial"
    palette_name = (palette or "six").lower()
    if palette_name not in ("six", "bw"):
        palette_name = "six"
    tz = (tz_name or "UTC").strip() or "UTC"

    key = (design, palette_name, tz, _ha_hash(ha_shape))
    if use_cache:
        cached = _cache_get(key)
        if cached is not None:
            return cached

    P = get_palette(design, palette_name)
    img = Image.new("RGB", CANVAS_SIZE, color=P.bg)

    if design == "swiss":
        from . import swiss
        swiss.render_dashboard(img, ha_shape or {}, P, tz_name=tz)
    else:
        from . import editorial
        editorial.render_dashboard(img, ha_shape or {}, P, tz_name=tz)

    if use_cache:
        _cache_put(key, img)
    return img
