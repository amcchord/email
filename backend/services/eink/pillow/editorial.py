"""Editorial dashboard -- Pillow port of docs/design/editorial.jsx.

Draws the Editorial newspaper layout at 800x480 onto an RGB Pillow image.
Pixel positions match editorial.jsx exactly where feasible.

Architecture
------------
This renderer is pure presentation. It never touches raw HA dicts and
never re-formats a HA timestamp. All state comes from typed views:

* The House rail reads the room temperatures directly; they are plain
  presentation values with no state to reconcile.
* Appliances read ``ApplianceView`` (built by the registry in
  ``appliances.py``). All clock strings are pre-localized to the
  user's IANA zone, so the washer/dishwasher hero can never print UTC.

See ``backend/services/eink/README.md`` for the full layering rules and
the "how to add a new appliance / new design" guide.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from PIL import Image, ImageDraw

from ..sauna_forecast import READY_F, TARGET_F
from . import flavor, fonts, icons, layout, meters
from .appliances import ActiveAppliance, pick_active, pool_near_target
from .draw import (
    Box,
    Run,
    _wrap_runs_into_lines,
    bullet,
    diamond,
    dotted_hr,
    double_hr,
    draw_arrow_down,
    draw_arrow_up,
    draw_dashed_arc,
    draw_drop_cap_paragraph,
    draw_fit_text_bl,
    draw_headline,
    draw_paragraph,
    draw_star_marker,
    draw_text_bl,
    draw_text_bl_center,
    draw_text_bl_right,
    draw_text_clipped_bl,
    draw_text_clipped_bl_right,
    draw_text_in_box,
    draw_tracked_text,
    draw_tracked_text_bl,
    draw_tracked_text_bl_center,
    draw_tracked_text_bl_right,
    em_to_px,
    fill_box,
    font_metrics,
    hairline_hr,
    hr,
    pick_fitting_size,
    square_marker,
    text_width,
    tracked_width,
    vline,
)
from .ha_view import (
    ApplianceView,
    _span,
    build_appliance_view,
)
from .helpers import (
    clamp,
    compass,
    fmt_clock,
    fmt_date,
    fmt_temp,
    fmt_weather,
    forecast_day_date,
    lerp_pct,
    parse_iso,
    safe_int,
    safe_round,
    title_case,
    to_float,
)
from .palette import Palette
from .render_ctx import RenderContext, build_render_context


# ── Top-level ──────────────────────────────────────────────────────────


def _reading(value: Any) -> str:
    """A whole-number reading, or a dash: unknown must never print as zero."""
    return "—" if to_float(value) is None else str(safe_round(value))


def render_dashboard(
    img: Image.Image,
    ha: dict,
    P: Palette,
    *,
    tz_name: Optional[str] = None,
) -> None:
    draw = ImageDraw.Draw(img)

    ctx = build_render_context(ha, P, tz_name=tz_name)
    active = pick_active(ha, ctx)
    # Editorial-only: drop the pool from the center column once it's
    # within a degree of target. The right-rail pool stat (drawn from
    # ha["pool"] directly) still shows the live water temperature.
    active = [
        a for a in active
        if not (a.kind == "pool" and pool_near_target(a.view))
    ]
    lead = active[0] if active else None
    rest = active[1:]

    L = layout.EDITORIAL

    _draw_masthead(draw, P, ctx.now_local, ha.get("weather") or {},
                   live=not ha.get("unavailable"))

    fill_box(draw, L.body_left_rule, P.rule)
    fill_box(draw, L.body_right_rule, P.rule)

    _draw_left_rail(draw, ctx, ha, L.body_left_rail.inset(right=14))
    _draw_lead_column(
        img, draw, ctx, ha, active,
        L.body_lead.inset(left=18, right=18),
    )
    _draw_right_rail(draw, ctx, ha, L.body_right_rail.inset(left=16))

    _draw_colophon(draw, ctx, ha)


# ── Masthead ───────────────────────────────────────────────────────────


def _draw_masthead(draw: ImageDraw.ImageDraw, P: Palette, now: datetime,
                   weather: dict, *, live: bool = True) -> None:
    """Newspaper flag. Time (left) | CAMBRIDGE wordmark + date (center) |
    weather glyph + temp + label (right), bracketed by a pin rule on top
    and a thick + hairline pair on the bottom.

    All text sits on baselines derived from font_metrics so the display
    row and the label row can never clip the rule stack.
    """
    L = layout.EDITORIAL
    TY = layout.EditorialType

    # Top pin rule intentionally not drawn -- the masthead reads cleaner
    # without a hairline against the panel edge. The thick + hairline
    # below the content band still bracket the flag.
    fill_box(draw, L.masthead_thick_rule, P.rule)
    fill_box(draw, L.masthead_hair_rule, P.rule)

    time_col = L.masthead_col_time
    wm_col = L.masthead_col_wm
    weather_col = L.masthead_col_weather
    content_y0 = L.masthead_content.y0
    content_y1 = L.masthead_content.y1

    ampm_font = fonts.serif(TY.AMPM_PX, italic=True, weight="bold")
    label_font = fonts.pix_cherry_small(TY.LABEL_PX, bold=True)
    fm_label = font_metrics(label_font)

    label_baseline = content_y1 - fm_label.descent

    # ── Time column (left) ─────────────────────────────────────────
    parts = now.strftime("%I:%M %p").lstrip("0").split(" ")
    time_s = parts[0]
    ampm = parts[1] if len(parts) > 1 else ""
    ampm_w = text_width(ampm_font, ampm) + 6
    fit_font, _fit_size = pick_fitting_size(
        lambda s: fonts.serif(s, weight="bold"),
        time_s, time_col.w - ampm_w, TY.TIME_CANDIDATES,
    )
    fm_time = font_metrics(fit_font)
    # Display baseline sits high enough that label row has the
    # MASTHEAD_LABEL_GAP_PX of breathing space below the descender.
    display_baseline = label_baseline - fm_label.ascent - TY.MASTHEAD_LABEL_GAP_PX - fm_time.descent
    # Time + temp share a "display row" baseline that's pulled 8 px down
    # from the wordmark baseline so the digits sit at the optical center
    # of the masthead instead of jamming against the top rule. The
    # CAMBRIDGE wordmark stays on the original baseline so it still
    # reads as the flag's anchor.
    display_row_baseline = display_baseline + 8
    draw.text((time_col.x0, display_row_baseline), time_s,
              font=fit_font, fill=P.ink, anchor="ls")
    tw = text_width(fit_font, time_s)
    draw.text((time_col.x0 + tw + 4, display_row_baseline), ampm,
              font=ampm_font, fill=P.muted, anchor="ls")
    draw_text_bl(draw, (time_col.x0, label_baseline),
                 f"{now.tzname()} \u00b7 {'LIVE' if live else 'NO DATA'}",
                 label_font, P.muted)

    # ── Wordmark column (center) ───────────────────────────────────
    wm_tracking = em_to_px(TY.WORDMARK_PX, TY.WORDMARK_TRACKING_EM)
    wm_fit_font, _ = pick_fitting_size(
        lambda s: fonts.serif(s, weight="bold"),
        "CAMBRIDGE", wm_col.w, TY.WORDMARK_CANDIDATES,
    )
    draw_tracked_text_bl_center(
        draw, (wm_col.cx, display_baseline),
        "CAMBRIDGE", wm_fit_font, P.ink, wm_tracking,
    )
    date_s = fmt_date(now)
    d_tracking = em_to_px(TY.LABEL_PX, TY.DATE_TRACKING_EM)
    date_w = tracked_width(label_font, date_s.upper(), d_tracking)
    draw_tracked_text_bl_center(
        draw, (wm_col.cx, label_baseline),
        date_s.upper(), label_font, P.muted, d_tracking,
    )
    # Right edge of the centered date -- the label row in the weather
    # column may borrow the empty band between here and the condition
    # label (see the feels/AQI cluster below).
    date_end_x = wm_col.cx + date_w // 2

    # ── Weather column (right) ─────────────────────────────────────
    # Prefer the on-house outdoor sensor; fall back to the weather entity
    # (often NWS/API) when the sensor is unavailable.
    temp = weather.get("outdoorTemp")
    if temp is None:
        temp = weather.get("temperature")
    temp_s = (f"{safe_round(temp)}\u00b0" if temp is not None else "\u2014")
    glyph_sz = TY.WEATHER_GLYPH_PX
    temp_max_w = weather_col.w - glyph_sz - 20
    temp_fit_font, _temp_fit_size = pick_fitting_size(
        lambda s: fonts.serif(s, weight="bold"),
        temp_s, temp_max_w, TY.TEMP_CANDIDATES,
    )
    temp_w = text_width(temp_fit_font, temp_s)
    glyph_top = content_y0
    # The gap keeps a sun's right-hand ray clear of the digits, where it
    # would otherwise read as a minus sign.
    glyph_x = weather_col.x1 - temp_w - 18 - glyph_sz - 4
    if weather.get("state"):
        _draw_weather_glyph(draw, (glyph_x, glyph_top),
                            size=glyph_sz, state=weather["state"], P=P)
    # Temp shares the display row baseline with the time, sitting 8 px
    # below the wordmark so the digits land at the icon's optical
    # center.
    draw.text((weather_col.x1 - temp_w, display_row_baseline), temp_s,
              font=temp_fit_font, fill=P.ink, anchor="ls")
    weather_label = fmt_weather(weather.get("state") or "").upper()
    l_tracking = em_to_px(TY.LABEL_PX, TY.WEATHER_LABEL_TRACKING_EM)
    draw_tracked_text_bl_right(
        draw,
        (weather_col.x1, label_baseline),
        weather_label, label_font, P.muted, l_tracking,
    )
    # Feels-like + AQI cluster sits left of the condition on the same
    # label baseline. It anchors at the weather column's left edge but may
    # slide further left into the empty band after the centered date when
    # a long condition ("PARTLY CLOUDY") squeezes the column. If even that
    # can't fit, the AQI tail drops first, then the whole cluster -- the
    # runs on this row must never collide.
    feels = weather.get("feelsLike")
    aqi = weather.get("aqi")
    parts = []
    if feels is not None:
        parts.append(f"FEELS {safe_round(feels)}\u00b0")
    if aqi is not None:
        parts.append(f"AQI {safe_round(aqi)}")
    if parts:
        cond_x0 = weather_col.x1 - tracked_width(label_font, weather_label,
                                                 l_tracking)
        min_x = date_end_x + 12
        candidates = [" \u00b7 ".join(parts)]
        if len(parts) > 1:
            candidates.append(parts[0])
        for candidate in candidates:
            cw = tracked_width(label_font, candidate, l_tracking)
            cx0 = min(weather_col.x0, cond_x0 - 16 - cw)
            if cx0 >= min_x:
                draw_tracked_text_bl(
                    draw, (cx0, label_baseline),
                    candidate, label_font, P.muted, l_tracking,
                )
                break


# HA weather condition -> Weather Icons (Erik Flowers) Unicode codepoint.
# Every HA condition has a dedicated glyph in this font, which is exactly
# why we replaced the hand-drawn primitives: the old fallbacks for
# `hail` / `windy` / `exceptional` / `snowy-rainy` / `lightning-rainy`
# rendered as a plain circle.
_WI_CODEPOINT = {
    "sunny":           "\uf00d",  # wi-day-sunny
    "clear":           "\uf00d",  # wi-day-sunny
    "clear-night":     "\uf02e",  # wi-night-clear
    "partlycloudy":    "\uf002",  # wi-day-cloudy
    "mostlycloudy":    "\uf013",  # wi-cloudy
    "cloudy":          "\uf013",  # wi-cloudy
    "rainy":           "\uf019",  # wi-rain
    "pouring":         "\uf01a",  # wi-showers
    "snowy":           "\uf01b",  # wi-snow
    "lightning":       "\uf016",  # wi-lightning
    "lightning-rainy": "\uf01e",  # wi-thunderstorm
    "snowy-rainy":     "\uf0b5",  # wi-sleet
    "fog":             "\uf014",  # wi-fog
    "mist":            "\uf014",
    "haze":            "\uf014",
    "hail":            "\uf015",  # wi-hail
    "windy":           "\uf021",  # wi-windy
    "windy-variant":   "\uf050",  # wi-strong-wind
    "exceptional":     "\uf01e",  # wi-thunderstorm (severe-weather catch-all)
}
_WI_FALLBACK = "\uf07b"  # wi-na (Not Available)


def _draw_weather_glyph(
    draw: ImageDraw.ImageDraw,
    xy: tuple,
    *,
    size: int,
    state: str,
    P: Palette,
) -> None:
    """Render a Weather Icons glyph for HA condition `state`, centered in
    a (size x size) box at `xy`. Single-color (P.ink); the 1-bit panel
    can't render the JSX prototype's color accents (yellow sun, blue
    raindrops) anyway, and a clean monochrome glyph reads much better at
    20--34 px than the old hand-drawn primitives."""
    s = (state or "").lower()
    cp = _WI_CODEPOINT.get(s, _WI_FALLBACK)
    # Weather Icons leaves substantial vertical padding inside the em
    # square; oversizing slightly fills the box without clipping the
    # actual ink (the bbox math below uses the rendered glyph's bounds,
    # not the em).
    font = fonts.icon_weather(int(size * 1.15))
    bbox = font.getbbox(cp)
    gw = bbox[2] - bbox[0]
    gh = bbox[3] - bbox[1]
    x = xy[0] + (size - gw) // 2 - bbox[0]
    y = xy[1] + (size - gh) // 2 - bbox[1]
    draw.text((x, y), cp, font=font, fill=P.ink)


# ── Section kickers (rail + lead headers) ──────────────────────────────


def _draw_kicker(
    draw: ImageDraw.ImageDraw,
    box: Box,
    *,
    text: str,
    P: Palette,
    color: Optional[tuple] = None,
    decor: bool = False,
) -> None:
    """Tracked-caps section kicker. Optional ornament on the right when
    ``decor`` is True (the rail variant)."""
    font = fonts.pix_cherry_small(layout.EditorialType.KICKER_PX, bold=True)
    tracking = em_to_px(layout.EditorialType.KICKER_PX,
                        layout.EditorialType.KICKER_TRACKING_EM)
    fm = font_metrics(font)
    baseline = box.y0 + fm.ascent
    fill = color or P.ink
    s = text.upper()
    draw_tracked_text_bl(draw, (box.x0, baseline), s, font, fill, tracking)
    tw = tracked_width(font, s, tracking)
    # Hairline rule from the end of the text to the right edge of the box.
    rule_x0 = box.x0 + tw + 8
    if rule_x0 < box.x1 - 4:
        rule_y = baseline - fm.ascent // 2
        if decor:
            dotted_hr(draw, rule_x0, box.x1, rule_y, dash=1, gap=3, fill=P.muted)
        else:
            draw.rectangle([(rule_x0, rule_y), (box.x1, rule_y)], fill=P.muted)


def _draw_diamond_kicker(
    draw: ImageDraw.ImageDraw,
    box: Box,
    *,
    text: str,
    P: Palette,
    accent: tuple,
    badge: Optional[str] = None,
) -> None:
    """Lead-story kicker: diamond bullet + tracked text + optional right
    badge (e.g. "LIVE", "UNLOAD")."""
    font = fonts.pix_cherry_small(layout.EditorialType.KICKER_PX, bold=True)
    tracking = em_to_px(layout.EditorialType.KICKER_PX,
                        layout.EditorialType.KICKER_TRACKING_EM)
    fm = font_metrics(font)
    baseline = box.y0 + fm.ascent
    diamond(draw, box.x0 + 3, baseline - fm.ascent // 2, 5, accent)
    s = text.upper()
    draw_tracked_text_bl(draw, (box.x0 + 14, baseline), s, font, P.ink, tracking)

    if badge:
        bf = fonts.pix_cherry_small(layout.EditorialType.KICKER_PX, bold=True)
        bw = tracked_width(bf, badge, tracking) + 10
        bh = fm.line_height + 2
        bx0 = box.x1 - bw
        by0 = box.y0
        draw.rectangle([(bx0, by0), (box.x1 - 1, by0 + bh - 1)], fill=accent)
        draw_tracked_text_bl(
            draw, (bx0 + 5, by0 + fm.ascent),
            badge, bf, P.bg, tracking,
        )


# ── Left rail ──────────────────────────────────────────────────────────


def _draw_left_rail(draw, ctx: RenderContext, ha, box: Box) -> None:
    """Three stacked stories: Outside / Sun / At Home, each separated by
    a hairline. The kicker-to-stat gap is 6px and section-to-section is
    `8 + hairline + 6`, which gives the rail a clear newspaper rhythm.
    """
    P = ctx.palette
    zone = ctx.zone
    weather = ha.get("weather") or {}
    cur_y = box.y0

    def _section(text: str) -> None:
        nonlocal cur_y
        kfont = fonts.pix_cherry_small(layout.EditorialType.KICKER_PX, bold=True)
        fm = font_metrics(kfont)
        _draw_kicker(draw, Box(box.x0, cur_y, box.x1, cur_y + fm.line_height),
                     text=text, P=P, decor=True)
        cur_y += fm.line_height + 6

    _section("Outside")
    cur_y = _draw_rail_stat(draw, P, box.x0, cur_y, box.w,
        k="Wind", v=_reading(weather.get("windSpeed")),
        u=f"mph {compass(weather.get('windBearing'))}")
    cur_y = _draw_rail_stat(draw, P, box.x0, cur_y, box.w,
        k="Humidity", v=_reading(weather.get("humidity")), u="%")
    uv_peak = weather.get("uvPeak")
    uv_u = f"peak {safe_round(uv_peak)}" if uv_peak is not None else ""
    cur_y = _draw_rail_stat(draw, P, box.x0, cur_y, box.w,
        k="UV Index", v=_reading(weather.get("uvIndex")), u=uv_u)
    cur_y = _draw_rail_stat(draw, P, box.x0, cur_y, box.w,
        k="Visibility", v=_reading(weather.get("visibility")), u="mi")

    cur_y += 8
    hairline_hr(draw, box.x0, box.x1, cur_y, fill=P.rule); cur_y += 6
    # The unavailable shape's default sun state isn't an observation.
    sun = {} if ha.get("unavailable") else (ha.get("sun") or {})
    sun_label = {"above_horizon": "Sun \u00b7 Risen",
                 "below_horizon": "Sun \u00b7 Set"}.get(sun.get("state"), "Sun")
    _section(sun_label)
    cur_y = _draw_sun_arc(draw, P, box.x0, cur_y, box.w, ha, zone)

    cur_y += 8
    hairline_hr(draw, box.x0, box.x1, cur_y, fill=P.rule); cur_y += 6
    _section("Forecast")
    cur_y = _draw_forecast_rows(draw, ctx, ha, box.x0, cur_y, box.w)


def _draw_rail_stat(draw, P, x0, y, w, *, k, v, u) -> int:
    """One Outside stat row: ``label .... value unit``.

    The label always fits (italicized noun); the value uses
    ``pick_fitting_size`` so a 3-digit number or a long pressure string
    can shrink instead of spilling into the unit column.
    """
    label_font = fonts.serif(layout.EditorialType.RAIL_LABEL_PX,
                             italic=True, weight="semibold")
    value_factory = lambda s: fonts.serif(s, weight="bold")
    unit_font = fonts.pix_cherry_small(9, bold=True)
    unit_tracking = em_to_px(9, 0.10)
    fm_l = font_metrics(label_font)
    label_w = text_width(label_font, k)
    unit_w = tracked_width(unit_font, u, unit_tracking)
    # Value column is bounded by [label + 6px gap, unit - 3px gap].
    avail = max(20, w - label_w - 6 - unit_w - 3)
    value_font, _val_size = pick_fitting_size(
        value_factory, v, avail,
        (layout.EditorialType.RAIL_VALUE_PX, 14, 13, 12),
    )
    fm_v = font_metrics(value_font)
    baseline = y + max(fm_v.ascent, fm_l.ascent)
    draw_text_bl(draw, (x0, baseline), k, label_font, P.ink)
    val_w = text_width(value_font, v)
    right = x0 + w
    unit_x = right - unit_w
    val_x = unit_x - 3 - val_w
    # If the value would touch the label, just truncate the value.
    if val_x < x0 + label_w + 6:
        from .draw import draw_text_clipped_bl_right
        # Truncate value to fit the available column.
        draw_tracked_text_bl(draw, (unit_x, baseline), u,
                             unit_font, P.muted, unit_tracking)
        draw_text_clipped_bl_right(draw, (unit_x - 3, baseline), v,
                                   value_font, P.ink, max_w=avail)
    else:
        draw_text_bl(draw, (val_x, baseline), v, value_font, P.ink)
        draw_tracked_text_bl(draw, (unit_x, baseline), u,
                             unit_font, P.muted, unit_tracking)
    under_y = baseline + max(fm_v.descent, fm_l.descent) + 2
    dotted_hr(draw, x0, x0 + w, under_y, dash=1, gap=3, fill=P.rule)
    return under_y + 2


def _draw_forecast_rows(draw, ctx: RenderContext, ha, x0, y, w) -> int:
    """Render up to 4 daily forecast slots in the left rail.

    Each row: condition glyph + weekday label + high/low temp cluster. The
    first slot is labelled "Today" rather than its weekday so it reads as
    the immediate outlook. When HA returns no forecast (older Core, weather
    integration without forecast support, transient service failure) we
    render a single muted italic "Forecast unavailable" line so the layout
    rhythm doesn't silently collapse.
    """
    P = ctx.palette
    weather = ha.get("weather") or {}
    forecast = (weather.get("forecast") or {}).get("daily") or []
    if not forecast:
        font = fonts.serif(12, italic=True, weight="semibold")
        fm = font_metrics(font)
        draw_text_bl(draw, (x0, y + fm.ascent),
                     "Forecast unavailable", font, P.muted)
        return y + fm.line_height + 4

    cur_y = y
    row_h = 30
    glyph_sz = 20
    weekday_font = fonts.serif(13, weight="semibold")
    hi_factory = lambda s: fonts.serif(s, weight="bold")
    lo_font = fonts.serif(12, italic=True, weight="semibold")
    sep_font = fonts.serif(12, italic=True, weight="semibold")
    fm_n = font_metrics(weekday_font)

    # Label rows from each slot's *calendar date* (via forecast_day_date,
    # which knows daily slots are day markers, not instants) instead of
    # assuming slot 0 is today and tz-shifting the rest -- that assumption
    # is what printed "Today, Monday, Tuesday" on a Monday.
    today = ctx.now_local.date()
    slots = forecast[:3]
    for idx, slot in enumerate(slots):
        slot_date = forecast_day_date(slot.get("datetime"), ctx.zone)
        if slot_date == today:
            label = "Today"
        elif slot_date is not None:
            label = slot_date.strftime("%a")
        elif idx == 0:
            label = "Today"
        else:
            label = "\u2014"

        glyph_y = cur_y + (row_h - glyph_sz) // 2
        _draw_weather_glyph(draw, (x0, glyph_y),
                            size=glyph_sz,
                            state=slot.get("condition") or "",
                            P=P)

        text_x = x0 + glyph_sz + 6
        baseline = cur_y + fm_n.ascent + 6
        draw_text_bl(draw, (text_x, baseline), label, weekday_font, P.ink)

        hi = slot.get("temperature")
        lo = slot.get("templow")
        hi_s = f"{safe_round(hi)}\u00b0" if hi is not None else "\u2014"
        lo_s = f"{safe_round(lo)}\u00b0" if lo is not None else "\u2014"
        sep_s = "/"

        label_w = text_width(weekday_font, label)
        avail = max(24, (x0 + w) - text_x - label_w - 8)
        hi_font, _hs = pick_fitting_size(
            hi_factory, hi_s, avail, (16, 15, 14, 13),
        )
        right_x = x0 + w
        lo_w = text_width(lo_font, lo_s)
        sep_w = text_width(sep_font, sep_s)
        hi_w = text_width(hi_font, hi_s)
        lo_x = right_x - lo_w
        sep_x = lo_x - sep_w
        hi_x = sep_x - hi_w
        draw_text_bl(draw, (hi_x, baseline), hi_s, hi_font, P.ink)
        draw_text_bl(draw, (sep_x, baseline), sep_s, sep_font, P.muted)
        draw_text_bl(draw, (lo_x, baseline), lo_s, lo_font, P.muted)

        if idx != len(slots) - 1:
            dotted_hr(draw, x0, x0 + w,
                      cur_y + row_h - 1, dash=1, gap=3, fill=P.rule)
        cur_y += row_h

    return cur_y


def _draw_sun_arc(draw, P, x0, y, w, ha, zone) -> int:
    sun = {} if ha.get("unavailable") else (ha.get("sun") or {})
    rise = fmt_clock(sun.get("nextRising") or sun.get("nextDawn"), tz=zone)
    set_s = fmt_clock(sun.get("nextSetting") or sun.get("nextDusk"), tz=zone)
    above = sun.get("state") == "above_horizon"
    try:
        r = parse_iso(sun.get("nextRising") or sun.get("nextDawn"))
        s_dt = parse_iso(sun.get("nextSetting") or sun.get("nextDusk"))
        now = parse_iso((ha or {}).get("fetchedAt")) or datetime.now(timezone.utc)
        if above and r and s_dt and s_dt > now:
            r_prev = r - timedelta(hours=24)
            total = (s_dt - r_prev).total_seconds()
            frac = (now - r_prev).total_seconds() / total if total else 0.5
        elif not above:
            frac = 0.0
        else:
            frac = 0.5
    except Exception:
        frac = 0.5
    frac = clamp(frac, 0.0, 1.0)
    W, H = min(144, w), 40
    cx = x0 + W // 2
    cy_flat = y + H
    rX = W // 2 - 8
    rY = H - 8
    draw.rectangle([(x0 + 2, cy_flat), (x0 + W - 3, cy_flat)], fill=P.ink)
    bbox = (cx - rX, cy_flat - rY, cx + rX, cy_flat + rY)
    draw_dashed_arc(draw, bbox, 180, 360, dash_deg=4, gap_deg=6, fill=P.ink, width=1)
    draw.rectangle([(cx - rX, cy_flat - 3), (cx - rX, cy_flat + 3)], fill=P.ink)
    draw.rectangle([(cx + rX, cy_flat - 3), (cx + rX, cy_flat + 3)], fill=P.ink)
    angle = math.pi - frac * math.pi
    sx = cx + int(rX * math.cos(angle))
    sy = cy_flat - int(rY * math.sin(angle))
    r = 5
    disk_color = P.yellow if P.yellow != P.ink else P.ink
    if sun.get("state"):  # Unknown: leave the arc empty rather than place a sun.
        draw.ellipse([(sx - r, sy - r), (sx + r, sy + r)],
                     fill=disk_color, outline=P.ink, width=1)
    lf = fonts.serif(12, italic=True, weight="semibold")
    fm = font_metrics(lf)
    baseline = y + H + 4 + fm.ascent
    arrow_sz = 8
    draw_arrow_up(draw, x0, baseline, size=arrow_sz, fill=P.muted)
    draw_text_bl(draw, (x0 + arrow_sz + 3, baseline), rise, lf, P.muted)
    set_tw = text_width(lf, set_s)
    draw_arrow_down(draw, x0 + w - arrow_sz - 3 - set_tw, baseline,
                    size=arrow_sz, fill=P.muted)
    draw_text_bl_right(draw, (x0 + w, baseline), set_s, lf, P.muted)
    return baseline + fm.descent + 4


# ── Right rail ─────────────────────────────────────────────────────────


def _draw_right_rail(draw, ctx: RenderContext, ha, box: Box) -> None:
    """House / Hearth / Pool stack. Same `8 + hairline + 6` rhythm as
    the left rail so the two rails read as siblings.
    """
    P = ctx.palette
    pool = ha.get("pool")
    cur_y = box.y0

    def _section(text: str) -> None:
        nonlocal cur_y
        kfont = fonts.pix_cherry_small(layout.EditorialType.KICKER_PX, bold=True)
        fm = font_metrics(kfont)
        _draw_kicker(draw, Box(box.x0, cur_y, box.x1, cur_y + fm.line_height),
                     text=text, P=P, decor=True)
        cur_y += fm.line_height + 6

    _section("The House")
    cur_y = _draw_house_readings(draw, ctx, ha, box.x0, cur_y, box.w)

    cur_y += 8
    hairline_hr(draw, box.x0, box.x1, cur_y, fill=P.rule); cur_y += 6
    _section("Solar \u00b7 Roof")
    cur_y = _draw_solar_section(draw, ctx, ha, box.x0, cur_y, box.w)

    if pool and pool.get("current") is not None:
        cur_y += 8
        hairline_hr(draw, box.x0, box.x1, cur_y, fill=P.rule); cur_y += 6
        _section("Pool")
        cur_y = _draw_pool_temp(draw, ctx, box.x0, cur_y, box.w, pool)


def _draw_house_readings(draw, ctx: RenderContext, ha, x0, y, w) -> int:
    """The two rooms we watch and today's coffee, within the fixed rail."""
    P = ctx.palette
    temps = ha.get("temps") or {}
    cups = (ha.get("coffee") or {}).get("cupsToday")
    readings = [
        (("Primary Suite",), fmt_temp(temps.get("primaryBedroom"))),
        (("Nursery",), fmt_temp(temps.get("nursery"))),
        (("Coffee", "cups today"), "—" if cups is None else str(cups)),
    ]
    name_font = fonts.serif(13, weight="semibold")
    fm_n = font_metrics(name_font)
    value_width = max(36, w - text_width(name_font, "Primary Suite") - 12)
    widest = max((value for _, value in readings),
                 key=lambda value: text_width(fonts.serif(22, weight="bold"), value))
    value_font, _ = pick_fitting_size(
        lambda size: fonts.serif(size, weight="bold"), widest,
        value_width, (22, 20, 18, 16),
    )
    fm_v = font_metrics(value_font)
    row_h = max(2 * fm_n.line_height, fm_v.line_height) + 8
    cur_y = y
    for index, (labels, value) in enumerate(readings):
        for line, label in enumerate(labels):
            baseline = cur_y + fm_n.ascent + line * fm_n.line_height
            draw_text_bl(draw, (x0, baseline), label, name_font,
                         P.muted if index == 2 and line else P.ink)
        draw_text_clipped_bl_right(
            draw, (x0 + w - 2, cur_y + fm_v.ascent), value,
            value_font, P.ink, max_w=value_width,
        )
        if index < len(readings) - 1:
            dotted_hr(draw, x0, x0 + w, cur_y + row_h - 1,
                      dash=1, gap=3, fill=P.rule)
        cur_y += row_h
    return cur_y


