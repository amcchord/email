"""Swiss dashboard: one big number on a strict grid, with an ordered pixel dither.

The left column answers one question at a time. When the house is calm the hero
is the time; when something is running it is the minutes left, and when
something needs a person it is an inverted slab saying what to do. The right
column is the same reference every time: the weather and the rooms we watch.

Dither rule
-----------
Solid ink is what has been measured. Dithered pixels are what is forecast or
ambient: the coming daylight, the day's temperature range, the part of a heat-up
still to come. Never put type on the dither; both stay crisp only while they
stay apart.

Like ``editorial.py`` this is pure presentation over ``ha_view`` and the
appliance registry. Unknown readings print as dashes, never zeros.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from PIL import Image, ImageChops, ImageDraw

from ..sauna_forecast import READY_F, TARGET_F
from . import fonts, layout
from .appliances import ActiveAppliance, pick_active, pool_near_target
from .draw import (
    Box,
    draw_text_bl,
    draw_text_bl_right,
    draw_tracked_text_bl,
    font_metrics,
    pixel_dither,
    pick_fitting_size,
    text_width,
    tracked_width,
)
from .ha_view import ApplianceView
from .helpers import (
    clamp,
    compass,
    fmt_date,
    fmt_temp,
    fmt_weather,
    forecast_day_date,
    parse_iso,
    safe_round,
    to_float,
)
from .palette import Palette
from .render_ctx import RenderContext, build_render_context

_DASH = "—"
_DOT = " · "


def _bold(size: int):
    return fonts.sans(size, weight="bold")


def _medium(size: int):
    return fonts.sans(size, weight="medium")


def _reading(value: Any) -> str:
    return _DASH if to_float(value) is None else str(safe_round(value))


# ── Top level ──────────────────────────────────────────────────────────


def render_dashboard(
    img: Image.Image,
    ha: dict,
    P: Palette,
    *,
    tz_name: Optional[str] = None,
) -> None:
    draw = ImageDraw.Draw(img)
    # FreeType's 1-bit rasterizer: hinted stems with no grey pixels to threshold.
    draw.fontmode = "1"
    ctx = build_render_context(ha, P, tz_name=tz_name)
    L = layout.SWISS

    active = [
        a for a in pick_active(ha, ctx)
        if not (a.kind == "pool" and pool_near_target(a.view))
    ]
    unavailable = bool(ha.get("unavailable"))
    story = _no_data_story() if unavailable else _story_for(active, ctx)

    _draw_header(draw, ctx, story, L.masthead)
    if story.attention:
        _draw_attention(img, draw, ctx, story, L.hero)
    else:
        _draw_hero(img, draw, ctx, story, L.hero)

    if story.progress is not None:
        _draw_progress(img, draw, ctx, story, L.band)
    elif not unavailable:
        _draw_daylight(img, draw, ctx, ha, L.band)

    if not unavailable:
        if len(active) > 1:
            _draw_also_running(draw, ctx, active[1:], L.lower)
        else:
            _draw_forecast(img, draw, ctx, ha, L.lower)

    _draw_weather(img, draw, ctx, ha, L.weather)
    _draw_readings(img, draw, ctx, ha, L.readings)
    _draw_footer(draw, ctx, ha, L.colophon)


# ── Hero story: what the big number is right now ───────────────────────


@dataclass(frozen=True)
class Progress:
    """A measured value against its goal, with labels for both ends."""
    fraction: float
    start_label: str
    end_label: str
    accent: tuple


@dataclass(frozen=True)
class Story:
    kicker: str
    number: str = ""
    unit: tuple[str, ...] = ()
    word: bool = False  # The number is a word, set smaller than digits.
    measured: bool = True  # False prints the number in dither alone.
    detail: str = ""
    attention: bool = False
    headline: tuple[str, str] = ("", "")
    accent: Optional[tuple] = None
    progress: Optional[Progress] = None
    facts: list[tuple[str, str]] = field(default_factory=list)
    is_clock: bool = False


def _no_data_story() -> Story:
    return Story(
        kicker="Home Assistant isn't answering",
        number="No data",
        word=True,
        measured=False,
        detail="Readings on this page are unknown, not calm.",
    )


def _minutes_until(view: ApplianceView, ctx: RenderContext) -> Optional[int]:
    if view.finish_at_local is None:
        return None
    seconds = (view.finish_at_local - ctx.now_local).total_seconds()
    return max(0, math.ceil(seconds / 60))


def _countdown(view: ApplianceView, ctx: RenderContext, kicker: str, detail: str,
               progress: Optional[Progress] = None) -> Story:
    minutes = _minutes_until(view, ctx)
    accent = ctx.accent(view.accent_kind)
    if minutes is None:
        return Story(kicker=kicker, number=view.status_label or "Running", word=True,
                     detail=detail, accent=accent, progress=progress)
    return Story(kicker=kicker, number=str(minutes), unit=("min", "left"), detail=detail,
                 accent=accent, progress=progress)


def _sauna_story(view: ApplianceView, ctx: RenderContext) -> Story:
    accent = ctx.accent(view.accent_kind)
    forecast = view.extras.get("forecast")
    room = view.extras.get("room_temp")
    if not forecast:
        target = view.target if 104 <= (view.target or 0) <= 212 else None
        return Story(
            kicker="Sauna" + _DOT + "Heating",
            number=fmt_temp(view.current),
            unit=("cabin",),
            detail=(f"Heating to {fmt_temp(target)}" if target else "Heating to its preset"),
            accent=accent,
        )
    progress = None
    if room is not None:
        progress = Progress(
            fraction=clamp((room - 60) / (READY_F - 60)),
            start_label=f"Room {fmt_temp(room)}",
            end_label=f"Ready at {READY_F}°",
            accent=accent,
        )
    if forecast["ready_reached"]:
        detail = f"Room reached {READY_F}° at {forecast['ready_label']}"
        return Story(kicker="Sauna" + _DOT + "Ready", number="Ready", word=True,
                     detail=detail, accent=accent, progress=progress)
    if forecast["ready_label"] is None:
        return Story(kicker="Sauna" + _DOT + "Heating", number=fmt_temp(room), unit=("room",),
                     detail=f"Won't reach {READY_F}° at this target", accent=accent,
                     progress=progress)
    if forecast["ends_before_ready"]:
        detail = f"Session ends {forecast['ends_before_ready']}, before it's ready"
    elif forecast["fan_state"] == "running":
        detail = f"Ready around {forecast['ready_label']}. Fan has {forecast['fan_note']}"
    elif forecast["fan_state"] == "due":
        detail = f"Ready around {forecast['ready_label']}. Run the fan now"
    elif forecast["fan_state"] == "planned":
        detail = (f"Ready around {forecast['ready_label']}. "
                  f"Run the fan at {forecast['fan_label']}")
    else:
        detail = f"Ready around {forecast['ready_label']}"
    return Story(kicker="Sauna" + _DOT + "Heating", number=str(forecast["ready_in_minutes"]),
                 unit=("min to", "ready"), detail=detail, accent=accent, progress=progress)


def _story_for(active: list[ActiveAppliance], ctx: RenderContext) -> Story:
    if not active:
        now = ctx.now_local
        return Story(
            kicker="", number=now.strftime("%I:%M").lstrip("0"),
            unit=(now.strftime("%p"),), is_clock=True,
            accent=ctx.accent("info"),
        )
    view = active[0].view
    kind = view.kind
    accent = ctx.accent(view.accent_kind)
    if kind == "sauna":
        return _sauna_story(view, ctx)
    if kind in ("washer-done", "dryer-done"):
        head = (("Move the wash", "to the dryer.") if kind == "washer-done"
                else ("Unload", "the dryer."))
        return Story(kicker=view.eyebrow_kicker, attention=True, headline=head, accent=accent,
                     detail=f"Finished {view.finish_label}{_DOT}{view.relative_label}")
    if kind == "pool":
        target = fmt_temp(view.target)
        progress = None
        if view.current is not None and view.target:
            floor = min(view.current, 50.0)
            progress = Progress(
                fraction=clamp((view.current - floor) / max(1.0, view.target - floor)),
                start_label=f"Water {fmt_temp(view.current)}",
                end_label=f"Target {target}", accent=accent,
            )
        return Story(kicker=view.eyebrow_kicker, number=fmt_temp(view.current), unit=("water",),
                     detail=f"Heating to {target}", accent=accent, progress=progress)
    if kind == "dishwasher":
        progress = None
        if view.progress_pct is not None:
            progress = Progress(
                fraction=clamp(view.progress_pct / 100),
                start_label=f"{view.progress_pct}% done",
                end_label="100%", accent=accent,
            )
        return _countdown(view, ctx, "Dishwasher" + _DOT + (view.status_label or "Running"),
                          f"Done by {view.finish_label}{_DOT}{view.program_label}", progress)
    name = {"washer": "Washer", "dryer": "Dryer"}.get(kind, kind.replace("-", " ").title())
    detail = f"Done by {view.finish_label}" if view.finish_at_local else ""
    return _countdown(view, ctx, f"{name}{_DOT}{view.status_label or 'Running'}", detail)


# ── Header ─────────────────────────────────────────────────────────────


def _draw_header(draw, ctx: RenderContext, story: Story, box: Box) -> None:
    """Place and date. With a countdown as the hero, the time moves here, so it
    is always on the page exactly once."""
    P = ctx.palette
    head = _bold(layout.SwissType.HEADER_PX)
    label = _medium(layout.SwissType.HEADER_PX)
    baseline = box.y0 + font_metrics(head).ascent
    now = ctx.now_local
    lead = "Cambridge" if story.is_clock else now.strftime("%I:%M %p").lstrip("0")
    draw_text_bl(draw, (box.x0, baseline), lead, head, P.ink)
    draw_text_bl_right(draw, (box.x1, baseline), fmt_date(now), label, P.ink)


# ── Hero ───────────────────────────────────────────────────────────────


def _draw_hero(img: Image.Image, draw, ctx: RenderContext, story: Story, box: Box) -> None:
    """The big number with a dithered shadow, its unit, and one line of detail."""
    T = layout.SwissType
    P = ctx.palette
    unit_font = _bold(26)
    unit_w = max((text_width(unit_font, u) for u in story.unit), default=0)
    room = box.w - (unit_w + 12 if unit_w else 0) - 8
    candidates = T.WORD_CANDIDATES if story.word else T.HERO_CANDIDATES
    factory = _bold
    font, size = pick_fitting_size(factory, story.number, room, candidates,
                                   tracking_em=T.HERO_TRACKING_EM)
    tracking = round(size * T.HERO_TRACKING_EM)
    fm = font_metrics(font)
    cap_h = font.getbbox("0")[3] - font.getbbox("0")[1]

    top = box.y0 + 10
    if story.kicker:
        kicker = _bold(T.LABEL_PX)
        draw_text_bl(draw, (box.x0, top + font_metrics(kicker).ascent), story.kicker, kicker, P.ink)
        top += font_metrics(kicker).line_height + 6
    baseline = top + cap_h

    # The shadow is a dithered copy of the digits, printed before the solid ink.
    shadow = 7 if not story.word else 5
    mask = Image.new("L", (box.w + shadow, cap_h + fm.descent + shadow + 4), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.fontmode = "1"
    if story.measured:
        draw_tracked_text_bl(mask_draw, (shadow, shadow + cap_h), story.number, font, 110, tracking)
        pixel_dither(img, (box.x0, top), mask, story.accent or P.ink)
        draw_tracked_text_bl(draw, (box.x0, baseline), story.number, font, P.ink, tracking)
    else:
        draw_tracked_text_bl(mask_draw, (0, cap_h), story.number, font, 190, tracking)
        pixel_dither(img, (box.x0, top), mask, P.ink)

    number_w = tracked_width(font, story.number, tracking)
    unit_x = box.x0 + number_w + shadow + 8
    unit_y = top + font_metrics(unit_font).ascent - 6
    for line in story.unit:
        draw_text_bl(draw, (unit_x, unit_y), line, unit_font, P.ink)
        unit_y += 28

    if story.detail:
        detail, _ = pick_fitting_size(_medium, story.detail, box.w, (18, 17, 16, 15))
        # Words can have descenders; digits sit on the baseline.
        y = baseline + (fm.descent if story.word else shadow) + 8 + font_metrics(detail).ascent
        draw_text_bl(draw, (box.x0, min(y, box.y1 - 4)), story.detail, detail, P.ink)


def _draw_attention(img: Image.Image, draw, ctx: RenderContext, story: Story, box: Box) -> None:
    """Something needs a person: the only large area of solid ink on the page,
    dissolving into pixels at its foot."""
    P = ctx.palette
    fill = story.accent or P.ink
    fade = 22
    slab = Box(box.x0, box.y0 + 6, box.x1, box.y1 - fade - 10)
    draw.rectangle([(slab.x0, slab.y0), (slab.x1 - 1, slab.y1 - 1)], fill=fill)
    tone = Image.linear_gradient("L").rotate(180).resize((box.w, fade))
    pixel_dither(img, (box.x0, slab.y1), tone, fill)

    x = slab.x0 + 18
    kicker = _bold(layout.SwissType.LABEL_PX)
    y = slab.y0 + 14 + font_metrics(kicker).ascent
    draw_text_bl(draw, (x, y), story.kicker, kicker, P.bg)
    first, second = story.headline
    head, _ = pick_fitting_size(_bold, first, slab.w - 36, (60, 56, 52, 48, 44))
    y += font_metrics(head).ascent + 6
    draw_text_bl(draw, (x, y), first, head, P.bg)
    tail = _medium(34)
    y += font_metrics(tail).ascent + 6
    draw_text_bl(draw, (x, y), second, tail, P.bg)
    detail = _medium(17)
    draw_text_bl(draw, (x, slab.y1 - 12), story.detail, detail, P.bg)


# ── Band: daylight or progress ─────────────────────────────────────────

_BAND_H = 30
_BAND_INSET = 4  # Room for the markers that stand proud of the bar.


def _draw_band_labels(draw, ctx: RenderContext, y: int, box: Box, items: list) -> None:
    """Small labels under a band. Each stays inside the box and clear of the last."""
    font = _medium(layout.SwissType.SMALL_PX)
    baseline = y + font_metrics(font).ascent
    next_x = box.x0
    for x, text in items:
        w = text_width(font, text)
        lx = max(next_x, min(x - w // 2, box.x1 - w))
        draw_text_bl(draw, (lx, baseline), text, font, ctx.palette.ink)
        next_x = lx + w + 10


def _draw_progress(img: Image.Image, draw, ctx: RenderContext, story: Story, box: Box) -> None:
    """Solid for how far it has come, dither for the distance left."""
    P = ctx.palette
    p = story.progress
    top = box.y0 + _BAND_INSET
    done = round(box.w * p.fraction)
    tone = Image.new("L", (box.w - done, _BAND_H), 96)
    if tone.width > 0:
        pixel_dither(img, (box.x0 + done, top), tone, p.accent)
    if done > 0:
        draw.rectangle([(box.x0, top), (box.x0 + done - 1, top + _BAND_H - 1)], fill=p.accent)
    draw.rectangle([(box.x1 - 2, top - 3), (box.x1 - 1, top + _BAND_H + 2)], fill=P.ink)
    font = _medium(layout.SwissType.SMALL_PX)
    baseline = top + _BAND_H + 5 + font_metrics(font).ascent
    draw_text_bl(draw, (box.x0, baseline), p.start_label, font, P.ink)
    draw_text_bl_right(draw, (box.x1, baseline), p.end_label, font, P.ink)


def _minute_of_day(iso: Any, ctx: RenderContext) -> Optional[int]:
    dt = parse_iso(iso)
    if dt is None:
        return None
    local = dt.astimezone(ctx.zone)
    return local.hour * 60 + local.minute


def _draw_daylight(img: Image.Image, draw, ctx: RenderContext, ha: dict, box: Box) -> None:
    """Midnight to midnight: dense dither for night, clearing to bare paper at noon,
    with a solid line for now. The daylight is drawn from real sunrise and sunset."""
    P = ctx.palette
    sun = ha.get("sun") or {}
    rise = _minute_of_day(sun.get("nextRising"), ctx)
    set_ = _minute_of_day(sun.get("nextSetting"), ctx)
    height = _BAND_H
    top = box.y0 + _BAND_INSET
    tone = Image.new("L", (box.w, height), 0)
    tone_draw = ImageDraw.Draw(tone)
    day = 1440
    if rise is None or set_ is None or set_ <= rise:
        rise, set_ = None, None
        tone_draw.rectangle([(0, 0), (box.w, height)], fill=70)
    else:
        for x in range(box.w):
            minute = x / box.w * day
            if rise <= minute <= set_:
                level = 40 * (1 - math.sin(math.pi * (minute - rise) / (set_ - rise)))
            else:
                # Night deepens away from the horizon.
                dist = min(abs(minute - rise), abs(minute - set_),
                           day - abs(minute - rise), day - abs(minute - set_))
                level = 90 + 80 * clamp(dist / 120)
            tone_draw.line([(x, 0), (x, height)], fill=int(level))
    pixel_dither(img, (box.x0, top), tone, P.ink)
    now = ctx.now_local.hour * 60 + ctx.now_local.minute
    nx = box.x0 + round(now / day * box.w)
    draw.rectangle([(nx - 1, top - 4), (nx + 1, top + height + 3)], fill=P.ink)
    # White keyline, so the marker stays legible on the densest dots.
    draw.rectangle([(nx - 3, top), (nx - 2, top + height - 1)], fill=P.bg)
    draw.rectangle([(nx + 2, top), (nx + 3, top + height - 1)], fill=P.bg)

    labels = []
    if rise is not None:
        for minute in (rise, set_):
            when = ctx.now_local.replace(hour=minute // 60, minute=minute % 60)
            labels.append((box.x0 + round(minute / day * box.w),
                           when.strftime("%I:%M %p").lstrip("0")))
    _draw_band_labels(draw, ctx, top + height + 5, box, labels)


# ── Lower left: forecast or everything else running ────────────────────


def _draw_forecast(img: Image.Image, draw, ctx: RenderContext, ha: dict, box: Box) -> None:
    """Each day's range as a dithered band on one shared scale, because it is a
    forecast. Today carries a solid tick for the temperature measured now."""
    P = ctx.palette
    T = layout.SwissType
    weather = ha.get("weather") or {}
    slots = ((weather.get("forecast") or {}).get("daily") or [])[:3]
    rows = []
    for idx, slot in enumerate(slots):
        hi, lo = to_float(slot.get("temperature")), to_float(slot.get("templow"))
        date = forecast_day_date(slot.get("datetime"), ctx.zone)
        if date == ctx.now_local.date() or (date is None and idx == 0):
            label = "Today"
        else:
            label = date.strftime("%a") if date else _DASH
        rows.append((label, hi, lo))
    known = [t for _, hi, lo in rows for t in (hi, lo) if t is not None]
    if not known:
        font = _medium(T.LABEL_PX)
        draw_text_bl(draw, (box.x0, box.y0 + font_metrics(font).ascent),
                     "Forecast unavailable", font, P.ink)
        return
    low, high = min(known), max(known)
    span = max(1.0, high - low)
    label_font = _bold(T.LABEL_PX)
    value_font = _bold(17)
    fm = font_metrics(value_font)
    row_h = box.h // 3
    bar_x0 = box.x0 + 58
    lo_w = text_width(value_font, "-00°")
    bar_x0 += lo_w
    bar_x1 = box.x1 - lo_w - 8
    outside = to_float(weather.get("outdoorTemp"))
    if outside is None:
        outside = to_float(weather.get("temperature"))
    for i, (label, hi, lo) in enumerate(rows):
        y = box.y0 + i * row_h
        baseline = y + (row_h + fm.ascent - fm.descent) // 2
        draw.rectangle([(box.x0, y), (box.x1 - 1, y)], fill=P.rule)
        draw_text_bl(draw, (box.x0, baseline), label, label_font, P.ink)
        draw_text_bl_right(draw, (bar_x0 - 8, baseline), fmt_temp(lo), value_font, P.ink)
        draw_text_bl(draw, (bar_x1 + 8, baseline), fmt_temp(hi), value_font, P.ink)
        if hi is None or lo is None:
            continue
        width = bar_x1 - bar_x0
        x0 = bar_x0 + round((lo - low) / span * width)
        x1 = bar_x0 + round((hi - low) / span * width)
        bar_h = 14
        bar_y = y + (row_h - bar_h) // 2 + 1
        if x1 > x0:
            pixel_dither(img, (x0, bar_y), Image.new("L", (x1 - x0, bar_h), 84), P.ink)
        if label == "Today" and outside is not None:
            nx = bar_x0 + round(clamp((outside - low) / span) * width)
            draw.rectangle([(nx - 1, bar_y - 3), (nx + 1, bar_y + bar_h + 2)], fill=P.ink)


def _draw_also_running(draw, ctx: RenderContext, rest: list[ActiveAppliance], box: Box) -> None:
    P = ctx.palette
    T = layout.SwissType
    row_h = box.h // 3
    label_font = _bold(T.LABEL_PX)
    detail_font = _medium(T.SMALL_PX)
    value_font = _bold(19)
    fm = font_metrics(value_font)
    for i, item in enumerate(rest[:3]):
        y = box.y0 + i * row_h
        view = item.view
        draw.rectangle([(box.x0, y), (box.x1 - 1, y)], fill=P.rule)
        baseline = y + (row_h + fm.ascent - fm.descent) // 2
        name, value, detail = _also_row(view, ctx)
        if i == 2 and len(rest) > 3:
            name, value, detail = f"+{len(rest) - 2} more", "", ""
        draw_text_bl(draw, (box.x0, baseline), name, label_font, P.ink)
        name_w = text_width(label_font, name)
        draw_text_bl(draw, (box.x0 + name_w + 10, baseline), detail, detail_font, P.ink)
        draw_text_bl_right(draw, (box.x1, baseline), value, value_font, P.ink)


def _also_row(view: ApplianceView, ctx: RenderContext) -> tuple[str, str, str]:
    name = {
        "sauna": "Sauna", "washer": "Washer", "dryer": "Dryer", "dishwasher": "Dishwasher",
        "washer-done": "Washer", "dryer-done": "Dryer", "pool": "Pool",
    }.get(view.kind, view.kind.title())
    if view.kind in ("washer-done", "dryer-done"):
        return name, view.relative_label or _DASH, "Done"
    if view.kind == "pool":
        return name, fmt_temp(view.current), f"Heating to {fmt_temp(view.target)}"
    if view.kind == "sauna":
        forecast = view.extras.get("forecast") or {}
        if forecast.get("ready_reached"):
            return name, "Ready", ""
        ready = forecast.get("ready_label")
        return (name, f"{forecast['ready_in_minutes']} min" if ready else fmt_temp(view.current),
                f"Ready around {ready}" if ready else "Heating")
    minutes = _minutes_until(view, ctx)
    return (name, f"{minutes} min" if minutes is not None else _DASH, view.status_label or "")


# ── Right column ───────────────────────────────────────────────────────


def _cloud_mask(size: tuple[int, int], box: tuple[int, int, int, int]) -> Image.Image:
    """A flat-bottomed cloud inside ``box``, as a white shape on black."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    mask = Image.new("L", size, 0)
    d = ImageDraw.Draw(mask)
    d.ellipse([(x0, y0 + h * 0.42), (x0 + w * 0.46, y1)], fill=255)
    d.ellipse([(x0 + w * 0.22, y0), (x0 + w * 0.72, y0 + h * 0.72)], fill=255)
    d.ellipse([(x0 + w * 0.56, y0 + h * 0.34), (x1, y1)], fill=255)
    d.rectangle([(x0 + w * 0.2, y0 + h * 0.55), (x0 + w * 0.8, y1)], fill=255)
    return mask


