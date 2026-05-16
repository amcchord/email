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

    # Vertical bands: pin(1) + content(52) + thick(3) + gap(2) + hair(1) = 59.
    # Plus 11 px free under the pin rule to seat the content band comfortably.
    masthead = Box(gutter, 12, CANVAS_W - gutter, 82)        # 70 px tall
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
    # Header
    header_bottom_rule: Box
    header_cell_wordmark: Box
    header_cell_status: Box
    header_cell_active: Box
    header_cell_refresh: Box
    header_rule_1: Box
    header_rule_2: Box
    header_rule_3: Box

    # Body dividers / rows
    body_top_row: Box
    body_bottom_row: Box
    body_mid_rule: Box
    hero_left: Box
    hero_right: Box
    hero_divider: Box
    hero_right_time: Box
    hero_right_outside: Box
    hero_right_inner_rule: Box
    bottom_left: Box
    bottom_middle: Box
    bottom_right: Box
    bottom_rule_left: Box
    bottom_rule_right: Box
    bottom_middle_top: Box     # pool cell
    bottom_middle_bottom: Box  # sauna cell
    bottom_middle_rule: Box

    # Footer
    footer_top_rule: Box
    footer_cell_src: Box
    footer_cell_status: Box
    footer_cell_zones: Box
    footer_cell_refresh: Box
    footer_rule_1: Box
    footer_rule_2: Box
    footer_rule_3: Box


class SwissType:
    """Swiss has much larger cells so the display digits can stay big --
    the fix there is baseline anchoring, not resizing."""
    WORDMARK_PX = 13
    WORDMARK_TRACKING_EM = 0.20
    HEADER_LABEL_PX = 11
    HEADER_TRACKING_EM = 0.14

    SECTION_LABEL_PX = 9
    SECTION_TRACKING_EM = 0.22

    HERO_QUIET_PX = 56
    HERO_QUIET_GIANT_PX = 160
    HERO_ACTIVE_HEAD_PX = 30
    HERO_ACTIVE_BIG_PX = 84

    TIME_BIG_PX = 64
    OUTSIDE_BIG_PX = 56
    POOL_SAUNA_BIG_PX = 50
    FLOOR_TEMP_PX = 18
    RADIANT_BIG_PX = 18

    FOOTER_LABEL_PX = 10
    FOOTER_TRACKING_EM = 0.16

    # Auto-fit candidate lists -- largest first; the helper picks the
    # biggest size that fits the column. The smallest entry must always
    # fit so the renderer never silently overflows.
    HERO_BIG_CANDIDATES = (84, 72, 64, 56, 48, 40, 36)
    HERO_QUIET_CANDIDATES = (56, 48, 40, 32)
    HERO_QUIET_GIANT_CANDIDATES = (160, 140, 120, 100)
    HERO_ACTIVE_HEAD_CANDIDATES = (30, 26, 22)
    TIME_BIG_CANDIDATES = (64, 56, 48, 40, 36, 32, 28)
    OUTSIDE_BIG_CANDIDATES = (56, 48, 40, 32, 28)
    POOL_SAUNA_BIG_CANDIDATES = (50, 44, 40, 32, 28)
    FLOOR_TEMP_CANDIDATES = (18, 16, 14, 12)
    RADIANT_BIG_CANDIDATES = (18, 16, 14, 12)


