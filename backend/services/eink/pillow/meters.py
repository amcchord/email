"""Instrument-style progress meters for Editorial's single-activity card.

The dither rule is the Swiss one (D-055): solid ink is what has been measured,
dither is what is only forecast, and type never sits on dither. Flat tones are
Bayer and gradients are Atkinson. Each meter takes only values the appliance
reports, so a missing reading drops a detail rather than inventing it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from PIL import Image, ImageDraw

from . import fonts
from .draw import (
    atkinson_dither,
    bayer_dither,
    draw_text_bl,
    draw_text_bl_right,
    draw_tracked_text_bl,
    draw_tracked_text_bl_center,
    draw_tracked_text_bl_right,
    em_to_px,
    font_metrics,
    text_width,
    tracked_width,
)
from .palette import Palette

RGB = Tuple[int, int, int]

# Sixteenths of ink for "still to come": sparse enough that solid ink stands out.
_FORECAST_TONE = 2 * 255 // 16
_LABEL_PX = 9
_TRACK_R = 6


def _label_font():
    return fonts.pix_cherry_small(_LABEL_PX, bold=True)


def _tracking() -> int:
    return em_to_px(_LABEL_PX, 0.14)


def draw_meter_stats(draw: ImageDraw.ImageDraw, P: Palette, x0: int, y: int, w: int, *,
                     value: str, value_label: str, accent: RGB,
                     right_value: str = "", right_label: str = "") -> int:
    """The meter's headline numbers: a big value at left, a smaller one at right."""
    big = fonts.serif(34, weight="bold")
    fm = font_metrics(big)
    baseline = y + fm.ascent
    draw_text_bl(draw, (x0, baseline), value, big, accent)
    label = _label_font()
    draw_tracked_text_bl(draw, (x0 + text_width(big, value) + 6, baseline), value_label,
                         label, P.ink, _tracking())
    if right_value:
        small = fonts.serif(20, weight="bold")
        draw_text_bl_right(draw, (x0 + w, baseline), right_value, small, P.ink)
        draw_tracked_text_bl_right(
            draw, (x0 + w, baseline - font_metrics(small).ascent - 3),
            right_label, label, P.ink, _tracking(),
        )
    return baseline + fm.descent


def draw_reading_line(draw: ImageDraw.ImageDraw, P: Palette, x0: int, y: int, w: int, *,
                      value: str, value_label: str, accent: RGB, right_value: str = "",
                      right_label: str = "", value_px: int = 20, right_px: int = 15) -> int:
    """A compact pair of readings on one baseline: value and label, then label and value.

    A label that would run into the other reading is dropped, the right one first.
    """
    big = fonts.serif(value_px, weight="bold")
    small = fonts.serif(right_px, weight="bold")
    label = _label_font()
    fm = font_metrics(big)
    baseline = y + fm.ascent
    draw_text_bl(draw, (x0, baseline), value, big, accent)
    left = x0 + text_width(big, value)
    right = x0 + w - (text_width(small, right_value) if right_value else 0)
    if right_value:
        draw_text_bl_right(draw, (x0 + w, baseline), right_value, small, P.ink)
    value_label_w = tracked_width(label, value_label, _tracking()) if value_label else 0
    right_label_w = tracked_width(label, right_label, _tracking()) if right_label else 0
    if right_label and left + 5 + value_label_w + 12 + right_label_w + 5 <= right:
        draw_tracked_text_bl_right(draw, (right - 5, baseline), right_label, label, P.ink,
                                   _tracking())
        right -= right_label_w + 5
    if value_label and left + 5 + value_label_w + 12 <= right:
        draw_tracked_text_bl(draw, (left + 5, baseline), value_label, label, P.ink, _tracking())
    return baseline + fm.descent


def phase_track_height() -> int:
    """How tall ``draw_phase_track`` draws, so a caller can check it has the room."""
    fm = font_metrics(_label_font())
    return 3 + 2 * _TRACK_R + 6 + fm.ascent + fm.descent + 3


@dataclass(frozen=True)
class BarSegment:
    """A measured stretch of the bar; ``minutes`` sets its share of the elapsed part."""
    minutes: float


