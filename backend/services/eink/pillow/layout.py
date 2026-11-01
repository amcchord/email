"""Canonical page-layout tables for the Pillow e-ink renderer.

All layout decisions for both designs live here. Each named `Box` maps
directly to a region the components draw into, so `render_dashboard`
never allocates a coordinate tuple itself. Type-size constants are
co-located so re-theming is a one-line edit.

Geometry contract:
  - 800 x 480 canvas, integer pixels, inclusive-top / exclusive-bottom.
  - Sibling boxes must not overlap (checked in `_verify()`).
  - Rules are boxes too: a 1-px hairline is `Box(x0, y, x1, y+1)`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple

from .draw import Box


CANVAS_W, CANVAS_H = 800, 480


# ── Base ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PageLayout:
    canvas: Box
    gutter_x: int
    masthead: Box
    body: Box
    colophon: Box


# ── Editorial ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EditorialLayout(PageLayout):
    # Masthead subdivisions (pin + content band + thick + gap + hair).
    masthead_pin_rule: Box
    masthead_content: Box
    masthead_thick_rule: Box
    masthead_hair_rule: Box

    # Three-column masthead grid: time / wordmark / weather.
    masthead_col_time: Box
    masthead_col_wm: Box
    masthead_col_weather: Box

    # Body columns (160 | flex | 168 per HANDOFF Sec 10).
    body_left_rail: Box
    body_lead: Box
    body_right_rail: Box

    # Rule lines that separate the three body columns (1-px hairlines).
    body_left_rule: Box
    body_right_rule: Box


class EditorialType:
    """Masthead / body type sizes in px. Chosen in concert with the
    70 px masthead budget + Source Serif 4's real ascent/descent.

    The display row (time / wordmark / temp) sits on a single baseline
    derived from the content-band top + ascent, so all three glyphs land
    identically. Labels sit one descent + `_MASTHEAD_LABEL_GAP` below
    that baseline.
    """
    # Display row (time / temp / wordmark) -- dropped from 50 to 40 per
    # the layout-system refactor so the 70 px masthead fits comfortably.
    TIME_PX = 40
    TEMP_PX = 40
    AMPM_PX = 14

    # Wordmark sits on the same display baseline; 34 px lands as the
    # dominant masthead element opposite the 40-px display digits next
    # to it, matching the JSX editorial.jsx intent (fontSize: 32 with
    # +letterSpacing rather than a pixel-tight match).
    WORDMARK_PX = 34
    WORDMARK_TRACKING_EM = 0.06

    # Cherry-Small labels (date, weather label) -- 9 px native bitmap.
    # Wider date tracking gives the label row air under the wordmark
    # so it reads as the edition stamp rather than a sub-title.
    LABEL_PX = 9
    DATE_TRACKING_EM = 0.26
    WEATHER_LABEL_TRACKING_EM = 0.18

    # Weather glyph size in the masthead.
    WEATHER_GLYPH_PX = 34

    # Spacing constants used when deriving the label baseline from the
    # display baseline (baseline + descent + gap + label_ascent).
    MASTHEAD_LABEL_GAP_PX = 3

    # Kicker / rail / colophon sizes (unchanged; still 10-px Cherry).
    KICKER_PX = 10
    KICKER_TRACKING_EM = 0.22
    RAIL_LABEL_PX = 13
    RAIL_VALUE_PX = 16
    COLOPHON_PX = 10

    # Auto-fit candidate lists -- largest first; the helper picks the
    # biggest size that fits the column. The smallest entry must always
    # fit so the renderer never silently overflows.
    TIME_CANDIDATES = (40, 36, 32, 28)
    TEMP_CANDIDATES = (40, 36, 32, 28)
    WORDMARK_CANDIDATES = (34, 32, 30, 28, 26)


def _build_editorial() -> EditorialLayout:
    canvas = Box(0, 0, CANVAS_W, CANVAS_H)
    gutter = 22

    # Vertical bands: content(52) + thick(3) + gap(2) + hair(1) = 58.
    # The pin rule that used to sit at the top of the masthead is no
    # longer drawn (see _draw_masthead in editorial.py); the masthead
    # itself is nudged 4px down so the content has clear air above it.
    masthead = Box(gutter, 16, CANVAS_W - gutter, 86)        # 70 px tall
    body = Box(gutter, 92, CANVAS_W - gutter, 452)           # 360 px tall
    colophon = Box(gutter, 456, CANVAS_W - gutter, 480)      # 24 px tall

    # Masthead internal bands -- numbers picked so content has 52 px.
    pin_rule = Box(masthead.x0, masthead.y0, masthead.x1, masthead.y0 + 1)
    content = Box(masthead.x0, masthead.y0 + 2, masthead.x1, masthead.y0 + 54)
    thick_rule = Box(masthead.x0, masthead.y0 + 57, masthead.x1, masthead.y0 + 60)
    hair_rule = Box(masthead.x0, masthead.y0 + 62, masthead.x1, masthead.y0 + 63)

    # Masthead columns: 170 | flex | 200 (with 4 px of end padding inside).
    col_time, col_wm, col_weather = content.split_cols(170, 1.0, 200)

    # Body column split: 160 | flex | 168, with 1-px rules.
    left_rail, lead, right_rail = body.split_cols(160, 1.0, 168)
    body_left_rule = Box(left_rail.x1 - 1, body.y0, left_rail.x1, body.y1)
    body_right_rule = Box(right_rail.x0, body.y0, right_rail.x0 + 1, body.y1)

    return EditorialLayout(
        canvas=canvas,
        gutter_x=gutter,
        masthead=masthead,
        body=body,
        colophon=colophon,
        masthead_pin_rule=pin_rule,
        masthead_content=content,
        masthead_thick_rule=thick_rule,
        masthead_hair_rule=hair_rule,
        masthead_col_time=col_time,
        masthead_col_wm=col_wm,
        masthead_col_weather=col_weather,
        body_left_rail=left_rail,
        body_lead=lead,
        body_right_rail=right_rail,
        body_left_rule=body_left_rule,
        body_right_rule=body_right_rule,
    )


EDITORIAL = _build_editorial()


# ── Swiss ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SwissLayout(PageLayout):
    """Two columns on a shared 24 px margin; no boxes, only whitespace and rules.

    ``masthead`` / ``body`` / ``colophon`` are the header row, everything
    between, and the footer. The left column stacks hero, band, and lower; the
    right column stacks the weather and the readings.
    """
    hero: Box
    band: Box
    lower: Box
    weather: Box
    readings: Box


class SwissType:
    """Inter sizes in px. The hero picks the largest candidate that fits."""
    HERO_CANDIDATES = (196, 180, 164, 148, 132, 116, 100, 84, 72)
    WORD_CANDIDATES = (112, 96, 84, 72, 60, 48)
    HERO_TRACKING_EM = -0.03
    HEADER_PX = 17
    LABEL_PX = 15
    SMALL_PX = 14
    VALUE_PX = 28
    TEMP_PX = 84


def _build_swiss() -> SwissLayout:
    W, H = CANVAS_W, CANVAS_H
    margin = 24
    split = 516
    column = 540
    footer_y = 446
    canvas = Box(0, 0, W, H)
    header = Box(margin, 16, split, 42)
    hero = Box(margin, 44, split, 268)
    band = Box(margin, 270, split, 330)
    lower = Box(margin, 336, split, 438)
    weather = Box(column, 16, W - margin, 150)
    readings = Box(column, 156, W - margin, 438)
    colophon = Box(margin, footer_y, W - margin, H - 8)
    return SwissLayout(
        canvas=canvas,
        gutter_x=margin,
        masthead=header,
        body=Box(margin, 44, W - margin, 438),
        colophon=colophon,
        hero=hero,
        band=band,
        lower=lower,
        weather=weather,
        readings=readings,
    )


SWISS = _build_swiss()


# ── Sanity check ──────────────────────────────────────────────────────


def _assert_inside(inner: Box, outer: Box, name: str) -> None:
    assert outer.x0 <= inner.x0 and inner.x1 <= outer.x1 \
        and outer.y0 <= inner.y0 and inner.y1 <= outer.y1, (
        f"{name}: {inner} leaks out of {outer}"
    )


def _assert_positive(b: Box, name: str) -> None:
    assert b.w > 0 and b.h > 0, f"{name}: {b} has non-positive size"


def _verify() -> None:
    """Import-time sanity check for both layouts. Catches a typo before
    it paints over the panel."""
    for L, name in ((EDITORIAL, "EDITORIAL"), (SWISS, "SWISS")):
        _assert_positive(L.canvas, f"{name}.canvas")
        for attr in ("masthead", "body", "colophon"):
            box = getattr(L, attr)
            _assert_positive(box, f"{name}.{attr}")
            _assert_inside(box, L.canvas, f"{name}.{attr}")

    # Editorial masthead bands must stack with no overlap.
    e = EDITORIAL
    bands = [
        ("pin", e.masthead_pin_rule),
        ("content", e.masthead_content),
        ("thick", e.masthead_thick_rule),
        ("hair", e.masthead_hair_rule),
    ]
    for _, b in bands:
        _assert_inside(b, e.masthead, "masthead band")
    for (n1, b1), (n2, b2) in zip(bands, bands[1:]):
        assert b1.y1 <= b2.y0, f"EDITORIAL masthead bands overlap: {n1} -> {n2}"

    cols = e.masthead_col_time, e.masthead_col_wm, e.masthead_col_weather
    for c in cols:
        _assert_inside(c, e.masthead_content, "masthead column")
    for c1, c2 in zip(cols, cols[1:]):
        assert c1.x1 == c2.x0, "masthead columns must be contiguous"

    for b in (e.body_left_rail, e.body_lead, e.body_right_rail):
        _assert_inside(b, e.body, "body column")
    assert e.body_left_rail.x1 == e.body_lead.x0
    assert e.body_lead.x1 == e.body_right_rail.x0

    # Swiss: the left column stacks, and neither column crosses the other.
    s = SWISS
    for upper, below in ((s.masthead, s.hero), (s.hero, s.band), (s.band, s.lower),
                         (s.lower, s.colophon), (s.weather, s.readings),
                         (s.readings, s.colophon)):
        assert upper.y1 <= below.y0, f"Swiss rows overlap: {upper} / {below}"
    for b in (s.masthead, s.hero, s.band, s.lower):
        assert b.x1 <= s.weather.x0, f"Swiss columns overlap: {b}"


_verify()