# Per-microinverter AC nameplate (~Enphase IQ8) used to scale the power
# bar's full range from the panel count, and a fallback full-scale for
# installs where the inverter count isn't available.
_SOLAR_PANEL_KW = 0.30
_SOLAR_PEAK_KW = 10.0


def _draw_solar_section(draw, ctx: RenderContext, ha, x0, y, w) -> int:
    """Rooftop solar stat block (Enphase Envoy).

    Today's generated kWh as the hero number, the live output as a bar
    filled to ``currentKw / peak_kw``, and a 7-day total + panel count
    sub-line. Reads ``ha['solar']`` directly -- these are plain numeric
    snapshot values (no state reconciliation or timestamp localization),
    so they don't need a ha_view wrapper, same as the ``ha['temps']``
    reads elsewhere in this renderer.
    """
    P = ctx.palette
    solar = ha.get("solar") or {}
    today = solar.get("todayKwh")
    # Solar reads as the sun's yellow where the palette has one; on the
    # 1-bit panel it collapses to ink like the sun disk does.
    accent = P.yellow if P.yellow != P.ink else P.ink

    if today is None:
        font = fonts.serif(12, italic=True, weight="semibold")
        fm = font_metrics(font)
        draw_text_bl(draw, (x0, y + fm.ascent), "Solar offline", font, P.muted)
        return y + fm.line_height + 4

    unit_font = fonts.pix_cherry_small(9, bold=True)
    u_tracking = em_to_px(9, 0.12)
    val_factory = lambda s: fonts.serif(s, weight="bold")

    # ── Hero: today's kWh (accent, left) + live kW (ink, right) ────
    cur_kw = solar.get("currentKw")
    now_val_s = f"{float(cur_kw):.1f}" if cur_kw is not None else "\u2014"
    now_font = fonts.serif(13, weight="bold")
    now_unit_w = tracked_width(unit_font, "kW", u_tracking)
    now_val_w = text_width(now_font, now_val_s)
    now_cluster_w = now_val_w + 3 + now_unit_w

    today_s = f"{float(today):.1f}"
    unit_s = "kWh TODAY"
    unit_w = tracked_width(unit_font, unit_s, u_tracking)
    # The today number gets whatever width is left after reserving the
    # unit caption and the right-hand live-kW cluster, so a 3-digit day
    # shrinks rather than colliding.
    avail = max(34, w - unit_w - 4 - now_cluster_w - 8)
    val_font, _ = pick_fitting_size(val_factory, today_s, avail, (18, 16, 15))
    fm_v = font_metrics(val_font)
    baseline = y + fm_v.ascent
    draw_text_bl(draw, (x0, baseline), today_s, val_font, accent)
    val_w = text_width(val_font, today_s)
    draw_tracked_text_bl(draw, (x0 + val_w + 4, baseline),
                         unit_s, unit_font, P.muted, u_tracking)
    nu_x = x0 + w - now_unit_w
    nv_x = nu_x - 3 - now_val_w
    draw_text_bl(draw, (nv_x, baseline), now_val_s, now_font, P.ink)
    draw_tracked_text_bl(draw, (nu_x, baseline), "kW", unit_font, P.muted, u_tracking)
    cur_y = baseline + fm_v.descent + 2

    # ── Live-output bar: current / rated peak ──────────────────────
    panel_count = solar.get("panelCount")
    peak_kw = panel_count * _SOLAR_PANEL_KW if panel_count else _SOLAR_PEAK_KW
    bar_h = 6
    draw.rectangle([(x0, cur_y), (x0 + w - 1, cur_y + bar_h - 1)],
                   outline=P.rule, width=1)
    if cur_kw is not None and peak_kw > 0:
        pct = clamp(float(cur_kw) / float(peak_kw), 0.0, 1.0)
        fill_w = int((w - 2) * pct)
        if fill_w > 0:
            draw.rectangle([(x0 + 1, cur_y + 1), (x0 + fill_w, cur_y + bar_h - 2)],
                           fill=accent)
    cur_y += bar_h

    # ── Sub-line: 7-day total as a balanced label .... value stat ──
    week = solar.get("weekKwh")
    sub_font = fonts.pix_cherry_small(9, bold=True)
    s_tracking = em_to_px(9, 0.12)
    fm_s = font_metrics(sub_font)
    sub_baseline = cur_y + 2 + fm_s.ascent
    draw_tracked_text_bl(draw, (x0, sub_baseline), "7-DAY",
                         sub_font, P.muted, s_tracking)
    if week is not None:
        draw_tracked_text_bl_right(draw, (x0 + w, sub_baseline),
                                   f"{float(week):.0f} KWH",
                                   sub_font, P.ink, s_tracking)
    return sub_baseline + fm_s.descent + 2