def draw_progress_bar(img: Image.Image, draw: ImageDraw.ImageDraw, P: Palette,
                      x0: int, y: int, w: int, *, pct: float, accent: RGB,
                      segments: Sequence[BarSegment] = (), ticks: Sequence[int] = (),
                      h: int = 20) -> int:
    """Solid to ``pct``, forecast tone after it, with a white cut between ``segments``.

    ``ticks`` are percentages notched into the frame. Returns the Y below the bar.
    """
    inner_x0, inner_x1 = x0 + 2, x0 + w - 2
    inner_w = inner_x1 - inner_x0
    filled = round(inner_w * max(0.0, min(100.0, pct)) / 100)
    if filled < inner_w:
        tone = Image.new("L", (inner_w - filled, h - 4), _FORECAST_TONE)
        bayer_dither(img, (inner_x0 + filled, y + 2), tone, P.ink)
    if filled:
        draw.rectangle([(inner_x0, y + 2), (inner_x0 + filled - 1, y + h - 3)], fill=accent)
    total = sum(s.minutes for s in segments)
    if total > 0:
        cut = 0.0
        for segment in segments[:-1]:
            cut += segment.minutes
            cx = inner_x0 + round(filled * cut / total)
            draw.rectangle([(cx - 1, y + 2), (cx, y + h - 3)], fill=P.bg)
    # The leading edge: a heavier post with a nub, so "now" reads at a glance.
    if 0 < filled < inner_w:
        edge = inner_x0 + filled
        draw.rectangle([(edge, y - 3), (edge + 1, y + h + 2)], fill=P.ink)
    draw.rectangle([(x0, y), (x0 + w - 1, y + h - 1)], outline=P.ink, width=2)
    for tick in ticks:
        tx = inner_x0 + round(inner_w * tick / 100)
        draw.rectangle([(tx, y + h), (tx, y + h + 3)], fill=P.ink)
    return y + h + (4 if ticks else 0)


def draw_tick_labels(draw: ImageDraw.ImageDraw, P: Palette, x0: int, y: int, w: int,
                     labels: Sequence[Tuple[int, str]]) -> int:
    """Small labels centred under ``draw_progress_bar`` ticks (end labels stay inside)."""
    font = _label_font()
    fm = font_metrics(font)
    baseline = y + fm.ascent
    inner_w = w - 4
    for pct, text in labels:
        tx = x0 + 2 + round(inner_w * pct / 100)
        if pct <= 0:
            draw_tracked_text_bl(draw, (x0, baseline), text, font, P.ink, _tracking())
        elif pct >= 100:
            draw_tracked_text_bl_right(draw, (x0 + w, baseline), text, font, P.ink, _tracking())
        else:
            draw_tracked_text_bl_center(draw, (tx, baseline), text, font, P.ink, _tracking())
    return baseline + fm.descent


