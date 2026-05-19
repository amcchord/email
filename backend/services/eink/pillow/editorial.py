"""Editorial dashboard -- Pillow port of docs/design/editorial.jsx.

Draws the Editorial newspaper layout at 800x480 onto an RGB Pillow image.
Pixel positions match editorial.jsx exactly where feasible.

Architecture
------------
This renderer is pure presentation. It never touches raw HA dicts and
never re-formats a HA timestamp. All state comes from typed views:

* HVAC reads ``FloorView`` / ``ZoneView`` / ``HvacSummary`` from
  ``ha_view.py``. These reconcile ``mode`` + ``hvac_action`` so a stale
  HA action can never label a cooling zone as "heating".
* Appliances read ``ApplianceView`` (built by the registry in
  ``appliances.py``). All clock strings are pre-localized to the
  user's IANA zone, so the washer/dishwasher hero can never print UTC.

See ``backend/services/eink/README.md`` for the full layering rules and
the "how to add a new appliance / new design" guide.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from PIL import Image, ImageDraw

from . import fonts, layout
from .appliances import ActiveAppliance, pick_active
from .draw import (
    Box,
    Run,
    bullet,
    diamond,
    dotted_hr,
    double_hr,
    draw_arrow_down,
    draw_arrow_right,
    draw_arrow_up,
    draw_dashed_arc,
    draw_drop_cap_paragraph,
    draw_fit_text_bl,
    draw_headline,
    draw_paragraph,
    draw_refresh_glyph,
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
    FloorView,
    HvacSummary,
    ZoneView,
    build_appliance_view,
    build_floor_views,
    build_hvac_summary,
    build_zone_view,
)
from .helpers import (
    clamp,
    compass,
    fmt_clock,
    fmt_date,
    fmt_temp,
    fmt_time,
    fmt_weather,
    lerp_pct,
    parse_iso,
    safe_int,
    safe_round,
    title_case,
)
from .palette import Palette
from .render_ctx import RenderContext, build_render_context


# ── Top-level ──────────────────────────────────────────────────────────


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
    lead = active[0] if active else None
    rest = active[1:]

    L = layout.EDITORIAL

    _draw_masthead(draw, P, ctx.now_local, ha.get("weather") or {})

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


def _draw_masthead(draw: ImageDraw.ImageDraw, P: Palette, now: datetime, weather: dict) -> None:
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
                 "EASTERN \u00b7 LIVE", label_font, P.muted)

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
    draw_tracked_text_bl_center(
        draw, (wm_col.cx, label_baseline),
        date_s.upper(), label_font, P.muted, d_tracking,
    )

    # ── Weather column (right) ─────────────────────────────────────
    temp = weather.get("temperature")
    temp_s = (f"{safe_round(temp)}\u00b0" if temp is not None else "\u2014")
    glyph_sz = TY.WEATHER_GLYPH_PX
    temp_max_w = weather_col.w - glyph_sz - 12
    temp_fit_font, _temp_fit_size = pick_fitting_size(
        lambda s: fonts.serif(s, weight="bold"),
        temp_s, temp_max_w, TY.TEMP_CANDIDATES,
    )
    temp_w = text_width(temp_fit_font, temp_s)
    glyph_top = content_y0
    # Weather Icons sits with extra whitespace on the right of its em
    # square, so we nudge it 4 px left to balance the optical gap to the
    # temperature digits next to it.
    glyph_x = weather_col.x1 - temp_w - 10 - glyph_sz - 4
    _draw_weather_glyph(draw, (glyph_x, glyph_top),
                        size=glyph_sz, state=weather.get("state") or "", P=P)
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
        k="Wind", v=f"{safe_round(weather.get('windSpeed'))}",
        u=f"mph {compass(weather.get('windBearing'))}")
    cur_y = _draw_rail_stat(draw, P, box.x0, cur_y, box.w,
        k="Humidity", v=f"{safe_round(weather.get('humidity'))}", u="%")
    pressure = weather.get("pressure")
    pressure_s = f"{float(pressure):.2f}" if pressure is not None else "\u2014"
    cur_y = _draw_rail_stat(draw, P, box.x0, cur_y, box.w,
        k="Pressure", v=pressure_s, u="inHg")
    cur_y = _draw_rail_stat(draw, P, box.x0, cur_y, box.w,
        k="Visibility", v=f"{safe_round(weather.get('visibility'))}", u="mi")

    cur_y += 8
    hairline_hr(draw, box.x0, box.x1, cur_y, fill=P.rule); cur_y += 6
    sun = ha.get("sun") or {}
    sun_label = "Sun \u00b7 " + ("Risen" if sun.get("state") == "above_horizon" else "Set")
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

    slots = forecast[:3]
    for idx, slot in enumerate(slots):
        dt = parse_iso(slot.get("datetime"))
        if dt is not None and ctx.zone is not None:
            dt = dt.astimezone(ctx.zone)
        if idx == 0:
            label = "Today"
        elif dt is not None:
            label = dt.strftime("%a")
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
    sun = ha.get("sun") or {}
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
    cur_y = _draw_floor_list(draw, ctx, ha, box.x0, cur_y, box.w)

    cur_y += 8
    hairline_hr(draw, box.x0, box.x1, cur_y, fill=P.rule); cur_y += 6
    _section("Hearth \u00b7 Radiant")
    climates = ha.get("climates") or {}
    cur_y = _draw_radiant_row(draw, ctx, box.x0, cur_y, box.w, "Main",
                              build_zone_view(climates.get("radiantMain"), name="Main"))
    cur_y = _draw_radiant_row(draw, ctx, box.x0, cur_y, box.w, "Apt",
                              build_zone_view(climates.get("radiantApt"), name="Apt"))

    cur_y += 8
    hairline_hr(draw, box.x0, box.x1, cur_y, fill=P.rule); cur_y += 6
    if pool and pool.get("heating"):
        _section("Pool")
        _draw_pool_mini(draw, P, box.x0, cur_y, box.w, pool)


def _draw_floor_list(draw, ctx: RenderContext, ha, x0, y, w) -> int:
    """One row per floor: name + sub-state on the left, big temp on the
    right. Heating renders in red, cooling in blue, idle in ink.

    The temp digits use a shared auto-fit pass so every row's number
    sits on the same baseline at the same size, no matter which one is
    widest (a 3-digit temp can't shift just one row).
    """
    P = ctx.palette
    floor_views = build_floor_views(ha, [
        ("third", "Third"),
        ("second", "Second"),
        ("first", "First"),
        ("basement", "Basement"),
    ])
    name_font = fonts.serif(13, weight="semibold")
    sub_font = fonts.pix_cherry_small(9, bold=True)
    sub_tracking = em_to_px(9, 0.16)
    fm_n = font_metrics(name_font)
    fm_s = font_metrics(sub_font)
    # Pick a single temp size against the widest expected string so all
    # four rows share one baseline. Reserve ~half the rail width for the
    # name+sub cluster.
    widest_temp = max((fmt_temp(v.temp) for v in floor_views),
                      key=lambda s: text_width(fonts.serif(22, weight='bold'), s),
                      default="00\u00b0")
    temp_factory = lambda s: fonts.serif(s, weight="bold")
    temp_font, _ = pick_fitting_size(
        temp_factory, widest_temp, max(36, w // 2),
        (22, 20, 18, 16),
    )
    fm_t = font_metrics(temp_font)
    row_h = fm_t.ascent + fm_s.line_height + 6
    cur_y = y
    for idx, view in enumerate(floor_views):
        active = view.state in ("heating", "cooling")
        accent = ctx.accent(view.accent_kind) if active else P.muted
        name_baseline = cur_y + fm_n.ascent
        draw_text_bl(draw, (x0, name_baseline), view.label, name_font, P.ink)
        sub_baseline = name_baseline + fm_n.descent + 2 + fm_s.ascent
        bullet(draw, x0 + 3, sub_baseline - fm_s.ascent // 2 + 1, 3,
               filled=active, color=accent)
        if view.state == "heating":
            sub_label = f"{view.heat_count} heat"
        elif view.state == "cooling":
            sub_label = f"{view.cool_count} cool"
        else:
            sub_label = "idle"
        draw_tracked_text_bl(draw, (x0 + 10, sub_baseline),
                             sub_label, sub_font, accent, sub_tracking)
        temp_s = fmt_temp(view.temp)
        temp_color = ctx.accent(view.accent_kind) if active else P.ink
        temp_baseline = cur_y + fm_t.ascent
        draw_text_bl_right(draw, (x0 + w, temp_baseline),
                           temp_s, temp_font, temp_color)
        if idx != len(floor_views) - 1:
            dotted_hr(draw, x0, x0 + w, cur_y + row_h - 1, dash=1, gap=3, fill=P.rule)
        cur_y += row_h
    return cur_y


def _draw_radiant_row(draw, ctx: RenderContext, x0, y, w, label, view: ZoneView) -> int:
    """Radiant zone row. Reads ``ZoneView.state`` so heating shows red,
    cooling shows blue, idle/off stays in ink. The `→ target` glyph is
    drawn as primitives because Cherry pixel font lacks U+2192.
    """
    P = ctx.palette
    if view is None or view.state == "unknown":
        return y
    active = view.state in ("heating", "cooling")
    color = ctx.accent(view.accent_kind) if active else P.ink
    left_font = fonts.pix_cherry_small(10, bold=True)
    l_tracking = em_to_px(10, 0.14)
    cur_factory = lambda s: fonts.serif(s, weight="bold")
    tgt_font = fonts.pix_cherry_small(9, bold=True)
    tgt_tracking = em_to_px(9, 0.10)
    fm_l = font_metrics(left_font)
    fm_t = font_metrics(tgt_font)
    cur_s = fmt_temp(view.current)
    tgt_temp_s = fmt_temp(view.target) if view.target is not None else ""
    label_w = tracked_width(left_font, label.upper(), l_tracking)
    bullet_w = 10
    arrow_sz = 7
    arrow_block_w = (arrow_sz + 3 + tracked_width(tgt_font, tgt_temp_s, tgt_tracking)) if tgt_temp_s else 0
    available = w - bullet_w - label_w - 6 - arrow_block_w - 5
    cur_font, _cur_size = pick_fitting_size(
        cur_factory, cur_s, max(20, available), (15, 14, 13, 12),
    )
    fm_c = font_metrics(cur_font)
    baseline = y + max(fm_c.ascent, fm_l.ascent, fm_t.ascent)
    bullet(draw, x0 + 3, baseline - fm_l.ascent // 2, 3,
           filled=active, color=color)
    draw_tracked_text_bl(draw, (x0 + 10, baseline),
                         label.upper(), left_font, color, l_tracking)
    cur_w = text_width(cur_font, cur_s)
    right = x0 + w
    tgt_temp_w = tracked_width(tgt_font, tgt_temp_s, tgt_tracking) if tgt_temp_s else 0
    if tgt_temp_s:
        tgt_x = right - tgt_temp_w
        arrow_x = tgt_x - arrow_sz - 3
        cur_x = arrow_x - 5 - cur_w
        draw_text_bl(draw, (cur_x, baseline), cur_s, cur_font, color)
        draw_arrow_right(draw, arrow_x, baseline, size=arrow_sz, fill=P.muted)
        draw_tracked_text_bl(draw, (tgt_x, baseline),
                             tgt_temp_s, tgt_font, P.muted, tgt_tracking)
    else:
        cur_x = right - cur_w
        draw_text_bl(draw, (cur_x, baseline), cur_s, cur_font, color)
    return baseline + max(fm_c.descent, fm_l.descent, fm_t.descent) + 2


def _draw_pool_mini(draw, P, x0, y, w, pool) -> None:
    if not pool:
        return
    heating = bool(pool.get("heating"))
    accent = P.red if heating else P.blue
    therm_w, therm_h = 14, 56
    _draw_vertical_thermometer(draw, P, x0, y, therm_w, therm_h,
        from_v=50, to_v=95,
        now=pool.get("current"), target=pool.get("target"), accent=accent)
    text_x = x0 + therm_w + 10
    text_max_w = max(20, x0 + w - text_x)
    cur_factory = lambda s: fonts.serif(s, weight="bold")
    cur_s = fmt_temp(pool.get("current"))
    cur_font, _cur_size = pick_fitting_size(
        cur_factory, cur_s, text_max_w, (28, 24, 22, 20, 18),
    )
    stat_font = fonts.pix_cherry_small(9, bold=True)
    s_tracking = em_to_px(9, 0.14)
    fm_c = font_metrics(cur_font)
    fm_s = font_metrics(stat_font)
    color = P.red if heating else P.ink
    baseline = y + fm_c.ascent
    draw_text_bl(draw, (text_x, baseline), cur_s, cur_font, color)
    sub_baseline = baseline + fm_c.descent + 6 + fm_s.ascent
    arrow_sz = 7
    draw_arrow_right(draw, text_x, sub_baseline, size=arrow_sz, fill=P.muted)
    draw_tracked_text_bl(draw, (text_x + arrow_sz + 3, sub_baseline),
                         fmt_temp(pool.get("target")),
                         stat_font, P.muted, s_tracking)
    air = pool.get("air")
    if air is not None:
        draw_tracked_text_bl(
            draw, (text_x, sub_baseline + fm_s.line_height + 2),
            f"AIR {safe_round(air)}\u00b0",
            stat_font, P.muted, s_tracking,
        )


def _draw_vertical_thermometer(
    draw, P, x0, y, w, h, *,
    from_v, to_v, now, target, accent,
) -> None:
    """Vertical version of _draw_thermometer used by the pool mini panel."""
    draw.rectangle([(x0, y), (x0 + w - 1, y + h - 1)],
                   outline=P.rule, width=1)
    if now is None:
        return
    pct = lerp_pct(float(now), from_v, to_v)
    fill_h = int((h - 2) * pct)
    if fill_h > 0:
        draw.rectangle(
            [(x0 + 1, y + h - 1 - fill_h),
             (x0 + w - 2, y + h - 2)],
            fill=accent,
        )
    if target is not None:
        tpct = lerp_pct(float(target), from_v, to_v)
        ty = y + h - 1 - int((h - 2) * tpct)
        draw.line([(x0 - 2, ty), (x0 + w + 1, ty)], fill=P.ink, width=1)


# ── Lead column ────────────────────────────────────────────────────────


def _draw_lead_column(img: Image.Image, draw, ctx: RenderContext, ha,
                      active: list, box: Box) -> None:
    """Composer for the center column.

    Branches on how many appliances are currently active:

    * 0 active: render the calm-edition hero. Slack is distributed so
      the headline sits ~1/3 from the top -- a magazine looks anchored,
      not floating.
    * 1 active: render the full per-kind hero, then place it at the
      same 1/3 gravity offset so the fact strip floats nearer the
      column center instead of hugging the top.
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
        y_end = _draw_calm_lead(sdraw, P, ha, 0, 0, box.w)
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
    return {
        "head_runs": [Run(view.status_label, norm, P.ink),
                      Run(", then spin.", ital, P.ink)],
        "deck": (f"Cycle #{view.extras.get('cycle_no', 0)} \u00b7 "
                 f"finishes {view.finish_label}."),
        "cells": [
            {"k": "Remaining", "v": view.remaining_label,
             "accent": ctx.accent(view.accent_kind)},
            {"k": "Done by",   "v": view.finish_label},
        ],
    }


def _co_washer_done(view: ApplianceView, ctx: RenderContext) -> dict:
    P = ctx.palette
    norm, ital = _co_lead_runs_normal_italic()
    return {
        "head_runs": [Run("Wash complete \u2014 ", norm, P.ink),
                      Run("move it.", ital, P.ink)],
        "deck": (f"Cycle #{view.extras.get('cycle_no', 0)} finished "
                 f"{view.finish_label} \u00b7 {view.relative_label}."),
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
    phase = view.extras.get("phase") or "running"
    if phase in _EDITORIAL_DRYER_PHASE_HEADS:
        runs = [Run(_EDITORIAL_DRYER_PHASE_HEADS[phase], ital, P.ink)]
    else:
        runs = [Run(view.status_label, norm, P.ink),
                Run(", then fold.", ital, P.ink)]
    return {
        "head_runs": runs,
        "deck": f"Finishing around {view.finish_label}.",
        "cells": [
            {"k": "Remaining", "v": view.remaining_label,
             "accent": ctx.accent(view.accent_kind)},
            {"k": "Done by",   "v": view.finish_label},
        ],
    }


def _co_dryer_done(view: ApplianceView, ctx: RenderContext) -> dict:
    P = ctx.palette
    norm, ital = _co_lead_runs_normal_italic()
    return {
        "head_runs": [Run("Drying complete \u2014 ", norm, P.ink),
                      Run("unload it.", ital, P.ink)],
        "deck": f"Finished {view.finish_label} \u00b7 {view.relative_label}.",
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
    program = view.program_label or "Auto"
    prog = view.progress_pct
    prog_s = f"{prog}%" if prog is not None else "\u2014"
    return {
        "head_runs": [Run(f"{program} ", norm, P.ink),
                      Run("cycle.", ital, P.ink)],
        "deck": (f"Finishing {view.relative_label} ({view.finish_label})."),
        "cells": [
            {"k": "Progress", "v": prog_s,
             "accent": ctx.accent(view.accent_kind)},
            {"k": "Finish",   "v": view.finish_label},
        ],
    }


def _co_sauna(view: ApplianceView, ctx: RenderContext) -> dict:
    P = ctx.palette
    norm, ital = _co_lead_runs_normal_italic()
    return {
        "head_runs": [Run("Cabin warming to ", norm, P.ink),
                      Run(f"{safe_round(view.target)}\u00b0.", ital,
                          ctx.accent(view.accent_kind))],
        "deck": (f"Now {safe_round(view.current)}\u00b0 \u00b7 "
                 f"{view.extras.get('heaters', 0)}/3 elements."),
        "cells": [
            {"k": "Cabin",  "v": fmt_temp(view.current),
             "accent": ctx.accent(view.accent_kind)},
            {"k": "Target", "v": fmt_temp(view.target)},
        ],
    }


def _co_pool(view: ApplianceView, ctx: RenderContext) -> dict:
    P = ctx.palette
    norm, ital = _co_lead_runs_normal_italic()
    return {
        "head_runs": [Run("Pool climbing to ", norm, P.ink),
                      Run(f"{safe_round(view.target)}\u00b0.", ital,
                          ctx.accent(view.accent_kind))],
        "deck": (f"Water {safe_round(view.current)}\u00b0 \u00b7 "
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


def _draw_calm_lead(draw, P, ha, x0, y, w) -> int:
    kicker_font = fonts.pix_cherry_small(11, bold=True)
    k_tracking = em_to_px(11, 0.30)
    fm_k = font_metrics(kicker_font)
    star_sz = 9
    kicker_label = "THE CALM EDITION"
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
    head_font = fonts.serif(38, weight="bold")
    italic_font = fonts.serif(38, italic=True, weight="bold")
    fm_h = font_metrics(head_font)
    line_height = fm_h.line_height + 2
    cur_y = y + fm_k.line_height + 8
    baseline = cur_y + fm_h.ascent
    draw_text_bl(draw, (x0, baseline), "All quiet on the", head_font, P.ink)
    baseline += line_height
    draw_text_bl(draw, (x0, baseline), "home front.", italic_font, P.ink)
    cur_y = baseline + fm_h.descent + 6
    deck_font = fonts.serif(14, italic=True, weight="semibold")
    fm_d = font_metrics(deck_font)
    draw_text_bl(draw, (x0, cur_y + fm_d.ascent),
                 "Nothing running, nothing demanding.", deck_font, P.muted)
    cur_y += fm_d.line_height + 6
    double_hr(draw, x0, x0 + w, cur_y, fill=P.rule)
    cur_y += 10
    open_windows = ha.get("openWindows") or []
    garage = (ha.get("garage") or {}).get("state") or "unknown"
    if open_windows:
        wins = f"{len(open_windows)} window{'s' if len(open_windows) > 1 else ''} open"
    else:
        wins = "All windows closed"
    body = (f"ll appliances idle. Climate within bounds across the four floors. "
            f"{wins}, garage {garage}.")
    body_font = fonts.serif(13)
    cap_font = fonts.serif(36, weight="bold")
    cur_y = draw_drop_cap_paragraph(
        draw, (x0, cur_y, w, 200), "A", body,
        cap_font=cap_font, body_font=body_font, fill=P.ink,
        line_height_px=18, cap_lines=2, cap_right_gutter=6,
    )
    return cur_y


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
    cell_h = 48
    draw.rectangle([(x0, y), (x0 + w - 1, y + 1)], fill=P.rule)
    bottom = y + 2 + cell_h
    label_font = fonts.pix_cherry_small(9, bold=True)
    tracking = em_to_px(9, 0.18)
    val_factory = lambda s: fonts.serif(s, weight="bold")
    val_candidates = (22, 20, 18, 16, 14)
    sub_font = fonts.pix_cherry_small(9, bold=True)
    sub_tracking = em_to_px(9, 0.10)
    fm_l = font_metrics(label_font)
    fm_s = font_metrics(sub_font)
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


def _draw_sauna_lead(draw, ctx: RenderContext, ha, item: ActiveAppliance, x0, y, w) -> int:
    P = ctx.palette
    view = item.view
    accent = ctx.accent(view.accent_kind)
    target = view.target
    current = view.current
    remaining = view.extras.get("remaining_deg")
    runs = [
        Run("The sauna is ", _hero_font(), P.ink),
        Run("warming", _hero_italic_bold_font(), accent),
        Run("\n", _hero_font(), P.ink),
        Run(f"to {safe_round(target)}\u00b0.", _hero_font(), P.ink),
    ]
    if remaining is not None:
        heaters = view.extras.get("heaters", 0)
        door = "open" if view.extras.get("door_open") else "closed"
        deck = (f"Cabin presently {safe_round(current)}\u00b0, with {int(remaining)}\u00b0 "
                f"left to climb. {heaters} of three elements lit; door {door}.")
    else:
        deck = f"Cabin holding at {safe_round(current)}\u00b0."
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
         "sub": f"{view.extras.get('room_humidity', 0)}% RH"},
    ])
    return cur_y


def _draw_washer_lead(draw, ctx: RenderContext, ha, item: ActiveAppliance, x0, y, w) -> int:
    P = ctx.palette
    view = item.view
    accent = ctx.accent(view.accent_kind)
    status = view.status_label
    runs = [Run(status, _hero_font(), P.ink),
            Run(", then spin.", _hero_italic_bold_font(), P.ink)]
    deck = f"Cycle #{view.extras.get('cycle_no', 0)}, finishing around {view.finish_label}."
    if view.remaining_label and view.remaining_label != "\u2014":
        deck += f" {view.remaining_label} remaining."
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


def _draw_washer_done_lead(draw, ctx: RenderContext, ha, item: ActiveAppliance, x0, y, w) -> int:
    P = ctx.palette
    view = item.view
    accent = ctx.accent(view.accent_kind)
    runs = [
        Run("Wash complete \u2014 ", _hero_font(), P.ink),
        Run("please move", _hero_italic_bold_font(), P.ink),
        Run("\n", _hero_font(), P.ink),
        Run("to the dryer.", _hero_italic_bold_font(), P.ink),
    ]
    deck = (f"Cycle #{view.extras.get('cycle_no', 0)} finished "
            f"{view.finish_label} \u00b7 {view.relative_label}.")
    body = "Cabin clean, drum still warm. The dryer awaits."
    return _draw_story_shell(draw, P, x0, y, w,
        kicker=view.eyebrow_kicker, accent=accent,
        badge="UNLOAD", headline_runs=runs, deck=deck, body=body)


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
    if phase in _EDITORIAL_DRYER_PHASE_HEADS:
        runs = [Run(_EDITORIAL_DRYER_PHASE_HEADS[phase],
                    _hero_italic_bold_font(), P.ink)]
    else:
        runs = [Run(view.status_label, _hero_font(), P.ink),
                Run(", then fold.", _hero_italic_bold_font(), P.ink)]
    deck = f"Finishing around {view.finish_label}."
    if view.remaining_label and view.remaining_label != "\u2014":
        deck += f" {view.remaining_label} remaining."
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
    runs = [
        Run("Drying complete \u2014 ", _hero_font(), P.ink),
        Run("please unload", _hero_italic_bold_font(), P.ink),
        Run("\n", _hero_font(), P.ink),
        Run("the dryer.", _hero_italic_bold_font(), P.ink),
    ]
    deck = f"Finished {view.finish_label} \u00b7 {view.relative_label}."
    body = "Drum's done its work. Time to fold."
    return _draw_story_shell(draw, P, x0, y, w,
        kicker=view.eyebrow_kicker, accent=accent,
        badge="UNLOAD", headline_runs=runs, deck=deck, body=body)


def _draw_dishwasher_lead(draw, ctx: RenderContext, ha, item: ActiveAppliance, x0, y, w) -> int:
    P = ctx.palette
    view = item.view
    accent = ctx.accent(view.accent_kind)
    prog = view.progress_pct
    prog_pct = f"{prog}%" if prog is not None else "\u2014"
    program = view.program_label or "\u2014"
    runs = [Run(f"{program} ", _hero_font(), P.ink),
            Run("cycle.", _hero_italic_bold_font(), P.ink)]
    deck = f"Finishing {view.relative_label} ({view.finish_label})."
    if prog is not None:
        deck += f" {prog}% complete."
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
    runs = [Run("Climbing to ", _hero_font(), P.ink),
            Run(f"{safe_round(target)}\u00b0",
                fonts.serif(32, italic=True, weight="bold"), accent),
            Run(".", _hero_font(), P.ink)]
    freeze = ("Freeze guard armed." if view.extras.get("freeze_protect")
              else "No freeze risk.")
    air = view.extras.get("air_temp")
    deck = (f"Heat exchanger active, water now {safe_round(current)}\u00b0. "
            f"Air {safe_round(air)}\u00b0. {freeze}")
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
    sub_baseline = title_baseline + fm_t.descent + 2 + fm_s.ascent
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
    in the center, status chips on the right.

    The right cluster reserves its width first; the quote is then
    truncated to whatever middle space remains so the two can never
    collide. If even after dropping the refresh chip the right cluster
    still doesn't fit, the quote falls back to a shorter form.
    """
    L = layout.EDITORIAL
    P = ctx.palette
    now = ctx.now_local
    box = L.colophon
    draw.rectangle([(box.x0, box.y0), (box.x1 - 1, box.y0 + 1)], fill=P.rule)
    label_font = fonts.pix_cherry_small(layout.EditorialType.COLOPHON_PX, bold=True)
    tracking = em_to_px(layout.EditorialType.COLOPHON_PX, 0.18)
    fm = font_metrics(label_font)
    baseline = box.y0 + 5 + fm.ascent

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
        left_text = "NOBODY HOME"
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

    # ── Right column: chips ────────────────────────────────────────
    summary: HvacSummary = build_hvac_summary(ha)
    win_count = len(ha.get("openWindows") or [])
    sep = "  \u00b7  "
    refresh_label = fmt_time(now).upper()
    zones_color = ctx.accent(summary.dominant) if summary.is_active else ctx.accent("idle")
    zones_text = summary.label
    wins_color = (ctx.accent("warn") if (win_count and P.yellow != P.ink)
                  else ctx.accent("idle"))

    bullet_dia = 7
    gap = 4
    refresh_sz = 8
    zones_w = tracked_width(label_font, zones_text, tracking)
    sep_w = tracked_width(label_font, sep, tracking)
    wins_text = f"{win_count} WIN"
    wins_w = tracked_width(label_font, wins_text, tracking)
    refresh_w = refresh_sz + 4 + tracked_width(label_font, refresh_label, tracking)
    total_with_refresh = (bullet_dia + gap + zones_w + sep_w
                          + bullet_dia + gap + wins_w + sep_w + refresh_w)
    total_no_refresh = (bullet_dia + gap + zones_w + sep_w
                        + bullet_dia + gap + wins_w)
    # Right cluster gets at most half of the box minus a 20-px gap
    # reservation for the quote.
    right_budget = (box.x1 - box.cx) - 20
    show_refresh = total_with_refresh <= right_budget
    total = total_with_refresh if show_refresh else total_no_refresh
    rx = box.x1 - total
    bullet(draw, rx + 3, baseline - fm.ascent // 2, 3,
           filled=summary.is_active, color=zones_color)
    cur_x = rx + bullet_dia + gap
    draw_tracked_text_bl(draw, (cur_x, baseline), zones_text,
                         label_font, zones_color, tracking)
    cur_x += zones_w
    draw_tracked_text_bl(draw, (cur_x, baseline), sep, label_font, P.muted, tracking)
    cur_x += sep_w
    square_marker(draw, cur_x + 3, baseline - fm.ascent // 2, 3,
                  filled=bool(win_count), color=wins_color)
    cur_x += bullet_dia + gap
    draw_tracked_text_bl(draw, (cur_x, baseline), wins_text,
                         label_font, wins_color, tracking)
    cur_x += wins_w
    if show_refresh:
        draw_tracked_text_bl(draw, (cur_x, baseline), sep,
                             label_font, P.muted, tracking)
        cur_x += sep_w
        draw_refresh_glyph(draw, cur_x, baseline,
                           size=refresh_sz, fill=P.muted)
        cur_x += refresh_sz + 4
        draw_tracked_text_bl(draw, (cur_x, baseline), refresh_label,
                             label_font, P.muted, tracking)

    # ── Center column: italic quote (last so it can use the real gap) ──
    quote_font = fonts.serif(12, italic=True, weight="semibold")
    fm_q = font_metrics(quote_font)
    quote_full = "\u201cAll the news that fits the house.\u201d"
    quote_short = "\u201cAll the news.\u201d"
    quote_baseline = box.y0 + 6 + fm_q.ascent
    quote_max_w = max(0, rx - 20 - (left_end_x + 12))
    quote = quote_full if text_width(quote_font, quote_full) <= quote_max_w else quote_short
    if text_width(quote_font, quote) <= quote_max_w and quote_max_w > 20:
        quote_w = text_width(quote_font, quote)
        center_x = (left_end_x + 12 + rx - 20) // 2
        draw_text_bl_center(draw, (center_x, quote_baseline),
                            quote, quote_font, P.muted)