def _draw_pool_temp(draw, ctx: RenderContext, x0, y, w, pool) -> int:
    """Compact pool row -- just the current water temperature.

    Sized to a single rail row (bullet + state caption on the left, big
    temp on the right) so it always fits beneath the solar section. The
    old mini-thermometer panel that lived here was ~60 px tall and got
    pushed off the bottom of the right rail once the solar block took the
    radiant section's place; the dashboard only needs the live temp here.
    """
    P = ctx.palette
    if not pool:
        return y
    heating = bool(pool.get("heating"))
    color = ctx.accent("heat") if heating else P.ink
    label_font = fonts.pix_cherry_small(10, bold=True)
    l_tracking = em_to_px(10, 0.14)
    temp_factory = lambda s: fonts.serif(s, weight="bold")
    cur_s = fmt_temp(pool.get("current"))
    label = "HEATING" if heating else "WATER"
    label_w = tracked_width(label_font, label, l_tracking)
    bullet_w = 10
    avail = max(24, w - bullet_w - label_w - 8)
    temp_font, _ = pick_fitting_size(temp_factory, cur_s, avail, (20, 18, 16, 15))
    fm_l = font_metrics(label_font)
    fm_t = font_metrics(temp_font)
    baseline = y + max(fm_t.ascent, fm_l.ascent)
    bullet(draw, x0 + 3, baseline - fm_l.ascent // 2, 3, filled=heating, color=color)
    draw_tracked_text_bl(draw, (x0 + 10, baseline), label, label_font, color, l_tracking)
    draw_text_bl_right(draw, (x0 + w, baseline), cur_s, temp_font, color)
    return baseline + max(fm_t.descent, fm_l.descent) + 2


# ── Lead column ────────────────────────────────────────────────────────


def _draw_lead_column(img: Image.Image, draw, ctx: RenderContext, ha,
                      active: list, box: Box) -> None:
    """Composer for the center column.

    Branches on how many appliances are currently active:

    * 0 active: render the calm-edition hero. Slack is distributed so
      the headline sits ~1/3 from the top -- a magazine looks anchored,
      not floating.
    * 1 active: render the feature card (icon, headline, instrument meter,
      facts) at the same 1/3 gravity offset.
    * 2 active: render two equal-weight co-lead stories stacked with a
      double-rule divider. This is the "Dryer + Washer" case where
      both deserve top-billing.
    * 3+ active: render the highest-severity item as the full hero,
      then the rest as briefs underneath -- still left-anchored
      because the content is approaching the column height anyway.

    Implementation note: cases 0 / 1 / 3+ paint to a scratch image so
    we can measure the rendered height, then composite at the chosen
    vertical offset. Pillow can't measure imperative drawing ahead of
    time, so the two-pass render is the price for clean centering.
    """
    P = ctx.palette
    lead = active[0] if active else None
    rest = active[1:]

    # Case: no house data. Say so rather than announcing a calm house.
    if ha.get("unavailable"):
        _draw_no_data_lead(draw, ctx, box)
        return

    # Case: exactly two active items -- render as paired co-leads.
    # This branch paints directly so the divider lands at the midline.
    if lead is not None and len(rest) == 1:
        _draw_two_co_leads(draw, ctx, ha, [lead, rest[0]], box)
        return

    # All other branches use the scratch-image / measure / center
    # approach so the lead doesn't hug the top when the column has
    # significant vertical slack. The scratch is sized to 2x the box
    # height so an overflowing brief gets fully painted on the scratch
    # (where we can crop it cleanly) instead of being silently clipped
    # by Pillow at the scratch edge.
    bg = P.bg
    scratch = Image.new("RGB", (box.w, box.h * 2), bg)
    sdraw = ImageDraw.Draw(scratch)

    if lead is None:
        y_end = _draw_calm_lead(sdraw, ctx, ha, 0, 0, box.w)
    elif not rest and lead.kind in _FEATURE_BUILDERS:
        y_end = _draw_feature(scratch, sdraw, ctx, lead, box.w)
    else:
        y_end = _draw_lead(sdraw, ctx, ha, lead, 0, 0, box.w)
        if rest:
            # Briefs are added one at a time; we stop as soon as the
            # next brief wouldn't fit. If any were dropped, the kicker
            # is augmented with a "+ N more" tail so the user knows
            # there are background tasks not on screen.
            kfont = fonts.pix_cherry_small(
                layout.EditorialType.KICKER_PX, bold=True,
            )
            fm_k = font_metrics(kfont)
            brief_row_h = 40
            divider_h = 10 + 5
            kicker_h = fm_k.line_height + 8
            limit_y = box.h
            # How many briefs fit?
            available = limit_y - (y_end + divider_h + kicker_h)
            max_fits = max(0, available // brief_row_h)
            shown = list(rest[:max_fits])
            hidden = len(rest) - len(shown)
            if shown:
                double_hr(sdraw, 0, box.w, y_end + 10, fill=P.rule, gap=2)
                y_end += divider_h
                kicker_text = "Also Active"
                if hidden > 0:
                    kicker_text += f"  \u00b7  +{hidden} more"
                _draw_kicker(
                    sdraw,
                    Box(0, y_end + 6, box.w, y_end + 6 + fm_k.line_height),
                    text=kicker_text, P=P,
                )
                y_end += kicker_h
                for idx, item in enumerate(shown):
                    y_end = _draw_brief(
                        sdraw, ctx, ha, 0, y_end, box.w, item,
                        last=(idx == len(shown) - 1),
                    )

    # Vertical distribution: leave 1/3 of slack at the top, 2/3 below.
    # This pulls the headline down toward the optical center without
    # making the column feel empty-bottomed. When content overflows
    # the column there's no slack to distribute -- top_pad falls to 0.
    rendered_h = min(box.h, y_end)
    slack = max(0, box.h - rendered_h)
    top_pad = slack // 3
    crop = scratch.crop((0, 0, box.w, rendered_h))
    img.paste(crop, (box.x0, box.y0 + top_pad))


def _draw_two_co_leads(draw, ctx: RenderContext, ha,
                       items: list, box: Box) -> None:
    """Render two equal-weight stories stacked vertically.

    Used when exactly two appliances are running so they read as
    co-leads rather than "one big + one tiny". The midline is a thin
    triple-rule horizontal divider (heavy + hairline + heavy).
    """
    P = ctx.palette
    # Reserve 14px in the middle for the divider stack.
    div_h = 14
    top_h = (box.h - div_h) // 2
    bot_h = box.h - div_h - top_h
    top_box = Box(box.x0, box.y0, box.x1, box.y0 + top_h)
    div_y = top_box.y1 + div_h // 2 - 2
    bot_box = Box(box.x0, top_box.y1 + div_h, box.x1, box.y1)

    _draw_co_lead_story(draw, ctx, items[0], top_box)
    # Divider: heavy (2px) + 2px gap + hairline.
    draw.rectangle([(box.x0, div_y), (box.x1 - 1, div_y + 1)], fill=P.rule)
    draw.rectangle([(box.x0, div_y + 4), (box.x1 - 1, div_y + 4)], fill=P.rule)
    _draw_co_lead_story(draw, ctx, items[1], bot_box)


# ── Co-lead story (data-driven, half-height) ──────────────────────────


def _draw_co_lead_story(draw, ctx: RenderContext,
                        item: ActiveAppliance, box: Box) -> None:
    """Compact magazine-style story used in the two-co-lead layout.

    Pure presentation -- reads ``item.view`` and dispatches text
    through ``_co_lead_descriptor`` so each kind contributes its own
    headline / deck / fact cells without rebuilding a full hero.
    """
    P = ctx.palette
    view = item.view
    accent = ctx.accent(view.accent_kind)

    descriptor = _co_lead_descriptor(view, ctx)

    # Kicker row with diamond + optional badge.
    kfont = fonts.pix_cherry_small(layout.EditorialType.KICKER_PX, bold=True)
    fm_k = font_metrics(kfont)
    _draw_diamond_kicker(
        draw, Box(box.x0, box.y0, box.x1, box.y0 + 18),
        text=view.eyebrow_kicker, P=P, accent=accent,
        badge=descriptor.get("badge"),
    )
    cur_y = box.y0 + fm_k.line_height + 6

    # Headline (22 px serif bold, max 2 lines).
    head_size = 22
    head_runs = descriptor["head_runs"]
    cur_y = draw_headline(
        draw, (box.x0, cur_y, box.w, head_size * 2 + 8),
        head_runs, line_height_px=head_size + 4, max_lines=2,
    )

    # Deck (one line, italic, muted).
    deck = descriptor.get("deck")
    if deck:
        deck_font = fonts.serif(13, italic=True, weight="semibold")
        cur_y = draw_paragraph(
            draw, (box.x0, cur_y + 4, box.w, 36),
            deck, font=deck_font, fill=P.muted, line_height_px=18,
            max_lines=2,
        )

    # Fact cells anchored at the bottom of the co-lead box so paired
    # stories' strips share a Y baseline.
    cells = descriptor.get("cells") or []
    if cells:
        cell_h = 38
        cells_y = box.y1 - cell_h - 4
        _draw_compact_fact_strip(draw, P, box.x0, cells_y, box.w, cells)


def _draw_compact_fact_strip(draw, P, x0, y, w, cells) -> int:
    """Two-or-three cell fact strip sized for the co-lead row.

    Same drawing approach as ``_draw_fact_strip`` but with tighter
    vertical proportions so two strips fit one above the other in the
    body column.
    """
    cell_w = w // max(1, len(cells))
    cell_h = 34
    draw.rectangle([(x0, y), (x0 + w - 1, y + 1)], fill=P.rule)
    bottom = y + 2 + cell_h
    label_font = fonts.pix_cherry_small(9, bold=True)
    tracking = em_to_px(9, 0.18)
    val_factory = lambda s: fonts.serif(s, weight="bold")
    val_candidates = (18, 17, 16, 14, 12)
    fm_l = font_metrics(label_font)
    inner_pad = 6
    for i, c in enumerate(cells):
        cx0 = x0 + i * cell_w
        if i > 0:
            draw.rectangle([(cx0, y + 2), (cx0, bottom - 1)], fill=P.rule)
        cell_cx = cx0 + cell_w // 2
        label = (c.get("k") or "").upper()
        label_baseline = y + 3 + fm_l.ascent
        max_label_w = cell_w - inner_pad * 2
        s_label = label
        while s_label and tracked_width(label_font, s_label, tracking) > max_label_w:
            s_label = s_label[:-1]
        if s_label:
            draw_tracked_text_bl_center(
                draw, (cell_cx, label_baseline),
                s_label, label_font, P.muted, tracking,
            )
        val = c.get("v") or "\u2014"
        color = c.get("accent") or P.ink
        val_font, _val_size = pick_fitting_size(
            val_factory, val, max(20, cell_w - inner_pad * 2), val_candidates,
        )
        fm_v = font_metrics(val_font)
        val_baseline = label_baseline + fm_l.descent + 2 + fm_v.ascent
        draw_text_bl_center(draw, (cell_cx, val_baseline), val, val_font, color)
    return bottom + 2


# Per-kind descriptors for co-lead stories. Each builder returns a
# dict with `head_runs`, optional `deck`, `cells` (list of {k, v}),
# and an optional `badge` (e.g. "UNLOAD"). Keeping this table next to
# EDITORIAL_LEAD_DRAWERS makes it obvious that adding a new appliance
# means adding *two* rows: one full-hero drawer + one co-lead builder.


def _co_lead_runs_normal_italic(size: int = 22):
    return (fonts.serif(size, weight="bold"),
            fonts.serif(size, italic=True, weight="bold"))


def _co_washer(view: ApplianceView, ctx: RenderContext) -> dict:
    P = ctx.palette
    norm, ital = _co_lead_runs_normal_italic()
    copy = flavor.pick_appliance_copy(view, ctx)
    runs = [Run(copy["head_pre"], norm, P.ink)]
    if copy["head_italic"]:
        runs.append(Run(copy["head_italic"], ital, P.ink))
    return {
        "head_runs": runs,
        "deck": copy["deck"],
        "cells": [
            {"k": "Remaining", "v": view.remaining_label,
             "accent": ctx.accent(view.accent_kind)},
            {"k": "Done by",   "v": view.finish_label},
        ],
    }


def _co_washer_done(view: ApplianceView, ctx: RenderContext) -> dict:
    P = ctx.palette
    norm, ital = _co_lead_runs_normal_italic()
    copy = flavor.done_copy(view, ctx)
    return {
        "head_runs": [Run(copy["head_pre"], norm, P.ink),
                      Run(copy["head_italic"], ital, P.ink)],
        "deck": copy["deck"],
        "cells": [
            {"k": "Finished", "v": view.finish_label,
             "accent": ctx.accent(view.accent_kind)},
            {"k": "Ago",      "v": view.relative_label or "\u2014"},
        ],
        "badge": "UNLOAD",
    }


def _co_dryer(view: ApplianceView, ctx: RenderContext) -> dict:
    P = ctx.palette
    norm, ital = _co_lead_runs_normal_italic()
    copy = flavor.pick_appliance_copy(view, ctx)
    runs = [Run(copy["head_pre"], norm, P.ink)]
    if copy["head_italic"]:
        runs.append(Run(copy["head_italic"], ital, P.ink))
    return {
        "head_runs": runs,
        "deck": copy["deck"],
        "cells": [
            {"k": "Remaining", "v": view.remaining_label,
             "accent": ctx.accent(view.accent_kind)},
            {"k": "Done by",   "v": view.finish_label},
        ],
    }


def _co_dryer_done(view: ApplianceView, ctx: RenderContext) -> dict:
    P = ctx.palette
    norm, ital = _co_lead_runs_normal_italic()
    copy = flavor.done_copy(view, ctx)
    return {
        "head_runs": [Run(copy["head_pre"], norm, P.ink),
                      Run(copy["head_italic"], ital, P.ink)],
        "deck": copy["deck"],
        "cells": [
            {"k": "Finished", "v": view.finish_label,
             "accent": ctx.accent(view.accent_kind)},
            {"k": "Ago",      "v": view.relative_label or "\u2014"},
        ],
        "badge": "UNLOAD",
    }


def _co_dishwasher(view: ApplianceView, ctx: RenderContext) -> dict:
    P = ctx.palette
    norm, ital = _co_lead_runs_normal_italic()
    prog = view.progress_pct
    prog_s = f"{prog}%" if prog is not None else "\u2014"
    copy = flavor.pick_appliance_copy(view, ctx)
    runs = [Run(copy["head_pre"], norm, P.ink)]
    if copy["head_italic"]:
        runs.append(Run(copy["head_italic"], ital, P.ink))
    return {
        "head_runs": runs,
        "deck": copy["deck"],
        "cells": [
            {"k": "Progress", "v": prog_s,
             "accent": ctx.accent(view.accent_kind)},
            {"k": "Finish",   "v": view.finish_label},
        ],
    }


def _co_sauna(view: ApplianceView, ctx: RenderContext) -> dict:
    P = ctx.palette
    norm, ital = _co_lead_runs_normal_italic()
    accent = ctx.accent(view.accent_kind)
    forecast = view.extras.get("forecast")
    if forecast:
        head, tail, deck = flavor.sauna_forecast_copy(view, forecast, ctx, READY_F)
        ready = forecast["ready_label"] or "\u2014"
        return {
            "head_runs": [Run(head, norm, P.ink), Run(tail, ital, accent)],
            "deck": deck,
            "cells": [
                {"k": "Room", "v": fmt_temp(view.extras.get("room_temp")),
                 "accent": accent},
                {"k": "Ready" if not forecast["ready_reached"] else "Reached",
                 "v": ready},
            ],
        }
    return {
        "head_runs": [Run("Cabin warming to ", norm, P.ink),
                      Run(f"{fmt_temp(view.target)}.", ital, accent)],
        "deck": (f"Now {fmt_temp(view.current)} \u00b7 "
                 f"{view.extras.get('heaters', 0)}/3 elements."),
        "cells": [
            {"k": "Cabin",  "v": fmt_temp(view.current), "accent": accent},
            {"k": "Target", "v": fmt_temp(view.target)},
        ],
    }


def _co_pool(view: ApplianceView, ctx: RenderContext) -> dict:
    P = ctx.palette
    norm, ital = _co_lead_runs_normal_italic()
    head, tail, _deck = flavor.pool_copy(view, ctx)
    return {
        "head_runs": [Run(head, norm, P.ink),
                      Run(tail, ital, ctx.accent(view.accent_kind))],
        "deck": (f"Water {fmt_temp(view.current)} \u00b7 "
                 f"air {fmt_temp(view.extras.get('air_temp'))}."),
        "cells": [
            {"k": "Water",  "v": fmt_temp(view.current),
             "accent": ctx.accent(view.accent_kind)},
            {"k": "Target", "v": fmt_temp(view.target)},
        ],
    }


def _co_unknown(view: ApplianceView, ctx: RenderContext) -> dict:
    P = ctx.palette
    norm, _ital = _co_lead_runs_normal_italic()
    return {
        "head_runs": [Run(view.kind.replace("-", " ").title() + ".",
                          norm, P.ink)],
        "deck": None,
        "cells": [],
    }


_CO_LEAD_DESCRIBERS = {
    "sauna":        _co_sauna,
    "washer":       _co_washer,
    "washer-done":  _co_washer_done,
    "dryer":        _co_dryer,
    "dryer-done":   _co_dryer_done,
    "dishwasher":   _co_dishwasher,
    "pool":         _co_pool,
}


def _co_lead_descriptor(view: ApplianceView, ctx: RenderContext) -> dict:
    """Build the co-lead descriptor for `view`. Falls back to a minimal
    placeholder for any kind not yet wired into ``_CO_LEAD_DESCRIBERS``."""
    builder = _CO_LEAD_DESCRIBERS.get(view.kind, _co_unknown)
    return builder(view, ctx)


def _draw_no_data_lead(draw, ctx: RenderContext, box: Box) -> None:
    """Home Assistant gave us nothing: this edition carries no house news."""
    P = ctx.palette
    kicker_font = fonts.pix_cherry_small(10, bold=True)
    fm_k = font_metrics(kicker_font)
    head_font = fonts.serif(32, weight="bold")
    fm_h = font_metrics(head_font)
    y = box.y0 + box.h // 4
    draw_tracked_text_bl(draw, (box.x0, y + fm_k.ascent), "STOP PRESS",
                         kicker_font, P.ink, em_to_px(10, 0.30))
    y += fm_k.line_height + 8
    draw_text_bl(draw, (box.x0, y + fm_h.ascent), "No news from the house.",
                 head_font, P.ink)
    y += fm_h.line_height + 4
    deck_font = fonts.serif(16, italic=True, weight="semibold")
    y = draw_paragraph(
        draw, (box.x0, y, box.w, 48),
        "Home Assistant isn't answering. Readings on this page are unknown, "
        "not calm.",
        font=deck_font, fill=P.ink, line_height_px=22, max_lines=2,
    )
    double_hr(draw, box.x0, box.x1, y + 8, fill=P.rule)


def _draw_calm_lead(draw, ctx: RenderContext, ha, x0, y, w) -> int:
    """Calm-state hero. The "All quiet" headline is compact so the
    hourly-rotating snippet (AI-generated when available,
    ``flavor.fallback_idle_snippet`` otherwise) gets to be the visual
    focal point under the double-rule."""
    P = ctx.palette
    kicker_font = fonts.pix_cherry_small(10, bold=True)
    k_tracking = em_to_px(10, 0.30)
    fm_k = font_metrics(kicker_font)
    star_sz = 8
    copy = flavor.calm_copy(ctx, ha)
    kicker_label = copy["kicker"]
    label_w = tracked_width(kicker_font, kicker_label, k_tracking)
    block_w = star_sz + 8 + label_w + 8 + star_sz
    block_x = x0 + max(0, (w - block_w) // 2)
    kicker_baseline = y + fm_k.ascent
    draw_star_marker(draw, block_x, kicker_baseline,
                     size=star_sz, fill=P.muted)
    draw_tracked_text_bl(draw, (block_x + star_sz + 8, kicker_baseline),
                         kicker_label, kicker_font, P.muted, k_tracking)
    draw_star_marker(draw, block_x + star_sz + 8 + label_w + 8,
                     kicker_baseline, size=star_sz, fill=P.muted)
    # Compact headline: 26-28 px serif (vs the old 38 px) keeps the
    # editorial flag but leaves room below for a much larger snippet.
    head_font = fonts.serif(26, weight="bold")
    italic_font = fonts.serif(26, italic=True, weight="bold")
    fm_h = font_metrics(head_font)
    line_height = fm_h.line_height + 1
    cur_y = y + fm_k.line_height + 6
    baseline = cur_y + fm_h.ascent
    # Try to fit the headline on a single line; fall back to two lines if it
    # doesn't measure.
    one_line = copy["head_pre"]
    tail = copy["head_italic"]
    one_line_w = text_width(head_font, one_line) + text_width(italic_font, tail)
    if one_line_w <= w:
        draw_text_bl(draw, (x0, baseline), one_line, head_font, P.ink)
        draw_text_bl(draw, (x0 + text_width(head_font, one_line), baseline),
                     tail, italic_font, P.ink)
    else:
        draw_text_bl(draw, (x0, baseline), one_line.rstrip(), head_font, P.ink)
        baseline += line_height
        draw_text_bl(draw, (x0, baseline), tail, italic_font, P.ink)
    cur_y = baseline + fm_h.descent + 4
    deck_font = fonts.serif(12, italic=True, weight="semibold")
    fm_d = font_metrics(deck_font)
    draw_text_bl(draw, (x0, cur_y + fm_d.ascent),
                 copy["deck"], deck_font, P.muted)
    cur_y += fm_d.line_height + 5
    double_hr(draw, x0, x0 + w, cur_y, fill=P.rule)
    cur_y += 10

    snippet = _resolve_idle_snippet(ctx, ha)
    cur_y = _draw_idle_snippet_block(draw, ctx, x0, cur_y, w, snippet)
    return cur_y


def _resolve_idle_snippet(ctx: RenderContext, ha: dict) -> dict:
    """Pick the snippet to render in the calm body.

    Priority:
    1. ``ha['dashboardSnippet']`` (populated by the renderer when the
       cron-generated row is available for the current local hour).
    2. ``flavor.fallback_idle_snippet`` (curated quotes + computed
       calendar facts).

    Returned dict shape: ``{"kind": str, "text": str, "byline": str}``.
    """
    candidate = ha.get("dashboardSnippet")
    if isinstance(candidate, dict):
        text = (candidate.get("text") or "").strip()
        if text:
            return {
                "kind": str(candidate.get("kind") or "quote"),
                "text": text,
                "byline": str(candidate.get("byline") or "").strip(),
            }
    return flavor.fallback_idle_snippet(ctx)


_SNIPPET_KICKER = {
    "quote": "QUOTE OF THE HOUR",
    "observation": "OBSERVED THIS HOUR",
}


def _draw_idle_snippet_block(draw, ctx: RenderContext, x0: int, y: int,
                             w: int, snippet: dict) -> int:
    """Render the snippet body + byline under the calm hero.

    Quotes get wrapped in curly quotes and rendered in italic so the
    feel is closer to a magazine pull-quote; observations stay in
    upright serif to read as a fact box. Both are sized to be the
    visual focal point of the calm hero (the headline above is
    intentionally compact to give this block the room).
    """
    P = ctx.palette
    kind = snippet.get("kind") or "quote"
    text = snippet.get("text") or ""
    byline = snippet.get("byline") or ""

    sub_kicker_font = fonts.pix_cherry_small(10, bold=True)
    sub_tracking = em_to_px(10, 0.22)
    fm_sub = font_metrics(sub_kicker_font)
    kicker_text = _SNIPPET_KICKER.get(kind, "NOTE OF THE HOUR")
    sub_baseline = y + fm_sub.ascent
    draw_tracked_text_bl(draw, (x0, sub_baseline), kicker_text,
                         sub_kicker_font, P.muted, sub_tracking)
    cur_y = y + fm_sub.line_height + 8

    # Snippet body candidates -- pick the largest that lets the rendered
    # paragraph fit the remaining lead column height (we cap at 5 lines
    # so a verbose quote doesn't push the byline off the panel).
    if kind == "quote":
        size_candidates = (22, 20, 18, 17, 16)
        font_factory = lambda s: fonts.serif(s, italic=True, weight="semibold")
        body_text = "\u201c" + text + "\u201d"
    else:
        size_candidates = (20, 19, 18, 17, 16)
        font_factory = lambda s: fonts.serif(s, weight="semibold")
        body_text = text
    body_font = _pick_snippet_size(font_factory, body_text, w, size_candidates)
    fm_b = font_metrics(body_font)
    line_h = fm_b.line_height + 3
    end_y = draw_paragraph(
        draw, (x0, cur_y, w, line_h * 5),
        body_text, font=body_font, fill=P.ink,
        line_height_px=line_h, max_lines=5,
    )
    cur_y = end_y + 8

    if byline:
        byline_font = fonts.serif(13, italic=True, weight="semibold")
        fm_y = font_metrics(byline_font)
        baseline = cur_y + fm_y.ascent
        draw_text_bl_right(draw, (x0 + w, baseline),
                           "\u2014 " + byline, byline_font, P.muted)
        cur_y = baseline + fm_y.descent + 2
    return cur_y


def _pick_snippet_size(factory, text: str, w: int, sizes):
    """Pick the largest snippet size that fits in <=4 lines.

    Falls back to the smallest candidate. ``draw_paragraph`` will then
    cap whatever's left at 5 lines, so this just biases the typography
    toward "big when it can be."
    """
    for size in sizes:
        font = factory(size)
        if _wrap_line_count(font, text, w) <= 4:
            return font
    return factory(sizes[-1])


def _wrap_line_count(font, text: str, w: int) -> int:
    """Approximate line count for a word-wrapped paragraph in width ``w``."""
    if not text:
        return 0
    words = text.split(" ")
    lines = 1
    cur = ""
    for word in words:
        candidate = word
        if cur:
            candidate = cur + " " + word
        if text_width(font, candidate) <= w:
            cur = candidate
        else:
            lines += 1
            cur = word
    return lines


def _draw_lead(draw, ctx: RenderContext, ha, item: ActiveAppliance, x0, y, w) -> int:
    """Dispatch to the per-kind lead drawer via the EDITORIAL_DRAWERS map.
    Each drawer consumes ``item.view`` (an ApplianceView) so nothing here
    or downstream calls ``fmt_clock`` against a raw HA timestamp."""
    drawer = EDITORIAL_LEAD_DRAWERS.get(item.kind, _draw_unknown_lead)
    return drawer(draw, ctx, ha, item, x0, y, w)


def _draw_story_shell(draw, P, x0, y, w, *, kicker, accent, headline_runs,
                      deck=None, body=None, badge=None) -> int:
    """Magazine lead: kicker -> 8px -> headline -> 12px -> deck -> 10px -> body.

    Every text block has a hard `max_lines` cap so a long status label or
    long program string can never push the fact strip off the body box.
    The headline auto-shrinks to 2 lines max; the deck wraps to 2 max;
    the body wraps to 4 max.
    """
    kfont = fonts.pix_cherry_small(layout.EditorialType.KICKER_PX, bold=True)
    fm_k = font_metrics(kfont)
    _draw_diamond_kicker(draw, Box(x0, y, x0 + w, y + 18),
                         text=kicker, P=P, accent=accent, badge=badge)
    cur_y = y + fm_k.line_height + 8
    cur_y = draw_headline(draw, (x0, cur_y, w, 100), headline_runs,
                          line_height_px=32, align="left",
                          max_lines=2)
    if deck:
        deck_font = fonts.serif(14, italic=True, weight="semibold")
        cur_y = draw_paragraph(draw, (x0, cur_y + 6, w, 36),
            deck, font=deck_font, fill=P.muted, line_height_px=18,
            max_lines=2)
    if body:
        body_font = fonts.serif(13)
        cur_y = draw_paragraph(draw, (x0, cur_y + 6, w, 80),
            body, font=body_font, fill=P.ink, line_height_px=18,
            max_lines=4)
    return cur_y


def _draw_thermometer(draw, P, x0, y, w, *, from_v, to_v, now, target,
                      accent, units="\u00b0", hide_target=False) -> int:
    if now is None:
        return y
    nowf = float(now)
    pct = lerp_pct(nowf, from_v, to_v)
    segs = 32
    fill_count = round(pct * segs)
    bar_h = 12
    bar_y1 = y + bar_h
    draw.rectangle([(x0, y), (x0 + w - 1, bar_y1 - 1)], outline=P.rule, width=1)
    seg_w = (w - 2) / segs
    for i in range(segs):
        sx0 = x0 + 1 + int(i * seg_w)
        sx1 = x0 + 1 + int((i + 1) * seg_w)
        if i < fill_count:
            draw.rectangle([(sx0, y + 1), (sx1 - 1, bar_y1 - 2)], fill=accent)
        elif i % 4 == 0:
            cx = (sx0 + sx1) // 2
            draw.rectangle([(cx, y + 2), (cx, bar_y1 - 3)], fill=P.muted)
    if not hide_target and target is not None:
        tpct = lerp_pct(float(target), from_v, to_v)
        tx = x0 + int(tpct * (w - 2))
        draw.rectangle([(tx, y - 3), (tx + 1, bar_y1 + 2)], fill=P.ink)
    lf = fonts.pix_cherry_small(9, bold=True)
    tracking = em_to_px(9, 0.10)
    fm = font_metrics(lf)
    ly = bar_y1 + 4 + fm.ascent
    draw_tracked_text_bl(draw, (x0, ly), f"{int(from_v)}{units}", lf, P.muted, tracking)
    mid = f"NOW {int(round(nowf))}{units}"
    draw_tracked_text_bl_center(draw, (x0 + w // 2, ly), mid, lf, P.ink, tracking)
    right = f"{int(to_v)}{units}"
    draw_tracked_text_bl_right(draw, (x0 + w, ly), right, lf, P.muted, tracking)
    return ly + fm.descent + 2


def _draw_fact_strip(draw, P, x0, y, w, cells) -> int:
    """Newspaper-style fact strip with `len(cells)` columns.

    Each cell's value runs through `pick_fitting_size` against the cell
    width so an outlier (`"2h45m"`, `"#199"`) shrinks just its own cell,
    not the whole row. The label and the optional sub-line use clipped
    drawing so a long label degrades to an ellipsis rather than crossing
    the cell rule.
    """
    cell_w = w // max(1, len(cells))
    draw.rectangle([(x0, y), (x0 + w - 1, y + 1)], fill=P.rule)
    label_font = fonts.pix_cherry_small(9, bold=True)
    tracking = em_to_px(9, 0.18)
    val_factory = lambda s: fonts.serif(s, weight="bold")
    val_candidates = (22, 20, 18, 16, 14)
    sub_font = fonts.pix_cherry_small(9, bold=True)
    sub_tracking = em_to_px(9, 0.10)
    fm_l = font_metrics(label_font)
    fm_s = font_metrics(sub_font)
    # A sub-line needs a taller strip, or it falls below the cell and collides
    # with whatever follows (or is cropped when nothing does).
    cell_h = 48
    if any(c.get("sub") for c in cells):
        fm_big = font_metrics(val_factory(val_candidates[0]))
        cell_h = max(cell_h, 4 + fm_l.ascent + fm_l.descent + 4 + fm_big.ascent
                     + fm_big.descent + 2 + fm_s.ascent + fm_s.descent)
    bottom = y + 2 + cell_h
    inner_pad = 6  # px reserved at each side of a cell for the value fit.
    for i, c in enumerate(cells):
        cx0 = x0 + i * cell_w
        cx1 = cx0 + cell_w
        if i > 0:
            draw.rectangle([(cx0, y + 2), (cx0, bottom - 1)], fill=P.rule)
        cell_cx = cx0 + cell_w // 2
        label = (c.get("k") or "").upper()
        label_baseline = y + 4 + fm_l.ascent
        # Clip the label to the cell (minus inner pad). Anything over goes
        # to ellipsis rather than crossing the cell rule.
        from .draw import draw_text_clipped_bl_right  # local alias is fine.
        # Centered tracked label, but we still cap by the cell width
        # (the tracking helper has no clipping, so pre-truncate).
        max_label_w = cell_w - inner_pad * 2
        s_label = label
        while s_label and tracked_width(label_font, s_label, tracking) > max_label_w:
            s_label = s_label[:-1]
        if s_label:
            draw_tracked_text_bl_center(draw, (cell_cx, label_baseline),
                s_label, label_font, P.muted, tracking)
        val = c.get("v") or "\u2014"
        color = c.get("accent") or P.ink
        val_font, _val_size = pick_fitting_size(
            val_factory, val, max(20, cell_w - inner_pad * 2), val_candidates,
        )
        fm_v = font_metrics(val_font)
        val_baseline = label_baseline + fm_l.descent + 4 + fm_v.ascent
        draw_text_bl_center(draw, (cell_cx, val_baseline), val, val_font, color)
        sub = c.get("sub")
        if sub:
            sub_baseline = val_baseline + fm_v.descent + 2 + fm_s.ascent
            s_sub = sub.upper()
            while s_sub and tracked_width(sub_font, s_sub, sub_tracking) > max_label_w:
                s_sub = s_sub[:-1]
            if s_sub:
                draw_tracked_text_bl_center(draw, (cell_cx, sub_baseline),
                    s_sub, sub_font, P.muted, sub_tracking)
    return bottom + 2


# ── Lead variants ──────────────────────────────────────────────────────


def _hero_font():
    return fonts.serif(32, weight="bold")


def _hero_italic_bold_font():
    return fonts.serif(32, italic=True, weight="bold")


def _draw_sauna_forecast_lead(draw, ctx: RenderContext, view: ApplianceView,
                              forecast: dict, x0, y, w) -> int:
    """Heat-up forecast card: when it's ready, both sensors, and the fan plan."""
    P = ctx.palette
    accent = ctx.accent(view.accent_kind)
    head, tail, deck = flavor.sauna_forecast_copy(view, forecast, ctx, READY_F)
    runs = [Run(head, _hero_font(), P.ink),
            Run(tail, _hero_italic_bold_font(), accent)]
    cur_y = _draw_story_shell(draw, P, x0, y, w,
        kicker=view.eyebrow_kicker, accent=accent,
        badge="READY" if forecast["ready_reached"] else "LIVE",
        headline_runs=runs, deck=deck)
    room = view.extras.get("room_temp")
    cur_y += 12
    cur_y = _draw_thermometer(draw, P, x0, cur_y, w,
        from_v=60, to_v=READY_F, now=room, target=None,
        accent=accent, hide_target=True)
    humidity = view.extras.get("room_humidity_pct")
    # A controller-preset session reports 32°F, which isn't a real target.
    goal = fmt_temp(view.target) if 104 <= (view.target or 0) <= 212 else "PRESET"
    if forecast["target_reached"]:
        target_sub = "REACHED"
    elif forecast["target_label"]:
        target_sub = f"IN {forecast['target_in']}"
    else:
        target_sub = "ABOVE TARGET"
    cur_y = _draw_fact_strip(draw, P, x0, cur_y + 6, w, [
        {"k": "Room", "v": fmt_temp(room), "accent": accent,
         "sub": None if humidity is None else f"{humidity}% RH"},
        {"k": "Thermostat", "v": fmt_temp(view.current),
         "sub": f"GOAL {goal}"},
        {"k": f"{TARGET_F}\u00b0 at",
         "v": forecast["target_label"] or "\u2014", "sub": target_sub},
        {"k": "Fan", "v": forecast["fan_label"], "sub": forecast["fan_note"]},
    ])
    return cur_y


def _draw_sauna_lead(draw, ctx: RenderContext, ha, item: ActiveAppliance, x0, y, w) -> int:
    P = ctx.palette
    view = item.view
    forecast = view.extras.get("forecast")
    if forecast:
        return _draw_sauna_forecast_lead(draw, ctx, view, forecast, x0, y, w)
    accent = ctx.accent(view.accent_kind)
    target = view.target
    current = view.current
    remaining = view.extras.get("remaining_deg")
    runs = [
        Run("The sauna is ", _hero_font(), P.ink),
        Run("warming", _hero_italic_bold_font(), accent),
        Run("\n", _hero_font(), P.ink),
        Run(f"to {fmt_temp(target)}.", _hero_font(), P.ink),
    ]
    if remaining is not None:
        heaters = view.extras.get("heaters", 0)
        door = "open" if view.extras.get("door_open") else "closed"
        deck = (f"Cabin presently {fmt_temp(current)}, with {int(remaining)}\u00b0 "
                f"left to climb. {heaters} of three elements lit; door {door}.")
    else:
        deck = f"Cabin holding at {fmt_temp(current)}."
    cur_y = _draw_story_shell(draw, P, x0, y, w,
        kicker=view.eyebrow_kicker, accent=accent,
        badge="LIVE", headline_runs=runs, deck=deck)
    cur_y += 12
    cur_y = _draw_thermometer(draw, P, x0, cur_y, w,
        from_v=60, to_v=max(float(target or 175), 175),
        now=current, target=target, accent=accent)
    cur_y = _draw_fact_strip(draw, P, x0, cur_y + 6, w, [
        {"k": "Cabin", "v": fmt_temp(current), "accent": accent},
        {"k": "Target", "v": fmt_temp(target)},
        {"k": "Elements", "v": f"{view.extras.get('heaters', 0)}/3"},
        {"k": "Room", "v": fmt_temp(view.extras.get("room_temp")),
         "sub": (None if view.extras.get("room_humidity_pct") is None
                 else f"{view.extras['room_humidity_pct']}% RH")},
    ])
    return cur_y


def _draw_washer_lead(draw, ctx: RenderContext, ha, item: ActiveAppliance, x0, y, w) -> int:
    P = ctx.palette
    view = item.view
    accent = ctx.accent(view.accent_kind)
    copy = flavor.pick_appliance_copy(view, ctx)
    runs = [Run(copy["head_pre"], _hero_font(), P.ink)]
    if copy["head_italic"]:
        runs.append(Run(copy["head_italic"], _hero_italic_bold_font(), P.ink))
    deck = copy["deck"]
    cur_y = _draw_story_shell(draw, P, x0, y, w,
        kicker=view.eyebrow_kicker, accent=accent,
        headline_runs=runs, deck=deck)
    energy = view.extras.get("energy_kwh_month") or 0.0
    cur_y = _draw_fact_strip(draw, P, x0, cur_y + 6, w, [
        {"k": "Remaining", "v": view.remaining_label, "accent": accent},
        {"k": "Done by", "v": view.finish_label},
        {"k": "Cycle", "v": f"#{view.extras.get('cycle_no', 0)}"},
        {"k": "Mo. kWh", "v": f"{float(energy):.2f}"},
    ])
    return cur_y


def _done_headline(copy: dict, P: Palette) -> list[Run]:
    """Two explicit lines: the news, then the instruction.

    Each line must fit the column: `draw_headline` drops lines past its limit, so an
    auto-wrapped first line would cost the instruction its ending.
    """
    return [
        Run(copy["head_pre"], _hero_font(), P.ink),
        Run("\n", _hero_font(), P.ink),
        Run(copy["head_italic"].strip(), _hero_italic_bold_font(), P.ink),
    ]


def _draw_washer_done_lead(draw, ctx: RenderContext, ha, item: ActiveAppliance, x0, y, w) -> int:
    P = ctx.palette
    view = item.view
    accent = ctx.accent(view.accent_kind)
    copy = flavor.done_copy(view, ctx)
    return _draw_story_shell(draw, P, x0, y, w,
        kicker=view.eyebrow_kicker, accent=accent,
        badge="UNLOAD", headline_runs=_done_headline(copy, P), deck=copy["deck"])


_EDITORIAL_DRYER_PHASE_HEADS = {
    "cooling":      "Cooling down.",
    "wrinkle_care": "Wrinkle care.",
    "pause":        "Paused.",
}


def _draw_dryer_lead(draw, ctx: RenderContext, ha, item: ActiveAppliance, x0, y, w) -> int:
    P = ctx.palette
    view = item.view
    accent = ctx.accent(view.accent_kind)
    phase = view.extras.get("phase") or "running"
    copy = flavor.pick_appliance_copy(view, ctx)
    runs = [Run(copy["head_pre"], _hero_font(), P.ink)]
    if copy["head_italic"]:
        runs.append(Run(copy["head_italic"], _hero_italic_bold_font(), P.ink))
    deck = copy["deck"]
    cur_y = _draw_story_shell(draw, P, x0, y, w,
        kicker=view.eyebrow_kicker, accent=accent,
        headline_runs=runs, deck=deck)
    cur_y = _draw_fact_strip(draw, P, x0, cur_y + 6, w, [
        {"k": "Remaining", "v": view.remaining_label, "accent": accent},
        {"k": "Done by", "v": view.finish_label},
        {"k": "Phase", "v": title_case(phase.replace("_", " "))},
    ])
    return cur_y


def _draw_dryer_done_lead(draw, ctx: RenderContext, ha, item: ActiveAppliance, x0, y, w) -> int:
    P = ctx.palette
    view = item.view
    accent = ctx.accent(view.accent_kind)
    copy = flavor.done_copy(view, ctx)
    return _draw_story_shell(draw, P, x0, y, w,
        kicker=view.eyebrow_kicker, accent=accent,
        badge="UNLOAD", headline_runs=_done_headline(copy, P), deck=copy["deck"])


def _draw_dishwasher_lead(draw, ctx: RenderContext, ha, item: ActiveAppliance, x0, y, w) -> int:
    P = ctx.palette
    view = item.view
    accent = ctx.accent(view.accent_kind)
    prog = view.progress_pct
    prog_pct = f"{prog}%" if prog is not None else "\u2014"
    copy = flavor.pick_appliance_copy(view, ctx)
    runs = [Run(copy["head_pre"], _hero_font(), P.ink)]
    if copy["head_italic"]:
        runs.append(Run(copy["head_italic"], _hero_italic_bold_font(), P.ink))
    deck = copy["deck"]
    cur_y = _draw_story_shell(draw, P, x0, y, w,
        kicker=view.eyebrow_kicker, accent=accent,
        headline_runs=runs, deck=deck)
    if prog is not None:
        cur_y += 12
        cur_y = _draw_thermometer(draw, P, x0, cur_y, w,
            from_v=0, to_v=100, now=prog, target=None,
            accent=accent, units="%", hide_target=True)
    door = view.extras.get("door_state") or ""
    door_label = "Closed" if door == "closed" else title_case(door)
    cur_y = _draw_fact_strip(draw, P, x0, cur_y + 6, w, [
        {"k": "Progress", "v": prog_pct, "accent": accent},
        {"k": "Finish", "v": view.finish_label},
        {"k": "Door", "v": door_label or "\u2014"},
    ])
    return cur_y


def _draw_pool_lead(draw, ctx: RenderContext, ha, item: ActiveAppliance, x0, y, w) -> int:
    P = ctx.palette
    view = item.view
    accent = ctx.accent(view.accent_kind)
    target = view.target
    current = view.current
    head, tail, deck = flavor.pool_copy(view, ctx)
    runs = [Run(head, _hero_font(), P.ink),
            Run(tail, fonts.serif(32, italic=True, weight="bold"), accent)]
    air = view.extras.get("air_temp")
    cur_y = _draw_story_shell(draw, P, x0, y, w,
        kicker=view.eyebrow_kicker, accent=accent,
        headline_runs=runs, deck=deck)
    cur_y += 12
    cur_y = _draw_thermometer(draw, P, x0, cur_y, w,
        from_v=50, to_v=max(float(target or 90), 90),
        now=current, target=target, accent=accent)
    cur_y = _draw_fact_strip(draw, P, x0, cur_y + 6, w, [
        {"k": "Water", "v": fmt_temp(current), "accent": accent},
        {"k": "Target", "v": fmt_temp(target)},
        {"k": "Air", "v": fmt_temp(air)},
        {"k": "Pump", "v": "On" if view.extras.get("pump_running") else "Off"},
    ])
    return cur_y


def _draw_unknown_lead(draw, ctx: RenderContext, ha, item: ActiveAppliance, x0, y, w) -> int:
    """Fallback for an appliance the registry knows about but Editorial
    has no drawer for. Renders a minimal kicker so layout doesn't break."""
    view = item.view
    accent = ctx.accent(view.accent_kind)
    return _draw_story_shell(draw, ctx.palette, x0, y, w,
        kicker=view.eyebrow_kicker, accent=accent,
        headline_runs=[Run(view.kind.replace("-", " ").title() + ".",
                           _hero_font(), ctx.palette.ink)])


# Per-design dispatch table. Adding a new appliance = add a row here +
# add the corresponding spec to ``appliances.APPLIANCES`` + add a brief
# variant below in ``EDITORIAL_BRIEFS`` if it can also appear as "also
# active".
EDITORIAL_LEAD_DRAWERS = {
    "sauna":        _draw_sauna_lead,
    "washer":       _draw_washer_lead,
    "washer-done":  _draw_washer_done_lead,
    "dryer":        _draw_dryer_lead,
    "dryer-done":   _draw_dryer_done_lead,
    "dishwasher":   _draw_dishwasher_lead,
    "pool":         _draw_pool_lead,
}


# ── Feature card (the only thing happening in the house) ───────────────


@dataclass(frozen=True)
class _Feature:
    """What one appliance contributes to the single-activity card."""
    kicker: str
    head_pre: str
    head_italic: str
    deck: str
    # (img, draw, y, w) -> y below the meter.
    meter: Callable[[Image.Image, Any, int, int], int]
    cells: list[dict]
    icon_phase: str = ""
    badge: Optional[str] = None
    italic_accent: bool = False


_WASHER_STATIONS = ("WASH", "RINSE", "SPIN", "DONE")
_DRYER_STATIONS = ("DRY", "COOL", "CARE", "DONE")
_ICON_GAP = 12
_FEATURE_HEAD_SIZES = (30, 28, 26, 24, 22)


def _feature_headline(feature: _Feature, ink, accent, w: int) -> tuple[list[Run], int]:
    """The largest headline that fits two lines beside the icon, and its line height."""
    runs: list[Run] = []
    for size in _FEATURE_HEAD_SIZES:
        runs = [Run(feature.head_pre, fonts.serif(size, weight="bold"), ink)]
        if feature.head_italic:
            runs.append(Run(feature.head_italic, fonts.serif(size, italic=True, weight="bold"),
                            accent if feature.italic_accent else ink))
        if len(_wrap_runs_into_lines(runs, w)) <= 2:
            break
    return runs, runs[0].font.size + 3


def _draw_feature(img: Image.Image, draw, ctx: RenderContext, item: ActiveAppliance, w: int) -> int:
    """Icon and headline side by side, then the deck, the meter and the facts."""
    P = ctx.palette
    view = item.view
    accent = ctx.accent(view.accent_kind)
    feature = _FEATURE_BUILDERS[item.kind](view, ctx, accent)
    icons.draw_icon(img, 0, 0, kind=item.kind, phase=feature.icon_phase, ink=P.ink, fill=accent)

    text_x = icons.ICON_SIZE + _ICON_GAP
    text_w = w - text_x
    kfont = fonts.pix_cherry_small(layout.EditorialType.KICKER_PX, bold=True)
    _draw_diamond_kicker(draw, Box(text_x, 0, w, 18), text=feature.kicker, P=P, accent=accent,
                         badge=feature.badge)
    runs, line_height = _feature_headline(feature, P.ink, accent, text_w)
    head_y = font_metrics(kfont).line_height + 7
    y = draw_headline(draw, (text_x, head_y, text_w, line_height * 2), runs,
                      line_height_px=line_height, max_lines=2)
    y = max(y, icons.ICON_SIZE)
    if feature.deck:
        y = draw_paragraph(draw, (0, y + 7, w, 40), feature.deck,
                           font=fonts.serif(15, italic=True, weight="semibold"),
                           fill=P.muted, line_height_px=19, max_lines=2)
    y = feature.meter(img, draw, y + 9, w)
    if feature.cells:
        y = _draw_fact_strip(draw, P, 0, y + 9, w, feature.cells)
    return y


def _laundry_meter(view: ApplianceView, accent, *, stations, current: Optional[int]):
    """Time left and the finish, the cycle's progress, then where it is in its phases."""
    cycle = view.extras.get("cycle")

    def meter(img, draw, y, w, *, P):
        label = f"LEFT · {cycle['pct']}%" if cycle else "LEFT"
        y = meters.draw_meter_stats(draw, P, 0, y, w, value=view.remaining_label, value_label=label,
                                    accent=accent, right_value=view.finish_label,
                                    right_label="DONE BY")
        if cycle:
            segments = [meters.BarSegment(minutes) for _, minutes in cycle["segments"]]
            y = meters.draw_progress_bar(img, draw, P, 0, y + 5, w, pct=cycle["pct"],
                                         accent=accent, segments=segments)
        return meters.draw_phase_track(img, draw, P, 0, y + 7, w, stations=stations,
                                       current=current, accent=accent)
    return meter


def _laundry_cells(view: ApplianceView, last: list[dict]) -> list[dict]:
    cycle = view.extras.get("cycle")
    if not cycle:
        return last
    return [{"k": "Started", "v": cycle["started_label"]},
            {"k": "Elapsed", "v": cycle["elapsed_label"]}, *last]


def _feature_washer(view: ApplianceView, ctx: RenderContext, accent) -> _Feature:
    P = ctx.palette
    copy = flavor.pick_appliance_copy(view, ctx)
    phase = view.extras.get("phase") or ""
    cycle = view.extras.get("cycle")
    past = [status for status, _ in cycle["segments"]] if cycle else []
    current = flavor.laundry_station("washer", phase, past)
    meter = _laundry_meter(view, accent, stations=_WASHER_STATIONS, current=current)
    energy = view.extras.get("energy_kwh_month") or 0.0
    return _Feature(
        kicker=f"Laundry · {view.status_label or 'Running'}",
        head_pre=copy["head_pre"], head_italic=copy["head_italic"], deck=copy["deck"],
        meter=lambda img, draw, y, w: meter(img, draw, y, w, P=P),
        cells=_laundry_cells(view, [
            {"k": "Cycle", "v": f"#{view.extras.get('cycle_no', 0)}"},
            {"k": "Mo. kWh", "v": f"{float(energy):.1f}"},
        ]),
        icon_phase=("pause" if "paus" in phase
                    else {1: "rinse", 2: "spin"}.get(current, "wash")),
    )


def _feature_dryer(view: ApplianceView, ctx: RenderContext, accent) -> _Feature:
    P = ctx.palette
    copy = flavor.pick_appliance_copy(view, ctx)
    phase = view.extras.get("phase") or "running"
    cycle = view.extras.get("cycle")
    past = [status for status, _ in cycle["segments"]] if cycle else []
    current = flavor.laundry_station("dryer", phase, past)
    meter = _laundry_meter(view, accent, stations=_DRYER_STATIONS, current=current)
    return _Feature(
        kicker=f"Laundry · {view.status_label or 'Drying'}",
        head_pre=copy["head_pre"], head_italic=copy["head_italic"], deck=copy["deck"],
        meter=lambda img, draw, y, w: meter(img, draw, y, w, P=P),
        cells=_laundry_cells(view, [
            {"k": "Phase", "v": view.status_label or title_case(phase.replace("_", " "))},
        ]),
        icon_phase=phase,
    )


def _waited_label(view: ApplianceView, ctx: RenderContext) -> str:
    if view.finish_at_local is None:
        return "—"
    minutes = (ctx.now_local - view.finish_at_local).total_seconds() / 60
    return _span(max(1, minutes))


def _feature_done(view: ApplianceView, ctx: RenderContext, accent, *,
                  stations, cells: list[dict]) -> _Feature:
    P = ctx.palette
    copy = flavor.done_copy(view, ctx)

    def meter(img, draw, y, w):
        y = meters.draw_meter_stats(draw, P, 0, y, w, value=_waited_label(view, ctx),
                                    value_label="WAITING", accent=accent,
                                    right_value=view.finish_label, right_label="FINISHED")
        return meters.draw_phase_track(img, draw, P, 0, y + 7, w, stations=stations,
                                       current=None, accent=accent, complete=True)

    return _Feature(
        kicker=view.eyebrow_kicker, head_pre=copy["head_pre"], head_italic=copy["head_italic"],
        deck=copy["deck"], meter=meter, cells=cells, badge="UNLOAD",
    )


def _feature_washer_done(view: ApplianceView, ctx: RenderContext, accent) -> _Feature:
    return _feature_done(view, ctx, accent, stations=_WASHER_STATIONS, cells=[
        {"k": "Cycle", "v": f"#{view.extras.get('cycle_no', 0)}"},
        {"k": "Next", "v": "Dryer"},
    ])


def _feature_dryer_done(view: ApplianceView, ctx: RenderContext, accent) -> _Feature:
    return _feature_done(view, ctx, accent, stations=_DRYER_STATIONS, cells=[])


def _feature_dishwasher(view: ApplianceView, ctx: RenderContext, accent) -> _Feature:
    P = ctx.palette
    copy = flavor.pick_appliance_copy(view, ctx)
    prog = view.progress_pct

    def meter(img, draw, y, w):
        value = "—" if prog is None else f"{prog}%"
        y = meters.draw_meter_stats(draw, P, 0, y, w, value=value, value_label="DONE",
                                    accent=accent, right_value=view.finish_label,
                                    right_label="FINISHES")
        if prog is None:
            return y
        y = meters.draw_progress_bar(img, draw, P, 0, y + 5, w, pct=prog, accent=accent,
                                     ticks=(0, 25, 50, 75, 100))
        return meters.draw_tick_labels(draw, P, 0, y + 2, w, (
            (0, "0"), (25, "25"), (50, "50"), (75, "75"), (100, "100"),
        ))

    door = view.extras.get("door_state") or ""
    return _Feature(
        kicker=view.eyebrow_kicker,
        head_pre=copy["head_pre"], head_italic=copy["head_italic"], deck=copy["deck"],
        meter=meter,
        cells=[
            {"k": "Program", "v": view.program_label or "—"},
            {"k": "Left", "v": view.remaining_label},
            {"k": "Door", "v": "Closed" if door == "closed" else (title_case(door) or "—")},
        ],
    )


def _feature_sauna(view: ApplianceView, ctx: RenderContext, accent) -> _Feature:
    P = ctx.palette
    forecast = view.extras.get("forecast")
    heaters = view.extras.get("heaters", 0)
    icon_phase = str(heaters)
    humidity = view.extras.get("room_humidity_pct")
    rh = None if humidity is None else f"{humidity}% RH"
    room = view.extras.get("room_temp")
    if not forecast:
        target, current = view.target, view.current
        remaining = view.extras.get("remaining_deg")
        door = "open" if view.extras.get("door_open") else "closed"
        deck = (f"Cabin presently {fmt_temp(current)}, with {int(remaining)}° left to climb. "
                f"{heaters} of three elements lit; door {door}."
                if remaining is not None else f"Cabin holding at {fmt_temp(current)}.")

        def plain_meter(img, draw, y, w):
            if current is None:
                return y
            high = max(float(target or 175), 175)
            return meters.draw_scale_meter(img, draw, P, 0, y + 9, w, low=60, high=high,
                                           now=float(current), target=target, accent=accent,
                                           step=10)

        return _Feature(
            kicker=view.eyebrow_kicker, head_pre="The sauna is ", head_italic="warming",
            deck=deck, meter=plain_meter, badge="LIVE", italic_accent=True, icon_phase=icon_phase,
            cells=[
                {"k": "Cabin", "v": fmt_temp(current), "accent": accent},
                {"k": "Target", "v": fmt_temp(target)},
                {"k": "Elements", "v": f"{heaters}/3"},
                {"k": "Room", "v": fmt_temp(room), "sub": rh},
            ],
        )

    head, tail, deck = flavor.sauna_forecast_copy(view, forecast, ctx, READY_F)

    def curve_meter(img, draw, y, w):
        if not forecast["curve"]:
            return y
        return meters.draw_heat_curve(
            img, draw, P, 0, y, w, 108, curve=forecast["curve"], history=forecast["history"],
            ready_f=READY_F, ready_minutes=forecast["ready_in_minutes"],
            ready_label=forecast["ready_label"], fan_minutes=forecast["fan_in_minutes"],
            accent=accent,
        )

    # A controller-preset session reports 32°F, which isn't a real target.
    goal = fmt_temp(view.target) if 104 <= (view.target or 0) <= 212 else "PRESET"
    if forecast["target_reached"]:
        target_sub = "REACHED"
    elif forecast["target_label"]:
        target_sub = f"IN {forecast['target_in']}"
    else:
        target_sub = "ABOVE TARGET"
    return _Feature(
        kicker=view.eyebrow_kicker, head_pre=head, head_italic=tail, deck=deck,
        meter=curve_meter, badge="READY" if forecast["ready_reached"] else "LIVE",
        italic_accent=True, icon_phase=icon_phase,
        cells=[
            {"k": "Room", "v": fmt_temp(room), "accent": accent, "sub": rh},
            {"k": "Thermostat", "v": fmt_temp(view.current), "sub": f"GOAL {goal}"},
            {"k": f"{TARGET_F}° at", "v": forecast["target_label"] or "—",
             "sub": target_sub},
            {"k": "Fan", "v": forecast["fan_label"], "sub": forecast["fan_note"]},
        ],
    )


def _feature_pool(view: ApplianceView, ctx: RenderContext, accent) -> _Feature:
    P = ctx.palette
    head, tail, deck = flavor.pool_copy(view, ctx)
    current, target = view.current, view.target
    air = view.extras.get("air_temp")

    def meter(img, draw, y, w):
        y = meters.draw_meter_stats(draw, P, 0, y, w, value=fmt_temp(current), value_label="WATER",
                                    accent=accent, right_value=fmt_temp(target), right_label="GOAL")
        if current is None:
            return y
        readings = [float(v) for v in (current, target, air) if v is not None]
        low = min(50.0, *readings)
        high = max(90.0, *readings)
        return meters.draw_scale_meter(
            img, draw, P, 0, y + 12, w, low=low - low % 5, high=high + (-high) % 5,
            now=float(current), target=target, accent=accent,
            marker=air, marker_label="AIR",
        )

    return _Feature(
        kicker=view.eyebrow_kicker, head_pre=head, head_italic=tail, deck=deck, meter=meter,
        italic_accent=True,
        cells=[
            {"k": "Air", "v": fmt_temp(air)},
            {"k": "Pump", "v": "On" if view.extras.get("pump_running") else "Off"},
            {"k": "Freeze guard", "v": "Armed" if view.extras.get("freeze_protect") else "Off"},
        ],
    )


_FEATURE_BUILDERS = {
    "sauna":        _feature_sauna,
    "washer":       _feature_washer,
    "washer-done":  _feature_washer_done,
    "dryer":        _feature_dryer,
    "dryer-done":   _feature_dryer_done,
    "dishwasher":   _feature_dishwasher,
    "pool":         _feature_pool,
}


# ── Brief + Colophon ───────────────────────────────────────────────────


def _draw_brief(draw, ctx: RenderContext, ha, x0, y, w, item: ActiveAppliance, *, last) -> int:
    """One-row "also active" entry. Reads the appliance view rather than
    the raw HA dict so timestamps stay in the user's zone.

    The row is intentionally a fixed 40 px so the lead column can
    pre-compute how many briefs fit below the hero without re-measuring
    after every draw.
    """
    P = ctx.palette
    view = item.view
    builder = EDITORIAL_BRIEFS.get(view.kind, _brief_unknown)
    title, sub, value = builder(view)
    row_h = 40
    diamond(draw, x0 + 3, y + 10, 6, ctx.accent(view.accent_kind))
    title_font = fonts.serif(14, weight="semibold")
    sub_font = fonts.serif(12, italic=True, weight="semibold")
    val_font = fonts.serif(16, weight="bold")
    fm_t = font_metrics(title_font)
    fm_s = font_metrics(sub_font)
    fm_v = font_metrics(val_font)
    title_baseline = y + fm_t.ascent + 2
    # Fixed leading: the font's full ascent + descent would put the sub-line
    # on the row's dotted rule.
    sub_baseline = title_baseline + 15
    val_baseline = y + fm_v.ascent + 4
    text_x = x0 + 14
    text_max_w = max(40, (x0 + w) - text_x - 60)
    draw_text_clipped_bl(draw, (text_x, title_baseline), title,
                         title_font, P.ink, max_w=text_max_w)
    draw_text_clipped_bl(draw, (text_x, sub_baseline), sub,
                         sub_font, P.muted, max_w=text_max_w)
    draw_text_bl_right(draw, (x0 + w, val_baseline), value, val_font,
                       ctx.accent(view.accent_kind))
    if not last:
        dotted_hr(draw, x0, x0 + w, y + row_h - 2, dash=1, gap=3, fill=P.rule)
    return y + row_h


def _brief_sauna(view: ApplianceView) -> tuple[str, str, str]:
    forecast = view.extras.get("forecast")
    if forecast and forecast["ready_label"]:
        ready = ("Ready since " if forecast["ready_reached"] else "Ready around ")
        return (
            "Sauna heating",
            f"{ready}{forecast['ready_label']} · "
            f"{view.extras.get('heaters', 0)} elements",
            f"{fmt_temp(view.extras.get('room_temp'))} → "
            f"{READY_F}°",
        )
    return (
        "Sauna heating",
        f"{view.extras.get('heaters', 0)} elements \u00b7 "
        f"{view.extras.get('duration', 0)}m cycle",
        f"{fmt_temp(view.current)} \u2192 {fmt_temp(view.target)}",
    )


def _brief_washer(view: ApplianceView) -> tuple[str, str, str]:
    title = f"Washer \u00b7 {view.status_label}"
    sub = f"Cycle #{view.extras.get('cycle_no', 0)} \u00b7 finishes {view.finish_label}"
    value = (f"{view.remaining_label} left"
             if view.remaining_label and view.remaining_label != "\u2014"
             else "\u2014")
    return title, sub, value


def _brief_washer_done(view: ApplianceView) -> tuple[str, str, str]:
    return (
        "Washer done",
        f"Cycle #{view.extras.get('cycle_no', 0)}",
        view.relative_label or "\u2014",
    )


def _brief_dryer(view: ApplianceView) -> tuple[str, str, str]:
    phase = view.extras.get("phase") or "running"
    title = f"Dryer \u00b7 {title_case(phase.replace('_', ' '))}"
    sub = f"Finishes {view.finish_label}"
    value = (f"{view.remaining_label} left"
             if view.remaining_label and view.remaining_label != "\u2014"
             else "\u2014")
    return title, sub, value


def _brief_dryer_done(view: ApplianceView) -> tuple[str, str, str]:
    return (
        "Dryer done",
        f"Finished {view.finish_label}",
        view.relative_label or "\u2014",
    )


def _brief_dishwasher(view: ApplianceView) -> tuple[str, str, str]:
    prog = view.progress_pct
    return (
        "Dishwasher running",
        view.program_label or "\u2014",
        f"{prog}%" if prog is not None else "\u2014",
    )


def _brief_pool(view: ApplianceView) -> tuple[str, str, str]:
    return (
        "Pool heating",
        f"Air {fmt_temp(view.extras.get('air_temp'))}",
        f"{fmt_temp(view.current)} \u2192 {fmt_temp(view.target)}",
    )


def _brief_unknown(view: ApplianceView) -> tuple[str, str, str]:
    return (view.kind.replace("-", " ").title(), "", "\u2014")


EDITORIAL_BRIEFS = {
    "sauna":        _brief_sauna,
    "washer":       _brief_washer,
    "washer-done":  _brief_washer_done,
    "dryer":        _brief_dryer,
    "dryer-done":   _brief_dryer_done,
    "dishwasher":   _brief_dishwasher,
    "pool":         _brief_pool,
}


# ── Colophon ───────────────────────────────────────────────────────────


def _draw_colophon(draw, ctx: RenderContext, ha) -> None:
    """Bottom strip: three columns -- people on the left, italic quote
    in the center, open windows on the right.

    The time appears only in the masthead, and the rooms we watch are in the
    House rail, so neither repeats here. The right chip reserves its width
    first; the quote is then fitted to the middle space remaining so the two
    can never collide.
    """
    L = layout.EDITORIAL
    P = ctx.palette
    box = L.colophon
    draw.rectangle([(box.x0, box.y0), (box.x1 - 1, box.y0 + 1)], fill=P.rule)
    label_font = fonts.pix_cherry_small(layout.EditorialType.COLOPHON_PX, bold=True)
    tracking = em_to_px(layout.EditorialType.COLOPHON_PX, 0.18)
    fm = font_metrics(label_font)
    baseline = box.y0 + 5 + fm.ascent
    unavailable = bool(ha.get("unavailable"))

    # ── Left column: people ────────────────────────────────────────
    people = ha.get("people") or []
    home_names = [p.get("name", "").split(" ")[0] for p in people if p.get("state") == "home"]
    if home_names:
        bullet(draw, box.x0 + 3, baseline - fm.ascent // 2, 3,
               filled=True, color=ctx.accent("ok"))
        left_text = " & ".join(home_names).upper() + " HOME"
        left_color = P.ink
    else:
        bullet(draw, box.x0 + 3, baseline - fm.ascent // 2, 3,
               filled=False, color=ctx.accent("idle"))
        left_text = "HOME UNKNOWN" if unavailable else "NOBODY HOME"
        left_color = P.muted
    left_max_w = (box.cx - box.x0) - 20  # reserve 20-px gap before quote.
    # Truncate the left text to its column.
    s_left = left_text
    while s_left and tracked_width(label_font, s_left, tracking) > left_max_w:
        s_left = s_left[:-1]
    if s_left and s_left != left_text:
        # Drop one more char and ellipsize.
        while s_left and tracked_width(label_font, s_left + "\u2026", tracking) > left_max_w:
            s_left = s_left[:-1]
        s_left = s_left + "\u2026"
    if s_left:
        draw_tracked_text_bl(draw, (box.x0 + 10, baseline), s_left,
                             label_font, left_color, tracking)
    left_end_x = box.x0 + 10 + tracked_width(label_font, s_left, tracking)

    # ── Right column: windows ─────────────────────────────────────
    win_count = len(ha.get("openWindows") or [])
    if unavailable:
        wins_text = "WINDOWS UNKNOWN"
    elif win_count:
        wins_text = f"{win_count} WINDOW{'S' if win_count != 1 else ''} OPEN"
    else:
        wins_text = "WINDOWS SHUT"
    wins_color = (ctx.accent("warn") if (win_count and P.yellow != P.ink)
                  else ctx.accent("idle"))
    bullet_dia = 7
    gap = 4
    rx = box.x1 - (bullet_dia + gap + tracked_width(label_font, wins_text, tracking))
    square_marker(draw, rx + 3, baseline - fm.ascent // 2, 3,
                  filled=bool(win_count), color=wins_color)
    draw_tracked_text_bl(draw, (rx + bullet_dia + gap, baseline), wins_text,
                         label_font, wins_color, tracking)

    # ── Center column: italic quote (last so it can use the real gap) ──
    quote_font = fonts.serif(12, italic=True, weight="semibold")
    fm_q = font_metrics(quote_font)
    quote_full = "\u201cAll the news that fits the house.\u201d"
    quote_short = "\u201cAll the news.\u201d"
    quote_baseline = box.y0 + 6 + fm_q.ascent
    quote_max_w = max(0, rx - 20 - (left_end_x + 12))
    quote = quote_full if text_width(quote_font, quote_full) <= quote_max_w else quote_short
    if text_width(quote_font, quote) <= quote_max_w and quote_max_w > 20:
        draw_text_bl_center(draw, (box.cx, quote_baseline),
                            quote, quote_font, P.muted)