def _build_swiss() -> SwissLayout:
    canvas = Box(0, 0, CANVAS_W, CANVAS_H)
    masthead = Box(0, 0, CANVAS_W, 36)
    body = Box(0, 36, CANVAS_W, CANVAS_H - 22)
    colophon = Box(0, CANVAS_H - 22, CANVAS_W, CANVAS_H)

    # Header
    header_bottom_rule = Box(0, masthead.y1 - 2, CANVAS_W, masthead.y1)
    header_cells = masthead.inset(bottom=2).split_cols(180, 1.0, 200, 110)
    h_wm, h_status, h_active, h_refresh = header_cells
    # Column separators (1-px hairlines between each pair).
    h_rule_1 = Box(h_wm.x1, masthead.y0, h_wm.x1 + 1, masthead.y1 - 2)
    h_rule_2 = Box(h_status.x1, masthead.y0, h_status.x1 + 1, masthead.y1 - 2)
    h_rule_3 = Box(h_active.x1, masthead.y0, h_active.x1 + 1, masthead.y1 - 2)

    # Body: top 170 (hero) + middle rule (2) + bottom (fills).
    top_row, mid_rule, bottom_row = body.split_rows(170, 2, 1.0)

    # Hero row: 7|5 split with a 2-px vertical rule.
    col = CANVAS_W / 12.0
    hero_split_x = int(round(col * 7))
    hero_left = Box(top_row.x0, top_row.y0, hero_split_x, top_row.y1)
    hero_divider = Box(hero_split_x, top_row.y0, hero_split_x + 2, top_row.y1)
    hero_right = Box(hero_split_x + 2, top_row.y0, top_row.x1, top_row.y1)
    # Right-side stack: time (top), outside (bottom), 1-px hairline between.
    split_y = hero_right.y0 + hero_right.h // 2
    hero_right_time = Box(hero_right.x0, hero_right.y0, hero_right.x1, split_y)
    hero_right_inner_rule = Box(hero_right.x0, split_y, hero_right.x1, split_y + 1)
    hero_right_outside = Box(hero_right.x0, split_y + 1, hero_right.x1, hero_right.y1)

    # Bottom row: 4|4|4 columns with 2-px vertical dividers.
    b1_x1 = int(round(col * 4))
    b2_x1 = int(round(col * 8))
    bottom_left = Box(bottom_row.x0, bottom_row.y0, b1_x1, bottom_row.y1)
    b_rule_left = Box(b1_x1, bottom_row.y0, b1_x1 + 2, bottom_row.y1)
    bottom_middle = Box(b1_x1 + 2, bottom_row.y0, b2_x1, bottom_row.y1)
    b_rule_right = Box(b2_x1, bottom_row.y0, b2_x1 + 2, bottom_row.y1)
    bottom_right = Box(b2_x1 + 2, bottom_row.y0, bottom_row.x1, bottom_row.y1)

    # Middle column stacks pool (top half) + sauna (bottom half).
    mid_split_y = bottom_middle.y0 + bottom_middle.h // 2
    bottom_middle_top = Box(bottom_middle.x0, bottom_middle.y0, bottom_middle.x1, mid_split_y)
    bottom_middle_rule = Box(bottom_middle.x0, mid_split_y, bottom_middle.x1, mid_split_y + 1)
    bottom_middle_bottom = Box(bottom_middle.x0, mid_split_y + 1, bottom_middle.x1, bottom_middle.y1)

    # Footer
    footer_top_rule = Box(0, colophon.y0, CANVAS_W, colophon.y0 + 2)
    foot_cells = colophon.inset(top=2).split_cols(120, 1.0, 1.0, 120)
    f_src, f_status, f_zones, f_refresh = foot_cells
    f_rule_1 = Box(f_src.x1, colophon.y0 + 2, f_src.x1 + 1, colophon.y1)
    f_rule_2 = Box(f_status.x1, colophon.y0 + 2, f_status.x1 + 1, colophon.y1)
    f_rule_3 = Box(f_zones.x1, colophon.y0 + 2, f_zones.x1 + 1, colophon.y1)

    return SwissLayout(
        canvas=canvas,
        gutter_x=0,
        masthead=masthead,
        body=body,
        colophon=colophon,
        header_bottom_rule=header_bottom_rule,
        header_cell_wordmark=h_wm,
        header_cell_status=h_status,
        header_cell_active=h_active,
        header_cell_refresh=h_refresh,
        header_rule_1=h_rule_1,
        header_rule_2=h_rule_2,
        header_rule_3=h_rule_3,
        body_top_row=top_row,
        body_bottom_row=bottom_row,
        body_mid_rule=mid_rule,
        hero_left=hero_left,
        hero_right=hero_right,
        hero_divider=hero_divider,
        hero_right_time=hero_right_time,
        hero_right_outside=hero_right_outside,
        hero_right_inner_rule=hero_right_inner_rule,
        bottom_left=bottom_left,
        bottom_middle=bottom_middle,
        bottom_right=bottom_right,
        bottom_rule_left=b_rule_left,
        bottom_rule_right=b_rule_right,
        bottom_middle_top=bottom_middle_top,
        bottom_middle_bottom=bottom_middle_bottom,
        bottom_middle_rule=bottom_middle_rule,
        footer_top_rule=footer_top_rule,
        footer_cell_src=f_src,
        footer_cell_status=f_status,
        footer_cell_zones=f_zones,
        footer_cell_refresh=f_refresh,
        footer_rule_1=f_rule_1,
        footer_rule_2=f_rule_2,
        footer_rule_3=f_rule_3,
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

    # Swiss: header cells must tile and not overlap.
    s = SWISS
    header_cells = (
        s.header_cell_wordmark,
        s.header_cell_status,
        s.header_cell_active,
        s.header_cell_refresh,
    )
    for c1, c2 in zip(header_cells, header_cells[1:]):
        assert c1.x1 <= c2.x0, f"Swiss header cells overlap: {c1} / {c2}"

    for b in (s.bottom_left, s.bottom_middle, s.bottom_right):
        _assert_inside(b, s.body_bottom_row, "Swiss bottom column")
    assert s.bottom_left.x1 <= s.bottom_middle.x0
    assert s.bottom_middle.x1 <= s.bottom_right.x0


_verify()
