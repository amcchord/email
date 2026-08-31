"""Top-level entry point for the portrait "Day Ahead" e-ink renderer.

Sibling of ``render.py`` (the 800x480 HA dashboard dispatcher). The shared
registry owns canvas geometry and exact content/design dispatch; this entry
point retains the portrait-specific public API.
"""
from __future__ import annotations

from typing import Optional

from PIL import Image

from .palette import get_palette
from .registry import get_design_renderer

def render_day_ahead_image(
    design: str,
    palette: str,
    day_shape: dict,
    *,
    tz_name: Optional[str] = None,
) -> Image.Image:
    """Render the Day Ahead screen to a 1200x1600 RGB Pillow image.

    `design`  : exact registered design key (currently 'editorial').
    `palette` : exact registered palette key ('six' | 'bw').
    `day_shape`: the dict from `day_client.assemble_day_shape`.
    `tz_name` : IANA timezone (passed through for any tz-aware formatting).
    """
    renderer = get_design_renderer("day_ahead", design)
    palette_name = (palette or "").strip().lower()
    P = get_palette(renderer.design_key, palette_name)
    img = Image.new("RGB", renderer.canvas_size, color=P.bg)
    renderer.render(img, day_shape or {}, P, tz_name=(tz_name or "UTC"))
    return img
