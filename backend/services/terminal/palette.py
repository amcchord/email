"""RGBQUAD palettes used by the BMP encoders.

All values are byte-exact mirrors of the tables in:
- docs/terminal/server-protocol.md  Â§5.2 (Spectra-6)
- docs/terminal/firmware-variants.md Â§4 (BW, Gray16)

A palette entry is a 4-byte RGBQUAD: B, G, R, 0.
"""
from __future__ import annotations


def _rgbquad(r: int, g: int, b: int) -> bytes:
    """RGBQUAD is little-endian B, G, R, 0."""
    return bytes((b & 0xFF, g & 0xFF, r & 0xFF, 0))


# 1 bpp BW: index 0 = black, index 1 = white.
BW_PALETTE: bytes = _rgbquad(0, 0, 0) + _rgbquad(255, 255, 255)
assert len(BW_PALETTE) == 8


# 4 bpp Gray16: index i -> gray value i*17 (so 0 = black, 15 = pure white).
GRAY16_PALETTE: bytes = b"".join(
    _rgbquad(i * 17, i * 17, i * 17) for i in range(16)
)
assert len(GRAY16_PALETTE) == 64


# 4 bpp Spectra-6: indices 0..5 are mandatory; 6..15 fill with white per the
# server-protocol guidance ("recommended to fill them with the white entry to
# keep image viewers happy").
SPECTRA6_COLORS: list[tuple[int, int, int]] = [
    (0, 0, 0),        # 0 black
    (255, 255, 255),  # 1 white
    (0, 255, 0),      # 2 green
    (0, 0, 255),      # 3 blue
    (255, 0, 0),      # 4 red
    (255, 255, 0),    # 5 yellow
]

SPECTRA6_PALETTE: bytes = b"".join(_rgbquad(*c) for c in SPECTRA6_COLORS) + (
    _rgbquad(255, 255, 255) * (16 - len(SPECTRA6_COLORS))
)
assert len(SPECTRA6_PALETTE) == 64
