"""Pixel-drawn appliance icons for Editorial's single-activity card.

Each icon shows what the appliance is doing now, not just what it is: the washer's
drum changes with the phase, and the sauna stove has one heat wave per lit element.
Everything is drawn at 1x with no anti-aliasing, so it survives the panel encoders.
Flat shading is Bayer and gradients are Atkinson, as in the Swiss design (D-055).
"""
from __future__ import annotations

import math
from typing import Callable, Iterable, Tuple

from PIL import Image, ImageDraw

from .draw import atkinson_dither, bayer_dither

ICON_SIZE = 84

RGB = Tuple[int, int, int]
_DRUM = (41, 50)
_DRUM_R = 19
# Sixteenths of ink, as in draw._DITHER_LEVELS.
_LIGHT = 4 * 255 // 16
_MID = 8 * 255 // 16
_WHITE = (255, 255, 255)


def _wave(cx0: int, cx1: int, y: int, amp: float, period: float, phase: float = 0.0):
    return [(x, round(y + amp * math.sin((x + phase) * 2 * math.pi / period)))
            for x in range(cx0, cx1 + 1)]


def _drum_mask(fill_from: int = -_DRUM_R, wave: bool = False, amp: float = 2.0) -> Image.Image:
    """Tone map of the drum's inside at full tone, below ``fill_from`` (drum-relative)."""
    d = _DRUM_R * 2 + 1
    mask = Image.new("L", (d, d), 0)
    ImageDraw.Draw(mask).ellipse([(0, 0), (d - 1, d - 1)], fill=255)
    if fill_from > -_DRUM_R:
        cut = Image.new("L", (d, d), 0)
        top = fill_from + _DRUM_R
        points = _wave(0, d - 1, top, amp, 22) if wave else [(0, top), (d - 1, top)]
        ImageDraw.Draw(cut).polygon([*points, (d - 1, d - 1), (0, d - 1)], fill=255)
        mask = Image.composite(mask, Image.new("L", (d, d), 0), cut)
    return mask


def _shade(img: Image.Image, origin, mask: Image.Image, level: int, fill: RGB) -> None:
    """Print ``mask``'s shape as a flat Bayer tone."""
    bayer_dither(img, origin, mask.point(lambda v: level if v else 0), fill)


def _machine(draw: ImageDraw.ImageDraw, x: int, y: int, ink: RGB, *, knob: bool = True) -> None:
    """The front-loader shared by washer and dryer: cabinet, controls, porthole, feet."""
    draw.rectangle([(x + 14, y + 79), (x + 22, y + 83)], fill=ink)
    draw.rectangle([(x + 60, y + 79), (x + 68, y + 83)], fill=ink)
    draw.rounded_rectangle([(x + 7, y + 1), (x + 75, y + 80)], radius=6,
                           fill=_WHITE, outline=ink, width=3)
    draw.rectangle([(x + 10, y + 18), (x + 72, y + 19)], fill=ink)
    if knob:
        draw.ellipse([(x + 14, y + 6), (x + 23, y + 15)], outline=ink, width=2)
        draw.rectangle([(x + 18, y + 7), (x + 19, y + 10)], fill=ink)
    draw.rectangle([(x + 48, y + 7), (x + 67, y + 13)], fill=ink)
    draw.rectangle([(x + 28, y + 8), (x + 31, y + 11)], fill=ink)
    draw.rectangle([(x + 35, y + 8), (x + 38, y + 11)], fill=ink)
    cx, cy = x + _DRUM[0], y + _DRUM[1]
    draw.ellipse([(cx - 26, cy - 26), (cx + 26, cy + 26)], outline=ink, width=4)


def _bubbles(draw, x: int, y: int, ink: RGB, points: Iterable[Tuple[int, int, int]]) -> None:
    cx, cy = x + _DRUM[0], y + _DRUM[1]
    for bx, by, r in points:
        draw.ellipse([(cx + bx - r, cy + by - r), (cx + bx + r, cy + by + r)],
                     fill=_WHITE, outline=ink)


