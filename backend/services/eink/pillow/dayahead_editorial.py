"""Day Ahead -- Editorial direction (Pillow port of the mockup editorial.jsx).

Renders the portrait 1200x1600 "Day Ahead" broadsheet: the date is the
masthead, Source Serif 4 for display type, TRMNL pixel fonts for every
label <= 21px. Pure presentation -- it consumes the ``DayShape`` dict from
``day_client.assemble_day_shape`` and never touches a DB or HA dict.

Colour is information (6-colour Spectra, snapped by the encoder):
  highs = RED, lows = BLUE, comfort-now warm/cool; meetings = BLUE,
  personal = GREEN, focus = INK, travel = GOLD; needs-you/now = RED;
  advisory/sun = YELLOW (marks only). Extra hues come from drawn dot-grid
  halftones (the masthead time-of-day sky) -- never under text -- so the
  encoder runs with dither=False and every pixel is already a palette ink.
"""
from __future__ import annotations

import logging
from typing import Optional

from PIL import Image, ImageDraw

from . import fonts
from .draw import (
    Box,
    diamond,
    draw_refresh_glyph,
    draw_text_bl,
    draw_text_bl_right,
    draw_text_clipped_bl,
    draw_tracked_text_bl,
    fill_box,
    font_metrics,
    hr,
    text_width,
    tracked_width,
    vline,
)
from .palette import Palette

logger = logging.getLogger(__name__)


# ── Frame geometry (mirrors editorial.jsx padding "30px 46px 26px") ────
CANVAS_W, CANVAS_H = 1200, 1600
PAD_TOP = 30
PAD_SIDE = 46
PAD_BOTTOM = 26
CX0 = PAD_SIDE
CX1 = CANVAS_W - PAD_SIDE          # 1154
CONTENT_W = CX1 - CX0              # 1108

# Bottom region (rails + colophon) is pinned to the bottom; the rails are
# sized to their content (computed from font metrics) so dividers always land
# in the inter-row gaps and slack falls into the timeline spacer above.
COLOPHON_H = 30
RAILS_COLOPHON_GAP = 14
RAILS_TIMELINE_GAP = 16

# The House is compact (a few temps), so it gets a fixed narrow column and the
# needs-reply list takes the rest of the width (longer subjects, fewer ellipses).
HOUSE_COL_W = 340
RAILS_GAP = 26

# Priorities rail layout (shared by the drawer and the height calc so they can
# never disagree -> no text-through-rules). Two-line rows: bold action line +
# muted detail line.
NR_MAX_ROWS = 5
NR_PAD_TOP = 4
NR_MID_GAP = 2
NR_PAD_BOTTOM = 8


# ── Colour helpers ─────────────────────────────────────────────────────


def _accent(P: Palette, name: Optional[str]):
    return {
        "red": P.red,
        "blue": P.blue,
        "green": P.green,
        "yellow": P.yellow,
        "ink": P.ink,
    }.get(name or "ink", P.ink)


# Event kind -> accent (meeting=blue, focus=ink, personal=green, travel=gold)
KIND_ACCENT = {"meeting": "blue", "focus": "ink", "personal": "green", "travel": "yellow"}

# Priority kind -> accent for the "what matters now" rail. prep=blue (meeting),
# reply/decision=red (acts on you), review=ink, personal=green, travel=gold.
PRIO_ACCENT = {
    "prep": "blue",
    "reply": "red",
    "decision": "red",
    "review": "ink",
    "personal": "green",
    "travel": "yellow",
}


def _temp_color(P: Palette, t, kind: str):
    if P.is_bw:
        return P.ink
    if kind == "hi":
        return P.red
    if kind == "lo":
        return P.blue
    if t is None:
        return P.ink
    if t >= 72:
        return P.red
    if t <= 55:
        return P.blue
    return P.ink


# ── Font shortcuts ─────────────────────────────────────────────────────


def _serif(size: int, weight: str = "regular", italic: bool = False):
    return fonts.serif(size, weight=weight, italic=italic)


def _tr(size: int, bold: bool = False):
    return fonts.pix_trmnl(size, bold=bold)


def _em(size: int, em: float) -> int:
    return int(round(size * em))


# ── Time-label helpers (port of mockup data.js) ────────────────────────


