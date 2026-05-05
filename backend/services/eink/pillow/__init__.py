"""Pillow e-ink dashboard renderer.

Draws the Editorial and Swiss designs from `docs/design/HANDOFF.md` directly
onto a 800x480 RGB Pillow image -- no HTML, no Chromium, no screenshotting.
The result goes straight into the BMP encoders in
`backend/services/terminal/bmp.py` with `dither=False`.

Exports:
    render_eink_image(design, palette, ha_shape, *, tz_name) -> PIL.Image.Image
"""
from .render import render_eink_image

__all__ = ["render_eink_image"]
