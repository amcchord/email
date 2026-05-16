"""Reusable drawing primitives for the Pillow e-ink renderer.

The JSX designs rely on CSS features Pillow doesn't have natively:
letter-spacing, text-wrap: balance, drop caps, text strokes, dotted
borders, and multi-run headlines (inline italic spans). This module
implements all of them at a level of fidelity that survives the
`dither=False` quantizer.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Callable, Iterable, List, Optional, Sequence, Tuple, Union

from PIL import Image, ImageDraw, ImageFont

from .palette import RGB


# ── Debug overlay toggle ───────────────────────────────────────────────
#
# When EINK_DEBUG_OUTLINES is set in the environment, every VStack/HRow
# row gets a 1-px magenta outline drawn over its Box AFTER the row's
# content is painted. Lets you eyeball whether any cell content has
# escaped its declared region. Off by default; no production cost.

DEBUG_OUTLINES: bool = bool(os.environ.get("EINK_DEBUG_OUTLINES"))
_DEBUG_OUTLINE_COLOR: RGB = (255, 0, 255)


# ── Box (rectangle) ───────────────────────────────────────────────────


Dim = Union[int, float]  # int = fixed px; float = ratio-of-remaining


@dataclass(frozen=True)
class Box:
    """Inclusive-exclusive rectangle: draws land in [x0, x1) × [y0, y1).

    Used throughout the renderer to thread layout down to components
    without tuple-unpacking. Intentionally immutable -- mutate by
    constructing new Boxes via `inset` / `translate` / `split_*`.
    """
    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def w(self) -> int:
        return self.x1 - self.x0

    @property
    def h(self) -> int:
        return self.y1 - self.y0

    @property
    def cx(self) -> int:
        return (self.x0 + self.x1) // 2

    @property
    def cy(self) -> int:
        return (self.y0 + self.y1) // 2

    @property
    def top(self) -> int:
        return self.y0

    @property
    def bottom(self) -> int:
        return self.y1

    @property
    def left(self) -> int:
        return self.x0

    @property
    def right(self) -> int:
        return self.x1

    def as_xyxy(self) -> Tuple[int, int, int, int]:
        return (self.x0, self.y0, self.x1, self.y1)

    def inset(
        self,
        *,
        top: int = 0,
        right: int = 0,
        bottom: int = 0,
        left: int = 0,
        all: Optional[int] = None,
    ) -> "Box":
        if all is not None:
            top = right = bottom = left = all
        return Box(
            self.x0 + left,
            self.y0 + top,
            self.x1 - right,
            self.y1 - bottom,
        )

    def translate(self, dx: int = 0, dy: int = 0) -> "Box":
        return Box(self.x0 + dx, self.y0 + dy, self.x1 + dx, self.y1 + dy)

    def split_cols(self, *widths: Dim) -> Tuple["Box", ...]:
        """Split horizontally. int = fixed px, float = ratio of the
        remainder left after fixed widths are subtracted.
        """
        return _split_along(self.x0, self.x1, widths, axis="x", outer=self)

    def split_rows(self, *heights: Dim) -> Tuple["Box", ...]:
        """Split vertically. Same rules as split_cols."""
        return _split_along(self.y0, self.y1, heights, axis="y", outer=self)


def _split_along(lo: int, hi: int, parts: Tuple[Dim, ...], *, axis: str, outer: Box) -> Tuple[Box, ...]:
    total = hi - lo
    fixed_sum = sum(p for p in parts if isinstance(p, int))
    ratio_sum = sum(p for p in parts if isinstance(p, float))
    remaining = max(0, total - fixed_sum)
    out: List[Box] = []
    cursor = lo
    for p in parts:
        if isinstance(p, int):
            size = p
        else:
            size = int(round(remaining * (p / ratio_sum))) if ratio_sum > 0 else 0
        next_cursor = cursor + size
        if axis == "x":
            out.append(Box(cursor, outer.y0, next_cursor, outer.y1))
        else:
            out.append(Box(outer.x0, cursor, outer.x1, next_cursor))
        cursor = next_cursor
    # Snap the last slice to the outer edge so rounding never leaves a 1-px gap.
    if out:
        last = out[-1]
        if axis == "x":
            out[-1] = Box(last.x0, last.y0, hi, last.y1)
        else:
            out[-1] = Box(last.x0, last.y0, last.x1, hi)
    return tuple(out)


def fill_box(draw: ImageDraw.ImageDraw, box: Box, fill: RGB) -> None:
    """Paint `box` solid. Half-open: stops at x1 - 1, y1 - 1."""
    if box.w <= 0 or box.h <= 0:
        return
    draw.rectangle([(box.x0, box.y0), (box.x1 - 1, box.y1 - 1)], fill=fill)


def fill_box_dither(
    draw: ImageDraw.ImageDraw,
    box: Box,
    fill: RGB,
    *,
    phase: int = 0,
) -> None:
    """50/50 checkerboard fill in a single palette colour.

    Survives the ``dither=False`` quantizer because every painted pixel
    is already a palette colour -- no blending happens. The pattern is
    locked to absolute pixel coordinates so adjacent dithered boxes
    line up cleanly without seams. ``phase`` flips the parity if a
    caller wants the inverse pattern.
    """
    if box.w <= 0 or box.h <= 0:
        return
    for y in range(box.y0, box.y1):
        x_start = box.x0 + ((box.x0 + y + phase) & 1)
        if x_start >= box.x1:
            continue
        draw.point(
            [(x, y) for x in range(x_start, box.x1, 2)],
            fill=fill,
        )


def stroke_box(
    draw: ImageDraw.ImageDraw,
    box: Box,
    *,
    fill: RGB,
    width: int = 1,
) -> None:
    if box.w <= 0 or box.h <= 0:
        return
    draw.rectangle(
        [(box.x0, box.y0), (box.x1 - 1, box.y1 - 1)],
        outline=fill,
        width=max(1, int(width)),
    )


def _dashed_outline(draw: ImageDraw.ImageDraw, box: Box, color: RGB,
                    *, dash: int = 3, gap: int = 2) -> None:
    """Paint a dashed outline along the inside of `box`. Used by the
    DEBUG_OUTLINES overlay."""
    if box.w <= 0 or box.h <= 0:
        return
    # Top + bottom edges
    for y in (box.y0, box.y1 - 1):
        x = box.x0
        while x < box.x1:
            end = min(x + dash, box.x1)
            draw.rectangle([(x, y), (end - 1, y)], fill=color)
            x += dash + gap
    # Left + right edges
    for x in (box.x0, box.x1 - 1):
        y = box.y0
        while y < box.y1:
            end = min(y + dash, box.y1)
            draw.rectangle([(x, y), (x, end - 1)], fill=color)
            y += dash + gap


# ── Stack composers (VStack / HRow) ───────────────────────────────────
#
# Declarative top-down (or left-to-right) layout helpers. Each call
# allocates a child Box that occupies a slice of the parent and dispatches
# a draw_fn(child_box) callback. Fixed-size rows take a literal pixel
# count; flex rows split whatever's left in the parent.
#
#   VStack(box, gap=4)
#     .fixed(14, lambda b: section_label(b))
#     .flex(lambda b: body(b))
#     .fixed(12, lambda b: footer(b))
#     .render(draw)
#
# Asserts at render() that fixed heights + gaps fit the parent. A typo
# in a height triggers AssertionError instead of silent overflow.


@dataclass
class _Row:
    height: Optional[int]   # None = flex
    draw_fn: Callable[[Box], None]
    weight: int = 1
    label: str = ""


class _Stack:
    """Internal base for VStack / HRow."""
    _axis: str = "y"  # 'y' for VStack, 'x' for HRow

    def __init__(self, box: Box, *, gap: int = 0):
        self._box = box
        self._gap = int(gap)
        self._rows: List[_Row] = []

    def fixed(self, size: int, draw_fn: Callable[[Box], None],
              *, label: str = "") -> "_Stack":
        self._rows.append(_Row(int(size), draw_fn, 1, label))
        return self

    def flex(self, draw_fn: Callable[[Box], None],
             *, weight: int = 1, label: str = "") -> "_Stack":
        self._rows.append(_Row(None, draw_fn, max(1, int(weight)), label))
        return self

    def gap_row(self, size: int) -> "_Stack":
        """Explicit blank gap (no draw_fn)."""
        self._rows.append(_Row(int(size), lambda _b: None, 1, "_gap"))
        return self

    def render(self, draw: ImageDraw.ImageDraw) -> None:
        if not self._rows:
            return
        total = self._box.h if self._axis == "y" else self._box.w
        gaps = self._gap * max(0, len(self._rows) - 1)
        fixed_total = sum(r.height or 0 for r in self._rows)
        flex_rows = [r for r in self._rows if r.height is None]
        flex_weight = sum(r.weight for r in flex_rows) or 1
        leftover = total - fixed_total - gaps

        assert leftover >= 0, (
            f"_Stack overflow: parent {self._box} has {total}px on the "
            f"{self._axis} axis but rows total {fixed_total}+{gaps} gap "
            f"({fixed_total + gaps}px). Rows: "
            + ", ".join(f"{r.label or '?'}={r.height}" for r in self._rows)
        )

        # Distribute flex space; round to ints, give the remainder to the
        # last flex row so we never leave or overflow a pixel.
        flex_sizes: dict[int, int] = {}
        if flex_rows and leftover > 0:
            assigned = 0
            for r in flex_rows[:-1]:
                s = (leftover * r.weight) // flex_weight
                flex_sizes[id(r)] = s
                assigned += s
            flex_sizes[id(flex_rows[-1])] = leftover - assigned
        else:
            for r in flex_rows:
                flex_sizes[id(r)] = 0

        cursor = self._box.y0 if self._axis == "y" else self._box.x0
        for i, r in enumerate(self._rows):
            size = r.height if r.height is not None else flex_sizes[id(r)]
            if self._axis == "y":
                child = Box(self._box.x0, cursor,
                            self._box.x1, cursor + size)
            else:
                child = Box(cursor, self._box.y0,
                            cursor + size, self._box.y1)
            if r.label != "_gap":
                r.draw_fn(child)
            if DEBUG_OUTLINES and r.label != "_gap":
                _dashed_outline(draw, child, _DEBUG_OUTLINE_COLOR)
            cursor += size + (self._gap if i < len(self._rows) - 1 else 0)


class VStack(_Stack):
    """Vertical stack: rows flow top-to-bottom inside the parent Box."""
    _axis = "y"


class HRow(_Stack):
    """Horizontal row: cells flow left-to-right inside the parent Box."""
    _axis = "x"


# ── Auto-fit text ──────────────────────────────────────────────────────


def pick_fitting_size(
    font_factory: Callable[[int], ImageFont.ImageFont],
    text: str,
    max_w: int,
    candidates: Sequence[int],
    *,
    tracking_em: float = 0.0,
) -> Tuple[ImageFont.ImageFont, int]:
    """Pick the largest size from `candidates` (any order; we sort them
    descending) such that `text` rendered in `font_factory(size)` fits
    within `max_w`. Returns (font, size). Falls back to the smallest if
    even that doesn't fit -- caller should size their column for the
    smallest candidate.
    """
    sorted_candidates = sorted(candidates, reverse=True)
    if not sorted_candidates:
        raise ValueError("pick_fitting_size requires at least one candidate")
    smallest = sorted_candidates[-1]
    if not text:
        f = font_factory(smallest)
        return f, smallest
    last_font = None
    last_size = smallest
    for size in sorted_candidates:
        f = font_factory(size)
        if tracking_em > 0:
            tracking_px = int(round(size * tracking_em))
            w = sum(int(f.getlength(ch)) for ch in text) + max(0, len(text) - 1) * tracking_px
        else:
            try:
                w = int(f.getlength(text))
            except Exception:
                bbox = f.getbbox(text)
                w = bbox[2] - bbox[0]
        if w <= max_w:
            return f, size
        last_font = f
        last_size = size
    # None fit; return the smallest (caller should have prevented this).
    return font_factory(smallest), smallest


def draw_fit_text_bl(
    draw: ImageDraw.ImageDraw,
    xy_baseline: Tuple[int, int],
    max_w: int,
    text: str,
    font_factory: Callable[[int], ImageFont.ImageFont],
    candidates: Sequence[int],
    fill: RGB,
    *,
    h_align: str = "left",       # 'left' | 'center' | 'right'
    tracking_em: float = 0.0,
) -> Tuple[ImageFont.ImageFont, int]:
    """Pick the largest font from `candidates` that fits `max_w` and draw
    `text` with its baseline at xy_baseline[1].

    `xy_baseline[0]` is interpreted per `h_align`:
      - 'left'   -> x is the leftmost glyph edge
      - 'center' -> x is the horizontal center of the rendered text
      - 'right'  -> x is the rightmost glyph edge

    Returns (font, size) so callers can position adjacent glyphs.
    """
    font, size = pick_fitting_size(
        font_factory, text, max_w, candidates, tracking_em=tracking_em,
    )
    if not text:
        return font, size
    tracking_px = int(round(size * tracking_em)) if tracking_em > 0 else 0

    if tracking_px > 0:
        w = sum(int(font.getlength(ch)) for ch in text) + max(0, len(text) - 1) * tracking_px
    else:
        try:
            w = int(font.getlength(text))
        except Exception:
            bbox = font.getbbox(text)
            w = bbox[2] - bbox[0]

    if h_align == "center":
        x = xy_baseline[0] - w // 2
    elif h_align == "right":
        x = xy_baseline[0] - w
    else:
        x = xy_baseline[0]

    if tracking_px > 0:
        cur = x
        for i, ch in enumerate(text):
            draw.text((cur, xy_baseline[1]), ch, font=font,
                      fill=fill, anchor="ls")
            cur += int(font.getlength(ch))
            if i < len(text) - 1:
                cur += tracking_px
    else:
        draw.text((x, xy_baseline[1]), text, font=font,
                  fill=fill, anchor="ls")
    return font, size


# ── Bound auditing (for tests / scripts) ──────────────────────────────


def assert_box_clean(
    img: Image.Image,
    box: Box,
    *,
    allow_outside: Sequence[Box] = (),
    ink_threshold: int = 50,
    band: int = 2,
) -> List[Tuple[int, int]]:
    """Scan the `band`-px ring immediately OUTSIDE `box` (right + bottom
    only -- left/top are usually shared rules) and return any pixels that
    look ink-like and aren't covered by an `allow_outside` rectangle.

    Returns a list of (x, y) offending coordinates. Empty list = clean.
    """
    px = img.load()
    width, height = img.size
    bad: List[Tuple[int, int]] = []

    def _is_ink(p) -> bool:
        if isinstance(p, int):
            return p < ink_threshold
        return p[0] < ink_threshold and p[1] < ink_threshold and p[2] < ink_threshold

    def _allowed(x: int, y: int) -> bool:
        for ab in allow_outside:
            if ab.x0 <= x < ab.x1 and ab.y0 <= y < ab.y1:
                return True
        return False

    # Right band
    for x in range(box.x1, min(width, box.x1 + band)):
        for y in range(max(0, box.y0), min(height, box.y1)):
            if _is_ink(px[x, y]) and not _allowed(x, y):
                bad.append((x, y))
    # Bottom band
    for y in range(box.y1, min(height, box.y1 + band)):
        for x in range(max(0, box.x0), min(width, box.x1)):
            if _is_ink(px[x, y]) and not _allowed(x, y):
                bad.append((x, y))
    return bad


# ── Font metrics ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class FontMetrics:
    """Vertical metrics of a FreeType font, in pixels."""
    ascent: int      # pixels from baseline up to the tallest ascender
    descent: int     # pixels from baseline down to the deepest descender (positive)
    line_height: int  # ascent + descent; the "em height"


@lru_cache(maxsize=128)
def _cached_metrics(font_id: int) -> Tuple[int, int]:
    """Internal helper: Pillow doesn't expose __hash__ on FreeTypeFont
    so we key the cache on id() (font instances are cached upstream in
    fonts.py, so id() stability is guaranteed)."""
    # Caller feeds through font_metrics() which owns the real object.
    raise RuntimeError("call font_metrics() instead")


def font_metrics(font: ImageFont.ImageFont) -> FontMetrics:
    """Return the font's (ascent, descent, line_height) in px.

    `font.getmetrics()` returns (ascent, descent) with descent positive.
    We cache per font-instance id so repeated calls in a draw loop
    don't keep hitting FreeType.
    """
    cache = font_metrics._cache  # type: ignore[attr-defined]
    key = id(font)
    hit = cache.get(key)
    if hit is not None:
        return hit
    try:
        ascent, descent = font.getmetrics()
    except AttributeError:
        # Bitmap/default fonts expose .size only.
        size = getattr(font, "size", 12)
        ascent, descent = int(size * 0.8), int(size * 0.2)
    fm = FontMetrics(int(ascent), int(descent), int(ascent + descent))
    cache[key] = fm
    return fm


font_metrics._cache = {}  # type: ignore[attr-defined]


# ── Measurement ────────────────────────────────────────────────────────


def measure_text(font: ImageFont.ImageFont, text: str) -> Tuple[int, int]:
    """Width/height for `text` in `font`, using the getbbox tightbox."""
    if not text:
        return (0, 0)
    try:
        bbox = font.getbbox(text)
        return (bbox[2] - bbox[0], bbox[3] - bbox[1])
    except Exception:
        # Some pixel fonts in Pillow < 10 fall back to getlength/getsize.
        try:
            return (int(font.getlength(text)), font.size)
        except Exception:
            return (len(text) * 6, 12)


def text_width(font: ImageFont.ImageFont, text: str) -> int:
    """Only the advance width of `text` in `font`."""
    if not text:
        return 0
    try:
        return int(font.getlength(text))
    except Exception:
        return measure_text(font, text)[0]


def tracked_width(
    font: ImageFont.ImageFont,
    text: str,
    tracking_px: int,
) -> int:
    if not text:
        return 0
    n = len(text)
    total = sum(text_width(font, ch) for ch in text)
    return total + max(0, n - 1) * int(tracking_px)


def em_to_px(size: int, em: float) -> int:
    return int(round(size * em))


# ── Text rendering ─────────────────────────────────────────────────────


def draw_text(
    draw: ImageDraw.ImageDraw,
    xy: Tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: RGB,
) -> int:
    """Draw text at xy; returns the advance width of the text."""
    if not text:
        return 0
    draw.text(xy, text, font=font, fill=fill)
    return text_width(font, text)


def draw_tracked_text(
    draw: ImageDraw.ImageDraw,
    xy: Tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: RGB,
    tracking_px: int,
) -> int:
    """Render `text` glyph-by-glyph, adding `tracking_px` between characters.

    Pillow has no letter-spacing; the JSX designs rely heavily on it
    (0.14em..0.30em on section labels). Returns total advance width.
    """
    if not text:
        return 0
    x, y = xy
    start_x = x
    for i, ch in enumerate(text):
        draw.text((x, y), ch, font=font, fill=fill)
        x += text_width(font, ch)
        if i < len(text) - 1:
            x += int(tracking_px)
    return x - start_x


def draw_tracked_text_right(
    draw: ImageDraw.ImageDraw,
    xy_right: Tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: RGB,
    tracking_px: int,
) -> int:
    """Draw tracked text right-aligned on `xy_right[0]`. Returns width drawn."""
    w = tracked_width(font, text, tracking_px)
    return draw_tracked_text(draw, (xy_right[0] - w, xy_right[1]), text, font, fill, tracking_px)


def draw_tracked_text_center(
    draw: ImageDraw.ImageDraw,
    xy_center: Tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: RGB,
    tracking_px: int,
) -> int:
    w = tracked_width(font, text, tracking_px)
    x = xy_center[0] - w // 2
    return draw_tracked_text(draw, (x, xy_center[1]), text, font, fill, tracking_px)


def draw_outlined_text(
    draw: ImageDraw.ImageDraw,
    xy: Tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    *,
    stroke_px: int,
    stroke_fill: RGB,
    fill: Optional[RGB] = None,
) -> int:
    """Outlined glyph for the Swiss calm-state '00'.

    Pillow natively supports stroke; we use a transparent fill unless an
    explicit fill is provided (the JSX uses `color: transparent` +
    `WebkitTextStroke`).
    """
    _fill = fill if fill is not None else (255, 255, 255)
    draw.text(
        xy,
        text,
        font=font,
        fill=_fill,
        stroke_width=int(stroke_px),
        stroke_fill=stroke_fill,
    )
    return text_width(font, text)


# ── Baseline-anchored text helpers ─────────────────────────────────────
#
# Pillow's default `draw.text((x, y), ...)` places text by the *top of
# the ascender line* (anchor='la'), which forces every caller to fudge
# with a hand-picked offset. The helpers below position by baseline
# instead, so vertical alignment is a function of font metrics (ascent /
# descent) and can't clip adjacent rules by construction.


def draw_text_bl(
    draw: ImageDraw.ImageDraw,
    xy_baseline: Tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: RGB,
) -> int:
    """Draw `text` with its baseline at xy_baseline[1].

    Returns the advance width in px so callers can chain.
    """
    if not text:
        return 0
    draw.text(xy_baseline, text, font=font, fill=fill, anchor="ls")
    return text_width(font, text)


def draw_text_bl_center(
    draw: ImageDraw.ImageDraw,
    xy_baseline: Tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: RGB,
) -> int:
    """Draw `text` with its baseline at xy_baseline[1], horizontally
    centered on xy_baseline[0]."""
    if not text:
        return 0
    draw.text(xy_baseline, text, font=font, fill=fill, anchor="ms")
    return text_width(font, text)


def draw_text_bl_right(
    draw: ImageDraw.ImageDraw,
    xy_baseline: Tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: RGB,
) -> int:
    """Draw `text` with its baseline at xy_baseline[1], right-aligned on
    xy_baseline[0]."""
    if not text:
        return 0
    draw.text(xy_baseline, text, font=font, fill=fill, anchor="rs")
    return text_width(font, text)


def draw_tracked_text_bl(
    draw: ImageDraw.ImageDraw,
    xy_baseline: Tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: RGB,
    tracking_px: int,
) -> int:
    """Tracked text on a baseline. Renders glyph-by-glyph because Pillow
    has no native letter-spacing."""
    if not text:
        return 0
    x, y = xy_baseline
    start = x
    for i, ch in enumerate(text):
        draw.text((x, y), ch, font=font, fill=fill, anchor="ls")
        x += text_width(font, ch)
        if i < len(text) - 1:
            x += int(tracking_px)
    return x - start


def draw_tracked_text_bl_center(
    draw: ImageDraw.ImageDraw,
    xy_baseline: Tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: RGB,
    tracking_px: int,
) -> int:
    w = tracked_width(font, text, tracking_px)
    x = xy_baseline[0] - w // 2
    return draw_tracked_text_bl(draw, (x, xy_baseline[1]), text, font, fill, tracking_px)


def draw_tracked_text_bl_right(
    draw: ImageDraw.ImageDraw,
    xy_baseline: Tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: RGB,
    tracking_px: int,
) -> int:
    w = tracked_width(font, text, tracking_px)
    x = xy_baseline[0] - w
    return draw_tracked_text_bl(draw, (x, xy_baseline[1]), text, font, fill, tracking_px)


def draw_text_in_box(
    draw: ImageDraw.ImageDraw,
    box: Box,
    text: str,
    font: ImageFont.ImageFont,
    fill: RGB,
    *,
    h_align: str = "left",    # 'left' | 'center' | 'right'
    v_align: str = "center",  # 'top' | 'center' | 'baseline' | 'bottom'
    tracking_px: int = 0,
) -> int:
    """Render `text` inside `box`, positioning by the chosen alignment.

    For v_align='baseline' the box's bottom is treated as the baseline
    so the text sits on it. For v_align='center' the baseline is
    derived from the font's ascent/descent so the glyph's ink-box is
    visually centered.
    """
    if not text:
        return 0
    fm = font_metrics(font)
    if v_align == "top":
        baseline_y = box.y0 + fm.ascent
    elif v_align == "bottom":
        baseline_y = box.y1 - fm.descent
    elif v_align == "baseline":
        baseline_y = box.y1
    else:
        baseline_y = box.cy + (fm.ascent - fm.descent) // 2

    if tracking_px > 0:
        w = tracked_width(font, text, tracking_px)
    else:
        w = text_width(font, text)

    if h_align == "center":
        x = box.cx - w // 2
    elif h_align == "right":
        x = box.x1 - w
    else:
        x = box.x0

    if tracking_px > 0:
        return draw_tracked_text_bl(draw, (x, baseline_y), text, font, fill, tracking_px)
    return draw_text_bl(draw, (x, baseline_y), text, font, fill)


# ── Rules (horizontal lines of various weights) ─────────────────────────


def hr(
    draw: ImageDraw.ImageDraw,
    x0: int,
    x1: int,
    y: int,
    *,
    thickness: int = 1,
    fill: RGB = (0, 0, 0),
) -> int:
    """Draw a horizontal rule `thickness` px tall starting at `y`.

    Returns y + thickness so callers can chain.
    """
    t = max(1, int(thickness))
    draw.rectangle([(x0, y), (x1 - 1, y + t - 1)], fill=fill)
    return y + t


def double_hr(
    draw: ImageDraw.ImageDraw,
    x0: int,
    x1: int,
    y: int,
    *,
    fill: RGB = (0, 0, 0),
    gap: int = 2,
) -> int:
    """Editorial-style 'heavy + hairline' rule pair.

    The JSX uses 2px + 1.5px gap + 0.75px; rounded to 2 + 2 + 1 for the
    panel grid. Returns the Y below the pair.
    """
    y = hr(draw, x0, x1, y, thickness=2, fill=fill)
    y += gap
    y = hr(draw, x0, x1, y, thickness=1, fill=fill)
    return y


def hairline_hr(
    draw: ImageDraw.ImageDraw,
    x0: int,
    x1: int,
    y: int,
    *,
    fill: RGB = (0, 0, 0),
) -> int:
    return hr(draw, x0, x1, y, thickness=1, fill=fill)


def dotted_hr(
    draw: ImageDraw.ImageDraw,
    x0: int,
    x1: int,
    y: int,
    *,
    dash: int = 1,
    gap: int = 2,
    fill: RGB = (0, 0, 0),
) -> int:
    """A hairline drawn as dash-gap rectangles. 0.5px dotted borders in the
    JSX render as 1px dots here (the panel can't do half-pixels anyway)."""
    x = x0
    while x < x1:
        end = min(x + dash, x1)
        draw.rectangle([(x, y), (end - 1, y)], fill=fill)
        x += dash + gap
    return y + 1


def vline(
    draw: ImageDraw.ImageDraw,
    x: int,
    y0: int,
    y1: int,
    *,
    thickness: int = 1,
    fill: RGB = (0, 0, 0),
) -> None:
    t = max(1, int(thickness))
    draw.rectangle([(x, y0), (x + t - 1, y1 - 1)], fill=fill)


def dotted_vr(
    draw: ImageDraw.ImageDraw,
    x: int,
    y0: int,
    y1: int,
    *,
    dash: int = 1,
    gap: int = 2,
    fill: RGB = (0, 0, 0),
) -> None:
    y = y0
    while y < y1:
        end = min(y + dash, y1)
        draw.rectangle([(x, y), (x, end - 1)], fill=fill)
        y += dash + gap


# ── Ornaments ──────────────────────────────────────────────────────────


def diamond(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    size: int,
    fill: RGB,
) -> None:
    """Filled diamond (rotated square) -- the JSX explicitly forbids the
    `◆` glyph because it renders inconsistently.
    """
    s = size / 2
    draw.polygon(
        [(cx, cy - s), (cx + s, cy), (cx, cy + s), (cx - s, cy)],
        fill=fill,
    )


def bullet(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    r: int,
    *,
    filled: bool,
    color: RGB,
    stroke: int = 1,
) -> int:
    """Filled or hollow bullet. The original JSX uses `●`/`○` inline as
    characters, but most pixel fonts (and FreeType fallback) render them
    as tofu boxes at non-native sizes. Drawing them as primitives gives
    us consistent ink and proper color support (red bullet for heating).

    Returns the outer diameter so callers can chain "bullet + label" rows.
    """
    box = [(cx - r, cy - r), (cx + r, cy + r)]
    if filled:
        draw.ellipse(box, fill=color)
    else:
        draw.ellipse(box, outline=color, width=max(1, int(stroke)))
    return r * 2 + 1


def square_marker(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    r: int,
    *,
    filled: bool,
    color: RGB,
) -> None:
    """Filled or hollow square marker -- used for the 'X WIN OPEN' chip in
    the colophon where the JSX reaches for a yellow square glyph."""
    box = [(cx - r, cy - r), (cx + r - 1, cy + r - 1)]
    if filled:
        draw.rectangle(box, fill=color)
    else:
        draw.rectangle(box, outline=color, width=1)


# Arrow / refresh / star primitives.
#
# Cherry pixel font (and several of the small sans bitmaps) ship without
# glyphs for U+2192 -> / U+2191 up / U+2193 down / U+21BB refresh / U+2605
# star. FreeType renders the missing-glyph .notdef rectangle, which the
# Editorial design exhibits as the visible "tofu boxes" next to target
# temps, the colophon refresh icon, and the calm-state eyebrow.
#
# Each primitive below paints the requested glyph at a baseline-aligned
# anchor and returns the drawn width so callers can compose them inline
# with tracked text rows.


def draw_arrow_right(
    draw: ImageDraw.ImageDraw,
    x: int,
    y_baseline: int,
    *,
    size: int = 7,
    fill: RGB,
) -> int:
    """Inline right-arrow glyph anchored at `(x, y_baseline)` with the
    shaft sitting at half-cap-height. Returns the advance width in px.

    Drawn as a 1-px shaft + filled triangle head. Visually balances
    Cherry-9 / Source-Serif-9..14 caps when `size` is 7-9.
    """
    sz = max(5, int(size))
    head_w = sz - 2
    head_h = sz - 2
    cy = y_baseline - sz // 2 - 1
    shaft_x0 = x
    shaft_x1 = x + sz - head_w
    if shaft_x1 > shaft_x0:
        draw.rectangle([(shaft_x0, cy), (shaft_x1, cy)], fill=fill)
    tip_x = x + sz - 1
    tip_y_top = cy - head_h // 2
    tip_y_bot = cy + head_h // 2
    head_left = tip_x - head_w
    draw.polygon(
        [(head_left, tip_y_top), (tip_x, cy), (head_left, tip_y_bot)],
        fill=fill,
    )
    return sz


def draw_arrow_up(
    draw: ImageDraw.ImageDraw,
    x: int,
    y_baseline: int,
    *,
    size: int = 7,
    fill: RGB,
) -> int:
    """Inline up-arrow glyph. Returns advance width."""
    sz = max(5, int(size))
    head_w = sz - 2
    head_h = sz - 2
    cx = x + sz // 2
    top_y = y_baseline - sz + 1
    bot_y = y_baseline - 1
    if bot_y > top_y + head_h:
        draw.rectangle([(cx, top_y + head_h), (cx, bot_y)], fill=fill)
    draw.polygon(
        [(cx - head_w // 2, top_y + head_h),
         (cx, top_y),
         (cx + head_w // 2, top_y + head_h)],
        fill=fill,
    )
    return sz


def draw_arrow_down(
    draw: ImageDraw.ImageDraw,
    x: int,
    y_baseline: int,
    *,
    size: int = 7,
    fill: RGB,
) -> int:
    """Inline down-arrow glyph. Returns advance width."""
    sz = max(5, int(size))
    head_w = sz - 2
    head_h = sz - 2
    cx = x + sz // 2
    top_y = y_baseline - sz + 1
    bot_y = y_baseline - 1
    if bot_y - head_h > top_y:
        draw.rectangle([(cx, top_y), (cx, bot_y - head_h)], fill=fill)
    draw.polygon(
        [(cx - head_w // 2, bot_y - head_h),
         (cx, bot_y),
         (cx + head_w // 2, bot_y - head_h)],
        fill=fill,
    )
    return sz


def draw_refresh_glyph(
    draw: ImageDraw.ImageDraw,
    x: int,
    y_baseline: int,
    *,
    size: int = 9,
    fill: RGB,
) -> int:
    """Inline refresh icon: three-quarter ring + arrowhead.

    Replaces the missing U+21BB glyph in the Editorial colophon. The ring
    is approximated with an unfilled ellipse and a small bg-tinted notch;
    the arrowhead caps the open end so it reads as a circular arrow at
    any size from 7 to 12 px.
    """
    sz = max(7, int(size))
    cx = x + sz // 2
    cy = y_baseline - sz // 2
    r = sz // 2
    # Pillow's `arc` is the cleanest way to get an open ring without
    # painting and then re-painting a notch.
    draw.arc(
        [(cx - r, cy - r), (cx + r, cy + r)],
        start=40,
        end=320,
        fill=fill,
        width=1,
    )
    # Arrowhead at the open end (~40° on the unit circle).
    a = math.radians(40)
    tip_x = cx + int(r * math.cos(a))
    tip_y = cy + int(r * math.sin(a))
    draw.polygon(
        [(tip_x, tip_y),
         (tip_x - 2, tip_y - 2),
         (tip_x + 1, tip_y - 3)],
        fill=fill,
    )
    return sz


def draw_star_marker(
    draw: ImageDraw.ImageDraw,
    x: int,
    y_baseline: int,
    *,
    size: int = 9,
    fill: RGB,
) -> int:
    """Inline 5-point star, baseline-aligned. Returns advance width.

    Replaces the missing U+2605 glyph used by the calm-state eyebrow
    (`★  THE CALM EDITION  ★`).
    """
    sz = max(7, int(size))
    cx = x + sz // 2
    cy = y_baseline - sz // 2 - 1
    r_outer = sz // 2
    r_inner = max(2, r_outer // 2)
    pts: List[Tuple[int, int]] = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rr = r_outer if i % 2 == 0 else r_inner
        pts.append((cx + int(rr * math.cos(ang)),
                    cy + int(rr * math.sin(ang))))
    draw.polygon(pts, fill=fill)
    return sz


# ── Text overflow (fit-then-ellipsize) ─────────────────────────────────


def draw_text_clipped_bl(
    draw: ImageDraw.ImageDraw,
    xy_baseline: Tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: RGB,
    *,
    max_w: int,
    ellipsis: str = "\u2026",
) -> int:
    """Baseline-anchored text that ellipsizes when it doesn't fit `max_w`.

    Pillow has no `text-overflow: ellipsis`. This helper measures the
    full string; if it overflows, it pops characters off the end and
    re-measures `text + ellipsis` until it fits. Returns the advance
    width actually drawn.

    Use this whenever the rendered string comes from outside data
    (person names, status labels, program names) where a worst-case
    expansion could otherwise spill the column.
    """
    if not text:
        return 0
    s = text
    full_w = text_width(font, s)
    if full_w <= max_w:
        draw.text(xy_baseline, s, font=font, fill=fill, anchor="ls")
        return full_w
    # Doesn't fit -- chop and append the ellipsis until it does.
    ell_w = text_width(font, ellipsis)
    if ell_w >= max_w:
        # Column is too narrow for even the ellipsis -- skip drawing
        # rather than paint a half-glyph over the rule.
        return 0
    while s and text_width(font, s + ellipsis) > max_w:
        s = s[:-1]
    if not s:
        return 0
    out = s + ellipsis
    draw.text(xy_baseline, out, font=font, fill=fill, anchor="ls")
    return text_width(font, out)


def draw_text_clipped_bl_right(
    draw: ImageDraw.ImageDraw,
    xy_baseline_right: Tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: RGB,
    *,
    max_w: int,
    ellipsis: str = "\u2026",
) -> int:
    """Right-aligned variant of draw_text_clipped_bl."""
    if not text:
        return 0
    s = text
    full_w = text_width(font, s)
    if full_w <= max_w:
        x = xy_baseline_right[0] - full_w
        draw.text((x, xy_baseline_right[1]), s,
                  font=font, fill=fill, anchor="ls")
        return full_w
    ell_w = text_width(font, ellipsis)
    if ell_w >= max_w:
        return 0
    while s and text_width(font, s + ellipsis) > max_w:
        s = s[:-1]
    if not s:
        return 0
    out = s + ellipsis
    w = text_width(font, out)
    x = xy_baseline_right[0] - w
    draw.text((x, xy_baseline_right[1]), out,
              font=font, fill=fill, anchor="ls")
    return w


# ── Multi-run headline layout (inline italic, etc.) ─────────────────────


@dataclass
class Run:
    """A span of text within a headline that shares a single font+fill."""
    text: str
    font: ImageFont.ImageFont
    fill: RGB


def _wrap_runs_into_lines(
    runs: Sequence[Run],
    max_w: int,
) -> List[List[Run]]:
    """Greedy wrap `runs` into lines bounded by `max_w`.

    Respects explicit '\\n' characters inside run text as forced breaks.
    """
    lines: List[List[Run]] = [[]]
    cur_w = 0

    for r in runs:
        # Break a run on explicit newlines into sub-runs separated by
        # forced-break markers.
        parts = r.text.split("\n") if r.text else [""]
        for i, part in enumerate(parts):
            if i > 0:
                lines.append([])
                cur_w = 0
            if not part:
                continue
            # Tokenize preserving spaces so we can rejoin cleanly.
            tokens = _tokenize_preserve_spaces(part)
            for tok in tokens:
                tok_w = text_width(r.font, tok)
                if cur_w + tok_w > max_w and cur_w > 0 and tok.strip():
                    lines.append([])
                    cur_w = 0
                    if not tok.strip():
                        continue
                # Append to the current line. Merge with the prior run if
                # it shares a font/fill to keep rendering tight.
                _append_to_line(lines[-1], tok, r)
                cur_w += tok_w
    return lines


def _tokenize_preserve_spaces(text: str) -> List[str]:
    tokens: List[str] = []
    buf: List[str] = []
    for ch in text:
        if ch == " ":
            if buf:
                tokens.append("".join(buf))
                buf = []
            tokens.append(" ")
        else:
            buf.append(ch)
    if buf:
        tokens.append("".join(buf))
    return tokens


def _append_to_line(line: List[Run], text: str, template: Run) -> None:
    if line and line[-1].font is template.font and line[-1].fill == template.fill:
        line[-1] = Run(line[-1].text + text, template.font, template.fill)
    else:
        line.append(Run(text, template.font, template.fill))


def line_width(line: Sequence[Run]) -> int:
    return sum(text_width(r.font, r.text) for r in line)


def draw_run_line(
    draw: ImageDraw.ImageDraw,
    xy: Tuple[int, int],
    line: Sequence[Run],
) -> int:
    x, y = xy
    start = x
    for r in line:
        draw.text((x, y), r.text, font=r.font, fill=r.fill)
        x += text_width(r.font, r.text)
    return x - start


def draw_headline(
    draw: ImageDraw.ImageDraw,
    box: Tuple[int, int, int, int],  # (x, y, w, h)
    runs: Sequence[Run],
    *,
    line_height_px: int,
    align: str = "left",  # 'left' | 'center'
    max_lines: Optional[int] = None,
) -> int:
    """Render a multi-run headline, wrapping inside `box`'s width.

    Returns the Y immediately below the last rendered line.
    """
    x, y, w, _h = box
    lines = _wrap_runs_into_lines([r for r in runs if r.text is not None], w)
    if max_lines is not None:
        lines = lines[:max_lines]
    cur_y = y
    for line in lines:
        if not line:
            # Empty line: advance by line_height.
            cur_y += line_height_px
            continue
        line_w = line_width(line)
        if align == "center":
            x0 = x + (w - line_w) // 2
        else:
            x0 = x
        draw_run_line(draw, (x0, cur_y), line)
        cur_y += line_height_px
    return cur_y


# ── Drop cap paragraph (Editorial calm lead) ───────────────────────────


def draw_drop_cap_paragraph(
    draw: ImageDraw.ImageDraw,
    box: Tuple[int, int, int, int],  # (x, y, w, max_h)
    cap_char: str,
    body_text: str,
    *,
    cap_font: ImageFont.ImageFont,
    body_font: ImageFont.ImageFont,
    fill: RGB,
    line_height_px: int,
    cap_lines: int = 2,
    cap_right_gutter: int = 6,
) -> int:
    """Render a paragraph that opens with a drop cap.

    The cap sits at the top-left; the first `cap_lines` body lines flow
    in the narrow zone to its right, then the paragraph resumes at the
    full column width. Returns Y below the last body line.
    """
    x, y, w, _ = box
    # Draw the cap glyph first so we can measure how wide it actually is.
    cap_w = text_width(cap_font, cap_char)
    draw.text((x, y - 2), cap_char, font=cap_font, fill=fill)

    narrow_x = x + cap_w + cap_right_gutter
    narrow_w = w - cap_w - cap_right_gutter
    if narrow_w < 40:
        narrow_w = w  # degenerate: column too narrow; ignore the cap shift.

    # Word-wrap the body twice: once into the narrow zone for the first
    # cap_lines lines, then into the full width for the remainder.
    words = _tokenize_preserve_spaces(body_text)

    def _fit_lines(tokens: List[str], width: int, max_lines: int) -> Tuple[List[str], List[str]]:
        """Return (line_texts, remaining_tokens)."""
        lines: List[str] = []
        cur = ""
        cur_w = 0
        i = 0
        while i < len(tokens) and len(lines) < max_lines:
            tok = tokens[i]
            tok_w = text_width(body_font, tok)
            if cur_w + tok_w > width and cur.strip():
                lines.append(cur)
                cur = ""
                cur_w = 0
                if not tok.strip():
                    i += 1
                    continue
            cur += tok
            cur_w += tok_w
            i += 1
        if cur and len(lines) < max_lines:
            lines.append(cur)
            i = len(tokens)
        return lines, tokens[i:]

    narrow_lines, remaining = _fit_lines(words, narrow_w, cap_lines)
    cur_y = y
    for line in narrow_lines:
        draw.text((narrow_x, cur_y), line.rstrip(), font=body_font, fill=fill)
        cur_y += line_height_px

    # Full-width remainder. Render until `box` runs out.
    x0 = x
    cur = ""
    cur_w = 0
    tail_lines: List[str] = []
    for tok in remaining:
        tok_w = text_width(body_font, tok)
        if cur_w + tok_w > w and cur.strip():
            tail_lines.append(cur)
            cur = ""
            cur_w = 0
            if not tok.strip():
                continue
        cur += tok
        cur_w += tok_w
    if cur.strip():
        tail_lines.append(cur)

    for line in tail_lines:
        draw.text((x0, cur_y), line.rstrip(), font=body_font, fill=fill)
        cur_y += line_height_px

    return cur_y


def draw_paragraph(
    draw: ImageDraw.ImageDraw,
    box: Tuple[int, int, int, int],
    text: str,
    *,
    font: ImageFont.ImageFont,
    fill: RGB,
    line_height_px: int,
    max_lines: Optional[int] = None,
) -> int:
    """Simple word-wrap paragraph -- no drop cap."""
    x, y, w, _ = box
    if not text:
        return y
    tokens = _tokenize_preserve_spaces(text)
    lines: List[str] = []
    cur = ""
    cur_w = 0
    for tok in tokens:
        tw = text_width(font, tok)
        if cur_w + tw > w and cur.strip():
            lines.append(cur)
            cur = ""
            cur_w = 0
            if not tok.strip():
                continue
        cur += tok
        cur_w += tw
    if cur.strip():
        lines.append(cur)
    if max_lines is not None:
        lines = lines[:max_lines]
    cur_y = y
    for line in lines:
        draw.text((x, cur_y), line.rstrip(), font=font, fill=fill)
        cur_y += line_height_px
    return cur_y


# ── Arc (for the sun arc) ──────────────────────────────────────────────


def draw_dashed_arc(
    draw: ImageDraw.ImageDraw,
    bbox: Tuple[int, int, int, int],
    start_deg: float,
    end_deg: float,
    *,
    dash_deg: float = 4.0,
    gap_deg: float = 6.0,
    fill: RGB,
    width: int = 1,
) -> None:
    """Approximate a dashed arc with a series of short `draw.arc` segments.

    Pillow's `draw.arc` doesn't take a dash pattern, and `ImageDraw`'s
    line is straight -- this is how the JSX's `strokeDasharray` is
    reproduced on the panel.
    """
    a = start_deg
    while a < end_deg:
        b = min(a + dash_deg, end_deg)
        draw.arc(bbox, a, b, fill=fill, width=width)
        a += dash_deg + gap_deg


# ── Centered text with vertical baseline at top ────────────────────────


def draw_text_center(
    draw: ImageDraw.ImageDraw,
    xy_center: Tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: RGB,
) -> None:
    if not text:
        return
    w, _h = measure_text(font, text)
    draw.text((xy_center[0] - w // 2, xy_center[1]), text, font=font, fill=fill)


def draw_text_right(
    draw: ImageDraw.ImageDraw,
    xy_right: Tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: RGB,
) -> int:
    if not text:
        return 0
    w = text_width(font, text)
    draw.text((xy_right[0] - w, xy_right[1]), text, font=font, fill=fill)
    return w
