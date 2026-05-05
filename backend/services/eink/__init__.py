"""E-ink dashboard renderer (Editorial / Swiss designs at 800x480).

Pulls live Home Assistant state, navigates a headless Chromium to the static
React bundle in `static/`, snapshots the 800x480 viewport, and hands the PNG
back to the existing `terminal/` BMP encoders.
"""