def _drop(draw, cx: int, cy: int, fill: RGB) -> None:
    """A 7x9 pixel water droplet with its point upward."""
    for i, half in enumerate((0, 0, 1, 1, 2, 3, 3, 3, 2)):
        draw.line([(cx - half, cy + i), (cx + half, cy + i)], fill=fill)


def _drum_origin(x: int, y: int) -> Tuple[int, int]:
    return (x + _DRUM[0] - _DRUM_R, y + _DRUM[1] - _DRUM_R)


def _pause_bars(draw, x: int, y: int, ink: RGB) -> None:
    cx, cy = x + _DRUM[0], y + _DRUM[1]
    draw.rectangle([(cx - 8, cy - 10), (cx - 3, cy + 10)], fill=ink)
    draw.rectangle([(cx + 3, cy - 10), (cx + 8, cy + 10)], fill=ink)


def _draw_washer(img, draw, x, y, ink, fill, phase) -> None:
    _machine(draw, x, y, ink)
    origin = _drum_origin(x, y)
    cx, cy = x + _DRUM[0], y + _DRUM[1]
    if phase == "pause":
        _pause_bars(draw, x, y, ink)
    elif phase == "rinse":
        # Clean water over a low tide, with droplets falling into it.
        _shade(img, origin, _drum_mask(6, wave=True), _LIGHT, fill)
        _drop(draw, cx - 9, cy - 13, ink)
        _drop(draw, cx + 1, cy - 8, ink)
        _drop(draw, cx + 10, cy - 14, ink)
    elif phase == "spin":
        # Tone that deepens toward the wall, as a load pinned there by the spin.
        d = _DRUM_R * 2 + 1
        tone = Image.new("L", (d, d), 0)
        for py in range(d):
            for px in range(d):
                r = math.hypot(px - _DRUM_R, py - _DRUM_R)
                if r <= _DRUM_R:
                    tone.putpixel((px, py), min(255, int(255 * (r / _DRUM_R) ** 3)))
        atkinson_dither(img, origin, tone, fill)
        for start, r in ((20, 13), (200, 13), (110, 7), (290, 7)):
            draw.arc([(cx - r, cy - r), (cx + r, cy + r)], start, start + 95,
                     fill=ink, width=2)
    else:
        # Water sloshing with bubbles on the surface.
        _shade(img, origin, _drum_mask(-3, wave=True, amp=3), _MID, fill)
        _bubbles(draw, x, y, ink, ((-8, -8, 3), (3, -12, 2), (9, -6, 4), (-1, -3, 2)))


def _shirt(draw, cx: int, cy: int, angle: float, fill: RGB) -> None:
    """A little T-shirt, rotated as if mid-tumble."""
    shape = [(-5, -8), (-2, -6), (2, -6), (5, -8), (11, -3), (8, 1), (5, -1),
             (5, 9), (-5, 9), (-5, -1), (-8, 1), (-11, -3)]
    c, s = math.cos(angle), math.sin(angle)
    draw.polygon([(cx + px * c - py * s, cy + px * s + py * c) for px, py in shape],
                 fill=fill)