def draw_phase_track(img: Image.Image, draw: ImageDraw.ImageDraw, P: Palette,
                     x0: int, y: int, w: int, *, stations: Sequence[str],
                     current: Optional[int], accent: RGB, complete: bool = False) -> int:
    """Stations along a line: done are solid, current is a target, upcoming are hollow.

    The stretch after the current station fades out, since how far along it is
    isn't reported. With ``current`` None (a pause, say) nothing is claimed as done.
    """
    r = _TRACK_R
    n = len(stations)
    pad = r + 10
    xs = [x0 + pad + round(i * (w - 2 * pad) / max(1, n - 1)) for i in range(n)]
    cy = y + r + 3
    font = _label_font()
    fm = font_metrics(font)
    for i in range(n - 1):
        left, right = xs[i] + r + 2, xs[i + 1] - r - 2
        reached = complete or (current is not None and i < current)
        if reached:
            draw.rectangle([(left, cy - 1), (right, cy + 1)], fill=accent)
        elif current is not None and i == current:
            span = right - left + 1
            ramp = Image.linear_gradient("L").rotate(90, expand=True).resize((span, 5))
            ramp = ramp.point(lambda v: int(v * 0.85))
            atkinson_dither(img, (left, cy - 2), ramp, accent)
        else:
            bayer_dither(img, (left, cy - 1), Image.new("L", (right - left + 1, 3), 8 * 255 // 16),
                         P.ink)
    for i, (sx, name) in enumerate(zip(xs, stations)):
        done = complete or (current is not None and i < current)
        here = not complete and current == i
        if here:
            draw.ellipse([(sx - r - 3, cy - r - 3), (sx + r + 3, cy + r + 3)],
                         outline=P.ink, width=2)
            draw.ellipse([(sx - r + 2, cy - r + 2), (sx + r - 2, cy + r - 2)], fill=accent)
        elif done:
            draw.ellipse([(sx - r, cy - r), (sx + r, cy + r)], fill=accent)
        else:
            draw.ellipse([(sx - r, cy - r), (sx + r, cy + r)], fill=P.bg, outline=P.ink, width=2)
        baseline = cy + r + 6 + fm.ascent
        if here:
            # The current station's name is underlined so it reads as the live one.
            tw = tracked_width(font, name, _tracking())
            draw.rectangle([(sx - tw // 2, baseline + 2), (sx + tw // 2, baseline + 3)], fill=P.ink)
        draw_tracked_text_bl_center(draw, (sx, baseline), name, font, P.ink, _tracking())
    return cy + r + 6 + fm.ascent + fm.descent + 3


def draw_scale_meter(img: Image.Image, draw: ImageDraw.ImageDraw, P: Palette,
                     x0: int, y: int, w: int, *, low: float, high: float, now: float,
                     target: Optional[float], accent: RGB, step: int = 5,
                     marker: Optional[float] = None, marker_label: str = "") -> int:
    """A ruled temperature scale: solid up to ``now``, forecast tone up to ``target``.

    Major ticks are labelled in degrees. ``marker`` adds a small pointer beneath the
    scale, used for the air temperature beside a pool.
    """
    def px(value: float) -> int:
        share = (max(low, min(high, value)) - low) / (high - low)
        return x0 + 2 + round((w - 4) * share)

    bar_h = 18
    now_x = px(now)
    if target is not None and px(target) > now_x:
        tone = Image.new("L", (px(target) - now_x, bar_h - 4), _FORECAST_TONE * 2)
        bayer_dither(img, (now_x, y + 2), tone, P.ink)
    if now_x > x0 + 2:
        draw.rectangle([(x0 + 2, y + 2), (now_x - 1, y + bar_h - 3)], fill=accent)
    draw.rectangle([(x0, y), (x0 + w - 1, y + bar_h - 1)], outline=P.ink, width=2)
    if low < now < high:
        draw.rectangle([(now_x, y - 3), (now_x + 1, y + bar_h + 2)], fill=P.ink)
    if target is not None:
        tx = px(target)
        draw.polygon([(tx - 5, y - 7), (tx + 5, y - 7), (tx, y - 1)], fill=P.ink)
    font = _label_font()
    fm = font_metrics(font)
    tick_y = y + bar_h
    baseline = tick_y + 6 + fm.ascent
    first = int(low + (step - low % step) % step)
    last_text_right = x0 - 100
    for value in range(first, int(high) + 1, step):
        tx = px(value)
        major = value % (step * 2) == 0
        draw.rectangle([(tx, tick_y), (tx, tick_y + (5 if major else 2))], fill=P.ink)
        if major:
            text = f"{value}°"
            text_w = tracked_width(font, text, _tracking())
            # An end label keeps inside the scale rather than overhanging it.
            left = max(x0, min(tx - text_w // 2, x0 + w - text_w))
            if left > last_text_right + 8:
                draw_tracked_text_bl(draw, (left, baseline), text, font, P.ink, _tracking())
                last_text_right = left + text_w
    bottom = baseline + fm.descent + 2
    if marker is not None and low <= marker <= high:
        mx = px(marker)
        draw.polygon([(mx, bottom), (mx - 4, bottom + 6), (mx + 4, bottom + 6)], fill=P.ink)
        if marker_label:
            label_base = bottom + 8 + fm.ascent
            draw_tracked_text_bl_center(draw, (mx, label_base), marker_label, font, P.ink, _tracking())
            bottom = label_base + fm.descent + 2
        else:
            bottom += 8
    return bottom


def draw_heat_curve(img: Image.Image, draw: ImageDraw.ImageDraw, P: Palette,
                    x0: int, y: int, w: int, h: int, *, curve: Sequence[Tuple[float, float]],
                    history: Sequence[Tuple[float, float]], ready_f: float,
                    ready_minutes: Optional[float], ready_label: Optional[str],
                    fan_minutes: Optional[float], accent: RGB,
                    low: float = 60, high: float = 190) -> int:
    """The room's temperature against time: a solid line measured, a dithered forecast.

    ``history`` holds (minutes before now, as negatives, °F) and ``curve`` (minutes
    after now, °F). The forecast is an Atkinson tone under its line, fading with
    distance, so measured and modelled heat can't be mistaken for each other.
    """
    label = _label_font()
    fm = font_metrics(label)
    plot_top = y + fm.line_height + 3
    axis_y = y + h - fm.line_height - 4
    plot_h = axis_y - plot_top
    start = min([m for m, _ in history] + [0.0])
    start = max(start, -120.0)
    horizon = max(30.0, (ready_minutes + 12.0) if ready_minutes is not None else 45.0)
    horizon = min(horizon, 180.0, curve[-1][0] if curve else 180.0)
    span = max(1.0, horizon - start)

    def px(minute: float) -> int:
        return x0 + round((w - 1) * (minute - start) / span)

    def py(value: float) -> int:
        share = (max(low, min(high, value)) - low) / (high - low)
        return axis_y - 1 - round((plot_h - 1) * share)

    now_x = px(0)
    future = [(m, v) for m, v in curve if 0 <= m <= horizon]
    # Forecast tone under the projected line, thinning toward the horizon.
    if len(future) > 1 and x0 + w - 1 > now_x:
        tone = Image.new("L", (x0 + w - now_x, plot_h), 0)
        end_x = x0 + w - 1
        for tx in range(now_x, end_x + 1):
            minute = start + (tx - x0) * span / max(1, w - 1)
            value = next((v for m, v in future if m >= minute), future[-1][1])
            top = py(value) - plot_top
            fade = 1 - (tx - now_x) / max(1, end_x - now_x)
            level = int(40 + 120 * fade)
            for ty in range(max(0, top), plot_h):
                depth = (ty - top) / max(1, plot_h - top)
                tone.putpixel((tx - now_x, ty), int(level * (1 - 0.65 * depth)))
        atkinson_dither(img, (now_x, plot_top), tone, accent)
    # Measured line: solid, heavy, and only ever from readings.
    measured = [(px(m), py(v)) for m, v in history if m >= start]
    if measured:
        measured.append((now_x, py(future[0][1] if future else history[-1][1])))
        if len(measured) > 1:
            draw.line(measured, fill=P.ink, width=3)
    # Forecast line: a dashed rule along the top of the tone.
    forecast_pts = [(px(m), py(v)) for m, v in future]
    for i in range(0, max(0, len(forecast_pts) - 1)):
        if (forecast_pts[i][0] // 6) % 2 == 0:
            draw.line([forecast_pts[i], forecast_pts[i + 1]], fill=P.ink, width=2)
    # Now: a post with the current reading on top of the plot.
    draw.rectangle([(now_x, plot_top - 2), (now_x + 1, axis_y)], fill=P.ink)
    now_value = future[0][1] if future else (history[-1][1] if history else None)
    if now_value is not None:
        ny = py(now_value)
        draw.ellipse([(now_x - 4, ny - 4), (now_x + 5, ny + 5)], fill=P.ink)
    # The ready level across the whole plot, labelled on clean paper above it.
    ready_y = py(ready_f)
    for tx in range(x0, x0 + w, 5):
        draw.rectangle([(tx, ready_y), (tx + 2, ready_y)], fill=P.bg)
        draw.rectangle([(tx, ready_y), (tx + 1, ready_y)], fill=P.ink)
    draw_tracked_text_bl(draw, (x0, y + fm.ascent), f"READY LINE {int(ready_f)}°",
                         label, P.ink, _tracking())
    # Where the forecast crosses the ready line.
    if ready_minutes is not None and 0 <= ready_minutes <= horizon:
        rx = px(ready_minutes)
        draw.polygon([(rx, ready_y - 6), (rx + 6, ready_y), (rx, ready_y + 6), (rx - 6, ready_y)],
                     fill=accent, outline=P.ink)
        if ready_label:
            text = ready_label
            right = min(x0 + w, rx + tracked_width(label, text, _tracking()) // 2)
            draw_tracked_text_bl_right(draw, (right, y + fm.ascent), text, label, P.ink, _tracking())
    # Axis, with hour-part ticks and the fan's planned run.
    draw.rectangle([(x0, axis_y), (x0 + w - 1, axis_y + 1)], fill=P.ink)
    baseline = axis_y + 4 + fm.ascent
    first = -int(-start // 30) * 30
    for minute in range(first, int(horizon) + 1, 30):
        if minute == 0:
            continue
        tx = px(minute)
        draw.rectangle([(tx, axis_y + 2), (tx, axis_y + 4)], fill=P.ink)
    draw_tracked_text_bl_center(
        draw, (min(max(now_x, x0 + 12), x0 + w - 12), baseline), "NOW", label, P.ink, _tracking(),
    )
    if fan_minutes is not None and 0 < fan_minutes <= horizon:
        fx = px(fan_minutes)
        draw.polygon([(fx, axis_y + 3), (fx - 4, axis_y + 9), (fx + 4, axis_y + 9)], fill=P.ink)
        if abs(fx - now_x) > 34:
            draw_tracked_text_bl(draw, (fx + 7, baseline), "FAN", label, P.ink, _tracking())
    return y + h
