"""Top-level entry point for the portrait "Day Ahead" e-ink renderer.

Sibling of ``render.py`` (the 800x480 HA dashboard dispatcher). Kept
separate so the landscape HA path's hard-coded ``CANVAS_SIZE = (800, 480)``
and ``{editorial, swiss}`` whitelist stay untouched -- this design is
portrait-native at 1200x1600 and Editorial-only.
"""
from __future__ import annotations

from typing import Optional

from PIL import Image

from .palette import get_palette

# E1004 13.3" Spectra-6 panel, portrait.
DAY_CANVAS = (1200, 1600)


def render_day_ahead_image(
    design: str,
    palette: str,
    day_shape: dict,
    *,
    tz_name: Optional[str] = None,
) -> Image.Image:
    """Render the Day Ahead screen to a 1200x1600 RGB Pillow image.

    `design`  : only 'editorial' is implemented (Swiss is a documented
                fallback in the spec but not shipped); anything else maps
                to editorial.
    `palette` : 'six' | 'bw'.
    `day_shape`: the dict from `day_client.assemble_day_shape`.
    `tz_name` : IANA timezone (passed through for any tz-aware formatting).
    """
    palette_name = (palette or "six").lower()
    if palette_name not in ("six", "bw"):
        palette_name = "six"
    P = get_palette("editorial", palette_name)
    img = Image.new("RGB", DAY_CANVAS, color=P.bg)

    from . import dayahead_editorial as d
    d.render_dashboard(img, day_shape or {}, P, tz_name=(tz_name or "UTC"))
    return img