def _draw_dryer(img, draw, x, y, ink, fill, phase) -> None:
    _machine(draw, x, y, ink, knob=False)
    # Vent slots in place of the washer's dial.
    for vx in (14, 18, 22):
        draw.rectangle([(x + vx, y + 6), (x + vx + 1, y + 14)], fill=ink)
    origin = _drum_origin(x, y)
    cx, cy = x + _DRUM[0], y + _DRUM[1]
    if phase == "pause":
        _pause_bars(draw, x, y, ink)
    elif phase == "cooling":
        for i in range(3):
            a = i * math.pi / 3 + math.pi / 6
            dx, dy = 15 * math.cos(a), 15 * math.sin(a)
            draw.line([(cx - dx, cy - dy), (cx + dx, cy + dy)], fill=ink, width=2)
            for sign in (-1, 1):
                ex, ey = cx + sign * dx * 0.7, cy + sign * dy * 0.7
                for turn in (-1, 1):
                    b = a + turn * math.pi / 3
                    draw.line([(ex, ey), (ex + sign * 5 * math.cos(b),
                                          ey + sign * 5 * math.sin(b))], fill=ink)
    else:
        # Warmth rising from the bottom of the drum, around a tumbling shirt.
        d = _DRUM_R * 2 + 1
        tone = _drum_mask()
        for py in range(d):
            ramp = int(190 * (py / (d - 1)) ** 2)
            for px in range(d):
                if tone.getpixel((px, py)):
                    tone.putpixel((px, py), ramp)
        atkinson_dither(img, origin, tone, fill)
        _shirt(draw, cx, cy - 1, 0.0 if phase == "wrinkle_care" else -0.55, ink)
        if phase == "wrinkle_care":
            for sx, sy in ((-14, -9), (14, -6)):
                draw.line([(cx + sx - 3, cy + sy), (cx + sx + 3, cy + sy)], fill=ink)
                draw.line([(cx + sx, cy + sy - 3), (cx + sx, cy + sy + 3)], fill=ink)


def _draw_dishwasher(img, draw, x, y, ink, fill, phase) -> None:
    draw.rectangle([(x + 12, y + 79), (x + 71, y + 83)], fill=ink)
    draw.rounded_rectangle([(x + 7, y + 1), (x + 75, y + 80)], radius=4,
                           fill=_WHITE, outline=ink, width=3)
    # Control band: a solid handle under a row of lights.
    draw.rectangle([(x + 10, y + 16), (x + 72, y + 17)], fill=ink)
    draw.rectangle([(x + 17, y + 21), (x + 65, y + 24)], fill=ink)
    for lx in (14, 21, 28):
        draw.rectangle([(x + lx, y + 7), (x + lx + 3, y + 10)], fill=ink)
    draw.rectangle([(x + 49, y + 6), (x + 67, y + 11)], fill=ink)
    # Cutaway: spray tone above a rack of plates.
    tone = Image.new("L", (56, 18), _LIGHT)
    bayer_dither(img, (x + 13, y + 30), tone, fill)
    for px, py in ((9, 36), (23, 33), (37, 36), (51, 33), (65, 36)):
        draw.ellipse([(x + px + 6, y + py), (x + px + 8, y + py + 2)], fill=_WHITE)
    for cx in (25, 41, 57):
        draw.ellipse([(x + cx - 9, y + 42), (x + cx + 9, y + 60)], fill=_WHITE,
                     outline=ink, width=2)
        draw.ellipse([(x + cx - 5, y + 46), (x + cx + 5, y + 56)], outline=ink)
    # The rack.
    draw.rectangle([(x + 13, y + 61), (x + 69, y + 62)], fill=ink)
    for rx in range(15, 69, 7):
        draw.line([(x + rx, y + 62), (x + rx, y + 69)], fill=ink)
    draw.rectangle([(x + 13, y + 70), (x + 69, y + 70)], fill=ink)


def _heat_line(draw, cx: int, y0: int, y1: int, ink: RGB) -> None:
    points = [(round(cx + 4 * math.sin((y - y0) * 2 * math.pi / 18)), y)
              for y in range(y0, y1 + 1)]
    draw.line(points, fill=ink, width=3, joint="curve")