def _ampm(minute: int) -> str:
    h = ((minute // 60 + 11) % 12) + 1
    m = minute % 60
    return str(h) if m == 0 else f"{h}:{m:02d}"


def _mer(minute: int) -> str:
    return "AM" if (minute // 60) < 12 else "PM"


def _dur_label(start_min: int, end_min: int) -> str:
    d = max(0, end_min - start_min)
    if d == 0:
        return ""
    if d % 60 == 0:
        return f"{d // 60}h"
    if d < 60:
        return f"{d}m"
    return f"{d // 60}h{d % 60}m"


def _rel_label(start_min: int, now_min: int) -> Optional[str]:
    d = start_min - now_min
    if d <= 0:
        return "now"
    if d < 60:
        return f"in {d}m"
    if d < 240:
        return f"in {d // 60}h" if d % 60 == 0 else f"in {d // 60}h{d % 60}m"
    return None


# ── DayShape prep + hero pick ──────────────────────────────────────────


def _prep(day: dict) -> dict:
    """Enrich events with display fields and pick the hero (now/next/calm)."""
    now_min = int(day.get("nowMin", 0))
    events = day.get("events") or []
    for e in events:
        sm = int(e.get("startMin", 0))
        em = int(e.get("endMin", 0))
        e["startLabel"] = _ampm(sm)
        e["startMer"] = _mer(sm)
        e["dur"] = _dur_label(sm, em)
        e["accent"] = KIND_ACCENT.get(e.get("kind"), "ink")
        e["happeningNow"] = (not e.get("allDay")) and sm <= now_min < em

    timed = [e for e in events if not e.get("allDay")]
    allday = [e for e in events if e.get("allDay")]
    upcoming = sorted(
        [e for e in timed if int(e.get("endMin", 0)) > now_min],
        key=lambda e: int(e.get("startMin", 0)),
    )

    hero_kind, hero = "calm", None
    for e in upcoming:
        if e["happeningNow"]:
            hero_kind, hero = "now", e
            break
    if hero is None and upcoming:
        hero_kind, hero = "next", upcoming[0]

    if hero is not None and hero_kind == "next":
        hero["rel"] = _rel_label(int(hero["startMin"]), now_min)
    elif hero is not None:
        hero["rel"] = "now"

    return {
        "timed": timed,
        "allday": allday,
        "upcoming": upcoming,
        "hero_kind": hero_kind,
        "hero": hero,
        "calm": hero_kind == "calm",
    }


# ── Weather glyph (B&W, hand-drawn -- port of atoms.jsx WeatherGlyph) ───


def _cloud(draw: ImageDraw.ImageDraw, cx: float, cy: float, w: float,
           color, bg, stroke: int) -> None:
    """Outlined cloud: draw the filled silhouette, then erase the interior
    inset by `stroke` so a clean `stroke`-px ring remains."""
    st = max(1, int(stroke))

    def _puffs(shrink: float):
        return [
            (cx - w * 0.30, cy, w * 0.30 - shrink),
            (cx + 0.00, cy - w * 0.16, w * 0.34 - shrink),
            (cx + w * 0.30, cy, w * 0.28 - shrink),
        ]

    def _base(shrink: float):
        return (cx - w * 0.55 + shrink, cy - w * 0.02 + shrink,
                cx + w * 0.55 - shrink, cy + w * 0.30 - shrink)

    # Outer silhouette.
    for px, py, r in _puffs(0):
        if r > 0:
            draw.ellipse([px - r, py - r, px + r, py + r], fill=color)
    bx0, by0, bx1, by1 = _base(0)
    draw.rectangle([bx0, by0, bx1, by1], fill=color)
    # Erase interior (leave the ring).
    for px, py, r in _puffs(st):
        if r > 0:
            draw.ellipse([px - r, py - r, px + r, py + r], fill=bg)
    bx0, by0, bx1, by1 = _base(st)
    if bx1 > bx0 and by1 > by0:
        draw.rectangle([bx0, by0, bx1, by1], fill=bg)


def draw_weather_glyph(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int,
                       code: str, *, color, bg, stroke: int = 3) -> None:
    """Hand-built weather symbol (no icon font). Pure ink on `bg`."""
    s = float(size)
    st = max(1, int(stroke))

    def ray(a, r1, r2, width):
        import math
        x1 = cx + math.cos(a) * r1
        y1 = cy + math.sin(a) * r1
        x2 = cx + math.cos(a) * r2
        y2 = cy + math.sin(a) * r2
        draw.line([(x1, y1), (x2, y2)], fill=color, width=max(1, int(width)))

    import math

    if code in ("sunny", "clear"):
        r = s * 0.20
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=st)
        for i in range(8):
            a = (math.pi / 4) * i
            ray(a, r + s * 0.10, r + s * 0.22, st)
    elif code == "partly":
        sx = cx - s * 0.14
        sy = cy - s * 0.16
        r = s * 0.16
        draw.ellipse([sx - r, sy - r, sx + r, sy + r], outline=color, width=st)
        for i in range(8):
            a = (math.pi / 4) * i
            x1 = sx + math.cos(a) * (r + s * 0.07)
            y1 = sy + math.sin(a) * (r + s * 0.07)
            x2 = sx + math.cos(a) * (r + s * 0.15)
            y2 = sy + math.sin(a) * (r + s * 0.15)
            draw.line([(x1, y1), (x2, y2)], fill=color, width=max(1, st - 1))
        _cloud(draw, cx + s * 0.06, cy + s * 0.12, s * 0.62, color, bg, st)
    elif code == "cloudy":
        _cloud(draw, cx, cy, s * 0.74, color, bg, st)
    elif code == "rain":
        _cloud(draw, cx, cy - s * 0.06, s * 0.66, color, bg, st)
        for i in range(3):
            x = cx - s * 0.18 + i * s * 0.18
            draw.line([(x, cy + s * 0.22), (x - s * 0.06, cy + s * 0.40)],
                      fill=color, width=st)
    else:
        f = _serif(int(s * 0.5), "bold")
        draw_text_bl(draw, (int(cx - s * 0.14), int(cy + s * 0.18)), "?", f, color)


def _weather_stamp(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int,
                   code: str, P: Palette) -> None:
    """Ink ring with a B&W weather glyph inside (the masthead stamp)."""
    r = size // 2
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=P.ink, width=3)
    draw_weather_glyph(draw, cx, cy, int(size * 0.66), code,
                       color=P.ink, bg=P.bg, stroke=3)


# ── Time-of-day masthead sky (drawn dot-grid halftone) ─────────────────


def _sky_period(now_min: int) -> str:
    h = (now_min or 0) / 60
    if h < 5:
        return "night"
    if h < 8:
        return "dawn"
    if h < 11:
        return "morning"
    if h < 15:
        return "midday"
    if h < 18:
        return "afternoon"
    if h < 21:
        return "dusk"
    return "night"


# Target sky hue per period -- a true RGB colour that Atkinson then dithers
# down to the panel inks. Duo periods (orange / violet) have no native ink, so
# the dither interleaves two inks to read as the mixed hue at distance.
def _period_sky_color(P: Palette, period: str):
    if P.is_bw:
        return (40, 40, 40)
    return {
        "dawn": (236, 122, 42),       # warm sunrise (red + yellow)
        "morning": (96, 146, 200),    # clear cool blue
        "midday": (42, 92, 168),      # deep blue
        "afternoon": (236, 150, 36),  # warm gold
        "dusk": (122, 72, 142),       # violet (blue + red)
        "night": (26, 52, 112),       # deep night blue
    }.get(period, (96, 146, 200))


def _period_inks(P: Palette, period: str):
    """The native inks Atkinson may use for a period (plus paper white)."""
    white = P.bg
    if P.is_bw:
        return [white, P.ink]
    duos = {
        "dawn": [white, P.red, P.yellow],
        "afternoon": [white, P.red, P.yellow],
        "dusk": [white, P.blue, P.red],
    }
    return duos.get(period, [white, P.blue])


def _draw_sky_atkinson(img: Image.Image, x0: int, y0: int, x1: int, y1: int,
                       now_min: int, P: Palette) -> None:
    """Paint the time-of-day masthead sky as an Atkinson-dithered gradient.

    A smooth vertical ramp (dense period-hue at the top fading to paper by
    the date line) is error-diffused to the panel inks, giving a crisp,
    pixel-perfect halftone. Every output pixel is already a palette colour,
    so the Spectra-6 encoder's ``dither=False`` passes it through verbatim
    and the result is deterministic (stable ETag). The weekday ink draws on
    top afterwards, so the dither never sits under type.
    """
    w = x1 - x0
    h = y1 - y0
    if w <= 0 or h <= 0:
        return
    period = _sky_period(now_min)
    top = _period_sky_color(P, period)
    inks = _period_inks(P, period)
    white = P.bg
    strength = 0.72 if period == "night" else 0.6
    if P.is_bw:
        strength = 0.5

    # Row-constant gradient: full strength at the top, easing to paper.
    px: list = [None] * (w * h)
    denom = float(h - 1) if h > 1 else 1.0
    for ry in range(h):
        f = 1.0 - ry / denom
        s = strength * (f ** 1.15)
        base = (
            white[0] + (top[0] - white[0]) * s,
            white[1] + (top[1] - white[1]) * s,
            white[2] + (top[2] - white[2]) * s,
        )
        row0 = ry * w
        for rx in range(w):
            px[row0 + rx] = base

    # Atkinson error diffusion (1/8 of the error to 6 forward neighbours).
    def _nearest(c):
        best = inks[0]
        bd = 1e18
        for p in inks:
            d = (c[0] - p[0]) ** 2 + (c[1] - p[1]) ** 2 + (c[2] - p[2]) ** 2
            if d < bd:
                bd = d
                best = p
        return best

    neigh = ((1, 0), (2, 0), (-1, 1), (0, 1), (1, 1), (0, 2))
    for ry in range(h):
        row0 = ry * w
        for rx in range(w):
            i = row0 + rx
            old = px[i]
            new = _nearest(old)
            px[i] = new
            er = (old[0] - new[0]) / 8.0
            eg = (old[1] - new[1]) / 8.0
            eb = (old[2] - new[2]) / 8.0
            if er or eg or eb:
                for dx, dy in neigh:
                    nx = rx + dx
                    ny = ry + dy
                    if 0 <= nx < w and 0 <= ny < h:
                        j = ny * w + nx
                        q = px[j]
                        px[j] = (q[0] + er, q[1] + eg, q[2] + eb)

    region = Image.new("RGB", (w, h))
    region.putdata([(int(p[0]), int(p[1]), int(p[2])) for p in px])
    img.paste(region, (x0, y0))


# ── Small ornaments ────────────────────────────────────────────────────


def _gem(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, color) -> None:
    diamond(draw, cx, cy, size, color)


def _dot_marker(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int, *,
                filled: bool, color) -> None:
    box = [cx - r, cy - r, cx + r, cy + r]
    if filled:
        draw.ellipse(box, fill=color)
    else:
        draw.ellipse(box, outline=color, width=2)


# ── Kickers ────────────────────────────────────────────────────────────


def _kicker_tab(draw: ImageDraw.ImageDraw, x0: int, x1: int, y: int,
                text: str, color, P: Palette) -> int:
    """Solid accent tab with paper text + accent rule + accent diamond.

    The single loudest colour on the page (one per render). Returns the y
    below the tab.
    """
    c = P.ink if P.is_bw else color
    f = _tr(21, bold=True)
    tracking = _em(21, 0.14)
    fm = font_metrics(f)
    tw = tracked_width(f, text, tracking)
    pad_x = 11
    tab_top = 6
    tab_bottom = 5
    tab_h = fm.ascent + tab_top + tab_bottom
    tab_w = tw + pad_x * 2
    # Tab background.
    fill_box(draw, Box(x0, y, x0 + tab_w, y + tab_h), c)
    baseline = y + tab_top + fm.ascent
    draw_tracked_text_bl(draw, (x0 + pad_x, baseline), text, f, P.bg, tracking)
    # Accent rule to the diamond, then the diamond.
    bar_y = y + tab_h // 2
    dia_cx = x1 - 6
    bar_x0 = x0 + tab_w + 12
    bar_x1 = dia_cx - 12
    if bar_x1 > bar_x0:
        hr(draw, bar_x0, bar_x1, bar_y - 2, thickness=4, fill=c)
    _gem(draw, dia_cx, bar_y, 12, c)
    return y + tab_h


def _kicker(draw: ImageDraw.ImageDraw, x0: int, x1: int, y: int, text: str,
            P: Palette, *, color=None, rule: bool = True) -> int:
    """Diamond + tracked label + optional rule to the right edge."""
    c = color or P.ink
    f = _tr(21, bold=True)
    tracking = _em(21, 0.15)
    fm = font_metrics(f)
    baseline = y + fm.ascent
    cy = y + fm.ascent // 2 + 1
    _gem(draw, x0 + 5, cy, 10, c)
    tx = x0 + 18
    w = draw_tracked_text_bl(draw, (tx, baseline), text, f, c, tracking)
    if rule:
        rule_x0 = tx + w + 12
        if rule_x0 < x1:
            hr(draw, rule_x0, x1, cy - 1, thickness=2, fill=P.rule)
    return y + fm.ascent + 4


# ── Masthead ───────────────────────────────────────────────────────────


_WEEKDAY_SIZES = (134, 126, 118, 110, 102, 96, 88)


def _fit_weekday(text: str, max_w: int):
    """Largest weekday serif size whose (untracked) width fits `max_w`.

    Negative tracking only tightens the rendered run, so an untracked fit is a
    safe upper bound -- the drawn weekday never exceeds `max_w`.
    """
    for sz in _WEEKDAY_SIZES:
        f = _serif(sz, "bold")
        if text_width(f, text) <= max_w:
            return f, sz
    return _serif(_WEEKDAY_SIZES[-1], "bold"), _WEEKDAY_SIZES[-1]


def _draw_masthead(img: Image.Image, draw: ImageDraw.ImageDraw, day: dict,
                   P: Palette, y: int) -> int:
    d = day.get("date") or {}
    now_min = int(day.get("nowMin", 0))
    weekday = (d.get("weekday") or "").strip()
    month_day = (d.get("monthDay") or "").strip()
    year = (d.get("year") or "").strip()

    band_top = y

    # Date group (floated right): red gem + "MONTH DAY" + italic year + blue gem.
    f_md = _serif(44, "semibold")
    f_yr = _serif(34, "regular", italic=True)
    fm_md = font_metrics(f_md)
    gap = 12
    dsz = 12
    w_md = text_width(f_md, month_day)
    w_yr = text_width(f_yr, year)
    date_w = dsz + gap + w_md + ((gap + w_yr) if year else 0) + gap + dsz

    # Weekday on the left, auto-fit into the width left of the date so long
    # days ("WEDNESDAY") never collide with the date.
    max_week_w = (CX1 - date_w - 40) - CX0
    f_week, week_sz = _fit_weekday(weekday, max_week_w)
    fm_week = font_metrics(f_week)

    # Eyebrow metrics first -- the title is centred against the bottom of the
    # "AS OF ..." line and the top of the red rule.
    f_eye = _tr(16)
    fm_eye = font_metrics(f_eye)
    eb_base = band_top + fm_eye.ascent + 2
    eyebrow_bottom = eb_base + fm_eye.descent

    # Centre the weekday cap-box between the eyebrow and the rule, with equal
    # (tightened) breathing space above and below.
    breath = 15
    cap_h = int(week_sz * 0.68)  # Source Serif cap height is ~0.66-0.70 em
    weekday_baseline = eyebrow_bottom + breath + cap_h
    band_bottom = weekday_baseline + breath

    # Full-bleed time-of-day sky (edge to edge). Ink text draws on top.
    _draw_sky_atkinson(img, 0, 0, CANVAS_W, band_bottom, now_min, P)

    # Eyebrow row.
    draw_tracked_text_bl(draw, (CX0 + 2, eb_base),
                         f"AS OF {(day.get('asOf') or '').upper()}", f_eye,
                         P.ink, _em(16, 0.14))
    draw_tracked_text_bl_right(draw, (CX1 - 2, eb_base), "THE DAY AHEAD",
                               f_eye, P.ink, _em(16, 0.22))

    # Weekday, left-aligned with tight tracking.
    draw_tracked_text_bl(draw, (CX0, weekday_baseline), weekday, f_week, P.ink,
                         _em(week_sz, -0.035))

    # Date, right-aligned on the weekday baseline, flanked by gems.
    x = CX1 - date_w
    mid = weekday_baseline - fm_md.ascent // 2
    _gem(draw, x + dsz // 2, mid, dsz, _accent(P, "red"))
    x += dsz + gap
    x += draw_text_bl(draw, (x, weekday_baseline), month_day, f_md, P.ink) + gap
    if year:
        x += draw_text_bl(draw, (x, weekday_baseline), year, f_yr, P.ink) + gap
    _gem(draw, x + dsz // 2, mid, dsz, _accent(P, "blue"))

    # Red spot rule.
    y = hr(draw, CX0, CX1, band_bottom, thickness=2, fill=_accent(P, "red"))
    return y


def _draw_tracked_center(draw, cx, baseline, text, font, fill, tracking_px):
    w = tracked_width(font, text, tracking_px)
    draw_tracked_text_bl(draw, (cx - w // 2, baseline), text, font, fill, tracking_px)


def draw_tracked_text_bl_right(draw, xy_right, text, font, fill, tracking_px):
    w = tracked_width(font, text, tracking_px)
    return draw_tracked_text_bl(draw, (xy_right[0] - w, xy_right[1]), text, font, fill, tracking_px)


# ── Weather band ───────────────────────────────────────────────────────


def _draw_weather(draw: ImageDraw.ImageDraw, day: dict, P: Palette, y: int) -> int:
    w = day.get("weather") or {}
    now = w.get("now") or {}
    top = y + 16
    stamp_size = 104
    stamp_cx = CX0 + stamp_size // 2
    stamp_cy = top + stamp_size // 2
    _weather_stamp(draw, stamp_cx, stamp_cy, stamp_size, now.get("code") or "cloudy", P)

    # Temp block to the right of the stamp.
    tx = CX0 + stamp_size + 18
    temp = now.get("temp")
    f_temp = _serif(84, "bold")
    fm_temp = font_metrics(f_temp)
    temp_base = top + fm_temp.ascent
    tc = _temp_color(P, temp, "now")
    temp_str = "--" if temp is None else str(temp)
    tw = draw_text_bl(draw, (tx, temp_base), temp_str, f_temp, tc)
    f_deg = _serif(32, "semibold")
    draw_text_bl(draw, (tx + tw + 2, top + font_metrics(f_deg).ascent + 4), "\u00b0", f_deg, tc)

    f_lab = _tr(16)
    fm_lab = font_metrics(f_lab)
    lab_base = temp_base + fm_lab.ascent + 6
    label = (now.get("label") or "").upper()
    draw_tracked_text_bl(draw, (tx, lab_base), label, f_lab, P.ink, _em(16, 0.1))

    hi, lo = w.get("hi"), w.get("lo")
    hilo_base = lab_base + fm_lab.ascent + 6
    cur = tx
    if hi is not None:
        cur += draw_text_bl(draw, (cur, hilo_base), f"HI {hi}\u00b0", f_lab, _accent(P, "red")) + 12
    if lo is not None:
        draw_text_bl(draw, (cur, hilo_base), f"LO {lo}\u00b0", f_lab, _accent(P, "blue"))

    stamp_bottom = top + stamp_size
    left_bottom = hilo_base + fm_lab.descent
    forecast = w.get("forecast") or []
    if forecast:
        # Divider rule then N equal forecast cells, aligned to the stamp height.
        div_x = tx + 360
        if div_x < CX0 + stamp_size + 140:
            div_x = CX0 + stamp_size + 200
        vline(draw, div_x, top + 6, stamp_bottom - 6, thickness=2, fill=P.rule)
        cells_x0 = div_x + 1
        cells = forecast[:3]
        cw = (CX1 - cells_x0) // max(1, len(cells))
        f_dow = _tr(16, bold=True)
        f_t = _tr(21)
        for i, fc in enumerate(cells):
            ccx = cells_x0 + cw * i + cw // 2
            if i < len(cells) - 1:
                vline(draw, cells_x0 + cw * (i + 1), top + 10, stamp_bottom - 10,
                      thickness=2, fill=P.rule)
            dy = top + 4 + font_metrics(f_dow).ascent
            _draw_tracked_center(draw, ccx, dy, fc.get("dow") or "", f_dow, P.ink, _em(16, 0.12))
            draw_weather_glyph(draw, ccx, top + 56, 34, fc.get("code") or "cloudy",
                               color=P.ink, bg=P.bg, stroke=2)
            fhi, flo = fc.get("hi"), fc.get("lo")
            ty = stamp_bottom - 8
            seg = []
            if fhi is not None:
                seg.append((f"{fhi}\u00b0", _accent(P, "red")))
            if flo is not None:
                seg.append((f"{flo}\u00b0", _accent(P, "blue")))
            seg_w = sum(text_width(f_t, s) for s, _ in seg) + (7 if len(seg) == 2 else 0)
            sx = ccx - seg_w // 2
            for s, col in seg:
                sx += draw_text_bl(draw, (sx, ty), s, f_t, col) + 7

    return max(stamp_bottom, left_bottom)


# ── Lead story ─────────────────────────────────────────────────────────


def _lead_deck(e: dict) -> str:
    if e.get("happeningNow"):
        loc = e.get("loc")
        return f"In progress now \u2014 {loc}." if loc else "In progress now."
    kind = e.get("kind")
    dur = e.get("dur") or ""
    loc = e.get("loc") or ""
    people = e.get("people") or 0
    if kind == "meeting":
        extra = f", {people} on the invite." if people else "."
        return f"{dur} in {loc}{extra}"
    if kind == "focus":
        return f"A {dur} window to get ahead before the day fills in."
    if kind == "personal":
        return f"Off the clock \u2014 {loc}." if loc else "Off the clock."
    return f"{dur} \u00b7 {loc}." if loc else f"{dur}."


def _period_word(now_min: int) -> str:
    p = _sky_period(now_min)
    if p in ("dusk", "night"):
        return "evening"
    if p in ("midday", "afternoon"):
        return "afternoon"
    return "morning"


def _fact_strip(draw: ImageDraw.ImageDraw, x0: int, x1: int, y: int,
                cells: list, P: Palette, tint: Optional[str]) -> int:
    a = _accent(P, tint) if tint else P.ink
    # Top accent rule.
    y = hr(draw, x0, x1, y, thickness=2, fill=a)
    f_key = _tr(12)
    f_val = _serif(27, "bold")
    f_sub = _tr(12)
    fm_key = font_metrics(f_key)
    fm_val = font_metrics(f_val)
    fm_sub = font_metrics(f_sub)
    pad_t, pad_b, pad_x = 11, 13, 16
    cell_h = pad_t + fm_key.ascent + 6 + fm_val.ascent + 5 + fm_sub.ascent + pad_b
    n = max(1, len(cells))
    cw = (x1 - x0) // n
    for i, c in enumerate(cells):
        cellx0 = x0 + cw * i
        if i:
            vline(draw, cellx0, y, y + cell_h, thickness=2, fill=P.rule)
        tx = cellx0 + (0 if i == 0 else 0) + pad_x
        ky = y + pad_t + fm_key.ascent
        draw_tracked_text_bl(draw, (tx, ky), (c.get("k") or "").upper(), f_key,
                             P.ink, _em(12, 0.16))
        vy = ky + 6 + fm_val.ascent
        col = c.get("color") or P.ink
        draw_text_clipped_bl(draw, (tx, vy), str(c.get("v") or ""), f_val, col,
                             max_w=cw - pad_x * 2)
        if c.get("sub"):
            sy = vy + 5 + fm_sub.ascent
            draw_tracked_text_bl(draw, (tx, sy), str(c["sub"]).upper(), f_sub,
                                 P.ink, _em(12, 0.06))
    # Bottom rule.
    bottom = y + cell_h
    hr(draw, x0, x1, bottom, thickness=2, fill=P.rule)
    return bottom + 2


def _draw_lead(draw: ImageDraw.ImageDraw, day: dict, prep: dict, P: Palette, y: int) -> int:
    y += 22
    if prep["calm"]:
        return _draw_lead_calm(draw, day, P, y)
    return _draw_lead_event(draw, day, prep, P, y)


def _draw_lead_event(draw: ImageDraw.ImageDraw, day: dict, prep: dict, P: Palette, y: int) -> int:
    e = prep["hero"]
    now_min = int(day.get("nowMin", 0))
    soon = e.get("happeningNow") or (int(e["startMin"]) - now_min <= 30)
    a_kind = "red" if (e.get("happeningNow") or soon) else "blue"
    a_color = _accent(P, a_kind)

    if e.get("happeningNow"):
        kick = "HAPPENING NOW"
    else:
        rel = e.get("rel")
        tail = rel.upper() if rel else f"{e['startLabel']} {e['startMer']}"
        kick = f"UP NEXT \u00b7 {tail}"
    y = _kicker_tab(draw, CX0, CX1, y, kick, a_color, P) + 12

    # Time column (right-aligned within min width 152) + accent bar + body.
    col_w = 152
    time_x1 = CX0 + col_w
    f_time = _serif(66, "bold")
    fm_time = font_metrics(f_time)
    time_base = y + 6 + fm_time.ascent
    draw_text_bl_right(draw, (time_x1, time_base), e["startLabel"], f_time, a_color)
    f_mer = _tr(21)
    fm_mer = font_metrics(f_mer)
    mer_base = time_base + fm_mer.ascent + 4
    draw_text_bl_right(draw, (time_x1, mer_base),
                       f"{e['startMer']} \u00b7 {e['dur']}", f_mer, P.ink)

    bar_x = time_x1 + 22
    body_x = bar_x + 4 + 18

    f_title = _serif(60, "bold")
    fm_title = font_metrics(f_title)
    title_base = y + fm_title.ascent
    end_y = _draw_wrapped(draw, body_x, CX1, title_base, e.get("title") or "",
                          f_title, P.ink, line_h=int(fm_title.line_height * 0.97),
                          max_lines=2)
    f_deck = _serif(26, "regular", italic=True)
    fm_deck = font_metrics(f_deck)
    deck_base = end_y + 10 + fm_deck.ascent
    deck_end = _draw_wrapped(draw, body_x, CX1, deck_base, _lead_deck(e), f_deck,
                             P.ink, line_h=fm_deck.line_height, max_lines=2)

    # Accent bar spans the time/body block height.
    bar_bottom = max(mer_base, deck_end)
    fill_box(draw, Box(bar_x, y, bar_x + 4, bar_bottom), a_color)

    y = max(mer_base, deck_end) + 18

    # FactStrip.
    upcoming = prep["upcoming"]
    nxt = upcoming[1] if len(upcoming) > 1 else None
    end_label = _ampm(int(e["endMin"]))
    where_sub = f"{e['people']} PEOPLE" if e.get("people") else (e.get("kind") or "").upper()
    cells = [
        {"k": "WHEN", "v": f"{e['startLabel']}\u2013{end_label}", "sub": e["startMer"]},
        {"k": "WHERE", "v": e.get("loc") or "\u2014", "sub": where_sub},
        {"k": "THEN", "v": (nxt["startLabel"] if nxt else "\u2014"),
         "sub": (nxt["title"].upper()[:16] if nxt else "CLEAR")},
    ]
    y = _fact_strip(draw, CX0, CX1, y, cells, P, a_kind)
    return y


def _draw_lead_calm(draw: ImageDraw.ImageDraw, day: dict, P: Palette, y: int) -> int:
    now_min = int(day.get("nowMin", 0))
    word = _period_word(now_min)
    y = _kicker_tab(draw, CX0, CX1, y, "THE QUIET EDITION", _accent(P, "green"), P) + 12

    f_cap = _serif(96, "bold")
    fm_cap = font_metrics(f_cap)
    cap_base = y + fm_cap.ascent
    cap_w = text_width(f_cap, "A")
    draw_text_bl(draw, (CX0, cap_base), "A", f_cap, _accent(P, "green"))

    body_x = CX0 + cap_w + 14
    f_head = _serif(60, "bold")
    fm_head = font_metrics(f_head)
    head_base = y + fm_head.ascent
    head_end = _draw_wrapped(draw, body_x, CX1, head_base, f"quiet {word} ahead.",
                             f_head, P.ink, line_h=int(fm_head.line_height * 0.97),
                             max_lines=2)
    mail = day.get("mail") or {}
    nr = mail.get("needsReply") or {}
    nr_count = int(nr.get("count", 0))
    inbox_clear = nr_count == 0

    f_deck = _serif(27, "regular", italic=True)
    fm_deck = font_metrics(f_deck)
    deck_base = max(head_end, cap_base) + 10 + fm_deck.ascent
    # The calm hero is calendar-only -- don't claim the inbox is clear when it
    # isn't (the rail below shows the real backlog).
    if inbox_clear:
        deck = (f"Nothing on the calendar and the inbox is clear. "
                f"The {word} is yours \u2014 enjoy it.")
    else:
        noun = "email" if nr_count == 1 else "emails"
        deck = (f"The calendar is clear. {nr_count} {noun} still "
                f"need a reply \u2014 see below.")
    deck_end = _draw_wrapped(draw, CX0, CX1, deck_base, deck, f_deck, P.ink,
                             line_h=fm_deck.line_height, max_lines=2)
    y = deck_end + 20

    tomorrow = (day.get("tomorrow") or {}).get("first") or {}
    if inbox_clear:
        inbox_cell = {"k": "INBOX", "v": "CLEAR", "sub": f"{mail.get('unread', 0)} UNREAD",
                      "color": _accent(P, "green")}
    else:
        inbox_cell = {"k": "INBOX", "v": str(nr_count), "sub": "NEED REPLY",
                      "color": _accent(P, "red")}
    cells = [
        inbox_cell,
        {"k": "AWAITING", "v": str(mail.get("awaiting", 0)), "sub": "TO HEAR BACK"},
        {"k": "TOMORROW", "v": (tomorrow.get("start") or "\u2014"),
         "sub": (tomorrow.get("title", "").upper()[:16] if tomorrow.get("title") else "CLEAR")},
    ]
    y = _fact_strip(draw, CX0, CX1, y, cells, P, "green")
    return y


# ── Timeline ───────────────────────────────────────────────────────────


def _layout_allday(titles: list, font, widths: list) -> tuple[list, int]:
    """Greedy-pack `titles` (joined by a dot separator) into up to 2 lines of
    the given pixel `widths`. Returns ``(lines, remaining)`` where lines is a
    2-list of strings and remaining is the count that didn't fit."""
    sep = "  \u00b7  "
    lines = ["", ""]
    li = 0
    i = 0
    n = len(titles)
    while i < n and li < len(lines):
        t = titles[i]
        trial = t if not lines[li] else lines[li] + sep + t
        if text_width(font, trial) <= widths[li]:
            lines[li] = trial
            i += 1
        elif not lines[li]:
            lines[li] = t  # lone over-long title: place it, draw clips it
            i += 1
            li += 1
        else:
            li += 1  # this line is full; retry the same title on the next one
    return lines, n - i


def _draw_allday_band(draw: ImageDraw.ImageDraw, x0: int, x1: int, y: int,
                      allday: list, P: Palette) -> int:
    """Compress every all-day event into a hanging 'ALL DAY' label plus at most
    two wrapped lines of titles (with a '+N MORE' tail on overflow)."""
    if not allday:
        return y
    titles = [(e.get("title") or "").strip() or "(untitled)" for e in allday]
    f_lbl = _tr(16, bold=True)
    f_t = _serif(22, "semibold")
    fm_t = font_metrics(f_t)
    a = _accent(P, "green")

    base1 = y + fm_t.ascent
    _gem(draw, x0 + 5, base1 - int(fm_t.ascent * 0.42), 10, a)
    lbl_x = x0 + 18
    lbl_w = draw_tracked_text_bl(draw, (lbl_x, base1), "ALL DAY", f_lbl, a, _em(16, 0.12))
    titles_x = lbl_x + lbl_w + 16
    w1 = x1 - titles_x
    w2 = x1 - x0

    lines, remaining = _layout_allday(titles, f_t, [w1, w2])
    if remaining > 0:
        suffix_w = text_width(f_t, "  +99 MORE")
        lines, remaining = _layout_allday(titles, f_t, [w1, max(0, w2 - suffix_w)])
        suffix = f"  +{remaining} MORE"
        lines[1] = (lines[1] + suffix) if lines[1] else suffix

    if lines[0]:
        draw_text_clipped_bl(draw, (titles_x, base1), lines[0], f_t, P.ink, max_w=w1)
    base2 = base1
    if lines[1]:
        base2 = base1 + int(fm_t.line_height * 0.98)
        draw_text_clipped_bl(draw, (x0, base2), lines[1], f_t, P.ink, max_w=w2)
    bottom = base2 + fm_t.descent
    return hr(draw, x0, x1, bottom + 10, thickness=2, fill=P.rule) + 10


def _draw_timeline(draw: ImageDraw.ImageDraw, day: dict, prep: dict, P: Palette,
                   y: int, *, max_bottom: int) -> int:
    y += 24
    upcoming = prep["upcoming"]
    allday = prep["allday"]
    y = _kicker(draw, CX0, CX1, y, f"THE DAY \u00b7 {len(upcoming)} AHEAD", P)
    y += 8

    # All-day events are compressed into a single 2-line band above the timed
    # rows so a stack of them can't eat the screen.
    if allday:
        y = _draw_allday_band(draw, CX0, CX1, y, allday, P)

    if not upcoming:
        f = _serif(26, "regular", italic=True)
        fm = font_metrics(f)
        msg = "Nothing else on the schedule today." if allday else \
            "No further events scheduled today."
        draw_text_bl(draw, (CX0, y + fm.ascent + 4), msg, f, P.ink)
        return y + fm.line_height + 6

    f_time = _serif(34, "bold")
    f_mer = _tr(12)
    f_title = _serif(31, "semibold")
    f_meta = _tr(16)
    fm_title = font_metrics(f_title)
    fm_meta = font_metrics(f_meta)
    row_h = 13 + max(font_metrics(f_time).ascent, fm_title.ascent) + 6 + fm_meta.ascent + 13
    time_col_w = 122
    dia_gutter = 16

    drawn = 0
    for i, e in enumerate(upcoming):
        if y + row_h > max_bottom:
            break
        a = _accent(P, KIND_ACCENT.get(e.get("kind"), "ink"))
        top = y
        # Divider between rows (at the boundary), so there's never a trailing
        # rule before the spacer.
        if drawn > 0:
            hr(draw, CX0, CX1, top, thickness=2, fill=P.rule)
        title_base = top + 13 + fm_title.ascent
        right_edge = CX0 + time_col_w
        # Time column, right-aligned within time_col_w so nothing spills into
        # the diamond gutter.
        fm_time = font_metrics(f_time)
        t_base = top + 13 + fm_time.ascent
        mer = e.get("startMer") or ""
        merw = text_width(f_mer, mer)
        if mer:
            draw_text_bl(draw, (right_edge - merw, t_base), mer, f_mer, P.ink)
        draw_text_bl_right(draw, (right_edge - merw - (3 if mer else 0), t_base),
                           e["startLabel"], f_time, a)
        # Diamond aligned to the title's cap-height centre, in the gutter.
        body_x = CX0 + time_col_w + dia_gutter + 12
        dia_cx = CX0 + time_col_w + dia_gutter // 2 + 4
        dia_cy = title_base - int(fm_title.ascent * 0.36)
        _gem(draw, dia_cx, dia_cy, 12, a)
        draw_text_clipped_bl(draw, (body_x, title_base), e.get("title") or "",
                             f_title, P.ink, max_w=CX1 - body_x)
        meta = (e.get("loc") or "").upper()
        dur = (e.get("dur") or "").upper()
        parts = [p for p in [meta, dur] if p]
        if e.get("people"):
            parts.append(f"{e['people']}P")
        meta_str = " \u00b7 ".join(parts)
        meta_base = title_base + 5 + fm_meta.ascent
        draw_tracked_text_bl(draw, (body_x, meta_base), meta_str, f_meta, P.ink,
                             _em(16, 0.06))
        y += row_h
        drawn += 1
    return y


# ── Bottom rails (needs-reply | the house) ─────────────────────────────


def _nr_row_h() -> int:
    fm_from = font_metrics(_tr(21, bold=True))
    fm_subj = font_metrics(_serif(21, "regular", italic=True))
    return (NR_PAD_TOP + fm_from.ascent + fm_from.descent + NR_MID_GAP
            + fm_subj.ascent + fm_subj.descent + NR_PAD_BOTTOM)


def _prio_header_h() -> int:
    fm_kick = font_metrics(_tr(21, bold=True))
    # kicker baseline + gap + rule + gap
    return (fm_kick.ascent + 4) + 8 + 2 + 8


def _priorities_height(day: dict) -> int:
    items = ((day.get("priorities") or {}).get("items")) or []
    header = _prio_header_h()
    if not items:
        fm = font_metrics(_serif(22, "regular", italic=True))
        return header + fm.ascent + fm.descent + 4
    n = max(1, min(NR_MAX_ROWS, len(items)))
    return header + n * _nr_row_h()


def _house_height(day: dict) -> int:
    house = day.get("house") or {}
    temps = house.get("temps") or {}
    fm_kick = font_metrics(_tr(21, bold=True))
    fm_out = font_metrics(_serif(60, "bold"))
    fm_lab = font_metrics(_tr(16))
    fm_ft = font_metrics(_serif(24, "semibold"))
    h = (fm_kick.ascent + 4) + 6 + fm_out.ascent + fm_lab.descent + 12
    floors = [v for v in (temps.get("third"), temps.get("second"),
                          temps.get("first"), temps.get("basement")) if v is not None]
    rows = (len(floors) + 1) // 2
    h += rows * (fm_ft.ascent + 8) + 10
    if (house.get("advisory") or "").strip():
        h += fm_lab.ascent + fm_lab.descent
    return h


def _draw_priorities(draw: ImageDraw.ImageDraw, x0: int, x1: int, y: int,
                     bottom: int, day: dict, P: Palette) -> None:
    """The 'what matters now' rail: up to five curated two-line priorities.

    Each row is a bold action line + a muted detail line, with a leading
    accent diamond keyed to the priority kind. Layout is driven by the same
    `_nr_row_h()` metrics as the height calc so dividers land in the gaps.
    """
    items = ((day.get("priorities") or {}).get("items")) or []
    empty = not items
    head_color = _accent(P, "green") if empty else _accent(P, "red")

    yy = _kicker(draw, x0, x1, y, "WHAT MATTERS NOW", P, color=head_color, rule=False)
    yy += 8
    yy = hr(draw, x0, x1, yy, thickness=2, fill=P.rule) + 8

    if empty:
        f = _serif(22, "regular", italic=True)
        fm = font_metrics(f)
        draw_text_bl(draw, (x0, yy + fm.ascent + 2), "Nothing pressing right now.", f, P.ink)
        return

    f_title = _tr(21, bold=True)
    f_detail = _serif(21, "regular", italic=True)
    fm_title = font_metrics(f_title)
    fm_detail = font_metrics(f_detail)
    pad_top, mid_gap, pad_bottom = NR_PAD_TOP, NR_MID_GAP, NR_PAD_BOTTOM
    title_box = fm_title.ascent + fm_title.descent
    row_h = _nr_row_h()

    avail = max(0, bottom - yy)
    max_rows = max(1, avail // row_h) if row_h else 0
    items = items[:min(NR_MAX_ROWS, max_rows)]
    n = len(items)
    dia_x = x0 + 6
    text_x = x0 + 24
    for i, it in enumerate(items):
        row_top = yy + i * row_h
        a = _accent(P, PRIO_ACCENT.get(it.get("kind"), "ink"))
        title_base = row_top + pad_top + fm_title.ascent
        # Kind diamond, aligned to the action line's cap-height centre.
        _gem(draw, dia_x, title_base - int(fm_title.ascent * 0.40), 11, a)
        draw_text_clipped_bl(draw, (text_x, title_base), (it.get("title") or "").strip(),
                             f_title, P.ink, max_w=x1 - text_x)
        detail = (it.get("detail") or "").strip()
        if detail:
            detail_base = row_top + pad_top + title_box + mid_gap + fm_detail.ascent
            draw_text_clipped_bl(draw, (text_x, detail_base), detail, f_detail,
                                 P.ink, max_w=x1 - text_x)
        if i < n - 1:
            hr(draw, x0, x1, row_top + row_h - pad_bottom // 2, thickness=2, fill=P.rule)


def _draw_house(draw: ImageDraw.ImageDraw, x0: int, x1: int, y: int, day: dict,
                P: Palette) -> None:
    house = day.get("house") or {}
    temps = house.get("temps") or {}
    yy = _kicker(draw, x0, x1, y, "THE HOUSE", P, rule=False)
    yy += 6
    outdoor = temps.get("outdoor")
    f_out = _serif(60, "bold")
    fm_out = font_metrics(f_out)
    base = yy + fm_out.ascent
    ostr = "\u2014" if outdoor is None else f"{outdoor}\u00b0"
    ow = draw_text_bl(draw, (x0, base), ostr, f_out, _temp_color(P, outdoor, "now"))
    f_lab = _tr(16)
    draw_tracked_text_bl(draw, (x0 + ow + 12, base), "OUTSIDE NOW", f_lab, P.ink, _em(16, 0.08))
    yy = base + font_metrics(f_lab).descent + 12

    # Floor temps in a 2-col grid.
    floors = [("3F", temps.get("third")), ("2F", temps.get("second")),
              ("1F", temps.get("first")), ("BSMT", temps.get("basement"))]
    floors = [(lbl, v) for lbl, v in floors if v is not None]
    f_fl = _tr(16)
    f_ft = _serif(24, "semibold")
    fm_ft = font_metrics(f_ft)
    col_w = (x1 - x0) // 2
    row_h = fm_ft.ascent + 8
    for i, (lbl, v) in enumerate(floors):
        col = i % 2
        rown = i // 2
        cellx0 = x0 + col * col_w
        cellx1 = cellx0 + col_w - 22
        fy = yy + rown * row_h + fm_ft.ascent
        draw_tracked_text_bl(draw, (cellx0, fy), lbl, f_fl, P.ink, _em(16, 0.1))
        draw_text_bl_right(draw, (cellx1, fy), f"{v}\u00b0", f_ft, P.ink)
    rows = (len(floors) + 1) // 2
    yy = yy + rows * row_h + 10

    # Advisory only (garage / windows). Presence is intentionally not shown.
    advisory = (house.get("advisory") or "").strip()
    if advisory:
        f_p = _tr(16)
        fm_p = font_metrics(f_p)
        py = yy + fm_p.ascent
        _gem(draw, x0 + 6, py - fm_p.ascent // 2, 11, _accent(P, "yellow"))
        draw_text_clipped_bl(draw, (x0 + 18, py), advisory.upper(), f_p, P.ink,
                             max_w=x1 - (x0 + 18))


def _draw_bottom(draw: ImageDraw.ImageDraw, day: dict, P: Palette,
                 rails_top: int, rails_h: int) -> None:
    rails_bottom = rails_top + rails_h
    # Asymmetric columns: the compact House gets a fixed narrow column so the
    # needs-reply list claims the extra width. Rule sits between them.
    gap = RAILS_GAP
    right_x0, right_x1 = CX1 - HOUSE_COL_W, CX1
    rule_x = right_x0 - gap
    left_x0, left_x1 = CX0, rule_x - gap
    vline(draw, rule_x - 1, rails_top, rails_bottom, thickness=2, fill=P.rule)
    _draw_priorities(draw, left_x0, left_x1, rails_top, rails_bottom, day, P)
    _draw_house(draw, right_x0, right_x1, rails_top, day, P)

    # Colophon.
    cy = CANVAS_H - PAD_BOTTOM - COLOPHON_H
    cy = hr(draw, CX0, CX1, cy, thickness=2, fill=_accent(P, "red")) + 8
    f = _tr(16)
    fm = font_metrics(f)
    base = cy + fm.ascent
    tomorrow = (day.get("tomorrow") or {}).get("first") or {}
    if tomorrow:
        left = f"TOMORROW \u00b7 {tomorrow.get('start', '')} {(tomorrow.get('title') or '').upper()}"
    else:
        left = "TOMORROW \u00b7 CLEAR"
    draw_text_clipped_bl(draw, (CX0, base), left, f, P.ink, max_w=480)
    # Center gems.
    gx = (CX0 + CX1) // 2
    _gem(draw, gx - 12, base - fm.ascent // 2, 8, _accent(P, "red"))
    _gem(draw, gx, base - fm.ascent // 2, 8, _accent(P, "blue"))
    _gem(draw, gx + 12, base - fm.ascent // 2, 8, _accent(P, "green"))
    # Right refresh stamp.
    as_of = (day.get("asOf") or "").upper()
    rt = f"  {as_of}"
    rw = text_width(f, rt)
    gw = 9
    draw_refresh_glyph(draw, CX1 - rw - gw, base, size=gw, fill=P.ink)
    draw_text_bl_right(draw, (CX1, base), rt, f, P.ink)


# ── Wrapped serif headline helper ──────────────────────────────────────


def _draw_wrapped(draw: ImageDraw.ImageDraw, x0: int, x1: int, baseline: int,
                  text: str, font, fill, *, line_h: int, max_lines: int) -> int:
    """Greedy word-wrap, baseline-anchored. Returns baseline of last line."""
    words = (text or "").split()
    if not words:
        return baseline
    max_w = x1 - x0
    lines: list[str] = []
    cur = ""
    for wd in words:
        trial = wd if not cur else cur + " " + wd
        if text_width(font, trial) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = wd
        if len(lines) >= max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    lines = lines[:max_lines]
    by = baseline
    for i, ln in enumerate(lines):
        if i == max_lines - 1 and i < len(lines):
            draw_text_clipped_bl(draw, (x0, by), ln, font, fill, max_w=max_w)
        else:
            draw_text_bl(draw, (x0, by), ln, font, fill)
        if i < len(lines) - 1:
            by += line_h
    return by


# ── Entry point ────────────────────────────────────────────────────────


def render_dashboard(img: Image.Image, day: dict, P: Palette, *,
                     tz_name: Optional[str] = None) -> None:
    draw = ImageDraw.Draw(img)
    prep = _prep(day)

    y = PAD_TOP
    y = _draw_masthead(img, draw, day, P, y)
    y = _draw_weather(draw, day, P, y)
    y = _draw_lead(draw, day, prep, P, y)

    # Size the bottom rails to their content and pin them above the colophon;
    # the timeline gets whatever space is left (its spacer absorbs slack).
    colophon_top = CANVAS_H - PAD_BOTTOM - COLOPHON_H
    rails_h = max(_priorities_height(day), _house_height(day))
    rails_top = colophon_top - RAILS_COLOPHON_GAP - rails_h

    _draw_timeline(draw, day, prep, P, y, max_bottom=rails_top - RAILS_TIMELINE_GAP)
    _draw_bottom(draw, day, P, rails_top, rails_h)
