"""Color palettes for the Pillow e-ink dashboard.

Ports `E_PALETTE` from docs/design/editorial.jsx and `SW_PALETTE` from
docs/design/swiss.jsx verbatim. Per HANDOFF.md Sec 2.1, `muted`/`soft` are
set to pure ink in both palettes so no grey ever lands on the panel; the
quantizer would snap it to black anyway.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


RGB = Tuple[int, int, int]


def _hex(h: str) -> RGB:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


@dataclass(frozen=True)
class Palette:
    # Colors are RGB tuples so Pillow can consume them directly.
    bg: RGB
    ink: RGB
    paper: RGB
    red: RGB
    blue: RGB
    green: RGB
    yellow: RGB
    rule: RGB
    soft: RGB
    muted: RGB

    @property
    def is_bw(self) -> bool:
        """True when this is a 2-color (B&W) palette.

        Used only at the one allowed branch-point (HANDOFF Sec 8): the
        inverted Pool/Sauna cells in Swiss, where the background needs to
        differ from the foreground to read as a solid fill.
        """
        return self.red == self.ink


# ── Editorial palette (ports editorial.jsx E_PALETTE) ─────────────────
E_PALETTE_SIX = Palette(
    bg=_hex("#ffffff"),
    ink=_hex("#111111"),
    paper=_hex("#f5efe4"),
    red=_hex("#c8261b"),
    blue=_hex("#1d4d8a"),
    green=_hex("#1f6b3a"),
    yellow=_hex("#e7b800"),
    rule=_hex("#111111"),
    soft=_hex("#111111"),
    muted=_hex("#111111"),
)

E_PALETTE_BW = Palette(
    bg=_hex("#ffffff"),
    ink=_hex("#000000"),
    paper=_hex("#ffffff"),
    red=_hex("#000000"),
    blue=_hex("#000000"),
    green=_hex("#000000"),
    yellow=_hex("#000000"),
    rule=_hex("#000000"),
    soft=_hex("#000000"),
    muted=_hex("#000000"),
)


# ── Swiss palette (ports swiss.jsx SW_PALETTE) ─────────────────────────
SW_PALETTE_SIX = Palette(
    bg=_hex("#ffffff"),
    ink=_hex("#0a0a0a"),
    paper=_hex("#ffffff"),
    red=_hex("#c8261b"),
    blue=_hex("#1d4d8a"),
    green=_hex("#1f6b3a"),
    yellow=_hex("#e7b800"),
    rule=_hex("#0a0a0a"),
    soft=_hex("#0a0a0a"),
    muted=_hex("#0a0a0a"),
)

SW_PALETTE_BW = Palette(
    bg=_hex("#ffffff"),
    ink=_hex("#000000"),
    paper=_hex("#ffffff"),
    red=_hex("#000000"),
    blue=_hex("#000000"),
    green=_hex("#000000"),
    yellow=_hex("#000000"),
    rule=_hex("#000000"),
    soft=_hex("#000000"),
    muted=_hex("#000000"),
)


def get_palette(design: str, palette: str) -> Palette:
    design = (design or "editorial").lower()
    palette = (palette or "six").lower()
    if design == "swiss":
        return SW_PALETTE_BW if palette == "bw" else SW_PALETTE_SIX
    return E_PALETTE_BW if palette == "bw" else E_PALETTE_SIX