def _draw_sauna(img, draw, x, y, ink, fill, phase) -> None:
    # A wave per lit element, so the icon reports the same fact as the card.
    elements = max(0, min(3, int(phase) if phase.isdigit() else 3))
    for i, cx in enumerate((26, 42, 58)[:3]):
        if i < elements or elements == 0 and i == 1:
            _heat_line(draw, x + cx, y + 2, y + 32, ink)
    # Stones heaped on the stove.
    for sx, sy, rx, ry in ((18, 39, 8, 5), (33, 36, 9, 6), (50, 36, 9, 6), (65, 39, 8, 5),
                           (26, 44, 9, 5), (42, 44, 10, 5), (58, 44, 9, 5)):
        draw.ellipse([(x + sx - rx, y + sy - ry), (x + sx + rx, y + sy + ry)],
                     fill=_WHITE, outline=ink, width=2)
    # The stove: tone that deepens toward the hot end at the top.
    w, h = 62, 28
    tone = Image.new("L", (w, h), 0)
    for py in range(h):
        level = int(215 * (1 - py / (h - 1)) ** 1.4)
        tone.paste(level, (0, py, w, py + 1))
    atkinson_dither(img, (x + 11, y + 50), tone, fill)
    draw.rectangle([(x + 10, y + 49), (x + 73, y + 78)], outline=ink, width=3)
    draw.rectangle([(x + 16, y + 78), (x + 22, y + 83)], fill=ink)
    draw.rectangle([(x + 61, y + 78), (x + 67, y + 83)], fill=ink)
    # Guard rail, clear of the tone so it stays a clean line.
    draw.rectangle([(x + 27, y + 62), (x + 56, y + 71)], fill=_WHITE, outline=ink, width=2)
    draw.rectangle([(x + 34, y + 66), (x + 49, y + 67)], fill=ink)


def _draw_pool(img, draw, x, y, ink, fill, phase) -> None:
    # Water: deepening toward the bottom, under a wavy surface.
    w, h = 80, 44
    tone = Image.new("L", (w, h), 0)
    surface = [(px, 6 + round(3 * math.sin(px * 2 * math.pi / 26))) for px in range(w)]
    for px, top in surface:
        for py in range(top, h):
            tone.putpixel((px, py), min(255, 40 + int(190 * (py / (h - 1)) ** 1.6)))
    atkinson_dither(img, (x + 2, y + 38), tone, fill)
    draw.line([(x + 2 + px, y + 38 + py) for px, py in surface], fill=ink, width=2)
    # White-capped swells on top of the tone.
    for wy in (58, 70):
        for wx in (10, 42):
            arc = _wave(x + wx, x + wx + 22, y + wy, 2, 22)
            draw.line(arc, fill=_WHITE, width=2)
    # Ladder: two rails that hook over the coping, rungs down into the water.
    for rx in (52, 68):
        draw.arc([(x + rx - 14, y + 2), (x + rx, y + 16)], 180, 360, fill=ink, width=3)
        draw.rectangle([(x + rx - 1, y + 9), (x + rx + 1, y + 56)], fill=ink)
    for ry in (20, 30, 40, 50):
        draw.rectangle([(x + 52, y + ry), (x + 68, y + ry + 2)], fill=ink)


_DRAWERS: dict[str, Callable] = {
    "washer": _draw_washer,
    "dryer": _draw_dryer,
    "dishwasher": _draw_dishwasher,
    "sauna": _draw_sauna,
    "pool": _draw_pool,
}


def _check_badge(draw, x: int, y: int, ink: RGB) -> None:
    """A solid disc with a tick, at the icon's lower right."""
    draw.ellipse([(x + 50, y + 50), (x + 83, y + 83)], fill=_WHITE)
    draw.ellipse([(x + 53, y + 53), (x + 80, y + 80)], fill=ink)
    draw.line([(x + 60, y + 67), (x + 65, y + 73), (x + 74, y + 60)], fill=_WHITE, width=4)


def draw_icon(img: Image.Image, x: int, y: int, *, kind: str, phase: str = "",
              ink: RGB, fill: RGB) -> None:
    """Paint the icon for ``kind`` in its ``phase`` at (x, y), ``ICON_SIZE`` square.

    ``fill`` carries the shading, so water and heat take the appliance's accent on a
    color panel. A ``-done`` kind adds a tick to the base appliance.
    """
    draw = ImageDraw.Draw(img)
    base = kind.removesuffix("-done")
    drawer = _DRAWERS.get(base)
    if drawer is None:
        return
    drawer(img, draw, x, y, ink, fill, phase)
    if kind.endswith("-done"):
        _check_badge(draw, x, y, ink)


def has_icon(kind: str) -> bool:
    return kind.removesuffix("-done") in _DRAWERS