def _disc_tone(size: int) -> Image.Image:
    """A disc that's densest at its core and thins toward its edge.

    Inset from its rectangle so its edge is never cut by the rectangle's sides.
    """
    inset = 4
    disc = size - 2 * inset
    tone = Image.radial_gradient("L").resize((disc, disc)).point(lambda v: int(190 - v * 0.42))
    mask = Image.new("L", (disc, disc), 0)
    ImageDraw.Draw(mask).ellipse([(0, 0), (disc - 1, disc - 1)], fill=255)
    out = Image.new("L", (size, size), 0)
    out.paste(ImageChops.multiply(tone, mask), (inset, inset))
    return out


def _draw_sky(img: Image.Image, ctx: RenderContext, state: str, x: int, y: int, size: int) -> None:
    """A printed weather mark. The sun is dithered; precipitation is solid strokes."""
    P = ctx.palette
    sun_ink = ctx.accent("warn") if P.yellow != P.ink else P.ink
    rain_ink = ctx.accent("info")
    s = (state or "").lower()
    canvas = (size, size)
    draw = ImageDraw.Draw(img)

    if s in ("sunny", "clear"):
        pixel_dither(img, (x, y), _disc_tone(size), sun_ink)
        return
    if s == "clear-night":
        tone = _disc_tone(size)
        cut = Image.new("L", canvas, 255)
        offset = int(size * 0.34)
        ImageDraw.Draw(cut).ellipse([(offset, -offset // 2), (size + offset, size - offset // 2)], fill=0)
        pixel_dither(img, (x, y), ImageChops.multiply(tone, cut), P.ink)
        return

    # Flat enough that precipitation stays above the condition line.
    cloud_box = (0, int(size * 0.14), size - 1, int(size * 0.62))
    if s == "partlycloudy":
        disc = int(size * 0.62)
        tone = Image.new("L", canvas, 0)
        tone.paste(_disc_tone(disc), (size - disc, 0))
        halo = _cloud_mask(canvas, (cloud_box[0] - 3, cloud_box[1] - 3, cloud_box[2], cloud_box[3] + 3))
        pixel_dither(img, (x, y), ImageChops.subtract(tone, halo), sun_ink)
    mask = _cloud_mask(canvas, cloud_box)
    level = 190 if s in ("cloudy", "mostlycloudy", "rainy", "pouring", "snowy", "snowy-rainy",
                         "lightning", "lightning-rainy", "hail", "exceptional") else 120
    img.paste(P.bg, (x, y), mask)
    pixel_dither(img, (x, y), mask.point(lambda v: level if v else 0), P.ink)

    # Precipitation below the cloud, in solid ink.
    base = y + cloud_box[3] + 5
    if s in ("rainy", "pouring", "lightning-rainy", "snowy-rainy", "hail"):
        count = 6 if s == "pouring" else 4
        for i in range(count):
            px = x + int(size * (0.14 + 0.72 * i / max(1, count - 1)))
            draw.line([(px + 5, base), (px - 2, base + 13)], fill=rain_ink, width=3)
    if s in ("snowy", "snowy-rainy", "hail"):
        for i in range(4):
            px = x + int(size * (0.2 + 0.2 * i))
            draw.ellipse([(px, base + 1 + (i % 2) * 7), (px + 5, base + 6 + (i % 2) * 7)], fill=P.ink)
    if s in ("lightning", "lightning-rainy", "exceptional"):
        cx = x + size // 2
        draw.polygon([(cx + 5, base - 12), (cx - 7, base + 6), (cx, base + 6),
                      (cx - 4, base + 18), (cx + 9, base - 1), (cx + 2, base - 1)], fill=P.ink)
    if s in ("fog", "mist", "haze"):
        for i in range(3):
            draw.rectangle([(x + 6 + i * 8, base + i * 6), (x + size - 8 - i * 4, base + i * 6 + 2)],
                           fill=P.ink)
    if s in ("windy", "windy-variant"):
        for i in range(3):
            draw.rectangle([(x + i * 6, base + i * 6), (x + size - 10 + i * 3, base + i * 6 + 2)],
                           fill=P.ink)


def _draw_weather(img: Image.Image, draw, ctx: RenderContext, ha: dict, box: Box) -> None:
    P = ctx.palette
    T = layout.SwissType
    weather = ha.get("weather") or {}
    temp = weather.get("outdoorTemp")
    if temp is None:
        temp = weather.get("temperature")
    temp_s = fmt_temp(temp)
    mark = 92
    temp_font, size = pick_fitting_size(_bold, temp_s, box.w - mark - 8, (T.TEMP_PX, 76, 68, 60))
    tracking = round(size * T.HERO_TRACKING_EM)
    cap_h = temp_font.getbbox("0")[3] - temp_font.getbbox("0")[1]
    baseline = box.y0 + 8 + cap_h
    draw_tracked_text_bl(draw, (box.x0, baseline), temp_s, temp_font, P.ink, tracking)
    state = weather.get("state")
    if state:
        _draw_sky(img, ctx, state, box.x1 - mark, box.y0, mark)

    line_font = _medium(T.SMALL_PX)
    fm = font_metrics(line_font)
    y = baseline + 8 + fm.ascent
    bits = [fmt_weather(state)] if state else []
    feels = weather.get("feelsLike")
    if feels is not None:
        bits.append(f"Feels {fmt_temp(feels)}")
    if bits:
        draw_text_bl(draw, (box.x0, y), _DOT.join(bits), line_font, P.ink)
    wind = _reading(weather.get("windSpeed"))
    bearing = compass(weather.get("windBearing"))
    second = [f"Wind {wind} {bearing}".rstrip(), f"Humidity {_reading(weather.get('humidity'))}%"]
    aqi = weather.get("aqi")
    if aqi is not None:
        second.append(f"AQI {safe_round(aqi)}")
    draw_text_bl(draw, (box.x0, y + fm.line_height), _DOT.join(second), line_font, P.ink)


def _draw_row(draw, ctx: RenderContext, y: int, box: Box, label: str, value: str,
              sub: str = "") -> None:
    P = ctx.palette
    T = layout.SwissType
    draw.rectangle([(box.x0, y), (box.x1 - 1, y)], fill=P.rule)
    label_font = _bold(T.LABEL_PX)
    fm_v = font_metrics(_bold(T.VALUE_PX))
    baseline = y + 6 + fm_v.ascent - 4
    draw_text_bl(draw, (box.x0, baseline - 8), label, label_font, P.ink)
    if sub:
        sub_font = _medium(T.SMALL_PX)
        draw_text_bl(draw, (box.x0, baseline + 8), sub, sub_font, P.ink)
    sub_w = text_width(_medium(T.SMALL_PX), sub) + 10 if sub else 0
    value_font, _ = pick_fitting_size(_bold, value, box.w - sub_w, (T.VALUE_PX, 24, 20, 18))
    draw_text_bl_right(draw, (box.x1, baseline), value, value_font, P.ink)


def _draw_readings(img: Image.Image, draw, ctx: RenderContext, ha: dict, box: Box) -> None:
    """The rooms we watch, then coffee, solar, and pool, at a fixed row height."""
    P = ctx.palette
    T = layout.SwissType
    temps = ha.get("temps") or {}
    cups = (ha.get("coffee") or {}).get("cupsToday")
    solar = ha.get("solar") or {}
    pool = ha.get("pool") or {}
    row_h = 52
    y = box.y0
    _draw_row(draw, ctx, y, box, "Primary Suite", fmt_temp(temps.get("primaryBedroom")))
    y += row_h
    _draw_row(draw, ctx, y, box, "Nursery", fmt_temp(temps.get("nursery")))
    y += row_h
    _draw_row(draw, ctx, y, box, "Coffee", _DASH if cups is None else str(cups), "cups today")
    y += row_h

    today = to_float(solar.get("todayKwh"))
    current = to_float(solar.get("currentKw"))
    if today is None:
        _draw_row(draw, ctx, y, box, "Solar", _DASH, "offline")
    else:
        now_s = _DASH if current is None else f"{current:.1f} kW now"
        _draw_row(draw, ctx, y, box, "Solar", f"{today:.1f}", f"kWh today{_DOT}{now_s}")
        panels = solar.get("panelCount")
        peak = (panels * 0.30) if panels else 10.0
        if current is not None:
            bar_y = y + row_h - 8
            filled = round(box.w * clamp(current / peak))
            rest = Image.new("L", (box.w - filled, 5), 70)
            if rest.width > 0:
                pixel_dither(img, (box.x0 + filled, bar_y), rest, P.ink)
            if filled > 0:
                accent = P.yellow if P.yellow != P.ink else P.ink
                draw.rectangle([(box.x0, bar_y), (box.x0 + filled - 1, bar_y + 4)], fill=accent)
    y += row_h

    if pool.get("current") is not None:
        _draw_row(draw, ctx, y, box, "Pool", fmt_temp(pool.get("current")),
                  "heating" if pool.get("heating") else "water")


# ── Footer ─────────────────────────────────────────────────────────────


def _draw_footer(draw, ctx: RenderContext, ha: dict, box: Box) -> None:
    """People on the left, exceptions on the right. An open garage is inverted,
    because it's the one line here that may need someone to go and do something.
    Only a reported "closed" says closed; anything else prints as what it is."""
    P = ctx.palette
    T = layout.SwissType
    draw.rectangle([(box.x0, box.y0), (box.x1 - 1, box.y0 + 2)], fill=P.ink)
    font = _bold(T.LABEL_PX)
    baseline = box.y0 + 8 + font_metrics(font).ascent
    if ha.get("unavailable"):
        draw_text_bl(draw, (box.x0, baseline), "Home unknown", font, P.ink)
        draw_text_bl_right(draw, (box.x1, baseline), f"Windows unknown{_DOT}Garage unknown",
                           _medium(T.LABEL_PX), P.ink)
        return
    people = ha.get("people") or []
    home = [p.get("name", "").split(" ")[0] for p in people if p.get("state") == "home"]
    draw_text_bl(draw, (box.x0, baseline),
                 (" & ".join(home) + " home") if home else "Nobody home", font, P.ink)

    windows = len(ha.get("openWindows") or [])
    window_s = (f"{windows} window{'s' if windows != 1 else ''} open" if windows
                else "Windows shut")
    garage = ((ha.get("garage") or {}).get("state") or "").lower()
    label = _medium(T.LABEL_PX)
    if garage in ("open", "opening"):
        text = f"Garage {garage}"
        w = text_width(font, text)
        x1 = box.x1
        fm = font_metrics(font)
        draw.rectangle([(x1 - w - 12, baseline - fm.ascent - 1), (x1 - 1, baseline + fm.descent)],
                       fill=ctx.accent("alert"))
        draw_text_bl(draw, (x1 - w - 6, baseline), text, font, P.bg)
        draw_text_bl_right(draw, (x1 - w - 22, baseline), window_s, label, P.ink)
    else:
        draw_text_bl_right(draw, (box.x1, baseline),
                           window_s + _DOT + f"Garage {garage or 'unknown'}", label, P.ink)
