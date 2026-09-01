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

from .palette import get_palette
from .registry import get_design_renderer

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


def render_eink_image(
    design: str,
    palette: str,
    ha_shape: Optional[dict],
    *,
    tz_name: Optional[str] = None,
    use_cache: bool = True,
) -> Image.Image:
    """Render the chosen design to a 800x480 RGB Pillow image.

    `design`  : exact registered design key ('editorial' | 'swiss')
    `palette` : exact registered palette key ('six' | 'bw')
    `ha_shape`: HAShape dict; None falls through to the calm/quiet state.
    `tz_name` : IANA timezone for the clock in the masthead/header.
    """
    renderer = get_design_renderer(
        "eink_dashboard",
        design,
        profile_key="landscape_16_9",
    )
    design = renderer.design_key
    palette_name = (palette or "").strip().lower()
    P = get_palette(design, palette_name)
    tz = (tz_name or "UTC").strip() or "UTC"

    key = (design, palette_name, tz, _ha_hash(ha_shape))
    if use_cache:
        cached = _cache_get(key)
        if cached is not None:
            return cached

    img = Image.new("RGB", renderer.canvas_size, color=P.bg)
    renderer.render(img, ha_shape or {}, P, tz_name=tz)

    if use_cache:
        _cache_put(key, img)
    return img
