"""Cached TrueType font loader for the Pillow e-ink renderer.

The JSX designs specify a small type-system (`TY` in editorial.jsx,
`SW_TY` in swiss.jsx). The Pillow port collapses those into flat
(family, size) keys -- we resolve each to a specific TTF on disk once
and then cache `ImageFont.FreeTypeFont` instances per `(path, size)`.

Pixel fonts are pinned to their native bitmap sizes (the same sizes the
old CSS override forced, per render.html's comment block):

    Cherry         -> 13 px (cherry-13-r/b.ttf)
    Cherry Small   -> 11 px (cherry-11-b.ttf, -10-r.ttf at 10)
    Tamzen 8x16    -> 16 px
    Tamzen 10x20   -> 20 px
    Spleen 12x24   -> 24 px
    Spleen 16x32   -> 32 px

FreeType will try to scale bitmap fonts if you ask for a non-native size,
which is how "AUSTIN HOME" -> "AUSTIN HONE" in the Chromium pipeline.
We just never request a non-native size for the pixel families.
"""
from __future__ import annotations

import os
import threading
from functools import lru_cache
from typing import Optional

from PIL import ImageFont


# Absolute path to `backend/services/eink/static/fonts/`.
_FONTS_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),  # .../services/eink/
    "static",
    "fonts",
)


# Outline-font file paths. These must exist on disk for the renderer to
# work; `scripts/fetch_eink_display_fonts.sh` seeds them.
_SERIF_REG = os.path.join(_FONTS_ROOT, "source-serif-4", "SourceSerif4-Regular.ttf")
_SERIF_SEMI = os.path.join(_FONTS_ROOT, "source-serif-4", "SourceSerif4-Semibold.ttf")
_SERIF_BOLD = os.path.join(_FONTS_ROOT, "source-serif-4", "SourceSerif4-Bold.ttf")
_SERIF_IT = os.path.join(_FONTS_ROOT, "source-serif-4", "SourceSerif4-It.ttf")
_SERIF_SIT = os.path.join(_FONTS_ROOT, "source-serif-4", "SourceSerif4-SemiboldIt.ttf")
_SERIF_BIT = os.path.join(_FONTS_ROOT, "source-serif-4", "SourceSerif4-BoldIt.ttf")

_SANS_MED = os.path.join(_FONTS_ROOT, "inter", "Inter-Medium.ttf")
_SANS_BOLD = os.path.join(_FONTS_ROOT, "inter", "Inter-Bold.ttf")

# Pixel-font bitmap files. Fixed sizes; do NOT ask these for non-native sizes.
_CHERRY_R = os.path.join(_FONTS_ROOT, "cherry", "cherry-13-r.ttf")
_CHERRY_B = os.path.join(_FONTS_ROOT, "cherry", "cherry-13-b.ttf")
_CHERRY_SM_R = os.path.join(_FONTS_ROOT, "cherry", "cherry-10-r.ttf")
_CHERRY_SM_B = os.path.join(_FONTS_ROOT, "cherry", "cherry-11-b.ttf")
_TAMZEN_R = os.path.join(_FONTS_ROOT, "tamzen", "Tamzen8x16r.ttf")
_TAMZEN_B = os.path.join(_FONTS_ROOT, "tamzen", "Tamzen8x16b.ttf")
_TAMZEN_BIG = os.path.join(_FONTS_ROOT, "tamzen", "Tamzen10x20b.ttf")
_SPLEEN = os.path.join(_FONTS_ROOT, "spleen", "spleen-12x24.ttf")
_SPLEEN_BIG = os.path.join(_FONTS_ROOT, "spleen", "spleen-16x32.ttf")


_font_lock = threading.Lock()


@lru_cache(maxsize=256)
def _load(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size=size)


def serif(size: int, *, weight: str = "regular", italic: bool = False) -> ImageFont.FreeTypeFont:
    """Return a Source Serif 4 face at `size` px.

    weight: 'regular' | 'semibold' | 'bold'
    italic: True to use the italic variant. Combined with semibold/bold this
    picks the SemiboldItalic / BoldItalic cuts respectively, which give
    enough stem weight to stay legible at small px sizes on 1-bit panels
    where the regular italic looks anemic.
    """
    w = (weight or "regular").lower()
    if italic:
        if w == "bold":
            path = _SERIF_BIT
        elif w == "semibold":
            path = _SERIF_SIT
        else:
            path = _SERIF_IT
    else:
        if w == "bold":
            path = _SERIF_BOLD
        elif w == "semibold":
            path = _SERIF_SEMI
        else:
            path = _SERIF_REG
    return _load(path, size)


def sans(size: int, *, weight: str = "medium") -> ImageFont.FreeTypeFont:
    """Return an Inter face at `size` px (standing in for Helvetica Neue).

    weight: 'medium' (500) | 'bold' (700).
    """
    w = (weight or "medium").lower()
    path = _SANS_BOLD if w == "bold" else _SANS_MED
    return _load(path, size)


# Pixel fonts: honor the bitmap's native size. Non-native requests round
# to the nearest available face (e.g. the JSX asks for fontSize: 9 or 10
# on cherrySmB but the bitmap is 11; we serve the 11 so no scaling occurs).


def _pick_cherry_small(bold: bool) -> str:
    return _CHERRY_SM_B if bold else _CHERRY_SM_R


def pix_cherry(size: int = 13, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Cherry 13x pixel font. Any non-13 size serves the 13px bitmap unscaled."""
    path = _CHERRY_B if bold else _CHERRY_R
    return _load(path, 13)


def pix_cherry_small(size: int = 11, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Cherry Small pixel font. Non-native sizes are clamped to the native
    bitmap size of the chosen weight (11 bold / 10 regular) to avoid the
    bitmap-scaling bug that turned 'HOME' into 'HONE' in the Chromium path.
    """
    path = _pick_cherry_small(bold)
    native = 11 if bold else 10
    return _load(path, native)


def pix_tamzen(size: int = 16, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = _TAMZEN_B if bold else _TAMZEN_R
    return _load(path, 16)


def pix_tamzen_big(size: int = 20) -> ImageFont.FreeTypeFont:
    return _load(_TAMZEN_BIG, 20)


def pix_spleen(size: int = 24) -> ImageFont.FreeTypeFont:
    return _load(_SPLEEN, 24)


def pix_spleen_big(size: int = 32) -> ImageFont.FreeTypeFont:
    return _load(_SPLEEN_BIG, 32)
